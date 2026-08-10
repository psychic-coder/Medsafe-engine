"""Load processed data artifacts into Neo4j.

Command-line entry point for the graph write path: applies constraints and indexes from
``graph.schema``, then invokes ``graph.loader`` over the artifacts in ``data/processed/`` in
dependency order (molecules, products and ``CONTAINS``, aliases and ``ALIAS_OF``, interaction
edges). Idempotent and re-runnable; reports node and relationship counts per label on completion so
a partial load is visible. Connection details come from ``medsafe.config``.

    python scripts/load_graph.py
    python scripts/load_graph.py --processed-dir data/demo --dry-run

``--dry-run`` loads into the in-memory backend instead of Neo4j, which validates every row against
the locked schema without writing anything — useful for checking a fresh ingestion before it
touches the database.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from medsafe.config import get_settings  # noqa: E402
from medsafe.errors import MedsafeError  # noqa: E402
from medsafe.graph.loader import load_artifacts  # noqa: E402
from medsafe.graph.repository import (  # noqa: E402
    GraphRepository,
    InMemoryRepository,
    Neo4jRepository,
)

logger = logging.getLogger("medsafe.load_graph")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--processed-dir", type=Path, default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate against the in-memory backend without writing to Neo4j.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Abort on the first invalid row instead of rejecting and reporting it.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the load report as JSON.")
    args = parser.parse_args(argv)

    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO))
    processed_dir = args.processed_dir or settings.data_processed_dir

    if not Path(processed_dir).is_dir():
        print(f"error: {processed_dir} does not exist — run the ingestion scripts first")
        return 2

    repository: GraphRepository
    if args.dry_run:
        repository = InMemoryRepository()
        target = "in-memory (dry run)"
    else:
        repository = Neo4jRepository(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database=settings.neo4j_database,
        )
        target = settings.neo4j_uri

    try:
        report = load_artifacts(repository, processed_dir, strict=args.strict)
    except MedsafeError as exc:
        print(f"error: {exc.code}: {exc.message}")
        if exc.detail:
            print(json.dumps(exc.detail, indent=2, default=str))
        return 1
    finally:
        if not args.dry_run:
            repository.close()

    if args.json:
        print(json.dumps(report.as_dict(), indent=2, default=str))
    else:
        print(f"loaded {processed_dir} -> {target}")
        print("\n".join(report.summary_lines()))

    # A skipped stage or a rejected row is a non-zero exit: a partial load must not look like a
    # clean one to whatever ran this.
    return 0 if report.complete else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:  # piping into head/less closes the stream early
        sys.exit(0)
