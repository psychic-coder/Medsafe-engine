"""Build the alias/bridge table joining the PMBJP and DDInter vocabularies.

Consumes the processed outputs of the two ingestion scripts plus any manual mappings in
``data/manual/``, normalizes every surface form, and produces the canonical ``Molecule`` list
together with the ``Alias`` rows (``raw_string``, ``normalized_string``, ``source`` in {ddinter,
pmbjp, manual, rxnorm_dump}) that link each vocabulary's names to a single ``molecule_id``.

Joins are made on exact normalized equality and curated manual mappings only. Fuzzy similarity may
be used to *propose* unresolved-name candidates into a review file for a human to accept into
``data/manual/`` — it never writes an alias directly. Blocklisted confusable pairs are excluded from
proposals entirely. This is the script where a wrong join silently becomes a wrong substitution, so
it reports unjoined names loudly rather than guessing.

    python scripts/build_bridge_table.py --propose

Outputs to ``data/processed/``: ``molecules.csv``, ``aliases.csv``, ``contains.csv``, and
``unjoined_names.csv``. With ``--propose`` it also writes ``review_candidates.csv``, which is an
*input to a human*, never to the loader.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from medsafe.config import get_settings  # noqa: E402
from medsafe.resolution.blocklist import ConfusablePairBlocklist  # noqa: E402
from medsafe.resolution.matcher import score_similarity  # noqa: E402
from medsafe.resolution.normalize import normalize  # noqa: E402

logger = logging.getLogger("medsafe.build_bridge_table")


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [
            {k: (v or "").strip() for k, v in row.items() if k} for row in csv.DictReader(handle)
        ]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def assign_molecule_ids(keys: list[str]) -> dict[str, str]:
    """Deterministic ``MOL######`` ids, assigned in sorted key order so reruns are stable."""
    return {key: f"MOL{index:06d}" for index, key in enumerate(sorted(set(keys)), start=1)}


def build(processed_dir: Path, manual_dir: Path, propose: bool) -> dict[str, Any]:
    pmbjp_aliases = _read_csv(processed_dir / "pmbjp_aliases.csv")
    ddinter_aliases = _read_csv(processed_dir / "ddinter_aliases.csv")
    manual_aliases = _read_csv(manual_dir / "manual_aliases.csv")
    products = _read_csv(processed_dir / "products.csv")

    # The canonical vocabulary is the DDInter side (bare INNs) plus anything a human has curated.
    # PMBJP catalogue names join onto it; they do not create molecules on their own, because a
    # catalogue row is a product, not evidence of a distinct molecule.
    canonical_keys = [
        row["normalized_string"] for row in ddinter_aliases if row.get("normalized_string")
    ]
    canonical_keys += [
        row["normalized_string"] for row in manual_aliases if row.get("normalized_string")
    ]
    molecule_ids = assign_molecule_ids(canonical_keys)

    molecules = [
        {"molecule_id": molecule_id, "inn_name": key, "category": "small_molecule"}
        for key, molecule_id in sorted(molecule_ids.items(), key=lambda item: item[1])
    ]

    aliases: dict[str, dict[str, Any]] = {}
    for row in ddinter_aliases + manual_aliases + pmbjp_aliases:
        key = row.get("normalized_string", "")
        molecule_id = molecule_ids.get(key)
        if not key or molecule_id is None:
            continue  # exact-equality join only; unjoined names are reported below
        aliases.setdefault(
            key,
            {
                "raw_string": row.get("raw_string", key),
                "normalized_string": key,
                "source": row.get("source", "manual"),
                "molecule_id": molecule_id,
            },
        )

    # Products join to molecules through their normalized generic name. A product whose name does
    # not join is reported, not attached to a best guess.
    contains: list[dict[str, Any]] = []
    unjoined: list[dict[str, Any]] = []
    for product in products:
        normalized = normalize(product.get("generic_name_raw", ""))
        molecule_id = molecule_ids.get(normalized.normalized)
        if molecule_id is None:
            unjoined.append(
                {
                    "product_id": product.get("product_id", ""),
                    "generic_name_raw": product.get("generic_name_raw", ""),
                    "normalized_string": normalized.normalized,
                    "reason": "no exact match in the canonical vocabulary",
                }
            )
            continue
        contains.append(
            {
                "product_id": product.get("product_id", ""),
                "molecule_id": molecule_id,
                "strength": normalized.strength_value,
                "unit": normalized.strength_unit,
            }
        )

    _write_csv(processed_dir / "molecules.csv", ["molecule_id", "inn_name", "category"], molecules)
    _write_csv(
        processed_dir / "aliases.csv",
        ["raw_string", "normalized_string", "source", "molecule_id"],
        list(aliases.values()),
    )
    _write_csv(
        processed_dir / "contains.csv",
        ["product_id", "molecule_id", "strength", "unit"],
        contains,
    )
    _write_csv(
        processed_dir / "unjoined_names.csv",
        ["product_id", "generic_name_raw", "normalized_string", "reason"],
        unjoined,
    )

    # ingest_ddinter.py emits interactions and the coverage manifest keyed by normalized *name*,
    # because molecule identity does not exist until this script assigns it. Rewriting them to
    # molecule_ids is this script's job — without it the loader matches no endpoints and every
    # INTERACTS_WITH edge is silently dropped, leaving a graph that answers "no known interaction"
    # for everything.
    rewritten = rewrite_interactions(processed_dir, molecule_ids)
    coverage_rewritten = rewrite_coverage_manifest(processed_dir, molecule_ids)

    proposals = 0
    if propose:
        proposals = write_proposals(processed_dir, unjoined, list(molecule_ids))

    return {
        "molecules": len(molecules),
        "aliases": len(aliases),
        "contains": len(contains),
        "interactions": rewritten["written"],
        "interactions_dropped": rewritten["dropped"],
        "coverage_molecules": coverage_rewritten,
        "unjoined_products": len(unjoined),
        "review_proposals": proposals,
    }


def rewrite_interactions(processed_dir: Path, molecule_ids: dict[str, str]) -> dict[str, int]:
    """Map ``interactions.csv`` from normalized names onto molecule ids, preserving ordering."""
    rows = _read_csv(processed_dir / "interactions.csv")
    if not rows:
        return {"written": 0, "dropped": 0}

    written: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for row in rows:
        left = molecule_ids.get(row.get("molecule_id_a", ""))
        right = molecule_ids.get(row.get("molecule_id_b", ""))
        if left is None or right is None or left == right:
            dropped.append({**row, "reason": "one or both molecules are not in the vocabulary"})
            continue
        # Re-apply canonical ordering: id order need not follow name order.
        first, second = (left, right) if left < right else (right, left)
        written.append({**row, "molecule_id_a": first, "molecule_id_b": second})

    _write_csv(
        processed_dir / "interactions.csv",
        ["molecule_id_a", "molecule_id_b", "severity", "mechanism", "provenance"],
        written,
    )
    if dropped:
        _write_csv(
            processed_dir / "unjoined_interactions.csv",
            ["molecule_id_a", "molecule_id_b", "severity", "reason"],
            dropped,
        )
    return {"written": len(written), "dropped": len(dropped)}


def rewrite_coverage_manifest(processed_dir: Path, molecule_ids: dict[str, str]) -> int:
    """Re-key ``molecule_atc_groups`` from normalized names onto molecule ids.

    A molecule that does not survive the re-key is simply absent from the mapping, and
    ``safety.interactions`` treats an absent molecule as not covered — the fail-closed direction.
    """
    import json

    manifest_path = processed_dir / "ddinter_coverage.json"
    if not manifest_path.is_file():
        return 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_name = manifest.get("molecule_atc_groups") or {}
    by_id = {
        molecule_ids[name]: group for name, group in by_name.items() if name in molecule_ids
    }
    manifest["molecule_atc_groups"] = by_id
    manifest["molecule_atc_groups_keyed_by"] = "molecule_id"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return len(by_id)


def write_proposals(
    processed_dir: Path, unjoined: list[dict[str, Any]], vocabulary: list[str], top_n: int = 3
) -> int:
    """Propose candidates for a human to accept. Never writes an alias directly.

    Blocklisted pairs are excluded outright: a proposal a reviewer might rubber-stamp is exactly the
    route by which a confusable becomes an accepted alias.
    """
    settings = get_settings()
    blocklist = ConfusablePairBlocklist.from_csv(settings.fuzzy_negative_blocklist)
    rows: list[dict[str, Any]] = []

    for item in unjoined:
        key = item["normalized_string"]
        if not key:
            continue
        scored = sorted(
            (
                (score_similarity(key, candidate), candidate)
                for candidate in vocabulary
                if not blocklist.contains(key, candidate, already_normalized=True)
            ),
            key=lambda pair: (-pair[0], pair[1]),
        )[:top_n]
        for score, candidate in scored:
            if score < settings.fuzzy_candidate_threshold:
                continue
            rows.append(
                {
                    "product_id": item["product_id"],
                    "unjoined_name": item["generic_name_raw"],
                    "normalized_string": key,
                    "proposed_inn_name": candidate,
                    "score": score,
                    "status": "PENDING_HUMAN_REVIEW",
                }
            )

    _write_csv(
        processed_dir / "review_candidates.csv",
        [
            "product_id",
            "unjoined_name",
            "normalized_string",
            "proposed_inn_name",
            "score",
            "status",
        ],
        rows,
    )
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--processed-dir", type=Path, default=None)
    parser.add_argument("--manual-dir", type=Path, default=None)
    parser.add_argument(
        "--propose",
        action="store_true",
        help="Also write fuzzy proposals to review_candidates.csv for human triage.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO))
    processed_dir = Path(args.processed_dir or settings.data_processed_dir)
    manual_dir = Path(args.manual_dir or settings.data_manual_dir)

    if not (processed_dir / "ddinter_aliases.csv").is_file():
        print(
            f"error: {processed_dir}/ddinter_aliases.csv not found.\n"
            "Run scripts/ingest_ddinter.py and scripts/ingest_pmbjp.py first. Both need the "
            "third-party sources in data/raw/, which are not redistributable and are not in this "
            "repository — use data/demo/ to exercise the downstream pipeline instead."
        )
        return 2

    report = build(processed_dir, manual_dir, args.propose)
    print(f"bridge table -> {processed_dir}")
    for key, value in report.items():
        print(f"  {key:<22} {value}")
    if report["unjoined_products"]:
        print(
            f"  {report['unjoined_products']} product names did not join and were written to "
            f"{processed_dir}/unjoined_names.csv. They have NO molecule and will not appear in "
            "resolution or substitution results."
        )
    if report["review_proposals"]:
        print(
            f"  {report['review_proposals']} fuzzy proposals written to review_candidates.csv. "
            "These are NOT aliases. Move accepted rows into data/manual/manual_aliases.csv."
        )
    # Unjoined names are expected on a first run, so they are reported loudly but do not fail the
    # build; a wrong join would be far worse than a missing one.
    return 0


if __name__ == "__main__":
    sys.exit(main())
