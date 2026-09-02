"""Validate the curated brand pack and emit the alias and combination artifacts.

``data/manual/brand_aliases_india.csv`` maps the name printed on a pack to its active ingredients.
This script turns it into two loadable artifacts and refuses to emit anything it cannot verify.

Why a build step rather than an alias file checked in directly
-------------------------------------------------------------
The alias table is an *auto-accept* path: a hit there resolves a drug with no human in the loop and
no score to inspect. Everything else on that path is machine-derived and re-derivable, so a
hand-edited file dropped straight into it would be the one unvalidated input to the most trusting
code in the engine. A typo in an ingredient name would not fail — it would silently produce a brand
that resolves to nothing, or worse, to something adjacent.

So every row is checked before it is allowed through:

1. **Every ingredient must exist in the molecule catalogue.** A brand naming an unknown ingredient
   is rejected, and the run reports it. Rejections are loud on purpose: a silently dropped brand is
   indistinguishable from a brand nobody added, and only one of those is a bug.
2. **No brand may collide with a molecule name.** If a trade name normalizes to the same key as a
   real INN, the exact-match path would shadow it and the two would be permanently confusable.
3. **No brand may collide with another brand** on a different ingredient set.
4. **The confusable-pair blocklist is enforced.** A brand whose key is a known look-alike of some
   other drug is rejected; it must not become an auto-accept route around the guard the blocklist
   exists to provide.
5. **An existing alias always wins.** Brand rows load after the bridge table, so a duplicate key
   would overwrite an entry that came from a different vocabulary with its own review history. The
   pack is additive: a key already present is skipped and reported, never silently replaced.

Outputs
-------
``<processed>/brand_aliases.csv``    single-ingredient brands, in ``Alias`` shape, merged into the
                                     alias table by ``scripts/load_graph.py``
``<processed>/combinations.csv``     multi-ingredient brands: ``brand_key, brand_raw, molecule_id,
                                     position, kind``

A combination is deliberately *not* an alias. Resolving "Augmentin" to amoxicillin would hide the
clavulanic acid from the interaction check and let the pricing layer treat a two-drug product as a
one-drug product — the two things ``docs/schema.md`` forbids. It gets its own artifact and its own
resolution status instead.

Usage::

    python scripts/build_brand_aliases.py
    python scripts/build_brand_aliases.py --processed-dir data/demo
    python scripts/build_brand_aliases.py --strict      # exit non-zero if any row was rejected
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from medsafe.config import get_settings  # noqa: E402
from medsafe.resolution.blocklist import load_blocklist  # noqa: E402
from medsafe.resolution.normalize import normalize_key  # noqa: E402

logger = logging.getLogger("medsafe.build_brand_aliases")

# ``Alias.source`` is a locked enum in docs/schema.md and "manual" is exactly what these rows are:
# hand-curated entries with a named curator and a review history. The finer brand/synonym
# distinction stays in the pack's ``kind`` column for whoever maintains it, and is not something the
# graph needs — the console tells a brand from an ingredient by comparing the alias string to the
# molecule name, which works without a new enum value and cannot drift out of step with one.
ALIAS_SOURCE = "manual"


@dataclass
class BuildReport:
    """What the run accepted, rejected, and why."""

    aliases: list[dict[str, str]] = field(default_factory=list)
    combinations: list[dict[str, str]] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)
    brands_total: int = 0

    @property
    def combination_brands(self) -> int:
        return len({row["brand_key"] for row in self.combinations})

    def reject(self, brand: str, reason: str, detail: str = "") -> None:
        self.rejected.append({"brand": brand, "reason": reason, "detail": detail})


def read_pack(path: Path) -> list[dict[str, str]]:
    """Read the curated pack, skipping ``#`` comment lines.

    ``csv`` has no comment syntax, and the pack's header block is the only documentation a curator
    reads before editing it, so comments are stripped here rather than removed from the file.
    """
    if not path.is_file():
        raise SystemExit(f"No brand pack at {path}")
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return [
        {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        for row in csv.DictReader(lines)
    ]


def read_existing_alias_keys(processed_dir: Path) -> set[str]:
    """Normalized keys already claimed by the bridge table, which the pack must not overwrite."""
    for stem in ("alias_bridge_table_final", "aliases"):
        path = processed_dir / f"{stem}.csv"
        if not path.is_file():
            continue
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return {
                normalize_key(row.get("normalized_string") or row.get("raw_string") or "")
                for row in csv.DictReader(handle)
            } - {""}
    return set()


def read_molecules(processed_dir: Path) -> dict[str, tuple[str, str]]:
    """``{normalized_inn: (molecule_id, inn_name)}`` from the molecule catalogue."""
    for stem in ("molecules", "molecule_catalog"):
        path = processed_dir / f"{stem}.csv"
        if path.is_file():
            break
    else:
        raise SystemExit(f"No molecule catalogue in {processed_dir}")

    with path.open(newline="", encoding="utf-8-sig") as handle:
        return {
            normalize_key(row["inn_name"]): (row["molecule_id"].strip(), row["inn_name"].strip())
            for row in csv.DictReader(handle)
            if row.get("molecule_id") and row.get("inn_name")
        }


def build(pack_path: Path, processed_dir: Path, blocklist_path: Path | None = None) -> BuildReport:
    molecules = read_molecules(processed_dir)
    existing_aliases = read_existing_alias_keys(processed_dir)
    blocklist = load_blocklist(blocklist_path) if blocklist_path else load_blocklist()
    report = BuildReport()

    seen: dict[str, tuple[str, ...]] = {}

    for row in read_pack(pack_path):
        brand = row.get("brand", "")
        if not brand:
            continue
        report.brands_total += 1
        kind = (row.get("kind") or "brand").lower()
        brand_key = normalize_key(brand)

        if not brand_key:
            report.reject(brand, "normalizes to an empty key")
            continue

        # A trade name that collides with a real INN would be shadowed forever by the exact-match
        # path, which runs first. Better to know at build time than to debug it as a wrong answer.
        if brand_key in molecules and kind != "synonym":
            report.reject(
                brand, "collides with a molecule name", f"{brand_key} is an INN in the catalogue"
            )
            continue

        raw_ingredients = [part.strip() for part in (row.get("ingredients") or "").split("|")]
        raw_ingredients = [part for part in raw_ingredients if part]
        if not raw_ingredients:
            report.reject(brand, "no ingredients listed")
            continue

        resolved: list[tuple[str, str]] = []
        missing: list[str] = []
        for ingredient in raw_ingredients:
            entry = molecules.get(normalize_key(ingredient))
            if entry is None:
                missing.append(ingredient)
            else:
                resolved.append(entry)
        if missing:
            report.reject(brand, "ingredient not in catalogue", ", ".join(missing))
            continue

        ids = tuple(molecule_id for molecule_id, _ in resolved)

        if brand_key in seen:
            if seen[brand_key] != ids:
                report.reject(brand, "duplicate brand with different ingredients", brand_key)
            continue

        if brand_key in existing_aliases:
            report.reject(
                brand,
                "already in the alias table",
                f"{brand_key} is claimed by an existing entry, which keeps precedence",
            )
            continue

        # The blocklist guards the fuzzy path; a brand alias would be an auto-accept route straight
        # past it, so the same pairs are refused here.
        confusable = next(
            (
                name
                for name in molecules
                if name != brand_key and blocklist.contains(brand_key, name)
            ),
            None,
        )
        if confusable is not None:
            report.reject(brand, "blocklisted confusable", f"look-alike of {confusable}")
            continue

        seen[brand_key] = ids

        if len(resolved) == 1:
            molecule_id, inn_name = resolved[0]
            report.aliases.append(
                {
                    "raw_string": brand,
                    "normalized_string": brand_key,
                    "source": ALIAS_SOURCE,
                    "molecule_id": molecule_id,
                    "inn_name": inn_name,
                    "note": row.get("note", ""),
                }
            )
        else:
            for position, (molecule_id, inn_name) in enumerate(resolved, start=1):
                report.combinations.append(
                    {
                        "brand_key": brand_key,
                        "brand_raw": brand,
                        "molecule_id": molecule_id,
                        "inn_name": inn_name,
                        "position": str(position),
                        "kind": kind,
                        "note": row.get("note", ""),
                    }
                )

    return report


def write_outputs(report: BuildReport, processed_dir: Path) -> tuple[Path, Path]:
    processed_dir.mkdir(parents=True, exist_ok=True)

    alias_path = processed_dir / "brand_aliases.csv"
    with alias_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["raw_string", "normalized_string", "source", "molecule_id"]
        )
        writer.writeheader()
        for row in report.aliases:
            writer.writerow({k: row[k] for k in writer.fieldnames})

    combo_path = processed_dir / "combinations.csv"
    with combo_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["brand_key", "brand_raw", "molecule_id", "inn_name", "position", "kind"],
        )
        writer.writeheader()
        for row in report.combinations:
            writer.writerow({k: row[k] for k in writer.fieldnames})

    return alias_path, combo_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    settings = get_settings()
    parser.add_argument(
        "--pack", type=Path, default=settings.data_manual_dir / "brand_aliases_india.csv"
    )
    parser.add_argument("--processed-dir", type=Path, default=settings.data_processed_dir)
    parser.add_argument("--blocklist", type=Path, default=None)
    parser.add_argument(
        "--strict", action="store_true", help="Exit non-zero if any row was rejected"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    report = build(args.pack, args.processed_dir, args.blocklist)

    print("brand pack")
    print(f"  rows read                {report.brands_total:>5}")
    print(f"  single-ingredient names  {len(report.aliases):>5}  -> auto-accept aliases")
    print(
        f"  combination brands       {report.combination_brands:>5}"
        "  -> expanded, never substituted"
    )
    print(f"  rejected                 {len(report.rejected):>5}")

    if report.rejected:
        print("\nrejected rows")
        by_reason: Counter[str] = Counter(row["reason"] for row in report.rejected)
        for reason, count in by_reason.most_common():
            print(f"  {reason} ({count})")
            for row in report.rejected:
                if row["reason"] == reason:
                    detail = f" — {row['detail']}" if row["detail"] else ""
                    print(f"    {row['brand']}{detail}")

    if args.dry_run:
        print("\ndry run — nothing written")
        return 1 if (args.strict and report.rejected) else 0

    alias_path, combo_path = write_outputs(report, args.processed_dir)
    print(f"\nwrote {alias_path}")
    print(f"wrote {combo_path}")

    return 1 if (args.strict and report.rejected) else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
