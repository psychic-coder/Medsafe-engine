"""Evaluation harness — runs the engine against the golden set and reports.

Loads the golden set, executes the relevant pipeline stage for each case (resolution, substitution,
interaction check), scores the outputs with ``metrics``, and emits a comparable run report so
changes to normalization rules, the alias table, or the fuzzy threshold can be evaluated before they
ship. Runnable per phase, from CI or the command line, without requiring a fully loaded graph for
the stages that do not need one.

    python -m medsafe.eval.harness --seed-dir data/demo
    python -m medsafe.eval.harness --seed-dir data/demo --threshold 70 --json

The exit code is non-zero when the run fails, so CI can gate on it. A single false accept or
blocklist violation is enough to fail, however good the other numbers are.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from medsafe.eval.golden_set import (
    GoldenSet,
    InteractionCase,
    ResolutionCase,
    SubstitutionCase,
    load_golden_set,
)
from medsafe.eval.metrics import (
    CaseOutcome,
    InteractionMetrics,
    ResolutionMetrics,
    RunReport,
    SubstitutionMetrics,
)
from medsafe.graph.repository import GraphRepository
from medsafe.pricing.substitution import find_substitutes_for_molecule
from medsafe.resolution.blocklist import ConfusablePairBlocklist
from medsafe.resolution.matcher import Matcher, ResolutionStatus
from medsafe.safety.interactions import AtcCoverage, MoleculeInput, check_interactions

__all__ = ["run_evaluation", "evaluate_resolution", "evaluate_substitution", "evaluate_interaction"]


def _matches_forbidden(molecule_id: str, inn_name: str, forbidden: tuple[str, ...]) -> bool:
    """A forbidden entry is either a molecule id or ``inn:<normalized name>``."""
    for token in forbidden:
        if token.startswith("inn:"):
            if inn_name == token[4:]:
                return True
        elif molecule_id == token:
            return True
    return False


def evaluate_resolution(matcher: Matcher, cases: list[ResolutionCase]) -> ResolutionMetrics:
    metrics = ResolutionMetrics()
    for case in cases:
        result = matcher.resolve(case.query)
        metrics.total += 1

        # Guard cases assert an absence, not a target path, so they are counted separately and
        # kept out of the accept/review/unresolved distribution.
        is_guard = case.expected_path == "any"
        if is_guard:
            metrics.guard_cases += 1
        elif result.status is ResolutionStatus.RESOLVED:
            metrics.auto_accepted += 1
        elif result.status is ResolutionStatus.NEEDS_REVIEW:
            metrics.routed_to_review += 1
        else:
            metrics.unresolved += 1

        # Forbidden molecules must appear neither as a match nor as a candidate.
        offenders = []
        if result.match is not None and _matches_forbidden(
            result.match.molecule.molecule_id, result.match.molecule.inn_name,
            case.forbidden_molecules,
        ):
            offenders.append(f"matched {result.match.molecule.inn_name}")
        for candidate in result.candidates:
            if _matches_forbidden(
                candidate.molecule.molecule_id, candidate.molecule.inn_name,
                case.forbidden_molecules,
            ):
                offenders.append(f"suggested {candidate.molecule.inn_name}")
        if offenders:
            metrics.blocklist_violations += 1
            metrics.outcomes.append(
                CaseOutcome(case.query, False, "; ".join(offenders), severity="critical")
            )
            continue

        if is_guard:
            metrics.outcomes.append(CaseOutcome(case.query, True))
            continue

        actual_path = result.path.value if result.path else result.status.value
        matched_id = result.match.molecule.molecule_id if result.match else None

        if case.expects_auto_accept:
            if matched_id == case.expected_molecule_id and actual_path == case.expected_path:
                metrics.correct_accepts += 1
                metrics.outcomes.append(CaseOutcome(case.query, True))
            elif result.match is not None:
                # Accepted, but the wrong molecule or the wrong path. This is the critical class.
                metrics.false_accepts += 1
                metrics.outcomes.append(
                    CaseOutcome(
                        case.query,
                        False,
                        f"expected {case.expected_molecule_id} via {case.expected_path}, "
                        f"accepted {matched_id} via {actual_path}",
                        severity="critical",
                    )
                )
            else:
                metrics.missed_accepts += 1
                metrics.outcomes.append(
                    CaseOutcome(
                        case.query, False, f"expected an auto-accept, got {actual_path}", "fail"
                    )
                )
            continue

        # Non-accept expectations: needs_review or unresolved.
        if result.match is not None:
            metrics.false_accepts += 1
            metrics.outcomes.append(
                CaseOutcome(
                    case.query,
                    False,
                    f"expected {case.expected_path}, auto-accepted {matched_id}",
                    severity="critical",
                )
            )
            continue

        if case.expected_path == "needs_review":
            metrics.candidate_opportunities += 1
            if case.expected_molecule_id:
                ranks = [
                    index
                    for index, candidate in enumerate(result.candidates, start=1)
                    if candidate.molecule.molecule_id == case.expected_molecule_id
                ]
                if ranks:
                    metrics.candidate_hits += 1
                    metrics.candidate_ranks.append(ranks[0])
            elif result.candidates:
                metrics.candidate_hits += 1
                metrics.candidate_ranks.append(1)

        passed = actual_path == case.expected_path
        metrics.outcomes.append(
            CaseOutcome(
                case.query,
                passed,
                "" if passed else f"expected {case.expected_path}, got {actual_path}",
            )
        )
    return metrics


def evaluate_substitution(
    repository: GraphRepository, cases: list[SubstitutionCase]
) -> SubstitutionMetrics:
    metrics = SubstitutionMetrics()
    for case in cases:
        result = find_substitutes_for_molecule(
            repository,
            case.molecule_id,
            form=case.form,
            strength_value=case.strength_value,
            strength_unit=case.strength_unit,
        )
        metrics.total += 1
        label = f"{case.molecule_id}/{case.form or 'any'}"

        offered = {s.product.product_id for s in result.substitutes}
        forbidden_hits = offered & set(case.forbidden_product_ids)
        if forbidden_hits:
            metrics.forbidden_product_offered += 1
            metrics.outcomes.append(
                CaseOutcome(
                    label, False, f"offered excluded product(s) {sorted(forbidden_hits)}",
                    severity="critical",
                )
            )
            continue

        failures = []
        if result.status.value == case.expected_status:
            metrics.correct_status += 1
        else:
            failures.append(f"status {result.status.value} != {case.expected_status}")

        if case.expected_reference_id is not None:
            reference_id = result.reference.product_id if result.reference else None
            if reference_id == case.expected_reference_id:
                metrics.correct_reference += 1
            else:
                failures.append(f"reference {reference_id} != {case.expected_reference_id}")

        if case.expected_best_savings_abs is not None:
            actual = result.best_savings_abs
            if abs(actual - case.expected_best_savings_abs) < 0.01:
                metrics.correct_savings += 1
            else:
                failures.append(f"best savings {actual} != {case.expected_best_savings_abs}")

        metrics.outcomes.append(CaseOutcome(label, not failures, "; ".join(failures)))
    return metrics


def evaluate_interaction(
    repository: GraphRepository,
    matcher: Matcher,
    coverage: AtcCoverage,
    cases: list[InteractionCase],
) -> InteractionMetrics:
    metrics = InteractionMetrics()
    for case in cases:
        results = matcher.resolve_many(case.drugs)
        inputs = [
            MoleculeInput(
                query=result.query,
                molecule_id=result.match.molecule.molecule_id if result.match else None,
                inn_name=result.match.molecule.inn_name if result.match else None,
                resolved=result.is_resolved,
            )
            for result in results
        ]
        report = check_interactions(repository, inputs, coverage)
        metrics.total_cases += 1
        metrics.total_pairs += len(report.pairs)

        summary = report.summary
        metrics.interactions_found += summary["interactions_found"]
        metrics.checked_no_interaction += summary["checked_no_interaction"]
        metrics.not_checked += summary["not_checked"]

        actual = tuple(pair.status.value for pair in report.pairs)
        label = " + ".join(case.drugs)

        # The critical class: a pair the case says is unverifiable came back clean.
        paired = zip(case.expected_statuses, actual, strict=False)
        misreported = [
            index
            for index, (expected, got) in enumerate(paired)
            if expected == "not_checked" and got == "no_known_interaction"
        ]
        if misreported:
            metrics.gap_misreported_as_clean += 1
            metrics.outcomes.append(
                CaseOutcome(
                    label, False, "coverage gap reported as no_known_interaction",
                    severity="critical",
                )
            )
            continue

        passed = actual == tuple(case.expected_statuses)
        if passed:
            metrics.correct_cases += 1
        metrics.outcomes.append(
            CaseOutcome(
                label,
                passed,
                "" if passed else f"expected {case.expected_statuses}, got {actual}",
            )
        )
    return metrics


def run_evaluation(
    repository: GraphRepository,
    blocklist: ConfusablePairBlocklist,
    coverage: AtcCoverage,
    golden: GoldenSet,
    *,
    candidate_threshold: int = 88,
    max_candidates: int = 5,
) -> RunReport:
    """Run every stage the golden set covers and return a comparable report."""
    matcher = Matcher(
        repository,
        blocklist,
        candidate_threshold=candidate_threshold,
        max_candidates=max_candidates,
    )
    return RunReport(
        resolution=evaluate_resolution(matcher, golden.resolution),
        substitution=evaluate_substitution(repository, golden.substitution),
        interaction=evaluate_interaction(repository, matcher, coverage, golden.interaction),
        config={
            "candidate_threshold": candidate_threshold,
            "max_candidates": max_candidates,
            "blocklist_pairs": len(blocklist),
            "blocklist_missing": blocklist.missing,
            "coverage_missing": coverage.missing,
        },
        sources=dict(golden.sources),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the engine against the golden set.")
    parser.add_argument(
        "--seed-dir",
        type=Path,
        default=None,
        help="Load an in-memory graph from these artifacts instead of connecting to Neo4j.",
    )
    parser.add_argument("--threshold", type=int, default=None, help="Fuzzy candidate threshold.")
    parser.add_argument("--max-candidates", type=int, default=None)
    parser.add_argument("--json", action="store_true", help="Emit the report as JSON.")
    args = parser.parse_args(argv)

    from medsafe.config import get_settings

    settings = get_settings()

    if args.seed_dir is not None:
        from medsafe.graph.loader import load_artifacts
        from medsafe.graph.repository import InMemoryRepository

        repository: GraphRepository = InMemoryRepository()
        load_artifacts(repository, args.seed_dir)
        manifest = Path(args.seed_dir) / "ddinter_coverage.json"
        coverage = AtcCoverage.from_manifest(
            manifest if manifest.is_file() else settings.coverage_manifest
        )
    else:
        from medsafe.graph.repository import Neo4jRepository

        repository = Neo4jRepository(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database=settings.neo4j_database,
        )
        coverage = AtcCoverage.from_manifest(settings.coverage_manifest)

    blocklist = ConfusablePairBlocklist.from_csv(settings.fuzzy_negative_blocklist)
    golden = load_golden_set(settings.data_manual_dir, blocklist)

    report = run_evaluation(
        repository,
        blocklist,
        coverage,
        golden,
        candidate_threshold=args.threshold or settings.fuzzy_candidate_threshold,
        max_candidates=args.max_candidates or settings.fuzzy_max_candidates,
    )

    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print("\n".join(report.summary_lines()))

    repository.close()
    return 0 if report.passed else 1


if __name__ == "__main__":  # pragma: no cover
    try:
        sys.exit(main())
    except BrokenPipeError:  # piping into head/less closes the stream early
        sys.exit(0)
