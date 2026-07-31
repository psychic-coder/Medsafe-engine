"""Ingest the PMBJP product catalogue into a processed product table.

Reads the raw PMBJP mirror from ``data/raw/`` (gitignored, not redistributable), parses each row
into the ``Product`` shape from ``docs/schema.md`` — ``product_id``, ``source="PMBJP"``,
``generic_name_raw``, ``form``, ``strength_raw``, ``mrp`` — runs the generic name through
``resolution.normalize`` to emit ``Alias`` rows with ``source="pmbjp"``, and writes the result to
``data/processed/``. Reports rows it could not parse rather than dropping them silently. Read-only
with respect to Neo4j; ``load_graph.py`` does the writing.

# TODO: implement in Phase 1
"""
