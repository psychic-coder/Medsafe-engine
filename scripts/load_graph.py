"""Load processed data artifacts into Neo4j.

Command-line entry point for the graph write path: applies constraints and indexes from
``graph.schema``, then invokes ``graph.loader`` over the artifacts in ``data/processed/`` in
dependency order (molecules, products and ``CONTAINS``, aliases and ``ALIAS_OF``, interaction
edges). Idempotent and re-runnable; reports node and relationship counts per label on completion so
a partial load is visible. Connection details come from ``medsafe.config``.

# TODO: implement in Phase 1
"""
