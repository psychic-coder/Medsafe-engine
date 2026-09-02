"""Neo4j graph layer.

Owns everything that touches the database: driver lifecycle, schema/constraint definitions
(``schema``), write-path loaders for the processed data artifacts (``loader``), and the read-path
Cypher used by resolution, pricing, and safety (``queries``). The node and relationship shapes are
fixed by ``docs/schema.md``.

# TODO: implement in Phase 1
"""
