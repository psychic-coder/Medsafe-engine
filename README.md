# medsafe-engine

A generic-medicine substitute and prescription-safety engine, with a web console.

Given a prescribed drug string, the engine normalizes and resolves it to a canonical molecule,
finds cheaper generic equivalents (PMBJP and branded sources) with computed savings, and surfaces
known molecule-to-molecule interactions against the rest of the patient's prescription. It is built
on a Neo4j property graph (`Molecule` / `Product` / `Alias` nodes) with a deliberately conservative
entity-resolution policy: exact and alias-table matches auto-accept, fuzzy matches only ever produce
candidates for human review. A FastAPI service exposes resolution and interaction-check endpoints, a
Next.js console consumes them, and an evaluation harness with a golden set is developed alongside
the engine rather than bolted on afterwards.

## Disclaimer

**This is a decision-support tool, not a diagnostic or dispensing authority.**

Output from this engine is informational and intended to support a qualified professional's
judgement. It must not be used as the sole basis for substituting, dispensing, prescribing, or
withholding any medication. Interaction data is incomplete by construction (see the coverage-gap
note in [docs/schema.md](docs/schema.md)) — an empty interaction result does not mean "safe".

---

## Contents

- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [The two guarantees](#the-two-guarantees)
- [Repository layout](#repository-layout)
- [Backend setup](#backend-setup)
- [Web console setup](#web-console-setup)
- [Running with Docker](#running-with-docker)
- [Data pipeline](#data-pipeline)
- [API reference](#api-reference)
- [Evaluation harness](#evaluation-harness)
- [Testing and linting](#testing-and-linting)
- [Configuration reference](#configuration-reference)
- [Design notes](#design-notes)
- [Troubleshooting](#troubleshooting)
- [Scope](#scope)

---

## Quick start

The fastest path to a working system needs no database. The graph is reached through a single
interface with two backends, so the whole pipeline runs in-process against the real dataset in
`data/processed/` — 2,327 molecules, 2,479 products and 138,412 interaction edges.

**Terminal 1 — the API:**

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

MEDSAFE_GRAPH_BACKEND=memory \
MEDSAFE_SEED_DIR=data/processed \
CORS_ALLOW_ORIGINS=http://localhost:3000 \
    uvicorn medsafe.api.main:app --reload
```

`COVERAGE_MANIFEST` and `COMBINATIONS_FILE` already default to their `data/processed/` paths, so
they do not need to be set. Both artifacts are tracked; rebuild them only after changing an input:

```bash
python scripts/build_coverage_manifest.py   # -> data/processed/ddinter_coverage.json
python scripts/build_brand_aliases.py       # -> data/processed/brand_aliases.csv, combinations.csv
```

**Terminal 2 — the web console:**

```bash
cd web
npm install
cp .env.local.example .env.local
npm run dev
```

Open <http://localhost:3000>. The header shows live engine state; it should read **Connected**
with no warnings. Warnings there mean a data file is missing and the engine is answering in a
degraded mode — see [Controls that fail open](#controls-that-fail-open).

To check the API on its own:

```bash
curl "localhost:8000/resolve?drug=Amoxicillin%20500mg%20Capsule"
curl -X POST localhost:8000/check -H 'content-type: application/json' \
     -d '{"drugs":["Warfarin","Ecosprin","Atorvastatin"]}'
```

`data/processed/` is the real ingested dataset and is what every command in this README runs
against. `data/demo/` also exists, but it is **test fixtures only** — 15 molecules in the exact
shape `graph.loader` expects, used by `pytest` and the evaluation harness so the suite stays
offline and fast. Nothing that serves a user reads it, and it should not be pointed at a running
console: it would answer real questions from a 15-drug catalogue.

---

## How it works

A drug string travels through four stages:

1. **Normalization** (`resolution/normalize.py`) strips catalogue noise — pack counts, dosage forms,
   salt names, strength tokens — and produces a comparison key. Nothing is discarded silently: the
   extracted form, strength, and salts all come back in the response.
2. **Matching** (`resolution/matcher.py`) tries an exact match on `Molecule.inn_name`, then the
   alias/bridge table. Either one auto-accepts. Anything else produces ranked *candidates* for a
   human-review queue, filtered through the confusable-pair blocklist.
3. **Substitution** (`pricing/substitution.py`) finds products sharing the resolved molecule via
   `CONTAINS`, checks equivalence (same molecule, comparable strength and unit, compatible form),
   and computes savings against an explicitly stated reference product.
4. **Interaction checking** (`safety/interactions.py`) takes every unordered pair of the resolved
   molecules and looks up `INTERACTS_WITH` edges, then reports *coverage* alongside the hits.

---

## The two guarantees

Two invariants shape the whole codebase, including the UI. Both are enforced structurally rather
than by convention, because both are patient-safety properties rather than data-quality niceties.

### 1. A fuzzy match is never an identification

> Exact match (post-normalization) and the alias/bridge table are the only auto-accept paths. Fuzzy
> matching produces candidates for a human-review queue and is **never** auto-merged.

`ResolvedMatch.path` can only hold `exact` or `alias`, so no value of the type means "resolved by
fuzzy". `ResolutionResult` validates at construction that a match is present if and only if the
status is `resolved`. The fuzzy branch never assigns a match, so no threshold setting reaches that
code path — the threshold decides which candidates are *shown*, never whether one is accepted. The
generated OpenAPI schema inherits the constraint: `MatchOut.path` is an enum of two values, and the
TypeScript types in `web/lib/types.ts` mirror it.

On top of that, the **confusable-pair blocklist** (`data/manual/fuzzy_negative_blocklist.csv`) holds
confirmed look-alike/sound-alike pairs — `hydralazine`/`hydroxyzine`, `vinblastine`/`vincristine`,
`prednisone`/`prednisolone`. Any pair present there is suppressed from candidate output entirely, at
any score. Suppressions are reported in the response for audit rather than hidden.

### 2. "Not checked" is never folded into "no interaction"

The DDInter bulk source covers ATC groups A, B, D, H, L, P, R and V. Groups C, G, J, M, N and S are
**not** covered. So a pair involving atorvastatin (group C) has not been checked, and reporting that
as "no known interaction" would be a confident lie.

`PairStatus` is therefore three-valued — `interaction`, `no_known_interaction`, `not_checked` — and
there is no boolean "interactions found" field anywhere in the API, because a boolean cannot
represent the third state. Coverage fails *closed*: a molecule with no ATC group in the manifest is
treated as not covered, and a missing manifest means nothing is covered.

---

## Repository layout

| Path | Contents |
| --- | --- |
| `src/medsafe/graph/` | Neo4j schema, loaders, and read queries (Phase 1) |
| `src/medsafe/resolution/` | Normalization, matching, confusable blocklist (Phase 2) |
| `src/medsafe/pricing/` | Substitute discovery and savings (Phase 4) |
| `src/medsafe/safety/` | Interaction lookup and coverage reporting |
| `src/medsafe/api/` | FastAPI app, routes, and response schemas (Phase 5) |
| `src/medsafe/explain.py` | Plain-English rendering of every engine state |
| `src/medsafe/eval/` | Golden set, metrics, and evaluation harness |
| `scripts/` | One-shot ingestion and graph-loading entry points |
| `tests/` | Test suite — offline, no database required |
| `web/` | Next.js + TypeScript + Tailwind console |
| `data/raw/` | Third-party sources — **gitignored, not redistributable** |
| `data/processed/` | Ingestion outputs consumed by the graph loader |
| `data/manual/` | Hand-curated files: the confusable-pair blocklist and the brand pack |
| `data/demo/` | Test fixtures only — 15 molecules, used by `pytest` and the eval harness |
| `docs/schema.md` | Locked graph schema and entity-resolution policy |

---

## Backend setup

### 1. Environment

```bash
cp .env.example .env
# edit .env — at minimum set NEO4J_PASSWORD
```

When running the API inside docker-compose, `NEO4J_URI` must point at the compose service
(`bolt://neo4j:7687`); from your host shell or a local uvicorn it is `bolt://localhost:7687`.

### 2. Install

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
# or, with uv:  uv sync --extra dev
```

Requires Python 3.11 or newer.

### 3. Run the API

```bash
# Against Neo4j (see "Running with Docker" to start one)
uvicorn medsafe.api.main:app --reload

# Against the in-process graph, no database needed. Same dataset, no Neo4j.
MEDSAFE_GRAPH_BACKEND=memory MEDSAFE_SEED_DIR=data/processed \
    uvicorn medsafe.api.main:app --reload

# Bind explicitly
uvicorn medsafe.api.main:app --host 0.0.0.0 --port 8000
```

Interactive API docs are at <http://localhost:8000/docs>; the OpenAPI schema is at
<http://localhost:8000/openapi.json>.

Startup never fails because the database is down. The driver is constructed lazily and a failure is
recorded, so `/health` still answers and `/health/ready` reports 503 *with the reason*.

---

## Web console setup

The console is a Next.js 16 app (React 19, TypeScript, Tailwind CSS) in `web/`. It is a pure client
of the API and holds no data of its own.

```bash
cd web
npm install
cp .env.local.example .env.local     # sets NEXT_PUBLIC_API_BASE_URL
```

| Command | What it does |
| --- | --- |
| `npm run dev` | Development server with hot reload on <http://localhost:3000> |
| `npm run build` | Production build |
| `npm start` | Serve the production build (run `build` first) |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run lint` | ESLint |

### The CORS pairing

The console runs on a different origin (`:3000`) from the API (`:8000`), so **the API must name the
console's origin** or every browser request fails at the preflight:

```bash
CORS_ALLOW_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

and the console must be told where the API is:

```bash
# web/.env.local
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

These two must agree. `NEXT_PUBLIC_API_BASE_URL` is read by the *browser*, so it must be a URL the
browser can reach — not a Docker service name. Setting `CORS_ALLOW_ORIGINS=*` allows any origin and
is fine for local development, but it also disables credentialed requests.

---

## Running with Docker

The default Docker stack uses the project’s original processed dataset from `data/processed/` and loads it into a Neo4j graph before the API becomes healthy. The demo fixtures remain available as an explicit override when you want a lightweight smoke test.

```bash
docker compose up --build
```

Open <http://localhost:3000> for the console, <http://localhost:8000/docs> for the API docs, and <http://localhost:7474> for the Neo4j browser. The `graph-loader` service runs once at startup and loads `data/processed/` into the graph before the API becomes healthy.

Useful commands:

```bash
docker compose logs -f api          # follow API logs
docker compose logs -f graph-loader # inspect the initial graph load
docker compose down                 # stop
docker compose down -v              # stop and delete graph data
docker compose exec neo4j cypher-shell -u neo4j -p "$NEO4J_PASSWORD"
```

The stack loads `data/processed/` — the real dataset — into Neo4j before the API becomes healthy.
Nothing in the compose file reads `data/demo/`.

To run only the database and not the full stack:

```bash
docker compose up -d neo4j
```

---

## Data pipeline

Scripts are run from the repo root, in this order. They read from `data/raw/` (gitignored — obtain
the PMBJP and DDInter sources separately) and write to `data/processed/`.

```bash
python scripts/ingest_pmbjp.py        # PMBJP catalogue -> products.csv, pmbjp_aliases.csv
python scripts/ingest_ddinter.py      # DDInter pairs   -> interactions.csv, ddinter_aliases.csv,
                                      #                    ddinter_coverage.json
python scripts/build_bridge_table.py  # join vocabularies -> molecules.csv, aliases.csv, contains.csv
python scripts/build_coverage_manifest.py  # rebuild ddinter_coverage.json from repo artifacts
python scripts/build_brand_aliases.py     # validate the brand pack -> brand_aliases.csv,
                                          #                            combinations.csv
python scripts/load_graph.py          # load everything into Neo4j
```

Each accepts `--help`. Common options:

```bash
python scripts/ingest_pmbjp.py --input data/raw/pmbjp_products.csv --output data/processed
python scripts/ingest_ddinter.py --input data/raw/ddinter_interactions.csv --atc data/raw/ddinter_atc.csv
python scripts/build_bridge_table.py --propose   # also emit review_candidates.csv
python scripts/load_graph.py --processed-dir data/processed --dry-run
```

Supporting scripts: `scripts/generate_contains.py` (rebuild the `CONTAINS` edge list from product
components) and `scripts/reconcile_data.py` (report how much of each source actually joined).

### Artifact names

The loader accepts two naming conventions for the same artifacts, because the ingestion scripts emit
canonical names while the curated snapshots carry the name of the pipeline stage that produced them.
Reports are always keyed by the logical stage name.

| Stage | Filenames accepted (first match wins) | Columns |
| --- | --- | --- |
| `molecules` | `molecules.csv`, `molecule_catalog.csv` | molecule_id, inn_name, category |
| `products` | `products.csv`, `pmbjp_final_clean.csv` | product_id, source, generic_name_raw, form, strength_raw, mrp |
| `contains` | `contains.csv` | product_id, molecule_id, strength, unit |
| `aliases` | `aliases.csv`, `alias_bridge_table_final.csv` | raw_string, normalized_string, source, molecule_id |
| `interactions` | `interactions.csv`, `ddinter_final_clean.csv` | molecule_id_a, molecule_id_b, severity, mechanism, provenance |

A `.json` list-of-objects is accepted for any stage. A missing file is reported as *skipped* rather
than raising — a partial load must be visible, not fatal.

### The brand pack, and why brands are a build step

`data/manual/brand_aliases_india.csv` maps the name printed on an Indian pack to its active
ingredients. It exists because the catalogue is keyed on INN/USAN names and nobody outside a
pharmacy writes those: without it, `Ecosprin`, `Glycomet 500`, `Dolo 650` — and `aspirin` and
`paracetamol`, which the catalogue holds as `acetylsalicylic acid` and `acetaminophen` — all
resolve to nothing, and a patient reads that as "this medicine is unknown".

The alias table is an auto-accept path, so the pack is validated by `scripts/build_brand_aliases.py`
before any of it reaches the graph, and a row that fails is rejected loudly rather than dropped:

- every ingredient must exist in the molecule catalogue;
- no brand may collide with a molecule name, or with another brand on different ingredients;
- the confusable-pair blocklist is enforced, so a curated alias cannot become an auto-accept route
  around the guard the rest of the engine obeys (this is why `vitamin c` is *not* in the pack — the
  blocklist lists `vitamin a`/`vitamin-c` as a dangerous pair);
- an existing alias always wins, so the pack is additive and never overwrites an entry from another
  vocabulary.

**Combination packs are never collapsed to one ingredient.** Augmentin is amoxicillin *and*
clavulanic acid. Mapping it to amoxicillin alone would drop the other ingredient out of the pairwise
interaction set while the report still said "checked" — the coverage lie the engine exists to
prevent, reached through resolution instead of through coverage. Multi-ingredient rows become
`combinations.csv`, resolve to a `combination` status carrying every component, expand into the
pairwise set, and are refused for substitution with `out_of_scope_fdc`.

### Rebuilding the coverage manifest

`ingest_ddinter.py` emits `ddinter_coverage.json` only when handed the raw per-drug ATC file, which
lives under gitignored `data/raw/`. `scripts/build_coverage_manifest.py` reconstructs it from
artifacts already in the repository, in two tiers:

| Tier | Source | Can grant coverage? |
| --- | --- | --- |
| 1 | `ddinter_anchor_profile.csv`, rows at full `anchor_concentration` | yes |
| 2 | `atc_stem_rules.csv` — WHO INN stems | no, uncovered groups only |

The tiering is the whole point. DDInter ships one file per ATC group, and a drug appears in a file
either as that file's *anchor* or merely as the partner in someone else's row — only the first says
anything about the drug's own group. Reading a group off the interaction table's `provenance`
column cannot tell those apart, and reports atorvastatin as covered group L on the strength of rows
anchored by something else; atorvastatin is a statin, group C, which DDInter never shipped. That
shortcut is left unused on purpose, and `build_manifest` asserts that no inference tier ever granted
a covered group.

### The confusable-pair blocklist

`data/manual/fuzzy_negative_blocklist.csv` is a hand-maintained safety control. It accepts either
column vocabulary (`molecule_a`/`molecule_b` or `name_a`/`name_b`; `origin` or `source`):

```csv
molecule_a,molecule_b,edit_distance,verdict,reason,origin
hydralazine,hydroxyzine,3,dangerous,classic look-alike pair - unrelated indications,lasa_curated
```

If a row's two names normalize to the **same** key, loading raises `ConfigurationError`. That is not
a typo check: it means a normalization rule has merged two drugs the blocklist says must stay apart,
and every downstream guarantee rests on those keys differing.

---

## API reference

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness. Touches nothing external, stays 200 without a graph. |
| `GET` | `/health/ready` | Readiness. 503 when the graph is unreachable or empty. |
| `GET` | `/resolve?drug=…` | Resolve one drug string, with substitutes. |
| `POST` | `/resolve` | Same, with a JSON body. |
| `POST` | `/check` | Pairwise interaction check across a prescription. |
| `GET` | `/suggest?q=…` | Type-ahead over names the engine can actually resolve. |

### `GET /resolve`

| Parameter | Type | Default | Notes |
| --- | --- | --- | --- |
| `drug` | string | required | 1–300 characters |
| `include_substitutes` | bool | `true` | Substitutes are only ever attached to a *resolved* molecule |

```bash
curl "localhost:8000/resolve?drug=Amoxicillin%20500mg%20Capsule"
```

Key response fields:

- `status` — `resolved` | `needs_review` | `unresolved`
- `match` — populated **only** when `status == "resolved"`; `path` is `exact` or `alias`
- `candidates[]` — unaccepted fuzzy suggestions, each carrying `requires_human_review: true`
- `suppressed[]` — candidates withheld by the blocklist, disclosed for audit
- `substitution` — `status`, the `reference` product the savings are measured against,
  `substitutes[]` with `savings_abs` and `savings_pct`, and `excluded[]` with reasons

A fixed-dose combination returns `substitution.status = "out_of_scope_fdc"`. Substituting on one
component of a combination is unsafe, so v1 refuses rather than partially substituting.

### `POST /check`

```bash
curl -X POST localhost:8000/check -H 'content-type: application/json' \
     -d '{"drugs":["Warfarin","Ecosprin","Atorvastatin"]}'
```

Accepts 1–50 drug strings. Every unordered pair appears exactly once, **including** pairs involving
unresolved inputs — a drug nobody could identify is the least safe thing to omit from a report.

- `pairs[].status` — `interaction` | `no_known_interaction` | `not_checked`
- `pairs[].reason` — why a pair was not checked
- `coverage_complete` — false when any pair was unchecked. **False does not mean interactions exist.**
- `summary` — counts for `pairs_total`, `interactions_found`, `checked_no_interaction`, `not_checked`

### Errors

Every non-2xx response has the same shape. No route returns a bare 500 body.

```json
{ "error": { "code": "graph_unavailable", "message": "…", "detail": null } }
```

| Code | HTTP | Meaning |
| --- | --- | --- |
| `validation_error` | 422 | Request failed schema validation |
| `resolution_error` | 422 | Input could not be processed into a comparison key |
| `schema_violation` | 422 | A write violates the locked schema |
| `out_of_scope` | 422 | Well-formed but outside v1 scope |
| `graph_unavailable` | 503 | Graph backend unreachable or a driver-level failure |
| `configuration_error` | 500 | Runtime settings missing or invalid |
| `internal_error` | 500 | Unhandled failure |

---

## Evaluation harness

The harness is not deferred — it is built alongside each phase.

The golden set is labelled against the `data/demo/` fixtures, so the harness runs there rather than
on the full dataset — a labelled case needs a known correct answer, and 2,327 molecules have not
been hand-labelled. This is the one place `data/demo/` is the right input.

```bash
python -m medsafe.eval.harness --seed-dir data/demo            # human-readable report
python -m medsafe.eval.harness --seed-dir data/demo --json     # machine-readable, for CI
python -m medsafe.eval.harness --seed-dir data/demo --threshold 70   # sweep the fuzzy threshold
```

Exit code is non-zero when the run fails. **A single false accept or blocklist violation fails the
run outright**, whatever the coverage numbers say — see `src/medsafe/eval/metrics.py`.

Expected output on the demo fixtures:

```
golden set run — PASS

resolution
  labelled cases       13
  blocklist guards     212
  auto-accept coverage 69.2%
  accept precision     100.0%
  FALSE ACCEPTS        0
  BLOCKLIST VIOLATIONS 0
```

---

## Testing and linting

```bash
pytest                      # 419 tests, offline, no database required
pytest -q                   # quiet
pytest tests/test_api.py    # one file
pytest -k blocklist         # by name
pytest --cov=medsafe        # coverage (needs pytest-cov)

ruff check .                # lint
ruff check --fix .          # autofix
```

The suite is deterministic and offline. The graph is an `InMemoryRepository` seeded from the
`data/demo/` **test fixtures** — deliberately, so a test run does not depend on a 138k-row
interaction table and cannot be changed by re-ingesting the real sources. It enforces the same
constraints as Neo4j, and settings are constructed directly so an ambient `NEO4J_URI` or a stale
`.env` cannot change a test outcome. The application itself never reads `data/demo/`.

Frontend checks:

```bash
cd web && npm run typecheck && npm run lint && npm run build
```

---

## Configuration reference

Settings load from the process environment, then `.env`, then declared defaults — so an exported
variable or a docker-compose `environment:` block always wins over a stale local file.

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEO4J_URI` | `bolt://localhost:7687` | Bolt endpoint. Inside compose: `bolt://neo4j:7687` |
| `NEO4J_USER` | `neo4j` | |
| `NEO4J_PASSWORD` | *(empty)* | Required for the Neo4j backend |
| `NEO4J_DATABASE` | `neo4j` | |
| `API_HOST` | `0.0.0.0` | |
| `API_PORT` | `8000` | |
| `LOG_LEVEL` | `INFO` | |
| `CORS_ALLOW_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated browser origins. `*` allows any |
| `MEDSAFE_GRAPH_BACKEND` | `neo4j` | `neo4j` or `memory` |
| `MEDSAFE_SEED_DIR` | *(unset)* | Artifacts to seed the in-memory backend from |
| `DATA_RAW_DIR` | `data/raw` | |
| `DATA_PROCESSED_DIR` | `data/processed` | |
| `DATA_MANUAL_DIR` | `data/manual` | |
| `FUZZY_CANDIDATE_THRESHOLD` | `88` | Score at/above which a pair becomes a review **candidate**. Never an auto-accept threshold |
| `FUZZY_MAX_CANDIDATES` | `5` | |
| `FUZZY_NEGATIVE_BLOCKLIST` | `data/manual/fuzzy_negative_blocklist.csv` | |
| `COVERAGE_MANIFEST` | `data/processed/ddinter_coverage.json` | Absent manifest ⇒ every pair reports `not_checked` |
| `COMBINATIONS_FILE` | `data/processed/combinations.csv` | Absent file ⇒ combination pack names do not resolve |

Frontend (`web/.env.local`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Read by the browser, so it must be browser-reachable |

### Controls that fail open

Two controls let the engine keep answering when their data files are missing, which makes them easy
to lose silently. Both are reported by `/health/ready` and in the console header:

- **Confusable-pair blocklist missing** — fuzzy candidates are unguarded.
- **Coverage manifest missing** — no pair can be reported as checked.
- **Combination index missing** — multi-ingredient pack names do not resolve.

---

## Design notes

### Plain English is a safety control, not presentation

Every state the engine can be in has a precise name — `not_checked`, `needs_review`,
`out_of_scope_fdc`, ATC group `C`. Those names are right for the API contract and unreadable to the
person the answer is for, and the failure mode is not confusion. It is that they guess, and the
guesses run the dangerous way: "not checked" gets read as "checked, fine", and "no match" as "this
medicine is unsafe" rather than "we could not read the name".

`src/medsafe/explain.py` renders every state into a `headline` / `detail` / `action` triple carried
on the response, so the sentence a human reads is produced in one place rather than reinvented by
each client from the enum names. `tests/test_explain.py` asserts the two properties that matter
across every renderable state: **no unchecked or unidentified state uses reassuring language**, and
**no recorded finding is hedged**. That test caught the phrase "not that the combination is fine" —
a negation, but a skimming reader takes "fine" and drops the "not".

### Type-ahead, because a dead end is not an answer

Most "we could not identify that" results are a spelling problem, and the user cannot fix it because
the thing they would search with is the thing they got wrong. `/suggest` offers names the engine is
guaranteed to resolve, so the dead end never happens.

Confusable names there are **flagged, not hidden**. The matcher's rule is to drop both members of a
blocklisted pair, which is free — the drug still resolves by exact match. Applying it to a dropdown
is not free: metoprolol, methotrexate and dexamethasone are each blocklisted against some neighbour,
so a blanket suppression means typing "met" returns a list with all three missing and the user
concludes the tool does not know their medicine. Each row instead carries the names it looks like,
which gives a reader holding the box *more* information at the moment it matters.

### The visual system

The console is built around one idea: a result's *epistemic status* is the most important thing on
the screen, so it is carried by the surface treatment rather than by a colour alone.

- **Confirmed** — solid stock, full ink.
- **Needs a human** — a diagonal hatch, literally "not signed off".
- **Not checked** — hollow, dashed rule, desaturated.

Status glyphs differ in *shape* as well as colour (filled, half, hollow), so the three states stay
distinguishable in greyscale and for colour-blind readers. "Not checked" is a neutral slate rather
than red or green on purpose: a coverage gap is neither an alarm nor a reassurance, and colouring it
as either would misreport it.

Interaction results are sorted interactions → not checked → clear. Burying coverage gaps under a
list of reassuring rows is how a gap gets missed.

Savings are never shown without their baseline. The engine computes them against a stated reference
product — when no prescribed product was supplied it uses the most expensive equivalent — so the
console puts the reference in the section heading rather than in a footnote.

Explanatory safety prose is set in a serif, giving it the voice of a printed package insert and
distinguishing the text a pharmacist must actually weigh from interface chrome. Monospace is
reserved strictly for real identifiers (`MOL001`, `PRD003`), which are codes rather than labels.

---

## Troubleshooting

**The console header says "Engine unreachable".**
The API is not running, or the browser blocked the request. Check `curl localhost:8000/health`. If
the API is up, confirm the console's origin appears in `CORS_ALLOW_ORIGINS` and that
`NEXT_PUBLIC_API_BASE_URL` points somewhere the *browser* can reach.

**`/health/ready` returns 503 with "contains no Molecule nodes".**
The graph is reachable but empty. Run the [data pipeline](#data-pipeline), or start the API with
`MEDSAFE_GRAPH_BACKEND=memory MEDSAFE_SEED_DIR=data/processed`.

**"confusable-pair blocklist is empty or missing — fuzzy candidates are UNGUARDED".**
`FUZZY_NEGATIVE_BLOCKLIST` points at a file that does not exist, or the CSV has no recognised name
columns. It must have `molecule_a`/`molecule_b` or `name_a`/`name_b`.

**`ConfigurationError: Blocklisted confusable pair normalizes to a single key`.**
Two names the blocklist calls distinct drugs now normalize identically. Either the row is a false
positive (two spellings of the same substance — remove it), or a normalization rule is over-merging
and needs narrowing. Do not silence this.

**Every pair reports `not_checked`.**
The coverage manifest is missing. Run `python scripts/build_coverage_manifest.py`, which rebuilds it
from artifacts already in the repo, or point `COVERAGE_MANIFEST` at a manifest produced by
`scripts/ingest_ddinter.py`.

**A well-known brand name is "not found".**
The brand pack has not been built. Run `python scripts/build_brand_aliases.py` and reload the graph.
If one specific brand is missing, add a row to `data/manual/brand_aliases_india.csv` and re-run —
the build reports exactly why any row was rejected.

**A load reports stages as SKIPPED.**
The artifact files are absent under either accepted filename. See
[Artifact names](#artifact-names).

**Port already in use.**
`uvicorn --port 8001`, or `npm run dev -- -p 3001` for the console (remember to update
`CORS_ALLOW_ORIGINS`).

---

## Scope

In scope for the MVP:

- **Phase 0 — Data recon & join.** Source profiling of the PMBJP mirror and DDInter dumps, and the
  bridge table joining them.
- **Phase 1 — Neo4j graph.** Schema, constraints, and loaders.
- **Phase 2 — Entity resolution.** Normalization, exact/alias matching, fuzzy *candidate*
  generation, and the confusable-pair blocklist.
- **Phase 4 — Pricing & substitution.** Substitute discovery and savings for single-molecule
  products.
- **Phase 5 — Response composition.** API responses and the web console, including explicit flagging
  of interaction coverage gaps.

Explicitly **out of scope**:

- **No OCR.** Input is text; prescription image ingestion is not part of this build.
- **No model fine-tuning.** Resolution is deterministic — normalization, lookup, and fuzzy
  candidates.
- **No Phase 3.** Deferred; the MVP jumps from Phase 2 to Phase 4.
- **No FDC-to-FDC substitution.** v1 substitution covers single-molecule products only.
