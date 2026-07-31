"""Graph write path — idempotent loaders for processed data artifacts.

Takes the outputs of the ingestion scripts in ``data/processed/`` and MERGEs them into Neo4j in
dependency order: ``Molecule`` nodes, then ``Product`` nodes with their ``CONTAINS {strength,
unit}`` edges, then ``Alias`` nodes with ``ALIAS_OF`` edges, then ``INTERACTS_WITH {severity,
mechanism, provenance}`` edges. Enforces the canonical ordering invariant on interaction edges
(``molecule_id_a < molecule_id_b``) so a pair is stored exactly once with no reverse duplicate,
batches writes, and is safe to re-run. Called by ``scripts/load_graph.py``.

# TODO: implement in Phase 1
"""
