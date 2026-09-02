"""Evaluation metrics.

Defines what is measured and how it is aggregated: resolution precision/recall by match path,
coverage (share of inputs auto-accepted vs. routed to review), candidate quality (is the true
molecule present in the candidate list, and at what rank), and — weighted above all of them — the
false-accept rate, particularly any blocklisted confusable pair surfacing as a match. A false accept
is not traded off against coverage here; it is reported as a hard failure. Also reports interaction
coverage-gap rates so the share of "not checked" results stays visible.

"Not traded off" is literal: :attr:`ResolutionMetrics.passed` is false whenever ``false_accepts`` or
``blocklist_violations`` is non-zero, whatever every other number says. There is no weighting in
which better coverage compensates for one wrong-drug accept.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "CaseOutcome",
    "ResolutionMetrics",
    "SubstitutionMetrics",
    "InteractionMetrics",
    "RunReport",
    "safe_ratio",
]


def safe_ratio(numerator: int, denominator: int) -> float:
    """Ratio rounded to 4dp, or 0.0 for an empty denominator."""
    return round(numerator / denominator, 4) if denominator else 0.0


@dataclass(frozen=True, slots=True)
class CaseOutcome:
    """One evaluated case. ``severity`` is ``fail`` for an ordinary miss, ``critical`` for a
    false accept or a blocklist violation."""

    case: str
    passed: bool
    detail: str = ""
    severity: str = "pass"

    @property
    def is_critical(self) -> bool:
        return self.severity == "critical"


@dataclass
class ResolutionMetrics:
    total: int = 0
    guard_cases: int = 0
    auto_accepted: int = 0
    routed_to_review: int = 0
    unresolved: int = 0
    correct_accepts: int = 0
    false_accepts: int = 0
    missed_accepts: int = 0
    blocklist_violations: int = 0
    candidate_hits: int = 0
    candidate_opportunities: int = 0
    candidate_ranks: list[int] = field(default_factory=list)
    outcomes: list[CaseOutcome] = field(default_factory=list)

    @property
    def labelled_total(self) -> int:
        """Cases carrying a path expectation. Guard-only cases (blocklist negatives) are excluded
        from the distribution metrics: they assert an absence, not a target path, so counting them
        would understate precision and coverage while telling you nothing about either."""
        return self.total - self.guard_cases

    @property
    def accept_coverage(self) -> float:
        """Share of labelled inputs that auto-accepted rather than being routed to review."""
        return safe_ratio(self.auto_accepted, self.labelled_total)

    @property
    def accept_precision(self) -> float:
        return safe_ratio(self.correct_accepts, self.auto_accepted)

    @property
    def accept_recall(self) -> float:
        expected = self.correct_accepts + self.missed_accepts
        return safe_ratio(self.correct_accepts, expected)

    @property
    def false_accept_rate(self) -> float:
        return safe_ratio(self.false_accepts, self.total)

    @property
    def guard_pass_rate(self) -> float:
        """Share of blocklist guard cases that held."""
        return safe_ratio(self.guard_cases - self.blocklist_violations, self.guard_cases)

    @property
    def candidate_recall(self) -> float:
        return safe_ratio(self.candidate_hits, self.candidate_opportunities)

    @property
    def mean_candidate_rank(self) -> float:
        if not self.candidate_ranks:
            return 0.0
        return round(sum(self.candidate_ranks) / len(self.candidate_ranks), 2)

    @property
    def passed(self) -> bool:
        """A single false accept or blocklist violation fails the run outright."""
        if self.false_accepts or self.blocklist_violations:
            return False
        return all(outcome.passed for outcome in self.outcomes)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "labelled_total": self.labelled_total,
            "guard_cases": self.guard_cases,
            "guard_pass_rate": self.guard_pass_rate,
            "auto_accepted": self.auto_accepted,
            "routed_to_review": self.routed_to_review,
            "unresolved": self.unresolved,
            "accept_coverage": self.accept_coverage,
            "accept_precision": self.accept_precision,
            "accept_recall": self.accept_recall,
            "false_accepts": self.false_accepts,
            "false_accept_rate": self.false_accept_rate,
            "blocklist_violations": self.blocklist_violations,
            "candidate_recall": self.candidate_recall,
            "mean_candidate_rank": self.mean_candidate_rank,
            "passed": self.passed,
        }


@dataclass
class SubstitutionMetrics:
    total: int = 0
    correct_status: int = 0
    correct_reference: int = 0
    correct_savings: int = 0
    forbidden_product_offered: int = 0
    outcomes: list[CaseOutcome] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        # Offering an excluded product (wrong strength, wrong form, or an FDC) is a safety failure,
        # not a scoring miss.
        if self.forbidden_product_offered:
            return False
        return all(outcome.passed for outcome in self.outcomes)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "status_accuracy": safe_ratio(self.correct_status, self.total),
            "reference_accuracy": safe_ratio(self.correct_reference, self.total),
            "savings_accuracy": safe_ratio(self.correct_savings, self.total),
            "forbidden_product_offered": self.forbidden_product_offered,
            "passed": self.passed,
        }


@dataclass
class InteractionMetrics:
    total_cases: int = 0
    total_pairs: int = 0
    correct_cases: int = 0
    interactions_found: int = 0
    checked_no_interaction: int = 0
    not_checked: int = 0
    gap_misreported_as_clean: int = 0
    outcomes: list[CaseOutcome] = field(default_factory=list)

    @property
    def coverage_gap_rate(self) -> float:
        """Share of pairs that were not checked. Expected to be non-zero — it must stay visible."""
        return safe_ratio(self.not_checked, self.total_pairs)

    @property
    def passed(self) -> bool:
        # Reporting an unchecked pair as clean is the failure this whole layer exists to prevent.
        if self.gap_misreported_as_clean:
            return False
        return all(outcome.passed for outcome in self.outcomes)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "total_pairs": self.total_pairs,
            "case_accuracy": safe_ratio(self.correct_cases, self.total_cases),
            "interactions_found": self.interactions_found,
            "checked_no_interaction": self.checked_no_interaction,
            "not_checked": self.not_checked,
            "coverage_gap_rate": self.coverage_gap_rate,
            "gap_misreported_as_clean": self.gap_misreported_as_clean,
            "passed": self.passed,
        }


@dataclass
class RunReport:
    """A comparable run report, so a normalization or threshold change is evaluated pre-merge."""

    resolution: ResolutionMetrics = field(default_factory=ResolutionMetrics)
    substitution: SubstitutionMetrics = field(default_factory=SubstitutionMetrics)
    interaction: InteractionMetrics = field(default_factory=InteractionMetrics)
    config: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.resolution.passed and self.substitution.passed and self.interaction.passed

    @property
    def critical_failures(self) -> list[CaseOutcome]:
        return [
            outcome
            for metrics in (self.resolution, self.substitution, self.interaction)
            for outcome in metrics.outcomes
            if outcome.is_critical
        ]

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "config": self.config,
            "sources": self.sources,
            "resolution": self.resolution.as_dict(),
            "substitution": self.substitution.as_dict(),
            "interaction": self.interaction.as_dict(),
            "critical_failures": [
                {"case": o.case, "detail": o.detail} for o in self.critical_failures
            ],
        }

    def summary_lines(self) -> list[str]:
        resolution, substitution, interaction = self.resolution, self.substitution, self.interaction
        lines = [
            f"golden set run — {'PASS' if self.passed else 'FAIL'}",
            "",
            "resolution",
            f"  labelled cases       {resolution.labelled_total}",
            f"  blocklist guards     {resolution.guard_cases}",
            f"  auto-accept coverage {resolution.accept_coverage:.1%}",
            f"  accept precision     {resolution.accept_precision:.1%}",
            f"  accept recall        {resolution.accept_recall:.1%}",
            f"  candidate recall     {resolution.candidate_recall:.1%} "
            f"(mean rank {resolution.mean_candidate_rank})",
            f"  FALSE ACCEPTS        {resolution.false_accepts}",
            f"  BLOCKLIST VIOLATIONS {resolution.blocklist_violations}",
            "",
            "substitution",
            f"  cases                {substitution.total}",
            f"  status accuracy      "
            f"{safe_ratio(substitution.correct_status, substitution.total):.1%}",
            f"  FORBIDDEN OFFERED    {substitution.forbidden_product_offered}",
            "",
            "interaction",
            f"  cases                {interaction.total_cases}",
            f"  pairs                {interaction.total_pairs}",
            f"  coverage-gap rate    {interaction.coverage_gap_rate:.1%}",
            f"  GAP READ AS CLEAN    {interaction.gap_misreported_as_clean}",
        ]
        if self.critical_failures:
            lines += ["", "CRITICAL FAILURES"]
            lines += [f"  {o.case}: {o.detail}" for o in self.critical_failures]
        return lines
