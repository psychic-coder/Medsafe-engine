# Demo fixtures

Hand-written artifacts in the exact shape `graph.loader` expects from `data/processed/`. They exist
so the engine can be run and tested end-to-end without the real PMBJP/DDInter sources (which are in
`data/raw/`, gitignored and not redistributable) and without a Neo4j instance.

    MEDSAFE_GRAPH_BACKEND=memory MEDSAFE_SEED_DIR=data/demo uvicorn medsafe.api.main:app

These are **fixtures, not clinical data**. Prices, product ids and the interaction set are
illustrative. The ATC group assignments in `ddinter_coverage.json` are real ATC first levels and are
what drives the covered/not-checked distinction in `safety.interactions`.
