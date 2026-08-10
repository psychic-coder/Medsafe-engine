"""Matching — resolves a normalized string to a ``Molecule``, or to review candidates.

Implements the locked resolution policy in a strict order. (1) Exact match on the normalized string
against ``Molecule.inn_name`` — auto-accept. (2) Lookup against the ``Alias``/bridge table via
``ALIAS_OF`` — auto-accept. (3) Otherwise, RapidFuzz/Levenshtein scoring over the vocabulary to
produce ranked CANDIDATES for the human-review queue, returned with their scores and clearly typed
as unaccepted. Candidates are filtered through ``blocklist`` first, and no fuzzy result is ever
auto-merged into a match regardless of score — that is a patient-safety bug, not a data-quality
tradeoff (see ``docs/schema.md``). The return type must make "resolved" and "needs review"
impossible to confuse at the call site.

That last requirement is enforced structurally, not by convention:

* :class:`ResolvedMatch` can only carry ``MatchPath.EXACT`` or ``MatchPath.ALIAS``. There is no
  representable value of the type that means "resolved by fuzzy".
* :class:`ResolutionResult` validates in ``__post_init__`` that ``match`` is set if and only if
  ``status is RESOLVED``, and that a resolved result carries no candidates. Constructing a result
  that presents a candidate as a match raises.
* The fuzzy branch never assigns ``match``. No configuration value reaches that code path — the
  threshold decides which candidates are *shown*, never whether one is accepted.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from rapidfuzz.distance import Levenshtein

from medsafe.graph.repository import GraphRepository
from medsafe.resolution.blocklist import ConfusablePairBlocklist, load_blocklist
from medsafe.resolution.normalize import NormalizedName, normalize

__all__ = [
    "MatchPath",
    "ResolutionStatus",
    "MoleculeRef",
    "ResolvedMatch",
    "ReviewCandidate",
    "SuppressedCandidate",
    "ResolutionResult",
    "Matcher",
    "score_similarity",
]


def score_similarity(left: str, right: str) -> float:
    """Levenshtein similarity in [0, 100], rounded to 2dp so ranking is reproducible."""
    return round(Levenshtein.normalized_similarity(left, right) * 100, 2)


class MatchPath(StrEnum):
    """How a molecule was reached. Only these two values exist, and both are auto-accept."""

    EXACT = "exact"
    ALIAS = "alias"


class ResolutionStatus(StrEnum):
    """Outcome of a resolution attempt."""

    RESOLVED = "resolved"
    NEEDS_REVIEW = "needs_review"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class MoleculeRef:
    """Projection of a ``Molecule`` node."""

    molecule_id: str
    inn_name: str
    category: str | None = None

    @classmethod
    def from_record(cls, record: dict) -> MoleculeRef:
        return cls(
            molecule_id=str(record["molecule_id"]),
            inn_name=str(record["inn_name"]),
            category=record.get("category"),
        )


@dataclass(frozen=True, slots=True)
class ResolvedMatch:
    """An auto-accepted match. Only reachable via the exact or alias path."""

    molecule: MoleculeRef
    path: MatchPath
    normalized_query: str
    alias_raw_string: str | None = None
    alias_source: str | None = None

    def __post_init__(self) -> None:
        if self.path not in (MatchPath.EXACT, MatchPath.ALIAS):
            raise ValueError(f"ResolvedMatch cannot be created for path {self.path!r}")


@dataclass(frozen=True, slots=True)
class ReviewCandidate:
    """An unaccepted fuzzy suggestion queued for a human. Never a match."""

    molecule: MoleculeRef
    score: float
    matched_string: str
    matched_on: str  # "inn_name" | "alias"
    requires_human_review: bool = True
    auto_accepted: bool = False

    def __post_init__(self) -> None:
        if self.auto_accepted or not self.requires_human_review:
            raise ValueError("A fuzzy candidate can never be auto-accepted")


@dataclass(frozen=True, slots=True)
class SuppressedCandidate:
    """A candidate removed by the blocklist. Reported for audit, never offered to a client."""

    molecule_id: str
    inn_name: str
    score: float
    reason: str
    confusable_with: str


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    """The single return type of :meth:`Matcher.resolve`.

    ``match`` is populated if and only if ``status is RESOLVED``; a result carrying candidates is
    never resolved. The invariant is checked at construction, so a caller cannot be handed an object
    that blurs the two.
    """

    query: str
    normalized: NormalizedName
    status: ResolutionStatus
    match: ResolvedMatch | None = None
    candidates: tuple[ReviewCandidate, ...] = ()
    suppressed: tuple[SuppressedCandidate, ...] = ()
    notes: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.status is ResolutionStatus.RESOLVED:
            if self.match is None:
                raise ValueError("A resolved result must carry a match")
            if self.candidates:
                raise ValueError("A resolved result must not carry review candidates")
        elif self.match is not None:
            raise ValueError("Only a resolved result may carry a match")
        if self.status is ResolutionStatus.NEEDS_REVIEW and not self.candidates:
            raise ValueError("needs_review requires at least one candidate")

    @property
    def is_resolved(self) -> bool:
        return self.status is ResolutionStatus.RESOLVED

    @property
    def molecule(self) -> MoleculeRef | None:
        """The resolved molecule, or ``None``. Never returns a candidate's molecule."""
        return self.match.molecule if self.match is not None else None

    @property
    def path(self) -> MatchPath | None:
        return self.match.path if self.match is not None else None


class Matcher:
    """Resolves raw drug strings under the locked policy.

    The vocabulary used for fuzzy scoring is read once per :meth:`resolve_many` call and cached for
    the matcher's lifetime, so a multi-drug ``/check`` request does not re-read it per drug.
    """

    def __init__(
        self,
        repository: GraphRepository,
        blocklist: ConfusablePairBlocklist | None = None,
        *,
        candidate_threshold: int | None = None,
        max_candidates: int | None = None,
    ) -> None:
        self.repository = repository
        if candidate_threshold is None or max_candidates is None:
            from medsafe.config import get_settings

            settings = get_settings()
            candidate_threshold = (
                settings.fuzzy_candidate_threshold
                if candidate_threshold is None
                else candidate_threshold
            )
            max_candidates = (
                settings.fuzzy_max_candidates if max_candidates is None else max_candidates
            )
        self.candidate_threshold = int(candidate_threshold)
        self.max_candidates = int(max_candidates)
        self.blocklist = blocklist if blocklist is not None else load_blocklist()
        self._vocabulary: list[dict] | None = None

    # --- vocabulary ---

    def _vocab(self) -> list[dict]:
        if self._vocabulary is None:
            self._vocabulary = self.repository.all_molecule_names()
        return self._vocabulary

    def invalidate_vocabulary(self) -> None:
        """Drop the cached vocabulary — call after a graph reload."""
        self._vocabulary = None

    # --- resolution ---

    def resolve(self, raw: str) -> ResolutionResult:
        """Resolve one raw drug string. Never raises for an unknown drug."""
        normalized = normalize(raw)
        key = normalized.normalized

        if not key:
            return ResolutionResult(
                query=raw,
                normalized=normalized,
                status=ResolutionStatus.UNRESOLVED,
                notes=("input normalized to an empty key",),
            )

        # (1) Exact — auto-accept. Takes precedence over every other path.
        record = self.repository.find_molecule_by_exact_name(key)
        if record is not None:
            return ResolutionResult(
                query=raw,
                normalized=normalized,
                status=ResolutionStatus.RESOLVED,
                match=ResolvedMatch(
                    molecule=MoleculeRef.from_record(record),
                    path=MatchPath.EXACT,
                    normalized_query=key,
                ),
            )

        # (2) Alias / bridge table — auto-accept. Takes precedence over fuzzy candidates.
        record = self.repository.find_molecule_by_alias(key)
        if record is not None:
            return ResolutionResult(
                query=raw,
                normalized=normalized,
                status=ResolutionStatus.RESOLVED,
                match=ResolvedMatch(
                    molecule=MoleculeRef.from_record(record),
                    path=MatchPath.ALIAS,
                    normalized_query=key,
                    alias_raw_string=record.get("alias_raw_string"),
                    alias_source=record.get("alias_source"),
                ),
            )

        # (3) Fuzzy — CANDIDATES ONLY. This branch cannot produce a match.
        candidates, suppressed = self._fuzzy_candidates(key)
        status = ResolutionStatus.NEEDS_REVIEW if candidates else ResolutionStatus.UNRESOLVED
        notes: tuple[str, ...] = ()
        if candidates:
            notes = ("fuzzy candidates require human review; none has been accepted",)
        if self.blocklist.missing:
            notes += ("confusable-pair blocklist is not loaded — fuzzy output is unguarded",)
        return ResolutionResult(
            query=raw,
            normalized=normalized,
            status=status,
            candidates=candidates,
            suppressed=suppressed,
            notes=notes,
        )

    def resolve_many(self, raws: Iterable[str]) -> list[ResolutionResult]:
        """Resolve several strings, sharing one vocabulary read."""
        return [self.resolve(raw) for raw in raws]

    # --- fuzzy internals ---

    def _score_molecule(self, key: str, entry: dict) -> tuple[float, str, str]:
        """Best (score, matched_string, matched_on) for one molecule across its surface forms."""
        best = (score_similarity(key, entry["inn_name"]), entry["inn_name"], "inn_name")
        for alias in entry.get("alias_strings") or []:
            if not alias:
                continue
            alias_score = score_similarity(key, alias)
            if alias_score > best[0]:
                best = (alias_score, alias, "alias")
        return best

    def _fuzzy_candidates(
        self, key: str
    ) -> tuple[tuple[ReviewCandidate, ...], tuple[SuppressedCandidate, ...]]:
        scored: list[tuple[float, str, str, dict]] = []
        for entry in self._vocab():
            score, matched_string, matched_on = self._score_molecule(key, entry)
            if score >= self.candidate_threshold:
                scored.append((score, matched_string, matched_on, entry))

        # Deterministic ordering: score desc, then inn_name, then molecule_id. Ties never reorder
        # between runs, so a review queue is reproducible.
        scored.sort(key=lambda item: (-item[0], item[3]["inn_name"], item[3]["molecule_id"]))

        suppressed: list[SuppressedCandidate] = []

        # Rule 1 — a candidate confusable with the query itself is never shown.
        survivors: list[tuple[float, str, str, dict]] = []
        for score, matched_string, matched_on, entry in scored:
            if self.blocklist.contains(key, entry["inn_name"]):
                suppressed.append(
                    SuppressedCandidate(
                        molecule_id=entry["molecule_id"],
                        inn_name=entry["inn_name"],
                        score=score,
                        reason="blocklisted confusable of the query string",
                        confusable_with=key,
                    )
                )
                continue
            survivors.append((score, matched_string, matched_on, entry))

        # Rule 2 — if both members of a confusable pair survive, fuzzy scoring demonstrably cannot
        # separate them here. Drop BOTH: offering either as a suggestion is what the blocklist
        # exists to prevent, and offering the higher-scoring one is exactly the wrong-drug failure.
        names = {entry["inn_name"] for _, _, _, entry in survivors}
        conflicted = {
            name
            for name in names
            for other in names
            if name != other and self.blocklist.contains(name, other)
        }
        final: list[ReviewCandidate] = []
        for score, matched_string, matched_on, entry in survivors:
            if entry["inn_name"] in conflicted:
                partner = next(
                    (
                        n
                        for n in conflicted
                        if n != entry["inn_name"]
                        and self.blocklist.contains(n, entry["inn_name"])
                    ),
                    "",
                )
                suppressed.append(
                    SuppressedCandidate(
                        molecule_id=entry["molecule_id"],
                        inn_name=entry["inn_name"],
                        score=score,
                        reason="blocklisted confusable pair both present in candidate set",
                        confusable_with=partner,
                    )
                )
                continue
            final.append(
                ReviewCandidate(
                    molecule=MoleculeRef.from_record(entry),
                    score=score,
                    matched_string=matched_string,
                    matched_on=matched_on,
                )
            )

        return tuple(final[: self.max_candidates]), tuple(suppressed)


def resolved_molecule_ids(results: Sequence[ResolutionResult]) -> list[str]:
    """Molecule ids of the resolved results only. Candidates never contribute."""
    return [r.match.molecule.molecule_id for r in results if r.match is not None]
