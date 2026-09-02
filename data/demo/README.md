# Test fixtures — not the dataset the application serves

Hand-written artifacts in the exact shape `graph.loader` expects from `data/processed/`. **Fifteen
molecules.** They exist so `pytest` and the evaluation harness can run offline, deterministically,
and without a Neo4j instance or the 138k-row interaction table.

They are **not** what the console or the API serve. That is `data/processed/` — the real ingested
dataset, 2,327 molecules and 2,479 products — and every command in the top-level README points
there.

## Do not point a running console at this directory

It would answer real questions from a fifteen-drug catalogue, and the answers would look
indistinguishable from real ones. A user searching for a medicine that is simply absent here gets
"we could not identify that", and a prescription check gets a confident report covering only the
handful of pairs these fixtures happen to contain. Both read as facts about the medicine rather
than facts about the fixture.

## What they are for

- `pytest` seeds an `InMemoryRepository` from here, so a test outcome cannot be changed by
  re-ingesting the real sources.
- `python -m medsafe.eval.harness --seed-dir data/demo` runs the golden set, which is labelled
  against these fifteen molecules. Labelled cases need known correct answers, and the full
  catalogue has not been hand-labelled — this is the one place these fixtures are the right input.

## Contents

Prices, product ids and the interaction set are illustrative. The ATC group assignments in
`ddinter_coverage.json` are real ATC first levels and are what drives the covered / not-checked
distinction in `safety.interactions`.

`brand_aliases.csv` and `combinations.csv` are generated, and are kept here so the fixtures exercise
every stage the loader knows about — without them `load_graph.py` reports the load as incomplete,
which is correct and which the tests assert. Rebuild with:

    python scripts/build_brand_aliases.py --processed-dir data/demo
