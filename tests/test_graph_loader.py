"""Tests for ``medsafe.graph.loader`` and ``medsafe.graph.schema``.

# TODO: TestConstraintsApplied — uniqueness on molecule_id, product_id, alias normalized_string
# TODO: TestMoleculeLoad — nodes created with valid category enum; invalid category rejected
# TODO: TestProductLoad — source enum enforced (PMBJP, branded_csv); mrp/strength_raw preserved
# TODO: TestContainsEdge — CONTAINS carries strength and unit
# TODO: TestAliasLoad — Alias nodes and ALIAS_OF edges; source enum enforced
# TODO: TestInteractionCanonicalOrdering — edge stored with molecule_id_a < molecule_id_b
# TODO: TestNoDuplicateReverseEdge — loading both (a,b) and (b,a) yields exactly one edge
# TODO: TestIdempotentReload — running the loader twice does not duplicate nodes or edges
# TODO: TestPartialLoadReporting — counts reported per label so an incomplete load is visible
"""
