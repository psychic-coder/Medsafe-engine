"""Tests for ``medsafe.eval``.

The harness is only useful if it *fails* on the things that matter, so most of these tests inject a
deliberately broken engine and assert the run goes red — a harness that always passes is worse than
no harness, because it looks like evidence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from medsafe.eval.golden_set import (
    BUILTIN_RESOLUTION_CASES,
    InteractionCase,
    ResolutionCase,
    SubstitutionCase,
    blocklist_negative_cases,
    load_golden_set,
)
from medsafe.eval.harness import (
    evaluate_interaction,
    evaluate_resolution,
    evaluate_substitution,
    run_evaluation,
)
from medsafe.eval.metrics import ResolutionMetrics, RunReport, safe_ratio
from medsafe.resolution.blocklist import ConfusablePairBlocklist
from medsafe.resolution.matcher import Matcher


class TestGoldenSet:
    def test_builtin_cases_are_used_when_no_files_exist(self, tmp_path: Path):
        golden = load_golden_set(tmp_path, ConfusablePairBlocklist())
        assert golden.sources["resolution"] == "builtin"
        assert len(golden.resolution) == len(BUILTIN_RESOLUTION_CASES)

    def test_every_blocklist_pair_becomes_two_cases(self, blocklist: ConfusablePairBlocklist):
        cases = blocklist_negative_cases(blocklist)
        assert len(cases) == 2 * len(blocklist), "each pair must be tested in both directions"

    def test_blocklist_negatives_are_folded_in(self, tmp_path: Path, blocklist):
        golden = load_golden_set(tmp_path, blocklist)
        assert len(golden.resolution) > len(BUILTIN_RESOLUTION_CASES)
        assert "generated" in golden.sources["blocklist_negatives"]

    def test_csv_cases_override_the_builtins(self, tmp_path: Path):
        (tmp_path / "golden_resolution.csv").write_text(
            "query,expected_path,expected_molecule_id,forbidden_molecules,note\n"
            "amoxicillin,exact,MOL001,,from file\n",
            encoding="utf-8",
        )
        golden = load_golden_set(tmp_path, ConfusablePairBlocklist())
        assert golden.resolution == [
            ResolutionCase("amoxicillin", "exact", "MOL001", (), "from file")
        ]

    def test_pipe_separated_lists_are_parsed(self, tmp_path: Path):
        (tmp_path / "golden_interaction.csv").write_text(
            "drugs,expected_statuses,note\nWarfarin|Aspirin,interaction,x\n", encoding="utf-8"
        )
        golden = load_golden_set(tmp_path, ConfusablePairBlocklist())
        assert golden.interaction[0].drugs == ("Warfarin", "Aspirin")


class TestResolutionScoring:
    def test_a_clean_engine_passes(self, matcher: Matcher):
        metrics = evaluate_resolution(matcher, list(BUILTIN_RESOLUTION_CASES))
        assert metrics.passed
        assert metrics.false_accepts == 0
        assert metrics.blocklist_violations == 0

    def test_guard_cases_are_excluded_from_the_distribution(self, matcher: Matcher, blocklist):
        cases = list(BUILTIN_RESOLUTION_CASES) + blocklist_negative_cases(blocklist)
        metrics = evaluate_resolution(matcher, cases)
        assert metrics.guard_cases == 2 * len(blocklist)
        assert metrics.labelled_total == len(BUILTIN_RESOLUTION_CASES)
        assert metrics.accept_precision == 1.0

    def test_accepting_the_wrong_molecule_is_a_critical_failure(self, matcher: Matcher):
        wrong = [ResolutionCase("amoxicillin", "exact", "MOL999")]
        metrics = evaluate_resolution(matcher, wrong)
        assert metrics.false_accepts == 1
        assert not metrics.passed
        assert metrics.outcomes[0].is_critical

    def test_auto_accepting_something_expected_to_need_review_is_critical(self, matcher: Matcher):
        metrics = evaluate_resolution(matcher, [ResolutionCase("amoxicillin", "needs_review")])
        assert metrics.false_accepts == 1
        assert not metrics.passed

    def test_a_missed_accept_fails_but_is_not_critical(self, matcher: Matcher):
        metrics = evaluate_resolution(matcher, [ResolutionCase("zzzznotadrug", "exact", "MOL001")])
        assert metrics.missed_accepts == 1
        assert metrics.false_accepts == 0
        assert not metrics.passed
        assert not metrics.outcomes[0].is_critical

    def test_a_suggested_forbidden_molecule_is_a_blocklist_violation(self, repository, blocklist):
        # An unguarded matcher will happily suggest hydroxyzine for hydralazine.
        unguarded = Matcher(
            repository, ConfusablePairBlocklist(), candidate_threshold=70, max_candidates=10
        )
        case = ResolutionCase("hydralazine", "unresolved", None, forbidden_molecules=("MOL007",))
        metrics = evaluate_resolution(unguarded, [case])
        assert metrics.blocklist_violations == 1
        assert not metrics.passed

        guarded = Matcher(repository, blocklist, candidate_threshold=70, max_candidates=10)
        assert evaluate_resolution(guarded, [case]).blocklist_violations == 0

    def test_candidate_rank_is_recorded(self, matcher: Matcher):
        metrics = evaluate_resolution(
            matcher, [ResolutionCase("amoxicilin", "needs_review", "MOL001")]
        )
        assert metrics.candidate_hits == 1
        assert metrics.mean_candidate_rank == 1.0


class TestSubstitutionScoring:
    def test_correct_expectations_pass(self, repository):
        metrics = evaluate_substitution(
            repository,
            [
                SubstitutionCase(
                    "MOL001",
                    form="capsule",
                    strength_value=500,
                    strength_unit="mg",
                    expected_reference_id="PRD003",
                    expected_best_savings_abs=79.50,
                )
            ],
        )
        assert metrics.passed
        assert metrics.correct_status == 1

    def test_a_wrong_savings_figure_fails(self, repository):
        metrics = evaluate_substitution(
            repository,
            [
                SubstitutionCase(
                    "MOL001",
                    form="capsule",
                    strength_value=500,
                    strength_unit="mg",
                    expected_best_savings_abs=1.0,
                )
            ],
        )
        assert not metrics.passed

    def test_offering_a_forbidden_product_is_critical(self, repository):
        metrics = evaluate_substitution(
            repository,
            [
                SubstitutionCase(
                    "MOL001",
                    form="capsule",
                    strength_value=500,
                    strength_unit="mg",
                    forbidden_product_ids=("PRD001",),
                )
            ],
        )
        assert metrics.forbidden_product_offered == 1
        assert not metrics.passed
        assert metrics.outcomes[0].is_critical


class TestInteractionScoring:
    def test_expected_statuses_are_compared_in_order(self, repository, matcher, coverage):
        metrics = evaluate_interaction(
            repository,
            matcher,
            coverage,
            [InteractionCase(("Warfarin", "Aspirin"), ("interaction",))],
        )
        assert metrics.passed
        assert metrics.interactions_found == 1

    def test_the_coverage_gap_rate_is_reported(self, repository, matcher, coverage):
        metrics = evaluate_interaction(
            repository,
            matcher,
            coverage,
            [InteractionCase(("Warfarin", "Atorvastatin"), ("not_checked",))],
        )
        assert metrics.coverage_gap_rate == 1.0
        assert metrics.passed

    def test_a_gap_reported_as_clean_is_critical(self, repository, matcher):
        from medsafe.safety.interactions import AtcCoverage

        # A manifest that wrongly claims group C is covered turns a gap into a clean result.
        lying = AtcCoverage(
            covered_groups=("A", "B", "C"),
            molecule_groups={"MOL004": "B", "MOL003": "C"},
        )
        metrics = evaluate_interaction(
            repository,
            matcher,
            lying,
            [InteractionCase(("Warfarin", "Atorvastatin"), ("not_checked",))],
        )
        assert metrics.gap_misreported_as_clean == 1
        assert not metrics.passed
        assert metrics.outcomes[0].is_critical


class TestRunReport:
    def test_a_full_run_against_the_demo_graph_passes(
        self, repository, blocklist, coverage, tmp_path
    ):
        golden = load_golden_set(tmp_path, blocklist)
        report = run_evaluation(repository, blocklist, coverage, golden)
        assert report.passed
        assert report.critical_failures == []

    def test_the_report_records_the_configuration(self, repository, blocklist, coverage, tmp_path):
        golden = load_golden_set(tmp_path, blocklist)
        report = run_evaluation(repository, blocklist, coverage, golden, candidate_threshold=70)
        assert report.config["candidate_threshold"] == 70
        assert report.config["blocklist_pairs"] == len(blocklist)

    def test_the_run_is_serialisable_for_comparison(
        self, repository, blocklist, coverage, tmp_path
    ):
        import json

        golden = load_golden_set(tmp_path, blocklist)
        payload = run_evaluation(repository, blocklist, coverage, golden).as_dict()
        assert json.loads(json.dumps(payload))["passed"] is True

    def test_a_run_with_no_blocklist_still_reports_it(self, repository, coverage, tmp_path):
        empty = ConfusablePairBlocklist()
        report = run_evaluation(repository, empty, coverage, load_golden_set(tmp_path, empty))
        assert report.config["blocklist_pairs"] == 0

    def test_one_critical_failure_fails_the_whole_run(self):
        report = RunReport()
        report.resolution.false_accepts = 1
        assert not report.passed

    def test_the_summary_names_critical_failures(self, repository, matcher):
        report = RunReport()
        report.resolution = evaluate_resolution(
            matcher, [ResolutionCase("amoxicillin", "exact", "MOL999")]
        )
        assert "CRITICAL FAILURES" in "\n".join(report.summary_lines())


@pytest.mark.parametrize(
    "numerator,denominator,expected", [(1, 2, 0.5), (0, 0, 0.0), (3, 3, 1.0)]
)
def test_safe_ratio_handles_an_empty_denominator(numerator, denominator, expected):
    assert safe_ratio(numerator, denominator) == expected


def test_metrics_pass_when_empty():
    assert ResolutionMetrics().passed
