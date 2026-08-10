"""Tests for ``medsafe.resolution.normalize``.

Normalization defines what "exact match (post-normalization)" means in the locked policy, so these
tests are a guard on what auto-accepts. ``TestDoesNotConflateDistinctDrugs`` is the load-bearing
one: it runs the whole confusable blocklist through normalization and asserts no pair collapses.
"""

from __future__ import annotations

import pytest

from medsafe.resolution.blocklist import ConfusablePairBlocklist
from medsafe.resolution.normalize import canonical_strength, normalize, normalize_key

# A cross-vocabulary sample: PMBJP-style catalogue rows, DDInter-style bare INNs, and manual
# entries.
SAMPLE_INPUTS = [
    "Amoxicillin 500mg Capsule",
    "AMOXYCILLIN 500MG CAP",
    "Metformin Hydrochloride 0.5g Tab",
    "  Paracetamol   (500 MG) Tablet ",
    "Sodium Chloride 0.9% Injection",
    "Salbutamol Sulphate Inhaler 100mcg",
    "Cephalexin 250mg",
    "Oestradiol 2mg tablet",
    "Atorvastatin Calcium 10 mg 10's",
    "warfarin",
    "Amoxicillin and Clavulanic Acid 500mg/125mg Tablet",
]


class TestCaseAndWhitespace:
    def test_case_is_folded(self):
        assert normalize_key("AMOXICILLIN") == "amoxicillin"
        assert normalize_key("AmOxIcIlLiN") == "amoxicillin"

    def test_leading_and_trailing_whitespace_trimmed(self):
        assert normalize_key("   warfarin   ") == "warfarin"

    def test_internal_whitespace_collapsed(self):
        assert normalize_key("clavulanic     acid") == "clavulanic acid"
        assert normalize_key("clavulanic\tacid") == "clavulanic acid"

    def test_empty_input_is_not_an_error(self):
        result = normalize("")
        assert result.normalized == ""
        assert result.tokens == ()


class TestPunctuationAndUnicode:
    def test_hyphens_become_separators(self):
        assert normalize_key("Co-Trimoxazole") == "co trimoxazole"

    def test_parentheses_removed(self):
        assert normalize_key("Paracetamol (500mg)") == "paracetamol"

    def test_accents_are_stripped(self):
        assert normalize_key("Cefalexín") == "cefalexin"

    def test_unicode_micro_sign_is_a_strength_unit_not_a_name_token(self):
        result = normalize("Salbutamol 100µg")
        assert result.normalized == "salbutamol"
        assert result.strength_unit == "mcg"

    def test_decimal_points_survive_punctuation_folding(self):
        result = normalize("Metformin 0.5g")
        assert result.strength_value == 0.5
        assert result.normalized == "metformin"

    def test_pack_counts_do_not_leak_into_the_key(self):
        assert normalize_key("Atorvastatin 10mg 10's") == "atorvastatin"
        assert normalize_key("Amlodipine 5mg 1x10") == "amlodipine"


class TestSaltAndEsterSuffixes:
    @pytest.mark.parametrize(
        "raw,salt",
        [
            ("Metformin Hydrochloride", "hydrochloride"),
            ("Metformin HCl", "hcl"),
            ("Amoxicillin Trihydrate", "trihydrate"),
            ("Warfarin Sodium", "sodium"),
            ("Atorvastatin Calcium", "calcium"),
            ("Salbutamol Sulphate", "sulfate"),
        ],
    )
    def test_salt_is_split_out_not_dropped(self, raw: str, salt: str):
        result = normalize(raw)
        assert salt in result.salts, "the salt must be preserved on its own field"
        assert salt not in result.normalized, "the salt must not remain in the comparison key"

    def test_salt_forms_share_one_key(self):
        keys = {
            normalize_key("Metformin"),
            normalize_key("Metformin HCl"),
            normalize_key("Metformin Hydrochloride"),
        }
        assert keys == {"metformin"}

    def test_salt_order_does_not_matter(self):
        assert normalize_key("Sodium Valproate") == normalize_key("Valproate Sodium")

    def test_a_name_made_only_of_salt_tokens_is_kept_intact(self):
        # "sodium chloride" is a drug, not a salt of nothing. Stripping both tokens would empty the
        # key and make every all-salt name collide.
        result = normalize("Sodium Chloride 0.9% Injection")
        assert result.normalized == "sodium chloride"
        assert result.salts == ()


class TestStrengthExtraction:
    @pytest.mark.parametrize(
        "raw,value,unit",
        [
            ("Amoxicillin 500mg", 500.0, "mg"),
            ("Amoxicillin 500 MG", 500.0, "mg"),
            ("Amoxicillin 500 mg", 500.0, "mg"),
            ("Metformin 0.5g", 0.5, "g"),
            ("Salbutamol 100mcg", 100.0, "mcg"),
            ("Salbutamol 100 ug", 100.0, "mcg"),
            ("Insulin 40IU", 40.0, "iu"),
            ("Lignocaine 2%", 2.0, "%"),
        ],
    )
    def test_value_and_unit_are_split_out(self, raw: str, value: float, unit: str):
        result = normalize(raw)
        assert result.strength_value == value
        assert result.strength_unit == unit

    def test_strength_is_never_silently_dropped(self):
        for raw in ("Amoxicillin 500mg", "Metformin 0.5g", "Salbutamol 100mcg"):
            assert normalize(raw).strength_raw is not None

    def test_strength_is_removed_from_the_key(self):
        assert normalize_key("Amoxicillin 500mg") == normalize_key("Amoxicillin")

    def test_multiple_strengths_are_all_recorded(self):
        result = normalize("Amoxicillin and Clavulanic Acid 500mg/125mg Tablet")
        assert result.strength_raw == "500mg/125mg"

    def test_canonical_strength_makes_units_comparable(self):
        assert canonical_strength(0.5, "g") == canonical_strength(500, "mg")
        assert canonical_strength(100, "mcg") == (0.1, "mg")
        assert canonical_strength(1, "l") == canonical_strength(1000, "ml")

    def test_canonical_strength_returns_none_when_not_comparable(self):
        assert canonical_strength(None, "mg") is None
        assert canonical_strength(5, None) is None
        assert canonical_strength(5, "sachets") is None


class TestFormExtraction:
    @pytest.mark.parametrize(
        "raw,form",
        [
            ("Amoxicillin Tablet", "tablet"),
            ("Amoxicillin Tab", "tablet"),
            ("Amoxicillin Capsule", "capsule"),
            ("Amoxicillin Cap", "capsule"),
            ("Amoxicillin Syrup", "syrup"),
            ("Amoxicillin Syp", "syrup"),
            ("Ceftriaxone Injection", "injection"),
            ("Ceftriaxone Inj", "injection"),
            ("Salbutamol Inhaler", "inhaler"),
        ],
    )
    def test_form_token_is_split_out_of_the_name(self, raw: str, form: str):
        result = normalize(raw)
        assert result.form == form
        assert form not in result.normalized

    def test_form_does_not_change_the_key(self):
        assert normalize_key("Amoxicillin Tablet") == normalize_key("Amoxicillin Syrup")

    def test_missing_form_is_none_not_a_guess(self):
        assert normalize("Amoxicillin 500mg").form is None


class TestSpellingVariants:
    @pytest.mark.parametrize(
        "british,american",
        [
            ("Amoxycillin", "Amoxicillin"),
            ("Salbutamol Sulphate", "Salbutamol Sulfate"),
            ("Cephalexin", "Cefalexin"),
            ("Oestradiol", "Estradiol"),
            ("Guaiphenesin", "Guaifenesin"),
        ],
    )
    def test_variants_normalize_to_the_same_key(self, british: str, american: str):
        assert normalize_key(british) == normalize_key(american)

    def test_synonyms_are_left_to_the_alias_table(self):
        # Different words for the same molecule are a curation decision, not a string rule.
        # Folding them here would hide that decision inside a string function.
        assert normalize_key("Paracetamol") != normalize_key("Acetaminophen")
        assert normalize_key("Adrenaline") != normalize_key("Epinephrine")


class TestIdempotence:
    @pytest.mark.parametrize("raw", SAMPLE_INPUTS)
    def test_normalizing_a_key_is_a_no_op(self, raw: str):
        key = normalize_key(raw)
        assert normalize_key(key) == key

    @pytest.mark.parametrize("raw", SAMPLE_INPUTS)
    def test_repeated_application_is_stable(self, raw: str):
        key = normalize_key(raw)
        for _ in range(5):
            key = normalize_key(key)
        assert key == normalize_key(raw)


class TestDeterminism:
    @pytest.mark.parametrize("raw", SAMPLE_INPUTS)
    def test_same_input_same_output(self, raw: str):
        assert len({normalize_key(raw) for _ in range(10)}) == 1

    def test_same_drug_across_vocabularies_lands_on_one_key(self):
        # A PMBJP catalogue row, a DDInter bare INN, and a manual entry must agree.
        keys = {
            normalize_key("Amoxicillin 500mg Capsule"),  # pmbjp
            normalize_key("amoxicillin"),  # ddinter
            normalize_key("Amoxycillin Trihydrate 500 MG CAP"),  # manual
        }
        assert keys == {"amoxicillin"}

    def test_full_result_is_reproducible(self):
        first = normalize("Metformin Hydrochloride 0.5g Tab")
        second = normalize("Metformin Hydrochloride 0.5g Tab")
        assert first == second


class TestDoesNotConflateDistinctDrugs:
    """Regression guard on the whole resolution policy.

    If normalization ever maps two blocklisted confusables onto one key, the exact-match path would
    auto-accept the wrong drug and no downstream control could catch it.
    """

    def test_no_blocklisted_pair_collapses_to_one_key(self, blocklist: ConfusablePairBlocklist):
        assert len(blocklist) > 0, "blocklist fixture must not be empty"
        collisions = [
            (entry.name_a, entry.name_b)
            for entry in blocklist.entries
            if entry.key_a == entry.key_b
        ]
        assert collisions == []

    def test_loading_the_blocklist_would_raise_on_a_collapsing_pair(self):
        from medsafe.errors import ConfigurationError

        with pytest.raises(ConfigurationError):
            # Same drug, two salt forms: these normalize to one key, so they cannot be a
            # "distinct drugs" blocklist row and the loader must say so rather than accept it.
            ConfusablePairBlocklist.from_pairs(
                [("Metformin Hydrochloride", "Metformin HCl")]
            )

    @pytest.mark.parametrize(
        "left,right",
        [
            ("hydralazine", "hydroxyzine"),
            ("prednisone", "prednisolone"),
            ("chlorpromazine", "chlorpropamide"),
            ("vinblastine", "vincristine"),
            ("lamivudine", "lamotrigine"),
        ],
    )
    def test_named_confusables_stay_apart(self, left: str, right: str):
        assert normalize_key(left) != normalize_key(right)
