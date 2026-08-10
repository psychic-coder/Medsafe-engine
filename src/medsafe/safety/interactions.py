"""Interaction checking and coverage reporting.

Takes a set of resolved molecules and returns the pairwise ``INTERACTS_WITH {severity, mechanism,
provenance}`` edges between them, matching each pair under the canonical ordering
(``molecule_id_a < molecule_id_b``) so direction never affects the result.

Critically, it also reports *coverage*, not just hits. The DDInter bulk source covers ATC groups
A, B, D, H, L, P, R, V only; C/J/N/G/M/S (cardiovascular, anti-infective, CNS, and others) are not
covered by bulk ingestion. This module must distinguish "checked, no known interaction" from "not
checked — molecule falls outside ingested coverage" and return that distinction per pair, so Phase 5
response composition can flag the gap explicitly. Collapsing the two into a bare "no interactions"
is the failure mode this module exists to prevent.

Where the ATC group lives
-------------------------
``docs/schema.md`` locks ``Molecule`` to ``{molecule_id, inn_name, category}`` — there is no ATC
property, and the schema is not ours to extend. The molecule-to-ATC-group mapping is therefore
carried in the *coverage manifest* that ``scripts/ingest_ddinter.py`` emits alongside the
interaction table (``data/processed/ddinter_coverage.json``), which is where the ingesting run's
own notion of what it covered belongs anyway. The graph is unchanged.

Fail-closed
-----------
A molecule with no ATC group in the manifest is treated as **not covered**, and a missing manifest
means nothing is covered. The safe default for "we do not know whether we checked this" is "we did
not check it": an unchecked pair reported as clean is precisely the failure this module prevents.
An existing edge is always reported regardless of coverage — coverage only ever governs how the
*absence* of an edge is described.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import combinations
from pathlib import Path

from medsafe.graph.repository import GraphRepository
from medsafe.graph.schema import canonical_pair

__all__ = [
    "PairStatus",
    "AtcCoverage",
    "MoleculeInput",
    "InteractionPair",
    "InteractionReport",
    "check_interactions",
    "DDINTER_COVERED_ATC_GROUPS",
    "DDINTER_UNCOVERED_ATC_GROUPS",
]

logger = logging.getLogger(__name__)

# From docs/schema.md — the ATC first levels the DDInter bulk source spans.
DDINTER_COVERED_ATC_GROUPS: frozenset[str] = frozenset({"A", "B", "D", "H", "L", "P", "R", "V"})
DDINTER_UNCOVERED_ATC_GROUPS: frozenset[str] = frozenset({"C", "G", "J", "M", "N", "S"})


class PairStatus(StrEnum):
    """The three outcomes a pair can have. ``NOT_CHECKED`` is never merged into ``NO_KNOWN``."""

    INTERACTION = "interaction"
    NO_KNOWN_INTERACTION = "no_known_interaction"
    NOT_CHECKED = "not_checked"


@dataclass(frozen=True, slots=True)
class MoleculeInput:
    """One drug in the prescription, resolved or not.

    An unresolved input keeps its ``query`` and carries ``molecule_id=None``: it stays in the
    pairwise set as ``NOT_CHECKED`` instead of being dropped, because a drug nobody could identify
    is the least safe thing to omit from a report.
    """

    query: str
    molecule_id: str | None = None
    inn_name: str | None = None
    resolved: bool = False

    @property
    def label(self) -> str:
        return self.inn_name or self.query


@dataclass(frozen=True, slots=True)
class InteractionPair:
    """One pair's outcome."""

    status: PairStatus
    left: MoleculeInput
    right: MoleculeInput
    severity: str | None = None
    mechanism: str | None = None
    provenance: str | None = None
    reason: str | None = None
    left_atc_group: str | None = None
    right_atc_group: str | None = None

    @property
    def checked(self) -> bool:
        return self.status is not PairStatus.NOT_CHECKED


@dataclass(frozen=True, slots=True)
class InteractionReport:
    """Full pairwise report. ``coverage_complete`` is false whenever any pair was not checked."""

    pairs: tuple[InteractionPair, ...] = ()
    inputs: tuple[MoleculeInput, ...] = ()
    covered_atc_groups: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default=())

    @property
    def interactions(self) -> tuple[InteractionPair, ...]:
        return tuple(p for p in self.pairs if p.status is PairStatus.INTERACTION)

    @property
    def not_checked(self) -> tuple[InteractionPair, ...]:
        return tuple(p for p in self.pairs if p.status is PairStatus.NOT_CHECKED)

    @property
    def coverage_complete(self) -> bool:
        return not self.not_checked

    @property
    def summary(self) -> dict[str, int]:
        return {
            "pairs_total": len(self.pairs),
            "interactions_found": len(self.interactions),
            "checked_no_interaction": sum(
                1 for p in self.pairs if p.status is PairStatus.NO_KNOWN_INTERACTION
            ),
            "not_checked": len(self.not_checked),
        }


class AtcCoverage:
    """Which molecules a given ingestion run actually covered.

    Loaded from the manifest ``scripts/ingest_ddinter.py`` emits. Absent manifest => empty coverage
    => every pair is reported as not checked, which is loud and safe rather than silent and wrong.
    """

    def __init__(
        self,
        covered_groups: Iterable[str] = (),
        molecule_groups: dict[str, str] | None = None,
        *,
        path: Path | None = None,
        missing: bool = False,
    ) -> None:
        self.covered_groups = frozenset(g.strip().upper() for g in covered_groups if g)
        self.molecule_groups = {
            str(k): str(v).strip().upper() for k, v in (molecule_groups or {}).items() if v
        }
        self.path = path
        self.missing = missing

    @classmethod
    def default(cls) -> AtcCoverage:
        """Groups from ``docs/schema.md`` with no molecule mapping — nothing resolves as covered."""
        return cls(DDINTER_COVERED_ATC_GROUPS, {})

    @classmethod
    def from_manifest(cls, path: Path | str | None) -> AtcCoverage:
        if path is None:
            return cls((), {}, missing=True)
        manifest_path = Path(path)
        if not manifest_path.is_file():
            logger.warning(
                "Interaction coverage manifest not found at %s — every pair will report "
                "not_checked",
                manifest_path,
            )
            return cls((), {}, path=manifest_path, missing=True)
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        return cls(
            payload.get("covered_atc_groups") or (),
            payload.get("molecule_atc_groups") or {},
            path=manifest_path,
        )

    def group_for(self, molecule_id: str | None) -> str | None:
        if molecule_id is None:
            return None
        return self.molecule_groups.get(molecule_id)

    def covers(self, molecule_id: str | None) -> bool:
        """True only when the molecule's ATC group is known *and* in the covered set."""
        group = self.group_for(molecule_id)
        return group is not None and group in self.covered_groups

    def reason_for(self, molecule: MoleculeInput) -> str | None:
        """Why a molecule is not covered, or ``None`` when it is."""
        if not molecule.resolved or molecule.molecule_id is None:
            return f"{molecule.query!r} could not be resolved to a molecule"
        if self.missing:
            return "no interaction coverage manifest is loaded"
        group = self.group_for(molecule.molecule_id)
        if group is None:
            return f"{molecule.label} has no ATC group in the coverage manifest"
        if group not in self.covered_groups:
            return (
                f"{molecule.label} is in ATC group {group}, which the ingested DDInter source "
                "does not cover"
            )
        return None


def check_interactions(
    repository: GraphRepository,
    molecules: Sequence[MoleculeInput],
    coverage: AtcCoverage | None = None,
) -> InteractionReport:
    """Return the pairwise interaction report for a prescription.

    Every unordered pair of inputs appears exactly once, including pairs involving unresolved inputs
    and pairs outside ingested coverage.
    """
    if coverage is None:
        from medsafe.config import get_settings

        coverage = AtcCoverage.from_manifest(get_settings().coverage_manifest)

    inputs = tuple(molecules)
    resolved_ids = [m.molecule_id for m in inputs if m.resolved and m.molecule_id]

    edges: dict[tuple[str, str], dict] = {}
    if len(set(resolved_ids)) >= 2:
        for record in repository.interactions_between(sorted(set(resolved_ids))):
            key = canonical_pair(str(record["molecule_id_a"]), str(record["molecule_id_b"]))
            edges[key] = record

    pairs: list[InteractionPair] = []
    for left, right in combinations(inputs, 2):
        pairs.append(_classify_pair(left, right, edges, coverage))

    notes: list[str] = []
    if coverage.missing:
        notes.append(
            "no interaction coverage manifest is loaded; no pair can be reported as checked"
        )
    if any(p.status is PairStatus.NOT_CHECKED for p in pairs):
        notes.append(
            "one or more pairs were NOT checked; an absent interaction is not evidence of safety"
        )

    return InteractionReport(
        pairs=tuple(pairs),
        inputs=inputs,
        covered_atc_groups=tuple(sorted(coverage.covered_groups)),
        notes=tuple(notes),
    )


def _classify_pair(
    left: MoleculeInput,
    right: MoleculeInput,
    edges: dict[tuple[str, str], dict],
    coverage: AtcCoverage,
) -> InteractionPair:
    left_group = coverage.group_for(left.molecule_id)
    right_group = coverage.group_for(right.molecule_id)

    # A known edge is always reported, whatever the coverage manifest says: if the pair is in the
    # graph it was demonstrably checked, and the edge is the evidence.
    if left.molecule_id and right.molecule_id and left.molecule_id != right.molecule_id:
        key = canonical_pair(left.molecule_id, right.molecule_id)
        record = edges.get(key)
        if record is not None:
            return InteractionPair(
                status=PairStatus.INTERACTION,
                left=left,
                right=right,
                severity=record.get("severity"),
                mechanism=record.get("mechanism"),
                provenance=record.get("provenance"),
                left_atc_group=left_group,
                right_atc_group=right_group,
            )

    # No edge. Whether that means "clean" or "unknown" is entirely a coverage question.
    reasons = [r for r in (coverage.reason_for(left), coverage.reason_for(right)) if r]
    if reasons:
        return InteractionPair(
            status=PairStatus.NOT_CHECKED,
            left=left,
            right=right,
            reason="; ".join(reasons),
            left_atc_group=left_group,
            right_atc_group=right_group,
        )

    if left.molecule_id == right.molecule_id:
        return InteractionPair(
            status=PairStatus.NOT_CHECKED,
            left=left,
            right=right,
            reason="the same molecule was supplied twice; no pairwise check applies",
            left_atc_group=left_group,
            right_atc_group=right_group,
        )

    return InteractionPair(
        status=PairStatus.NO_KNOWN_INTERACTION,
        left=left,
        right=right,
        reason="both molecules are within ingested DDInter coverage and no edge exists",
        left_atc_group=left_group,
        right_atc_group=right_group,
    )
