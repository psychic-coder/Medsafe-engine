"""Tests for ``medsafe.resolution.matcher``.

The policy under test is locked in ``docs/schema.md``: exact and alias are the only auto-accept
paths, fuzzy produces review candidates and nothing else, and blocklisted confusables never surface.

``TestFuzzyNeverAutoAccepts`` and ``TestBlocklistedPairNeverReturned`` are the patient-safety tests.
Both deliberately run at settings *more permissive* than production — threshold 0 and threshold 70
respectively — so that they prove the guarantee holds structurally rather than proving that the
default threshold happened to hide the problem.
"""

from __future__ import annotations

import pytest

from medsafe.graph.loader import ArtifactSet, load_records
from medsafe.graph.repository import InMemoryRepository
from medsafe.resolution.blocklist import ConfusablePairBlocklist
from medsafe.resolution.matcher import (
    Matcher,
    MatchPath,
    MoleculeRef,
    ResolutionResult,
    ResolutionStatus,
    ResolvedMatch,
    ReviewCandidate,
)


class TestExactMatch:
    def test_inn_name_resolves_and_auto_accepts(self, matcher: Matcher):
        result = matcher.resolve("amoxicillin")
        assert result.status is ResolutionStatus.RESOLVED
        assert result.is_resolved
        assert result.path is MatchPath.EXACT
        assert result.molecule.molecule_id == "MOL001"
        assert result.candidates == ()

    def test_exact_match_survives_normalization_noise(self, matcher: Matcher):
        result = matcher.resolve("  AMOXICILLIN Trihydrate 500 MG Capsule  ")
        assert result.path is MatchPath.EXACT
        assert result.molecule.molecule_id == "MOL001"

    def test_multi_token_inn_resolves(self, matcher: Matcher):
        result = matcher.resolve("Clavulanic Acid")
        assert result.path is MatchPath.EXACT
        assert result.molecule.molecule_id == "MOL014"

    def test_normalized_query_is_reported(self, matcher: Matcher):
        result = matcher.resolve("Amoxicillin 500mg Cap")
        assert result.match.normalized_query == "amoxicillin"


class TestAliasResolvedMatch:
    def test_alias_only_string_auto_accepts(self, matcher: Matcher):
        result = matcher.resolve("Albuterol")
        assert result.status is ResolutionStatus.RESOLVED
        assert result.path is MatchPath.ALIAS

    def test_alias_returns_the_molecule_it_points_at(self, matcher: Matcher):
        result = matcher.resolve("Albuterol")
        assert result.molecule.molecule_id == "MOL012"
        assert result.molecule.inn_name == "salbutamol"

    def test_alias_provenance_is_reported(self, matcher: Matcher):
        result = matcher.resolve("Albuterol")
        assert result.match.alias_raw_string == "Albuterol"
        assert result.match.alias_source == "rxnorm_dump"

    def test_brand_alias_resolves_through_catalogue_noise(self, matcher: Matcher):
        result = matcher.resolve("Ecosprin 75 Tablet")
        assert result.path is MatchPath.ALIAS
        assert result.molecule.inn_name == "aspirin"


class TestFuzzyCandidateGeneration:
    def test_near_miss_returns_candidates(self, matcher: Matcher):
        result = matcher.resolve("amoxicilin")
        assert result.status is ResolutionStatus.NEEDS_REVIEW
        assert result.candidates
        assert result.candidates[0].molecule.inn_name == "amoxicillin"

    def test_result_is_typed_as_unresolved(self, matcher: Matcher):
        result = matcher.resolve("amoxicilin")
        assert not result.is_resolved
        assert result.match is None
        assert result.molecule is None
        assert result.path is None

    def test_candidates_carry_scores(self, matcher: Matcher):
        result = matcher.resolve("amoxicilin")
        for candidate in result.candidates:
            assert 0 <= candidate.score <= 100
            assert candidate.score >= matcher.candidate_threshold

    def test_candidates_are_marked_for_human_review(self, matcher: Matcher):
        result = matcher.resolve("amoxicilin")
        assert all(c.requires_human_review for c in result.candidates)
        assert not any(c.auto_accepted for c in result.candidates)

    def test_result_says_nothing_was_accepted(self, matcher: Matcher):
        result = matcher.resolve("amoxicilin")
        assert any("human review" in note for note in result.notes)

    def test_candidate_count_is_capped(self, repository, blocklist):
        capped = Matcher(repository, blocklist, candidate_threshold=0, max_candidates=3)
        assert len(capped.resolve("xyzzyplugh").candidates) <= 3


class TestFuzzyNeverAutoAccepts:
    def test_no_threshold_setting_turns_a_candidate_into_a_match(self, repository, blocklist):
        # Threshold 0 admits the entire vocabulary as candidates. Not one becomes a match.
        wide_open = Matcher(repository, blocklist, candidate_threshold=0, max_candidates=50)
        for query in ("amoxicilin", "metformim", "atorvastatn", "xyzzyplugh"):
            result = wide_open.resolve(query)
            assert result.match is None
            assert result.status is not ResolutionStatus.RESOLVED
            assert not result.is_resolved

    def test_a_near_perfect_score_is_still_only_a_candidate(self, repository, blocklist):
        wide_open = Matcher(repository, blocklist, candidate_threshold=0, max_candidates=50)
        result = wide_open.resolve("amoxicillim")  # one character out; scores in the high 90s
        top = result.candidates[0]
        assert top.score > 90
        assert result.match is None
        assert not top.auto_accepted

    def test_the_match_type_cannot_represent_a_fuzzy_path(self):
        molecule = MoleculeRef("MOL001", "amoxicillin", "small_molecule")
        with pytest.raises(ValueError):
            ResolvedMatch(molecule=molecule, path="fuzzy", normalized_query="amoxicilin")

    def test_a_candidate_cannot_be_flagged_accepted(self):
        molecule = MoleculeRef("MOL001", "amoxicillin", "small_molecule")
        with pytest.raises(ValueError):
            ReviewCandidate(
                molecule=molecule,
                score=99.0,
                matched_string="amoxicillin",
                matched_on="inn_name",
                auto_accepted=True,
            )

    def test_a_result_cannot_present_candidates_as_resolved(self, matcher: Matcher):
        near_miss = matcher.resolve("amoxicilin")
        with pytest.raises(ValueError):
            ResolutionResult(
                query=near_miss.query,
                normalized=near_miss.normalized,
                status=ResolutionStatus.RESOLVED,
                match=None,
                candidates=near_miss.candidates,
            )

    def test_a_non_resolved_result_cannot_carry_a_match(self, matcher: Matcher):
        resolved = matcher.resolve("amoxicillin")
        with pytest.raises(ValueError):
            ResolutionResult(
                query="amoxicilin",
                normalized=resolved.normalized,
                status=ResolutionStatus.NEEDS_REVIEW,
                match=resolved.match,
            )


class TestBlocklistedPairNeverReturned:
    """A confirmed confusable is never a match and never a review suggestion, at any score."""

    def test_partner_is_suppressed_when_the_query_is_its_confusable(
        self, permissive_matcher: Matcher
    ):
        # "hydralazine" is not in the graph; "hydroxyzine" is, and scores 72.7 at this threshold.
        result = permissive_matcher.resolve("hydralazine")
        names = {c.molecule.inn_name for c in result.candidates}
        assert "hydroxyzine" not in names
        assert result.match is None

    def test_the_suppression_is_reported_for_audit(self, permissive_matcher: Matcher):
        result = permissive_matcher.resolve("hydralazine")
        suppressed = {s.inn_name for s in result.suppressed}
        assert "hydroxyzine" in suppressed
        assert all(s.reason for s in result.suppressed)

    def test_both_members_are_dropped_when_both_would_surface(
        self, permissive_matcher: Matcher
    ):
        # Fuzzy scoring demonstrably cannot separate them here, so offering either — including the
        # higher-scoring one — is the wrong-drug failure mode.
        result = permissive_matcher.resolve("prednisolon")
        names = {c.molecule.inn_name for c in result.candidates}
        assert "prednisolone" not in names
        assert "prednisone" not in names
        suppressed = {s.inn_name for s in result.suppressed}
        assert {"prednisolone", "prednisone"} <= suppressed

    def test_suppression_holds_with_the_threshold_wide_open(self, repository, blocklist):
        wide_open = Matcher(repository, blocklist, candidate_threshold=0, max_candidates=50)
        for query in ("hydralazine", "prednisolon"):
            names = {c.molecule.inn_name for c in wide_open.resolve(query).candidates}
            for candidate_name in names:
                for other in names:
                    assert not blocklist.contains(candidate_name, other)

    def test_no_blocklisted_partner_of_any_query_ever_appears(self, repository, blocklist):
        wide_open = Matcher(repository, blocklist, candidate_threshold=0, max_candidates=50)
        vocabulary = [m["inn_name"] for m in repository.all_molecule_names()]
        for name in vocabulary:
            partners = blocklist.partners_of(name)
            if not partners:
                continue
            candidates = {c.molecule.inn_name for c in wide_open.resolve(name).candidates}
            assert not (candidates & partners)

    def test_an_exact_match_is_unaffected_by_the_blocklist(self, permissive_matcher: Matcher):
        # The blocklist guards fuzzy scoring. An exact key match is not a guess and still accepts.
        result = permissive_matcher.resolve("prednisone")
        assert result.status is ResolutionStatus.RESOLVED
        assert result.path is MatchPath.EXACT
        assert result.molecule.molecule_id == "MOL011"


class TestNoMatch:
    def test_unknown_string_is_unresolved_not_an_error(self, matcher: Matcher):
        result = matcher.resolve("zzzznotadrug")
        assert result.status is ResolutionStatus.UNRESOLVED
        assert result.candidates == ()
        assert result.match is None

    def test_empty_string_is_unresolved_not_an_error(self, matcher: Matcher):
        result = matcher.resolve("   ")
        assert result.status is ResolutionStatus.UNRESOLVED
        assert result.candidates == ()

    def test_a_string_of_only_dosage_noise_is_unresolved(self, matcher: Matcher):
        result = matcher.resolve("500mg tablet")
        assert result.status is ResolutionStatus.UNRESOLVED


class TestMatchPathPrecedence:
    def test_exact_wins_over_alias(self):
        # "foo" is both an INN and an alias pointing at a different molecule. Exact must win.
        repo = InMemoryRepository()
        load_records(
            repo,
            ArtifactSet(
                molecules=[
                    {"molecule_id": "M1", "inn_name": "foo", "category": "small_molecule"},
                    {"molecule_id": "M2", "inn_name": "bar", "category": "small_molecule"},
                ],
                aliases=[
                    {
                        "raw_string": "foo",
                        "normalized_string": "foo",
                        "source": "manual",
                        "molecule_id": "M2",
                    }
                ],
            ),
        )
        result = Matcher(repo, ConfusablePairBlocklist(), candidate_threshold=88,
                         max_candidates=5).resolve("foo")
        assert result.path is MatchPath.EXACT
        assert result.molecule.molecule_id == "M1"

    def test_alias_wins_over_fuzzy_candidates(self, matcher: Matcher):
        # "Atorva" is an alias for atorvastatin and also scores highly against it by fuzz.
        result = matcher.resolve("Atorva")
        assert result.path is MatchPath.ALIAS
        assert result.candidates == ()

    def test_a_resolved_result_never_carries_candidates(self, matcher: Matcher):
        for query in ("amoxicillin", "Albuterol", "Ecosprin"):
            assert matcher.resolve(query).candidates == ()


class TestCandidateOrdering:
    def test_candidates_are_ranked_by_score_descending(self, repository, blocklist):
        wide_open = Matcher(repository, blocklist, candidate_threshold=0, max_candidates=50)
        scores = [c.score for c in wide_open.resolve("amoxicilin").candidates]
        assert scores == sorted(scores, reverse=True)

    def test_ties_break_deterministically_by_name(self):
        # "axx" is exactly one edit from both "abx" and "acx": identical scores, so the tie-break
        # decides the order. A review queue that reshuffles between runs is not reviewable.
        repo = InMemoryRepository()
        load_records(
            repo,
            ArtifactSet(
                molecules=[
                    {"molecule_id": "M2", "inn_name": "acx", "category": "small_molecule"},
                    {"molecule_id": "M1", "inn_name": "abx", "category": "small_molecule"},
                ]
            ),
        )
        matcher = Matcher(
            repo, ConfusablePairBlocklist(), candidate_threshold=0, max_candidates=10
        )
        names = [c.molecule.inn_name for c in matcher.resolve("axx").candidates]
        assert names[:2] == ["abx", "acx"]

    def test_ordering_is_stable_across_runs(self, repository, blocklist):
        wide_open = Matcher(repository, blocklist, candidate_threshold=0, max_candidates=50)
        runs = {
            tuple(c.molecule.molecule_id for c in wide_open.resolve("amoxicilin").candidates)
            for _ in range(5)
        }
        assert len(runs) == 1
