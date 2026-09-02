# Graph schema (locked)

This schema is locked. Do not reinterpret or extend it without an explicit decision to reopen it.

```
(:Molecule {molecule_id, inn_name, category})
    category ∈ {small_molecule, biologic, herbal, vaccine}

(:Product {product_id, source, generic_name_raw, form, strength_raw, mrp})
    source ∈ {PMBJP, branded_csv}

(:Alias {raw_string, normalized_string, source})
    source ∈ {ddinter, pmbjp, manual, rxnorm_dump}

(:Product)-[:CONTAINS {strength, unit}]->(:Molecule)
(:Alias)-[:ALIAS_OF]->(:Molecule)
(:Molecule)-[:INTERACTS_WITH {severity, mechanism, provenance}]->(:Molecule)
    -- canonical ordering molecule_id_a < molecule_id_b, no duplicate reverse edges
(:Product)-[:SUBSTITUTE_FOR {savings_pct, savings_abs}]->(:Product)
    -- v1: single-molecule products only, FDC-to-FDC substitution deferred

Entity resolution policy (locked, non-negotiable):
- Exact match (post-normalization) + Alias/bridge table only for auto-accept.
- Fuzzy matching (RapidFuzz, Levenshtein) may generate CANDIDATES for a human-review queue only.
- NEVER auto-merge a fuzzy match. 67 confirmed dangerous confusable pairs exist in this vocabulary
  (see fuzzy_negative_blocklist.csv) — auto-accepting fuzzy matches is a patient-safety bug, not a
  data-quality bug.

Known data limitation: DDInter bulk source covers ATC groups A,B,D,H,L,P,R,V only — C/J/N/G/M/S
(cardiovascular, anti-infective, CNS, etc.) are not covered by bulk ingestion. Interaction checks
against molecules in the uncovered groups will silently return "no known interaction" rather than
"not checked" unless the API explicitly flags coverage gaps — this must be handled in Phase 5
response composition, not ignored.
```
