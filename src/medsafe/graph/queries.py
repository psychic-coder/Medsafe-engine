"""Graph read path — parameterized Cypher for every query the engine issues.

Centralizes read queries so no Cypher is written inline in the resolution, pricing, safety, or API
layers: exact and alias lookup of a normalized string to a ``Molecule``; products containing a given
molecule; candidate substitute products for a product (single-molecule only in v1); and interaction
edges between a set of molecules, respecting the canonical ordering so a pair is matched in either
direction. Returns plain records for the callers to map into Pydantic models.

# TODO: implement in Phase 1
"""
