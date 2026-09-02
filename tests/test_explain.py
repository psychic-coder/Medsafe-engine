"""Tests for the plain-English layer.

Two of these are not ordinary unit tests. :class:`TestUncheckedIsNeverReassuring` and
:class:`TestFindingsAreNeverSoftened` assert a property over *every* state the renderer can produce,
because the wording is the last thing standing between a coverage gap and a reader who concludes
their prescription is fine. A regression there is a safety regression, and it would not otherwise
fail anything: the enum would still say ``not_checked``, the tests would still pass, and only the
sentence a human reads would have changed.
"""

from __future__ import annotations

import re

import pytest

from medsafe.explain import (
    ATC_GROUP_LABELS,
    explain_coverage,
    explain_pair,
    explain_resolution,
    explain_substitution,
    readable_provenance,
    severity_label,
)
from medsafe.pricing.substitution import SubstitutionStatus
from medsafe.resolution.matcher import ResolutionStatus
from medsafe.safety.interactions import PairStatus

# Words that tell a reader nothing is wrong. None may appear in a state where we did not look.
REASSURING = (
    "safe",
    "fine",
    "no problem",
    "all clear",
    "nothing to worry",
    "don't worry",
    "no risk",
    "harmless",
)

# Hedges that would downgrade a recorded finding into a maybe.
HEDGING = ("might", "possibly", "perhaps", "probably", "may be")


def _text(explanation) -> str:
    return " ".join(
        part for part in (explanation.headline, explanation.detail, explanation.action) if part
    ).lower()


def _contains_word(haystack: str, phrase: str) -> bool:
    """Whole-word match, so "unsafe" does not count as a hit for "safe"."""
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", haystack) is not None


class TestUncheckedIsNeverReassuring:
    """No unchecked or unidentified state may read as an all-clear."""

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"left_resolved": False},
            {"right_resolved": False},
            {"coverage_missing": True},
            {"left_group": "C"},
            {"right_group": "N"},
            {"left_group": "J", "right_group": "M"},
            {},
        ],
    )
    def test_not_checked_never_reads_as_clear(self, kwargs: dict) -> None:
        explanation = explain_pair(
            PairStatus.NOT_CHECKED, left="warfarin", right="atorvastatin", **kwargs
        )
        body = _text(explanation)
        assert "not checked" in body or "could not" in body
        for word in REASSURING:
            assert not _contains_word(body, word), (
                f"{word!r} appeared in a not_checked explanation"
            )

    def test_not_checked_always_says_what_to_do(self) -> None:
        explanation = explain_pair(
            PairStatus.NOT_CHECKED, left="warfarin", right="atorvastatin", left_group="C"
        )
        assert explanation.action, "an unchecked pair must tell the reader what to do next"

    @pytest.mark.parametrize(
        "status", [ResolutionStatus.UNRESOLVED, ResolutionStatus.NEEDS_REVIEW]
    )
    def test_unidentified_never_reads_as_clear(self, status: ResolutionStatus) -> None:
        explanation = explain_resolution(
            status, query="Zinthromax", candidate_names=("azithromycin",)
        )
        for word in REASSURING:
            assert not _contains_word(_text(explanation), word)

    def test_unidentified_does_not_imply_the_drug_is_dangerous(self) -> None:
        """The opposite failure: "not in our list" must not read as "this drug is bad"."""
        explanation = explain_resolution(ResolutionStatus.UNRESOLVED, query="Zinthromax")
        assert "unsafe" in explanation.detail or "not mean" in explanation.detail

    def test_coverage_summary_with_gaps_never_claims_a_clean_list(self) -> None:
        explanation = explain_coverage(
            pairs_total=3, interactions_found=0, checked_clear=1, not_checked=2
        )
        body = _text(explanation)
        for word in REASSURING:
            assert not _contains_word(body, word)
        assert "not check" in body

    def test_missing_manifest_says_so_and_blames_the_server(self) -> None:
        explanation = explain_coverage(
            pairs_total=3,
            interactions_found=0,
            checked_clear=0,
            not_checked=3,
            coverage_missing=True,
        )
        assert "could not check" in explanation.headline.lower()
        assert "missing" in explanation.detail.lower()


class TestFindingsAreNeverSoftened:
    """A recorded interaction is reported as recorded, not as a possibility."""

    @pytest.mark.parametrize("severity", ["Major", "Moderate", "Minor", "Unknown", None])
    def test_headline_does_not_hedge(self, severity: str | None) -> None:
        explanation = explain_pair(
            PairStatus.INTERACTION, left="warfarin", right="aspirin", severity=severity
        )
        headline = explanation.headline.lower()
        for word in HEDGING:
            assert not _contains_word(headline, word), f"{word!r} softened a real finding"

    def test_a_major_interaction_is_escalated(self) -> None:
        explanation = explain_pair(
            PairStatus.INTERACTION, left="warfarin", right="aspirin", severity="Major"
        )
        assert "serious" in explanation.headline.lower()
        assert explanation.action and "doctor" in explanation.action.lower()

    def test_no_finding_tells_the_reader_not_to_self_medicate(self) -> None:
        explanation = explain_pair(
            PairStatus.INTERACTION, left="warfarin", right="aspirin", severity="Major"
        )
        assert "do not stop" in (explanation.action or "").lower()

    def test_unknown_severity_is_not_treated_as_small(self) -> None:
        explanation = explain_pair(
            PairStatus.INTERACTION, left="a", right="b", severity="Unknown"
        )
        assert "not a reason to assume it is small" in explanation.detail

    def test_a_clean_pair_states_the_check_actually_happened(self) -> None:
        explanation = explain_pair(PairStatus.NO_KNOWN_INTERACTION, left="a", right="b")
        assert "real check" in explanation.detail


class TestSeverityBucketing:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Major", "major"),
            ("severe", "major"),
            ("Moderate", "moderate"),
            ("Minor", "minor"),
            ("Unknown", "unknown"),
            ("", "unknown"),
            (None, "unknown"),
        ],
    )
    def test_buckets(self, raw: str | None, expected: str) -> None:
        assert severity_label(raw) == expected


class TestReadableProvenance:
    def test_a_source_filename_becomes_a_sentence(self) -> None:
        text = readable_provenance("ddinter_downloads_code_B.csv")
        assert text is not None
        assert ".csv" not in text
        assert "DDInter" in text
        assert ATC_GROUP_LABELS["B"] in text

    def test_several_files_are_joined(self) -> None:
        text = readable_provenance(
            "ddinter_downloads_code_A.csv|ddinter_downloads_code_B.csv"
        )
        assert text is not None
        assert ATC_GROUP_LABELS["A"] in text and ATC_GROUP_LABELS["B"] in text

    def test_empty_provenance_yields_nothing_rather_than_a_placeholder(self) -> None:
        assert readable_provenance("") is None
        assert readable_provenance(None) is None

    def test_unrecognised_provenance_is_passed_through_not_invented(self) -> None:
        text = readable_provenance("some_other_source.csv")
        assert text is not None and "some_other_source.csv" in text


class TestResolutionWording:
    def test_a_brand_is_explained_as_a_brand(self) -> None:
        explanation = explain_resolution(
            ResolutionStatus.RESOLVED,
            query="Ecosprin",
            inn_name="acetylsalicylic acid",
            alias_raw_string="ecosprin",
        )
        assert "brand name" in explanation.detail

    def test_a_combination_names_every_ingredient(self) -> None:
        explanation = explain_resolution(
            ResolutionStatus.COMBINATION,
            query="Augmentin",
            component_names=("amoxicillin", "clavulanic acid"),
        )
        assert "amoxicillin" in explanation.headline
        assert "clavulanic acid" in explanation.headline

    def test_a_combination_explains_why_no_swap_is_offered(self) -> None:
        explanation = explain_resolution(
            ResolutionStatus.COMBINATION,
            query="Augmentin",
            component_names=("amoxicillin", "clavulanic acid"),
        )
        assert "not the same medicine" in explanation.detail

    def test_review_wording_refuses_to_guess(self) -> None:
        explanation = explain_resolution(
            ResolutionStatus.NEEDS_REVIEW,
            query="hydralzine",
            candidate_names=("hydralazine", "hydroxyzine"),
        )
        assert "will not guess" in explanation.detail.lower()


class TestSubstitutionWording:
    def test_a_combination_refusal_explains_itself(self) -> None:
        explanation = explain_substitution(
            SubstitutionStatus.OUT_OF_SCOPE_FDC, inn_name="amoxicillin"
        )
        assert "more than one active ingredient" in explanation.detail

    def test_savings_are_quoted_with_their_baseline(self) -> None:
        explanation = explain_substitution(
            SubstitutionStatus.OK,
            inn_name="metformin",
            substitute_count=2,
            best_savings_pct=40.0,
            reference_price=100.0,
            best_price=60.0,
        )
        assert "40%" in explanation.detail
        assert "100.00" in explanation.detail and "60.00" in explanation.detail

    def test_no_products_does_not_imply_the_drug_is_unavailable(self) -> None:
        explanation = explain_substitution(
            SubstitutionStatus.NO_PRODUCTS, inn_name="rare thing"
        )
        assert "does not cover every medicine" in explanation.detail


class TestCoverageSummaryArithmetic:
    def test_singular_and_plural_agree(self) -> None:
        one = explain_coverage(
            pairs_total=1, interactions_found=0, checked_clear=1, not_checked=0
        )
        assert "1 combination checked" in one.headline
        many = explain_coverage(
            pairs_total=3, interactions_found=0, checked_clear=3, not_checked=0
        )
        assert "3 combinations checked" in many.headline

    def test_an_empty_list_asks_for_more_input(self) -> None:
        explanation = explain_coverage(
            pairs_total=0, interactions_found=0, checked_clear=0, not_checked=0
        )
        assert explanation.action and "add" in explanation.action.lower()

    def test_findings_are_counted_in_the_headline(self) -> None:
        explanation = explain_coverage(
            pairs_total=4, interactions_found=2, checked_clear=1, not_checked=1
        )
        assert "2 known interactions" in explanation.headline
        assert "1 of them could not be checked" in explanation.detail


class TestGrammarAgreement:
    """Singular and plural must agree.

    Not pedantry. "All 1 combination fall outside the data we have" is the sentence that tells a
    reader their prescription was not checked, and a reader who trips over the grammar of the most
    important sentence on the page is a reader who skims it.
    """

    def test_a_single_unchecked_pair_reads_as_singular(self) -> None:
        explanation = explain_coverage(
            pairs_total=1, interactions_found=0, checked_clear=0, not_checked=1
        )
        body = _text(explanation)
        assert "1 combination fall" not in body
        assert "these combinations" not in body
        assert "this combination" in body

    def test_a_single_clear_pair_reads_as_singular(self) -> None:
        explanation = explain_coverage(
            pairs_total=1, interactions_found=0, checked_clear=1, not_checked=0
        )
        assert "all 1 combination" not in explanation.headline.lower()

    def test_several_unchecked_pairs_read_as_plural(self) -> None:
        explanation = explain_coverage(
            pairs_total=3, interactions_found=0, checked_clear=0, not_checked=3
        )
        assert "3 combinations fall" in explanation.detail
