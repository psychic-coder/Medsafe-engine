"""Graph read path — parameterized Cypher for every query the engine issues.

Centralizes read queries so no Cypher is written inline in the resolution, pricing, safety, or API
layers: exact and alias lookup of a normalized string to a ``Molecule``; products containing a given
molecule; candidate substitute products for a product (single-molecule only in v1); and interaction
edges between a set of molecules, respecting the canonical ordering so a pair is matched in either
direction. Returns plain records for the callers to map into Pydantic models.

Every statement is parameterized — no string interpolation of user input anywhere — and every one is
exercised through :class:`medsafe.graph.repository.Neo4jRepository`. The write-path MERGEs used by
``graph.loader`` live at the bottom of this module so all Cypher in the project sits in one file.
"""

from __future__ import annotations

__all__ = [
    "MOLECULE_BY_EXACT_NAME",
    "MOLECULE_BY_ALIAS",
    "MOLECULE_BY_ID",
    "MOLECULES_BY_IDS",
    "ALL_MOLECULE_NAMES",
    "PRODUCTS_FOR_MOLECULE",
    "PRODUCT_BY_ID",
    "MOLECULES_FOR_PRODUCT",
    "SUBSTITUTE_CANDIDATES",
    "INTERACTIONS_BETWEEN",
    "MERGE_MOLECULE",
    "MERGE_PRODUCT",
    "MERGE_CONTAINS",
    "MERGE_ALIAS",
    "MERGE_INTERACTION",
    "MERGE_SUBSTITUTE_FOR",
    "NODE_COUNTS",
    "RELATIONSHIP_COUNTS",
    "PING",
    "LIST_CONSTRAINTS",
]

# --- Read path: resolution ----------------------------------------------------------------------

# (1) Exact match, post-normalization. Molecule.inn_name is stored already-normalized by the loader,
#     so this is a straight equality lookup, not a CONTAINS/STARTS WITH scan. Auto-accept path.
MOLECULE_BY_EXACT_NAME = """
MATCH (m:Molecule {inn_name: $normalized_string})
RETURN m.molecule_id AS molecule_id,
       m.inn_name    AS inn_name,
       m.category    AS category
ORDER BY m.molecule_id
LIMIT 1
"""

# (2) Alias / bridge-table lookup. Also an auto-accept path.
MOLECULE_BY_ALIAS = """
MATCH (a:Alias {normalized_string: $normalized_string})-[:ALIAS_OF]->(m:Molecule)
RETURN m.molecule_id      AS molecule_id,
       m.inn_name         AS inn_name,
       m.category         AS category,
       a.raw_string       AS alias_raw_string,
       a.normalized_string AS alias_normalized_string,
       a.source           AS alias_source
ORDER BY m.molecule_id
LIMIT 1
"""

MOLECULE_BY_ID = """
MATCH (m:Molecule {molecule_id: $molecule_id})
RETURN m.molecule_id AS molecule_id,
       m.inn_name    AS inn_name,
       m.category    AS category
"""

MOLECULES_BY_IDS = """
MATCH (m:Molecule)
WHERE m.molecule_id IN $molecule_ids
RETURN m.molecule_id AS molecule_id,
       m.inn_name    AS inn_name,
       m.category    AS category
ORDER BY m.molecule_id
"""

# (3) Fuzzy CANDIDATE generation reads the whole vocabulary and scores it in Python (RapidFuzz).
#     Scoring is deliberately not pushed into Cypher: the candidate policy, the blocklist filter and
#     the "never auto-accept" rule all live in medsafe.resolution.matcher, where they are testable.
ALL_MOLECULE_NAMES = """
MATCH (m:Molecule)
OPTIONAL MATCH (a:Alias)-[:ALIAS_OF]->(m)
RETURN m.molecule_id AS molecule_id,
       m.inn_name    AS inn_name,
       m.category    AS category,
       collect(DISTINCT a.normalized_string) AS alias_strings
ORDER BY m.molecule_id
"""

# --- Read path: products and substitution --------------------------------------------------------

PRODUCTS_FOR_MOLECULE = """
MATCH (p:Product)-[c:CONTAINS]->(m:Molecule {molecule_id: $molecule_id})
RETURN p.product_id       AS product_id,
       p.source           AS source,
       p.generic_name_raw AS generic_name_raw,
       p.form             AS form,
       p.strength_raw     AS strength_raw,
       p.mrp              AS mrp,
       c.strength         AS strength,
       c.unit             AS unit,
       COUNT { (p)-[:CONTAINS]->(:Molecule) } AS molecule_count
ORDER BY p.mrp ASC, p.product_id ASC
"""

PRODUCT_BY_ID = """
MATCH (p:Product {product_id: $product_id})
RETURN p.product_id       AS product_id,
       p.source           AS source,
       p.generic_name_raw AS generic_name_raw,
       p.form             AS form,
       p.strength_raw     AS strength_raw,
       p.mrp              AS mrp,
       COUNT { (p)-[:CONTAINS]->(:Molecule) } AS molecule_count
"""

MOLECULES_FOR_PRODUCT = """
MATCH (p:Product {product_id: $product_id})-[c:CONTAINS]->(m:Molecule)
RETURN m.molecule_id AS molecule_id,
       m.inn_name    AS inn_name,
       m.category    AS category,
       c.strength    AS strength,
       c.unit        AS unit
ORDER BY m.molecule_id
"""

# v1 substitution is single-molecule only (docs/schema.md). The molecule_count = 1 predicate on both
# sides is what enforces that: an FDC never appears as a source or as a substitute. Equivalence on
# form/strength and the savings arithmetic are applied by medsafe.pricing.substitution.
SUBSTITUTE_CANDIDATES = """
MATCH (source:Product {product_id: $product_id})-[:CONTAINS]->(m:Molecule)
WITH source, m
WHERE COUNT { (source)-[:CONTAINS]->(:Molecule) } = 1
MATCH (candidate:Product)-[c:CONTAINS]->(m)
WHERE candidate.product_id <> source.product_id
  AND COUNT { (candidate)-[:CONTAINS]->(:Molecule) } = 1
RETURN candidate.product_id       AS product_id,
       candidate.source           AS source,
       candidate.generic_name_raw AS generic_name_raw,
       candidate.form             AS form,
       candidate.strength_raw     AS strength_raw,
       candidate.mrp              AS mrp,
       c.strength                 AS strength,
       c.unit                     AS unit,
       m.molecule_id              AS molecule_id
ORDER BY candidate.mrp ASC, candidate.product_id ASC
"""

# --- Read path: interactions ---------------------------------------------------------------------

# Edges are stored once under canonical ordering (molecule_id_a < molecule_id_b), so an undirected
# MATCH over the id set returns each pair exactly once regardless of the order the caller supplied.
INTERACTIONS_BETWEEN = """
MATCH (a:Molecule)-[r:INTERACTS_WITH]-(b:Molecule)
WHERE a.molecule_id IN $molecule_ids
  AND b.molecule_id IN $molecule_ids
  AND a.molecule_id < b.molecule_id
RETURN a.molecule_id AS molecule_id_a,
       a.inn_name    AS inn_name_a,
       b.molecule_id AS molecule_id_b,
       b.inn_name    AS inn_name_b,
       r.severity    AS severity,
       r.mechanism   AS mechanism,
       r.provenance  AS provenance
ORDER BY a.molecule_id, b.molecule_id
"""

# --- Write path: idempotent MERGEs used by graph.loader -------------------------------------------

MERGE_MOLECULE = """
UNWIND $rows AS row
MERGE (m:Molecule {molecule_id: row.molecule_id})
SET m.inn_name = row.inn_name,
    m.category = row.category
RETURN count(m) AS written
"""

MERGE_PRODUCT = """
UNWIND $rows AS row
MERGE (p:Product {product_id: row.product_id})
SET p.source           = row.source,
    p.generic_name_raw = row.generic_name_raw,
    p.form             = row.form,
    p.strength_raw     = row.strength_raw,
    p.mrp              = row.mrp
RETURN count(p) AS written
"""

MERGE_CONTAINS = """
UNWIND $rows AS row
MATCH (p:Product {product_id: row.product_id})
MATCH (m:Molecule {molecule_id: row.molecule_id})
MERGE (p)-[c:CONTAINS]->(m)
SET c.strength = row.strength,
    c.unit     = row.unit
RETURN count(c) AS written
"""

MERGE_ALIAS = """
UNWIND $rows AS row
MATCH (m:Molecule {molecule_id: row.molecule_id})
MERGE (a:Alias {normalized_string: row.normalized_string})
SET a.raw_string = row.raw_string,
    a.source     = row.source
MERGE (a)-[:ALIAS_OF]->(m)
RETURN count(a) AS written
"""

# rows are pre-ordered canonically by graph.schema.validate_interaction, so MERGE on the directed
# pattern cannot produce a reverse duplicate.
MERGE_INTERACTION = """
UNWIND $rows AS row
MATCH (a:Molecule {molecule_id: row.molecule_id_a})
MATCH (b:Molecule {molecule_id: row.molecule_id_b})
MERGE (a)-[r:INTERACTS_WITH]->(b)
SET r.severity   = row.severity,
    r.mechanism  = row.mechanism,
    r.provenance = row.provenance
RETURN count(r) AS written
"""

MERGE_SUBSTITUTE_FOR = """
UNWIND $rows AS row
MATCH (sub:Product {product_id: row.substitute_product_id})
MATCH (src:Product {product_id: row.product_id})
MERGE (sub)-[s:SUBSTITUTE_FOR]->(src)
SET s.savings_abs = row.savings_abs,
    s.savings_pct = row.savings_pct
RETURN count(s) AS written
"""

# --- Operational -----------------------------------------------------------------------------

PING = "RETURN 1 AS ok"

LIST_CONSTRAINTS = "SHOW CONSTRAINTS YIELD name RETURN collect(name) AS names"

NODE_COUNTS = """
MATCH (n)
UNWIND labels(n) AS label
RETURN label, count(*) AS count
ORDER BY label
"""

RELATIONSHIP_COUNTS = """
MATCH ()-[r]->()
RETURN type(r) AS type, count(r) AS count
ORDER BY type
"""
