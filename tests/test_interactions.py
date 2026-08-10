"""Tests for ``medsafe.safety.interactions``.

The distinction this module exists to protect is "checked, none found" vs "not checked". These tests
assert it holds in the three ways it can be lost: an uncovered ATC group, a molecule missing from
the manifest, and a missing manifest entirely. All three must fail closed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from medsafe.graph.repository import InMemoryRepository
from medsafe.safety.interactions import (
    DDINTER_COVERED_ATC_GROUPS,
    DDINTER_UNCOVERED_ATC_GROUPS,
    AtcCoverage,
    InteractionReport,
    MoleculeInput,
    PairStatus,
    check_interactions,
)


def resolved(molecule_id: str, inn_name: str) -> MoleculeInput:
    return MoleculeInput(query=inn_name, molecule_id=molecule_id, inn_name=inn_name, resolved=True)


UNRESOLVED = MoleculeInput(query="zzzznotadrug", resolved=False)
WARFARIN = resolved("MOL004", "warfarin")  # ATC B, covered
ASPIRIN = resolved("MOL005", "aspirin")  # ATC B, covered
METFORMIN = resolved("MOL002", "metformin")  # ATC A, covered
ATORVASTATIN = resolved("MOL003", "atorvastatin")  # ATC C, NOT covered
AMOXICILLIN = resolved("MOL001", "amoxicillin")  # ATC J, NOT covered


class TestCoverageGroups:
    def test_the_two_group_sets_match_the_locked_docs(self):
        assert DDINTER_COVERED_ATC_GROUPS == {"A", "B", "D", "H", "L", "P", "R", "V"}
        assert DDINTER_UNCOVERED_ATC_GROUPS == {"C", "G", "J", "M", "N", "S"}

    def test_the_sets_are_disjoint_and_complete(self):
        assert not (DDINTER_COVERED_ATC_GROUPS & DDINTER_UNCOVERED_ATC_GROUPS)
        assert len(DDINTER_COVERED_ATC_GROUPS | DDINTER_UNCOVERED_ATC_GROUPS) == 14


class TestInteractionFound:
    def test_a_known_edge_is_reported_with_its_properties(
        self, repository: InMemoryRepository, coverage: AtcCoverage
    ):
        report = check_interactions(repository, [WARFARIN, ASPIRIN], coverage)
        pair = report.pairs[0]
        assert pair.status is PairStatus.INTERACTION
        assert pair.severity == "major"
        assert pair.mechanism
        assert pair.provenance == "ddinter"

    def test_direction_does_not_affect_the_result(
        self, repository: InMemoryRepository, coverage: AtcCoverage
    ):
        forward = check_interactions(repository, [WARFARIN, ASPIRIN], coverage)
        backward = check_interactions(repository, [ASPIRIN, WARFARIN], coverage)
        assert forward.summary == backward.summary
        assert forward.pairs[0].severity == backward.pairs[0].severity

    def test_every_unordered_pair_appears_once(
        self, repository: InMemoryRepository, coverage: AtcCoverage
    ):
        report = check_interactions(
            repository, [WARFARIN, ASPIRIN, METFORMIN, ATORVASTATIN], coverage
        )
        assert report.summary["pairs_total"] == 6

    def test_a_known_edge_is_reported_even_outside_coverage(
        self, repository: InMemoryRepository
    ):
        # If the pair is in the graph it was demonstrably checked; the edge is the evidence.
        blind = AtcCoverage(covered_groups=(), molecule_groups={})
        report = check_interactions(repository, [WARFARIN, ASPIRIN], blind)
        assert report.pairs[0].status is PairStatus.INTERACTION


class TestCheckedAndClean:
    def test_two_covered_molecules_with_no_edge_are_reported_clean(
        self, repository: InMemoryRepository, coverage: AtcCoverage
    ):
        report = check_interactions(repository, [WARFARIN, METFORMIN], coverage)
        assert report.pairs[0].status is PairStatus.NO_KNOWN_INTERACTION
        assert report.coverage_complete is True

    def test_the_clean_result_states_why_it_is_trustworthy(
        self, repository: InMemoryRepository, coverage: AtcCoverage
    ):
        report = check_interactions(repository, [WARFARIN, METFORMIN], coverage)
        assert "within ingested DDInter coverage" in report.pairs[0].reason


class TestCoverageGap:
    def test_an_uncovered_group_is_not_checked(
        self, repository: InMemoryRepository, coverage: AtcCoverage
    ):
        report = check_interactions(repository, [WARFARIN, ATORVASTATIN], coverage)
        pair = report.pairs[0]
        assert pair.status is PairStatus.NOT_CHECKED
        assert pair.right_atc_group == "C"
        assert "does not cover" in pair.reason

    @pytest.mark.parametrize("other", [ATORVASTATIN, AMOXICILLIN])
    def test_uncovered_molecules_never_produce_a_clean_result(
        self, repository: InMemoryRepository, coverage: AtcCoverage, other: MoleculeInput
    ):
        report = check_interactions(repository, [WARFARIN, other], coverage)
        assert report.pairs[0].status is not PairStatus.NO_KNOWN_INTERACTION

    def test_a_molecule_missing_from_the_manifest_is_not_checked(
        self, repository: InMemoryRepository
    ):
        partial = AtcCoverage(DDINTER_COVERED_ATC_GROUPS, {"MOL004": "B"})
        report = check_interactions(repository, [WARFARIN, METFORMIN], partial)
        assert report.pairs[0].status is PairStatus.NOT_CHECKED
        assert "no ATC group" in report.pairs[0].reason

    def test_a_missing_manifest_makes_nothing_checkable(self, repository: InMemoryRepository):
        missing = AtcCoverage.from_manifest(None)
        report = check_interactions(repository, [WARFARIN, METFORMIN], missing)
        assert report.pairs[0].status is PairStatus.NOT_CHECKED
        assert report.coverage_complete is False
        assert any("no interaction coverage manifest" in note for note in report.notes)

    def test_an_absent_manifest_file_is_flagged(self, tmp_path: Path):
        absent = AtcCoverage.from_manifest(tmp_path / "nope.json")
        assert absent.missing is True
        assert absent.covers("MOL004") is False

    def test_a_manifest_round_trips(self, tmp_path: Path):
        path = tmp_path / "cov.json"
        path.write_text(
            json.dumps({"covered_atc_groups": ["A"], "molecule_atc_groups": {"M1": "a"}}),
            encoding="utf-8",
        )
        loaded = AtcCoverage.from_manifest(path)
        assert loaded.covers("M1") is True, "group codes are compared case-insensitively"
        assert loaded.covers("M2") is False

    def test_the_report_warns_that_absence_is_not_safety(
        self, repository: InMemoryRepository, coverage: AtcCoverage
    ):
        report = check_interactions(repository, [WARFARIN, ATORVASTATIN], coverage)
        assert any("not evidence of safety" in note for note in report.notes)


class TestUnresolvedInput:
    def test_an_unresolved_drug_is_kept_in_the_pairwise_set(
        self, repository: InMemoryRepository, coverage: AtcCoverage
    ):
        report = check_interactions(repository, [WARFARIN, UNRESOLVED], coverage)
        assert report.summary["pairs_total"] == 1
        assert report.pairs[0].status is PairStatus.NOT_CHECKED

    def test_the_reason_names_the_unresolved_string(
        self, repository: InMemoryRepository, coverage: AtcCoverage
    ):
        report = check_interactions(repository, [WARFARIN, UNRESOLVED], coverage)
        assert "zzzznotadrug" in report.pairs[0].reason

    def test_two_unresolved_inputs_still_produce_a_pair(
        self, repository: InMemoryRepository, coverage: AtcCoverage
    ):
        other = MoleculeInput(query="alsonotadrug", resolved=False)
        report = check_interactions(repository, [UNRESOLVED, other], coverage)
        assert report.summary["pairs_total"] == 1
        assert report.pairs[0].status is PairStatus.NOT_CHECKED


class TestReportShape:
    def test_the_summary_accounts_for_every_pair(
        self, repository: InMemoryRepository, coverage: AtcCoverage
    ):
        report = check_interactions(
            repository, [WARFARIN, ASPIRIN, ATORVASTATIN, METFORMIN, UNRESOLVED], coverage
        )
        summary = report.summary
        assert summary["pairs_total"] == 10
        assert (
            summary["interactions_found"]
            + summary["checked_no_interaction"]
            + summary["not_checked"]
            == summary["pairs_total"]
        )

    def test_a_single_drug_produces_no_pairs(
        self, repository: InMemoryRepository, coverage: AtcCoverage
    ):
        report = check_interactions(repository, [WARFARIN], coverage)
        assert report.pairs == ()
        assert report.coverage_complete is True

    def test_the_same_molecule_twice_is_not_a_clean_pair(
        self, repository: InMemoryRepository, coverage: AtcCoverage
    ):
        report = check_interactions(repository, [WARFARIN, WARFARIN], coverage)
        assert report.pairs[0].status is PairStatus.NOT_CHECKED
        assert "twice" in report.pairs[0].reason

    def test_an_empty_report_is_coverage_complete(self):
        assert InteractionReport().coverage_complete is True

    def test_results_are_deterministic(
        self, repository: InMemoryRepository, coverage: AtcCoverage
    ):
        runs = {
            tuple(
                (p.left.label, p.right.label, p.status)
                for p in check_interactions(
                    repository, [WARFARIN, ASPIRIN, ATORVASTATIN], coverage
                ).pairs
            )
            for _ in range(5)
        }
        assert len(runs) == 1
