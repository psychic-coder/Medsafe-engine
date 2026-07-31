# medsafe-engine

A generic-medicine substitute and prescription-safety engine. Given a prescribed drug string, the
engine normalizes and resolves it to a canonical molecule, finds cheaper generic equivalents (PMBJP
and branded sources) with computed savings, and surfaces known molecule-to-molecule interactions
against the rest of the patient's prescription. It is built on a Neo4j property graph
(`Molecule` / `Product` / `Alias` nodes) with a deliberately conservative entity-resolution policy:
exact and alias-table matches auto-accept, fuzzy matches only ever produce candidates for human
review. A FastAPI service exposes resolution and interaction-check endpoints, and an evaluation
harness with a golden set is developed alongside the engine rather than bolted on afterwards.

## Disclaimer

**This is a decision-support tool, not a diagnostic or dispensing authority.**

Output from this engine is informational and intended to support a qualified professional's
judgement. It must not be used as the sole basis for substituting, dispensing, prescribing, or
withholding any medication. Interaction data is incomplete by construction (see the coverage-gap
note in [docs/schema.md](docs/schema.md)) — an empty interaction result does not mean "safe".

## MVP scope

In scope for the MVP:

- **Phase 0 — Data recon & join.** *(complete)* Source profiling of the PMBJP mirror and DDInter
  dumps, and the bridge table joining them.
- **Phase 1 — Neo4j graph.** Schema, constraints, and loaders for `Molecule`, `Product`, `Alias`
  and their relationships.
- **Phase 2 — Entity resolution.** Normalization, exact/alias matching, fuzzy *candidate*
  generation, and the confusable-pair blocklist.
- **Phase 4 — Pricing & substitution.** Substitute discovery and savings computation for
  single-molecule products.
- **Phase 5 — Response composition.** API responses, including explicit flagging of interaction
  coverage gaps.

Explicitly **out of scope** for the MVP:

- **No OCR.** Input is text; prescription image ingestion is not part of this build.
- **No model fine-tuning.** Resolution is deterministic (normalization + lookup + fuzzy candidates);
  no trained or fine-tuned models.
- **No Phase 3.** Phase 3 is deferred; the MVP jumps from Phase 2 to Phase 4.
- **No FDC-to-FDC substitution.** v1 substitution covers single-molecule products only.

The evaluation harness (`src/medsafe/eval/`) is **not** deferred — it is built alongside each phase.

## Setup

### 1. Environment

```bash
cp .env.example .env
# edit .env — at minimum set NEO4J_PASSWORD
```

When running the API inside docker-compose, `NEO4J_URI` must point at the compose service
(`bolt://neo4j:7687`); from your host shell or a local uvicorn it is `bolt://localhost:7687`.

### 2. Start the stack

```bash
docker compose up -d neo4j     # Neo4j alone (browser on http://localhost:7474, bolt on 7687)
docker compose up              # Neo4j + API
```

The `api` service waits on the `neo4j` healthcheck before starting.

### 3. Local development install

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
# or, with uv:  uv sync --extra dev
```

### 4. Run ingestion

Scripts are run from the repo root, in this order. They read from `data/raw/` (gitignored — obtain
the PMBJP and DDInter sources separately) and write to `data/processed/`.

```bash
python scripts/ingest_pmbjp.py          # PMBJP product catalogue -> processed products
python scripts/ingest_ddinter.py        # DDInter interaction pairs -> processed interactions
python scripts/build_bridge_table.py    # join the two vocabularies -> alias/bridge table
python scripts/load_graph.py            # load processed artifacts into Neo4j
```

### 5. Run the API and tests

```bash
uvicorn medsafe.api.main:app --reload
pytest
ruff check .
```

## Repository layout

| Path | Contents |
| --- | --- |
| `src/medsafe/graph/` | Neo4j schema, loaders, and read queries (Phase 1) |
| `src/medsafe/resolution/` | Normalization, matching, confusable blocklist (Phase 2) |
| `src/medsafe/pricing/` | Substitute discovery and savings (Phase 4) |
| `src/medsafe/safety/` | Interaction lookup and coverage reporting |
| `src/medsafe/api/` | FastAPI app, routes, and response schemas (Phase 5) |
| `src/medsafe/eval/` | Golden set, metrics, and evaluation harness |
| `scripts/` | One-shot ingestion and graph-loading entry points |
| `data/raw/` | Third-party sources — **gitignored, not redistributable** |
| `docs/schema.md` | Locked graph schema and entity-resolution policy |

## Graph schema

The graph schema and the entity-resolution policy are **locked**. See
[docs/schema.md](docs/schema.md). The policy summary, because it matters everywhere:

> Exact match (post-normalization) and the alias/bridge table are the only auto-accept paths. Fuzzy
> matching produces candidates for a human-review queue and is **never** auto-merged. Auto-accepting
> a fuzzy match in this vocabulary is a patient-safety bug.
