"""Reconcile alias and interaction data with molecule catalog.

Reads the raw alias_bridge_table_final.csv and ddinter_final_clean.csv and enriches them
with molecule_id references by matching drug names against the molecule catalog.

Output files replace the originals in data/processed/, making them ready for the graph loader.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from medsafe.resolution.normalize import normalize_key

logger_output = []


def log(msg: str = "") -> None:
    print(msg)
    logger_output.append(msg)


def main() -> int:
    processed_dir = Path(__file__).resolve().parents[1] / "data" / "processed"

    # Step 1: Load molecules and create lookup
    log("Step 1: Loading molecule catalog...")
    mol_by_normalized: dict[str, str] = {}
    mol_by_id: dict[str, str] = {}
    
    mol_path = processed_dir / "molecule_catalog.csv"
    with mol_path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            mol_id = row.get("molecule_id", "").strip()
            inn_name = row.get("inn_name", "").strip()
            if mol_id and inn_name:
                mol_by_id[mol_id] = inn_name
                norm_key = normalize_key(inn_name)
                mol_by_normalized[norm_key] = mol_id
    
    log(f"  Loaded {len(mol_by_id)} molecules\n")

    # Step 2: Enrich aliases
    log("Step 2: Enriching aliases...")
    alias_path = processed_dir / "aliases.csv"
    alias_rows: list[dict[str, str]] = []
    unmatched_aliases = 0
    
    with alias_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        for row in reader:
            norm_string = row.get("normalized_string", "").strip()
            norm_key = normalize_key(norm_string)
            mol_id = mol_by_normalized.get(norm_key)
            
            if mol_id:
                row["molecule_id"] = mol_id
                alias_rows.append(row)
            else:
                unmatched_aliases += 1
    
    log(f"  Matched {len(alias_rows)} / {len(alias_rows) + unmatched_aliases} aliases")
    if unmatched_aliases > 0:
        log(f"  ⚠ {unmatched_aliases} aliases could not be matched (likely combination drugs)\n")
    else:
        log()

    # Step 3: Enrich interactions
    log("Step 3: Enriching interactions...")
    interaction_path = processed_dir / "interactions.csv"
    interaction_rows: list[dict[str, str]] = []
    unmatched_interactions = 0
    unmatched_names: dict[str, int] = {}
    self_loops: list[tuple[str, str, str]] = []
    
    with interaction_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            drug_a = row.get("drug_a", "").strip()
            drug_b = row.get("drug_b", "").strip()
            
            norm_a = normalize_key(drug_a)
            norm_b = normalize_key(drug_b)
            mol_a = mol_by_normalized.get(norm_a)
            mol_b = mol_by_normalized.get(norm_b)
            
            if mol_a and mol_b:
                if mol_a == mol_b and drug_a != drug_b:
                    self_loops.append((drug_a, drug_b, mol_a))
                # Canonical ordering: molecule_id_a <= molecule_id_b
                if mol_a <= mol_b:
                    row["molecule_id_a"] = mol_a
                    row["molecule_id_b"] = mol_b
                else:
                    row["molecule_id_a"] = mol_b
                    row["molecule_id_b"] = mol_a
                
                # Map columns to loader expectations
                row["severity"] = row.get("severity", "")
                row["mechanism"] = row.get("mechanism", "")
                row["provenance"] = row.get("source_file", "ddinter")
                
                interaction_rows.append(row)
            else:
                unmatched_interactions += 1
                if not mol_a:
                    unmatched_names[drug_a] = unmatched_names.get(drug_a, 0) + 1
                if not mol_b:
                    unmatched_names[drug_b] = unmatched_names.get(drug_b, 0) + 1
    
    log(f"  Matched {len(interaction_rows)} / {len(interaction_rows) + unmatched_interactions} interactions")
    if unmatched_interactions > 0:
        log(f"  ⚠ {unmatched_interactions} interactions could not be matched (drugs not in catalog)")
        log("\n--- Top 100 unmatched distinct names ---")
        sorted_unmatched = sorted(unmatched_names.items(), key=lambda x: x[1], reverse=True)[:100]
        for name, count in sorted_unmatched:
            log(f"    {count:>5} {name}")
    if self_loops:
        log("\n--- Self-loops (distinct strings resolving to same molecule_id) ---")
        for da, db, mid in self_loops:
            log(f"    {mid}: '{da}' and '{db}'")
    log()

    # Step 4: Write enriched CSVs
    log("Step 4: Writing enriched CSVs...")
    
    # Write aliases with molecule_id
    alias_out = processed_dir / "alias_bridge_table_final.csv"
    if alias_rows:
        headers = ["raw_string", "normalized_string", "source", "molecule_id"]
        with alias_out.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for row in alias_rows:
                filtered = {k: row.get(k, "") for k in headers}
                writer.writerow(filtered)
        log(f"  Wrote {len(alias_rows)} aliases to {alias_out.name}")
    
    # Write interactions with molecule_ids
    interaction_out = processed_dir / "ddinter_final_clean.csv"
    if interaction_rows:
        headers = ["molecule_id_a", "molecule_id_b", "severity", "mechanism", "provenance"]
        with interaction_out.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for row in interaction_rows:
                filtered = {k: row.get(k, "") for k in headers}
                writer.writerow(filtered)
        log(f"  Wrote {len(interaction_rows)} interactions to {interaction_out.name}\n")
    
    log("=" * 70)
    log("RECONCILIATION COMPLETE")
    log("=" * 70)
    log(f"Aliases:      {len(alias_rows):>6} (expected ~164)")
    log(f"Interactions: {len(interaction_rows):>6} (expected ~160,235)")
    log("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
