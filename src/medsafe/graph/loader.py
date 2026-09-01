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
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from medsafe.errors import SchemaViolationError
from medsafe.graph.repository import GraphRepository

logger = logging.getLogger(__name__)

__all__ = [
    "LoadReport",
    "ArtifactSet",
    "load_artifacts",
    "load_records",
    "read_artifact",
    "read_stage",
]

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

# A stage is a logical thing to load; the filename it arrives under is not.
#
# ``scripts/build_bridge_table.py`` and ``scripts/ingest_*.py`` emit the canonical names
# (``molecules.csv``, ``products.csv``, ...), while the curated snapshots in ``data/processed/``
# and ``data/demo/`` carry the names of the pipeline stage that produced them
# (``molecule_catalog.csv``, ``pmbjp_final_clean.csv``, ...). Both are the same artifact, so a
# stage resolves against an ordered list of candidate stems and takes the first that exists.
# Reporting is always keyed by the logical stage name, so an operator reading a LoadReport does not
# need to know which naming convention a given directory happens to use.
STAGE_FILES: dict[str, tuple[str, ...]] = {
    MOLECULES_FILE: ("molecules", "molecule_catalog"),
    PRODUCTS_FILE: ("products", "pmbjp_final_clean"),
    CONTAINS_FILE: ("contains",),
    ALIASES_FILE: ("alias_bridge_table_final", "aliases"),
    INTERACTIONS_FILE: ("ddinter_final_clean", "interactions"),
}

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
    anchors: dict[str, str] = field(default_factory=dict)  # inn_name -> ddinter_anchor (ATC)


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


def read_stage(processed_dir: Path, stage: str) -> list[Record] | None:
    """Read the artifact for a logical ``stage``, trying each candidate filename in order."""
    for stem in STAGE_FILES.get(stage, (stage,)):
        rows = read_artifact(processed_dir, stem)
        if rows is not None:
            return rows
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


def _load_anchor_profile(manual_dir: Path | str) -> dict[str, str]:
    """Load drug → ATC group mapping from ddinter_anchor_profile.csv.
    
    Returns a dict mapping drug names to their top_file (ATC group). Missing file yields empty dict.
    """
    csv_path = Path(manual_dir) / "ddinter_anchor_profile.csv"
    if not csv_path.is_file():
        logger.warning(
            "Anchor profile not found at %s; ddinter_anchor will be None for all molecules",
            csv_path,
        )
        return {}
    
    anchors: dict[str, str] = {}
    try:
        with csv_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                drug = (row.get("drug") or "").strip()
                atc = (row.get("top_file") or "").strip()
                if drug and atc:
                    anchors[drug.lower()] = atc
    except Exception as exc:
        # If the file is malformed, silently skip: anchors are optional enrichment
        logger.warning(f"Failed to load anchor profile from {csv_path}: {exc}")
    return anchors


def _enrich_molecules_with_anchors(
    molecules: list[Record], anchors: dict[str, str]
) -> list[Record]:
    """Attach ddinter_anchor to molecules by looking up inn_name in the anchor map."""
    enriched = []
    for mol in molecules:
        drug_key = str(mol.get("inn_name") or "").lower()
        anchor = anchors.get(drug_key)
        enriched.append({**mol, "ddinter_anchor": anchor})
    return enriched


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

    # Enrich molecules with anchors before merging
    molecules = artifacts.molecules
    if artifacts.anchors:
        molecules = _enrich_molecules_with_anchors(molecules, artifacts.anchors)

    _merge_stage(repo, report, MOLECULES_FILE, molecules, strict)
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
    
    Loads anchors from ``data/manual/ddinter_anchor_profile.csv`` relative to ``data/`` root and
    enriches Molecule nodes with ATC group information for Phase 5 coverage tracking.
    """
    directory = Path(processed_dir)
    # Anchors live in data/manual/, siblings of data/processed/
    manual_dir = directory.parent / "manual"
    
    report = LoadReport()
    if apply_schema:
        report.schema_statements = len(repo.apply_schema())
    report.counts_before = repo.counts()

    # Load anchors and molecules, enrich before merge
    anchors = _load_anchor_profile(manual_dir)
    molecules = read_stage(directory, MOLECULES_FILE)
    if molecules is not None:
        molecules = _enrich_molecules_with_anchors(molecules, anchors)

    _merge_stage(repo, report, MOLECULES_FILE, molecules, strict)
    _merge_stage(repo, report, PRODUCTS_FILE, read_stage(directory, PRODUCTS_FILE), strict)
    _merge_stage(repo, report, CONTAINS_FILE, read_stage(directory, CONTAINS_FILE), strict)
    _merge_stage(repo, report, ALIASES_FILE, read_stage(directory, ALIASES_FILE), strict)
    _merge_stage(repo, report, INTERACTIONS_FILE, read_stage(directory, INTERACTIONS_FILE), strict)

    report.counts_after = repo.counts()
    return report
