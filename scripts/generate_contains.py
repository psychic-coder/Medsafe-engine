

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from medsafe.resolution.normalize import normalize, normalize_key


def generate_contains() -> int:
    processed_dir = Path(__file__).resolve().parents[1] / "data" / "processed"

    mol_map: dict[str, str] = {}
    with (processed_dir / "molecule_catalog.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            mol_map[normalize_key(row["inn_name"])] = row["molecule_id"]

    alias_map: dict[str, str] = {}
    with (processed_dir / "alias_bridge_table_final.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            alias_map[normalize_key(row["normalized_string"])] = row["molecule_id"]

    contains_rows: list[dict[str, str | float]] = []
    unmatched_count = 0

    with (processed_dir / "pmbjp_final_clean.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pid = row["product_id"]
            comps = [c.strip() for c in row.get("components", "").split("|") if c.strip()]
            strengths = [s.strip() for s in row.get("strength_raw", "").split(";") if s.strip()]

            for idx, c in enumerate(comps):
                key = normalize_key(c)
                mol_id = mol_map.get(key) or alias_map.get(key)
                if mol_id:
                    s_str = strengths[idx] if idx < len(strengths) else row.get("strength_raw", "")
                    norm_res = normalize(f"{c} {s_str}")
                    val = norm_res.strength_value
                    unit = norm_res.strength_unit
                    if val is None:
                        norm_s = normalize(f"drug {s_str}")
                        val = norm_s.strength_value
                        unit = norm_s.strength_unit
                    contains_rows.append(
                        {
                            "product_id": pid,
                            "molecule_id": mol_id,
                            "strength": val if val is not None else "",
                            "unit": unit if unit else "",
                        }
                    )
                else:
                    unmatched_count += 1

    out_path = processed_dir / "contains.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["product_id", "molecule_id", "strength", "unit"])
        writer.writeheader()
        writer.writerows(contains_rows)

    print(
        f"Generated {len(contains_rows)} CONTAINS edges to {out_path.name} "
        f"({unmatched_count} unmatched components)"
    )
    return len(contains_rows)


if __name__ == "__main__":
    generate_contains()
