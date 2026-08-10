"""Graph write path — idempotent loaders for processed data artifacts.

Takes the outputs of the ingestion scripts in ``data/processed/`` and MERGEs them into Neo4j in
dependency order: ``Molecule`` nodes, then ``Product`` nodes with their ``CONTAINS {strength,
unit}`` edges, then ``Alias`` nodes with ``ALIAS_OF`` edges, then ``INTERACTS_WITH {severity,
mechanism, provenance}`` edges. Enforces the canonical ordering invariant on interaction edges
(``molecule_id_a < molecule_id_b``) so a pair is stored exactly once with no reverse duplicate,
batches writes, and is safe to re-run. Called by ``scripts/load_graph.py``.

The loader writes through :class:`medsafe.graph.repository.GraphRepository`, so the same code path
and the same idempotency guarantees apply to Neo4j and to the in-memory backend used by tests.

Expected artifact files in ``data/processed/`` (CSV, header row required; ``.json`` list-of-objects
is also accepted for each):

===================  =========================================================================
molecules.csv        molecule_id, inn_name, category
products.csv         product_id, source, generic_name_raw, form, strength_raw, mrp
contains.csv         product_id, molecule_id, strength, unit
aliases.csv          raw_string, normalized_string, source, molecule_id
interactions.csv     molecule_id_a, molecule_id_b, severity, mechanism, provenance
===================  =========================================================================

A missing file is reported as skipped rather than raising: a partial load must be *visible*, not
fatal, so an operator can see exactly which stage did not run.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from medsafe.errors import SchemaViolationError
from medsafe.graph.repository import GraphRepository

__all__ = ["LoadReport", "ArtifactSet", "load_artifacts", "load_records", "read_artifact"]

MOLECULES_FILE = "molecules"
PRODUCTS_FILE = "products"
CONTAINS_FILE = "contains"
ALIASES_FILE = "aliases"
INTERACTIONS_FILE = "interactions"

# Dependency order is load-bearing: an edge whose endpoints do not exist yet is silently dropped by
# a MATCH-based MERGE, so nodes must always precede the edges that reference them.
LOAD_ORDER: tuple[str, ...] = (
    MOLECULES_FILE,
    PRODUCTS_FILE,
    CONTAINS_FILE,
    ALIASES_FILE,
    INTERACTIONS_FILE,
)

Record = dict[str, Any]


@dataclass
class LoadReport:
    """Per-stage outcome of a load. Printed by ``scripts/load_graph.py``."""

    written: dict[str, int] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    counts_before: dict[str, dict[str, int]] = field(default_factory=dict)
    counts_after: dict[str, dict[str, int]] = field(default_factory=dict)
    schema_statements: int = 0

    @property
    def complete(self) -> bool:
        """True when every stage ran and nothing was rejected."""
        return not self.skipped and not self.rejected

    def as_dict(self) -> dict[str, Any]:
        return {
            "written": dict(self.written),
            "skipped": list(self.skipped),
            "rejected": list(self.rejected),
            "counts_before": self.counts_before,
            "counts_after": self.counts_after,
            "schema_statements": self.schema_statements,
            "complete": self.complete,
        }

    def summary_lines(self) -> list[str]:
        lines = [f"schema statements applied: {self.schema_statements}"]
        for stage in LOAD_ORDER:
            if stage in self.skipped:
                lines.append(f"  {stage:<14} SKIPPED (artifact not found)")
            else:
                lines.append(f"  {stage:<14} {self.written.get(stage, 0):>7} rows")
        for label, count in sorted(self.counts_after.get("nodes", {}).items()):
            lines.append(f"  node  {label:<14} {count:>7}")
        for rel_type, count in sorted(self.counts_after.get("relationships", {}).items()):
            lines.append(f"  rel   {rel_type:<14} {count:>7}")
        if self.rejected:
            lines.append(f"  REJECTED ROWS: {len(self.rejected)} (see report.rejected)")
        if self.skipped:
            lines.append(f"  INCOMPLETE LOAD: {len(self.skipped)} stage(s) skipped")
        return lines


@dataclass
class ArtifactSet:
    """In-memory equivalent of the processed directory, used by tests and the eval harness."""

    molecules: list[Record] = field(default_factory=list)
    products: list[Record] = field(default_factory=list)
    contains: list[Record] = field(default_factory=list)
    aliases: list[Record] = field(default_factory=list)
    interactions: list[Record] = field(default_factory=list)


def _coerce_scalar(value: str) -> Any:
    """CSV gives strings; turn empties into None so optional properties stay unset."""
    stripped = value.strip()
    return stripped if stripped != "" else None


def read_artifact(processed_dir: Path, stem: str) -> list[Record] | None:
    """Read ``<stem>.csv`` (preferred) or ``<stem>.json``. Returns ``None`` when neither exists."""
    csv_path = processed_dir / f"{stem}.csv"
    if csv_path.is_file():
        with csv_path.open(newline="", encoding="utf-8") as handle:
            return [
                {key: _coerce_scalar(value or "") for key, value in row.items() if key}
                for row in csv.DictReader(handle)
            ]
    json_path = processed_dir / f"{stem}.json"
    if json_path.is_file():
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise SchemaViolationError(
                f"{json_path.name} must contain a list of objects", detail={"path": str(json_path)}
            )
        return list(payload)
    return None


def _normalize_keys(stage: str, rows: list[Record]) -> list[Record]:
    """Re-normalize the comparison keys on write.

    ``Molecule.inn_name`` and ``Alias.normalized_string`` are the keys the exact and alias lookups
    compare against, so they must be in the key space produced by
    :func:`medsafe.resolution.normalize.normalize_key`. Applying it here rather than trusting the
    ingestion scripts means the graph can never drift out of step with the current normalization
    rules, and it is idempotent, so re-running the loader is still a no-op.
    """
    from medsafe.resolution.normalize import normalize_key

    if stage == MOLECULES_FILE:
        return [{**row, "inn_name": normalize_key(str(row.get("inn_name") or ""))} for row in rows]
    if stage == ALIASES_FILE:
        prepared = []
        for row in rows:
            source_string = row.get("normalized_string") or row.get("raw_string") or ""
            prepared.append({**row, "normalized_string": normalize_key(str(source_string))})
        return prepared
    return rows


def _merge_stage(
    repo: GraphRepository,
    report: LoadReport,
    stage: str,
    rows: Iterable[Record] | None,
    strict: bool,
) -> None:
    """Run one merge stage, recording rows written, rejected rows, or a skip."""
    if rows is None:
        report.skipped.append(stage)
        return
    rows = _normalize_keys(stage, list(rows))
    merge = {
        MOLECULES_FILE: repo.merge_molecules,
        PRODUCTS_FILE: repo.merge_products,
        CONTAINS_FILE: repo.merge_contains,
        ALIASES_FILE: repo.merge_aliases,
        INTERACTIONS_FILE: repo.merge_interactions,
    }[stage]

    if strict:
        report.written[stage] = merge(rows)
        return

    # Non-strict: reject bad rows individually so one malformed line cannot abort a whole load.
    accepted: list[Record] = []
    for row in rows:
        try:
            merge([row])
        except SchemaViolationError as exc:
            report.rejected.append({"stage": stage, "error": exc.message, "detail": exc.detail})
        else:
            accepted.append(row)
    report.written[stage] = len(accepted)


def load_records(
    repo: GraphRepository,
    artifacts: ArtifactSet,
    *,
    apply_schema: bool = True,
    strict: bool = True,
) -> LoadReport:
    """Load an :class:`ArtifactSet` already in memory. Idempotent: re-running is a no-op."""
    report = LoadReport()
    if apply_schema:
        report.schema_statements = len(repo.apply_schema())
    report.counts_before = repo.counts()

    _merge_stage(repo, report, MOLECULES_FILE, artifacts.molecules, strict)
    _merge_stage(repo, report, PRODUCTS_FILE, artifacts.products, strict)
    _merge_stage(repo, report, CONTAINS_FILE, artifacts.contains, strict)
    _merge_stage(repo, report, ALIASES_FILE, artifacts.aliases, strict)
    _merge_stage(repo, report, INTERACTIONS_FILE, artifacts.interactions, strict)

    report.counts_after = repo.counts()
    return report


def load_artifacts(
    repo: GraphRepository,
    processed_dir: Path | str,
    *,
    apply_schema: bool = True,
    strict: bool = False,
) -> LoadReport:
    """Load every artifact found in ``processed_dir`` in dependency order.

    Missing artifacts are recorded in ``report.skipped`` rather than raising, so an incomplete load
    is visible in the report instead of aborting the run. Defaults to non-strict so a single bad
    row is rejected and reported instead of failing the whole load.
    """
    directory = Path(processed_dir)
    report = LoadReport()
    if apply_schema:
        report.schema_statements = len(repo.apply_schema())
    report.counts_before = repo.counts()

    for stage in LOAD_ORDER:
        _merge_stage(repo, report, stage, read_artifact(directory, stage), strict)

    report.counts_after = repo.counts()
    return report
