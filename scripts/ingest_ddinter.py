

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from medsafe.config import get_settings  # noqa: E402
from medsafe.resolution.normalize import normalize_key  # noqa: E402
from medsafe.safety.interactions import (  # noqa: E402
    DDINTER_COVERED_ATC_GROUPS,
    DDINTER_UNCOVERED_ATC_GROUPS,
)

logger = logging.getLogger("medsafe.ingest_ddinter")

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "drug_a": ("drug_a", "drug1", "drug_1", "name_a", "a"),
    "drug_b": ("drug_b", "drug2", "drug_2", "name_b", "b"),
    "severity": ("severity", "level", "interaction_level"),
    "mechanism": ("mechanism", "description", "interaction_description", "effect"),
}


def _slug(header: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in header.strip().lower()).strip("_")


def build_column_map(headers: list[str]) -> dict[str, str]:
    slugged = {_slug(h): h for h in headers}
    mapping: dict[str, str] = {}
    for field, candidates in COLUMN_ALIASES.items():
        for candidate in candidates:
            if candidate in slugged:
                mapping[field] = slugged[candidate]
                break
    return mapping


def canonical_row(
    name_a: str, name_b: str, severity: str, mechanism: str
) -> dict[str, Any] | None:
    """Normalize a pair into canonical order. Returns ``None`` for a self-pair or a blank name."""
    key_a, key_b = normalize_key(name_a), normalize_key(name_b)
    if not key_a or not key_b or key_a == key_b:
        return None
    left, right = (key_a, key_b) if key_a < key_b else (key_b, key_a)
    return {
        "molecule_id_a": left,
        "molecule_id_b": right,
        "severity": (severity or "unknown").strip().lower(),
        "mechanism": (mechanism or "").strip(),
        "provenance": "ddinter",
    }


def read_atc_map(path: Path | None) -> dict[str, str]:
    """Read a ``drug_name,atc_code`` file into ``{normalized_name: atc_first_level}``."""
    if path is None or not path.is_file():
        return {}
    mapping: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            slugged = {_slug(k): v for k, v in row.items() if k}
            name = slugged.get("drug_name") or slugged.get("name") or slugged.get("drug") or ""
            atc = slugged.get("atc_code") or slugged.get("atc") or ""
            key = normalize_key(name)
            if key and atc:
                mapping[key] = atc.strip().upper()[:1]
    return mapping


def ingest(input_path: Path, output_dir: Path, atc_path: Path | None) -> dict[str, Any]:
    with input_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        mapping = build_column_map(list(reader.fieldnames or []))
        if "drug_a" not in mapping or "drug_b" not in mapping:
            raise SystemExit(
                f"error: could not locate two drug-name columns in {reader.fieldnames}"
            )
        rows = list(reader)

    atc_map = read_atc_map(atc_path)
    interactions: dict[tuple[str, str], dict[str, Any]] = {}
    aliases: dict[str, dict[str, str]] = {}
    skipped = 0

    for row in rows:
        name_a = str(row.get(mapping["drug_a"], "") or "")
        name_b = str(row.get(mapping["drug_b"], "") or "")
        parsed = canonical_row(
            name_a,
            name_b,
            str(row.get(mapping.get("severity", ""), "") or ""),
            str(row.get(mapping.get("mechanism", ""), "") or ""),
        )
        if parsed is None:
            skipped += 1
            continue
        # Reverse duplicates collapse onto the same key, so the loader never sees both directions.
        interactions[(parsed["molecule_id_a"], parsed["molecule_id_b"])] = parsed
        for raw in (name_a, name_b):
            key = normalize_key(raw)
            if key:
                aliases.setdefault(
                    key, {"raw_string": raw.strip(), "normalized_string": key, "source": "ddinter"}
                )

    observed_groups = sorted({group for group in atc_map.values() if group})
    covered = sorted(set(observed_groups) & DDINTER_COVERED_ATC_GROUPS) or sorted(
        DDINTER_COVERED_ATC_GROUPS
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(
        output_dir / "interactions.csv",
        ["molecule_id_a", "molecule_id_b", "severity", "mechanism", "provenance"],
        list(interactions.values()),
    )
    _write_csv(
        output_dir / "ddinter_aliases.csv",
        ["raw_string", "normalized_string", "source"],
        list(aliases.values()),
    )

    manifest = {
        "source": f"DDInter bulk ({input_path.name})",
        "covered_atc_groups": covered,
        "uncovered_atc_groups": sorted(DDINTER_UNCOVERED_ATC_GROUPS),
        "observed_atc_groups": observed_groups,
        # Keyed by normalized name here; build_bridge_table.py rewrites these to molecule_ids once
        # identity is assigned.
        "molecule_atc_groups": atc_map,
        "note": (
            "Molecules absent from molecule_atc_groups are treated as NOT covered. An empty "
            "mapping makes every pair report not_checked, which is the intended fail-closed "
            "behaviour."
        ),
    }
    (output_dir / "ddinter_coverage.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )

    return {
        "input_rows": len(rows),
        "interactions": len(interactions),
        "aliases": len(aliases),
        "skipped": skipped,
        "atc_mapped_drugs": len(atc_map),
        "covered_atc_groups": covered,
    }


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--atc", type=Path, default=None, help="drug_name,atc_code mapping file")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO))
    input_path = args.input or (settings.data_raw_dir / "ddinter_interactions.csv")
    output_dir = args.output_dir or settings.data_processed_dir

    if not Path(input_path).is_file():
        print(
            f"error: {input_path} not found.\n"
            "The DDInter dumps are third-party and not redistributable, so they are not in this "
            "repository (see data/raw/ in .gitignore). Obtain them separately and pass --input, "
            "or use the fixtures in data/demo/ to exercise the pipeline."
        )
        return 2

    report = ingest(Path(input_path), Path(output_dir), args.atc)
    print(f"ingested {input_path} -> {output_dir}")
    for key, value in report.items():
        print(f"  {key:<22} {value}")
    if not report["atc_mapped_drugs"]:
        print(
            "  WARNING: no ATC mapping supplied (--atc). Every interaction check will report "
            "'not checked'. Supply the mapping to make coverage meaningful."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
