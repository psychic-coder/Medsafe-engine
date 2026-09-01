

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from medsafe.config import get_settings  # noqa: E402
from medsafe.resolution.normalize import normalize  # noqa: E402

logger = logging.getLogger("medsafe.ingest_pmbjp")

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "product_id": ("product_id", "drug_code", "code", "sr_no", "s_no", "id"),
    "generic_name_raw": ("generic_name", "drug_name", "product_name", "name", "generic"),
    "form": ("form", "dosage_form", "dosage_type"),
    "strength_raw": ("strength", "dosage", "strength_raw"),
    "mrp": ("mrp", "price", "unit_price", "mrp_rs", "mrp_inr"),
}

# Deliberately NOT mapped: "unit_size", "pack", "pack_size". In the PMBJP mirror those hold pack
# counts ("10 Capsules", "10's"), not dosage form or strength. Mapping them would put "10 Capsules"
# into Product.form and break every substitution equivalence check, so they are reported as
# unrecognised and form/strength are recovered from the drug name instead.


def _slug(header: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in header.strip().lower()).strip("_")


def build_column_map(headers: list[str]) -> tuple[dict[str, str], list[str]]:
    """Map source headers onto Product fields. Returns ``(mapping, unrecognised_headers)``."""
    slugged = {_slug(h): h for h in headers}
    mapping: dict[str, str] = {}
    for field, candidates in COLUMN_ALIASES.items():
        for candidate in candidates:
            if candidate in slugged and slugged[candidate] not in mapping.values():
                mapping[field] = slugged[candidate]
                break
    used = set(mapping.values())
    return mapping, [h for h in headers if h not in used]


def parse_row(row: dict[str, Any], mapping: dict[str, str], index: int) -> dict[str, Any]:
    """Parse one catalogue row. Raises ``ValueError`` with a reason the caller can report."""
    name = str(row.get(mapping.get("generic_name_raw", ""), "") or "").strip()
    if not name:
        raise ValueError("no generic name")

    raw_mrp = str(row.get(mapping.get("mrp", ""), "") or "").strip()
    cleaned = raw_mrp.replace(",", "").replace("\u20b9", "").replace("Rs", "").strip()
    try:
        mrp = float(cleaned)
    except ValueError as exc:
        raise ValueError(f"unparseable MRP {raw_mrp!r}") from exc

    product_id = str(row.get(mapping.get("product_id", ""), "") or "").strip()
    if not product_id:
        product_id = f"PMBJP-{index:06d}"

    # Form and strength are recovered from the name when the source has no column for them.
    normalized = normalize(name)
    form = str(row.get(mapping.get("form", ""), "") or "").strip() or normalized.form
    strength = str(row.get(mapping.get("strength_raw", ""), "") or "").strip()
    strength = strength or normalized.strength_raw

    return {
        "product": {
            "product_id": product_id,
            "source": "PMBJP",
            "generic_name_raw": name,
            "form": form,
            "strength_raw": strength,
            "mrp": mrp,
        },
        "alias": {
            "raw_string": name,
            "normalized_string": normalized.normalized,
            "source": "pmbjp",
        },
    }


def ingest(input_path: Path, output_dir: Path) -> dict[str, Any]:
    """Parse the catalogue and write ``products.csv`` and ``pmbjp_aliases.csv``."""
    with input_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        mapping, unrecognised = build_column_map(headers)
        if "generic_name_raw" not in mapping or "mrp" not in mapping:
            raise SystemExit(
                f"error: could not locate a name and price column in {headers}. "
                "Add the header to COLUMN_ALIASES rather than letting it be guessed."
            )
        rows = list(reader)

    products: list[dict[str, Any]] = []
    aliases: dict[str, dict[str, Any]] = {}
    unparsed: list[dict[str, Any]] = []

    for index, row in enumerate(rows, start=1):
        try:
            parsed = parse_row(row, mapping, index)
        except ValueError as exc:
            unparsed.append({"row": index, "reason": str(exc), "raw": row})
            continue
        products.append(parsed["product"])
        alias = parsed["alias"]
        if alias["normalized_string"]:
            aliases.setdefault(alias["normalized_string"], alias)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(
        output_dir / "products.csv",
        ["product_id", "source", "generic_name_raw", "form", "strength_raw", "mrp"],
        products,
    )
    _write_csv(
        output_dir / "pmbjp_aliases.csv",
        ["raw_string", "normalized_string", "source"],
        list(aliases.values()),
    )
    if unparsed:
        _write_csv(
            output_dir / "pmbjp_unparsed.csv",
            ["row", "reason"],
            [{"row": u["row"], "reason": u["reason"]} for u in unparsed],
        )

    return {
        "input_rows": len(rows),
        "products": len(products),
        "aliases": len(aliases),
        "unparsed": len(unparsed),
        "unrecognised_columns": unrecognised,
        "column_map": mapping,
    }


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO))
    input_path = args.input or (settings.data_raw_dir / "pmbjp_products.csv")
    output_dir = args.output_dir or settings.data_processed_dir

    if not Path(input_path).is_file():
        print(
            f"error: {input_path} not found.\n"
            "The PMBJP mirror is third-party and not redistributable, so it is not in this "
            "repository (see data/raw/ in .gitignore). Obtain it separately and pass --input, "
            "or use the fixtures in data/demo/ to exercise the pipeline."
        )
        return 2

    report = ingest(Path(input_path), Path(output_dir))
    print(f"ingested {input_path} -> {output_dir}")
    for key, value in report.items():
        print(f"  {key:<22} {value}")
    if report["unparsed"]:
        print(
            f"  {report['unparsed']} rows could not be parsed and were written to "
            f"{output_dir}/pmbjp_unparsed.csv — they are NOT in products.csv"
        )
    return 1 if report["unparsed"] else 0


if __name__ == "__main__":
    sys.exit(main())
