"""Tests for ``medsafe.pricing.substitution``.

The rules under test are conservative by design: an equivalence that cannot be *verified* is not an
equivalence, and a combination product is reported as out of scope rather than partially matched.
"""

from __future__ import annotations

import pytest

from medsafe.graph.loader import ArtifactSet, load_records
from medsafe.graph.repository import InMemoryRepository
from medsafe.pricing.substitution import (
    SubstitutionStatus,
    find_substitutes_for_molecule,
    find_substitutes_for_product,
    materialize_substitute_edges,
)


class TestSavingsArithmetic:
    def test_savings_abs_and_pct_are_computed_from_mrp(self, repository: InMemoryRepository):
        result = find_substitutes_for_product(repository, "PRD003")  # 112.00 branded
        by_id = {s.product.product_id: s for s in result.substitutes}
        assert by_id["PRD001"].savings_abs == 79.50  # 112.00 - 32.50
        assert by_id["PRD001"].savings_pct == 70.98
        assert by_id["PRD002"].savings_abs == 14.00
        assert by_id["PRD002"].savings_pct == 12.50

    def test_results_are_ranked_by_absolute_saving(self, repository: InMemoryRepository):
        result = find_substitutes_for_product(repository, "PRD003")
        savings = [s.savings_abs for s in result.substitutes]
        assert savings == sorted(savings, reverse=True)

    def test_costlier_products_are_excluded_by_default(self, repository: InMemoryRepository):
        result = find_substitutes_for_product(repository, "PRD001")  # the cheapest already
        assert result.status is SubstitutionStatus.NO_SUBSTITUTES
        reasons = {e["reason"] for e in result.excluded}
        assert "not cheaper than the reference" in reasons

    def test_costlier_products_can_be_requested(self, repository: InMemoryRepository):
        result = find_substitutes_for_product(repository, "PRD001", include_costlier=True)
        assert result.substitutes
        assert all(s.savings_abs <= 0 for s in result.substitutes)

    def test_a_zero_price_reference_does_not_divide_by_zero(self):
        repo = InMemoryRepository()
        load_records(
            repo,
            ArtifactSet(
                molecules=[{"molecule_id": "M1", "inn_name": "x", "category": "small_molecule"}],
                products=[
                    {
                        "product_id": "P1",
                        "source": "PMBJP",
                        "generic_name_raw": "x",
                        "form": "tablet",
                        "strength_raw": "1mg",
                        "mrp": 0,
                    },
                    {
                        "product_id": "P2",
                        "source": "PMBJP",
                        "generic_name_raw": "x",
                        "form": "tablet",
                        "strength_raw": "1mg",
                        "mrp": 5,
                    },
                ],
                contains=[
                    {"product_id": "P1", "molecule_id": "M1", "strength": 1, "unit": "mg"},
                    {"product_id": "P2", "molecule_id": "M1", "strength": 1, "unit": "mg"},
                ],
            ),
        )
        result = find_substitutes_for_product(repo, "P1", include_costlier=True)
        assert result.substitutes[0].savings_pct == 0.0
        assert any("cannot be computed" in note for note in result.notes)


class TestEquivalenceRules:
    def test_a_different_strength_is_excluded(self, repository: InMemoryRepository):
        result = find_substitutes_for_product(repository, "PRD003")
        excluded = {e["product_id"]: e["reason"] for e in result.excluded}
        assert "strength differs" in excluded["PRD004"]

    def test_strengths_are_compared_after_unit_conversion(self, repository: InMemoryRepository):
        # PRD012 is 0.5g; PRD010 and PRD011 are 500mg.
        result = find_substitutes_for_product(repository, "PRD012")
        assert {s.product.product_id for s in result.substitutes} == {"PRD010", "PRD011"}

    def test_a_different_form_is_excluded(self):
        repo = InMemoryRepository()
        load_records(
            repo,
            ArtifactSet(
                molecules=[{"molecule_id": "M1", "inn_name": "x", "category": "small_molecule"}],
                products=[
                    {
                        "product_id": "P1",
                        "source": "branded_csv",
                        "generic_name_raw": "x tablet",
                        "form": "tablet",
                        "strength_raw": "1mg",
                        "mrp": 50,
                    },
                    {
                        "product_id": "P2",
                        "source": "PMBJP",
                        "generic_name_raw": "x syrup",
                        "form": "syrup",
                        "strength_raw": "1mg",
                        "mrp": 5,
                    },
                ],
                contains=[
                    {"product_id": "P1", "molecule_id": "M1", "strength": 1, "unit": "mg"},
                    {"product_id": "P2", "molecule_id": "M1", "strength": 1, "unit": "mg"},
                ],
            ),
        )
        result = find_substitutes_for_product(repo, "P1")
        assert result.substitutes == ()
        assert "dosage form differs" in result.excluded[0]["reason"]

    def test_unverifiable_equivalence_is_not_equivalence(self):
        repo = InMemoryRepository()
        load_records(
            repo,
            ArtifactSet(
                molecules=[{"molecule_id": "M1", "inn_name": "x", "category": "small_molecule"}],
                products=[
                    {
                        "product_id": "P1",
                        "source": "branded_csv",
                        "generic_name_raw": "x",
                        "form": "tablet",
                        "strength_raw": "1mg",
                        "mrp": 50,
                    },
                    {
                        "product_id": "P2",
                        "source": "PMBJP",
                        "generic_name_raw": "x",
                        "form": "tablet",
                        "strength_raw": "",
                        "mrp": 5,
                    },
                ],
                contains=[
                    {"product_id": "P1", "molecule_id": "M1", "strength": 1, "unit": "mg"},
                    {"product_id": "P2", "molecule_id": "M1", "strength": None, "unit": None},
                ],
            ),
        )
        result = find_substitutes_for_product(repo, "P1")
        assert result.substitutes == ()
        assert "not comparable" in result.excluded[0]["reason"]


class TestSingleMoleculeRule:
    def test_an_fdc_reference_is_out_of_scope(self, repository: InMemoryRepository):
        result = find_substitutes_for_product(repository, "PRD040")
        assert result.status is SubstitutionStatus.OUT_OF_SCOPE_FDC
        assert result.substitutes == ()

    def test_the_out_of_scope_reason_is_explicit(self, repository: InMemoryRepository):
        result = find_substitutes_for_product(repository, "PRD040")
        assert any("unsafe" in note for note in result.notes)

    def test_an_fdc_is_never_offered_as_a_substitute(self, repository: InMemoryRepository):
        result = find_substitutes_for_product(repository, "PRD003")
        assert "PRD040" not in {s.product.product_id for s in result.substitutes}

    def test_a_molecule_available_only_in_an_fdc_is_out_of_scope(
        self, repository: InMemoryRepository
    ):
        result = find_substitutes_for_molecule(repository, "MOL014")
        assert result.status is SubstitutionStatus.OUT_OF_SCOPE_FDC


class TestMoleculeEntryPoint:
    def test_the_baseline_is_the_most_expensive_equivalent(self, repository: InMemoryRepository):
        result = find_substitutes_for_molecule(
            repository, "MOL001", form="capsule", strength_value=500, strength_unit="mg"
        )
        assert result.reference.product_id == "PRD003"
        assert any("most expensive" in note for note in result.notes)

    def test_an_explicit_reference_product_is_honoured(self, repository: InMemoryRepository):
        result = find_substitutes_for_molecule(
            repository, "MOL001", reference_product_id="PRD002"
        )
        assert result.reference.product_id == "PRD002"
        assert {s.product.product_id for s in result.substitutes} == {"PRD001"}

    def test_form_and_strength_constrain_the_pool(self, repository: InMemoryRepository):
        result = find_substitutes_for_molecule(
            repository, "MOL001", form="capsule", strength_value=250, strength_unit="mg"
        )
        assert result.status is SubstitutionStatus.NO_SUBSTITUTES

    def test_an_unknown_molecule_reports_no_products(self, repository: InMemoryRepository):
        result = find_substitutes_for_molecule(repository, "NOPE")
        assert result.status is SubstitutionStatus.NO_PRODUCTS

    def test_an_unknown_product_reports_no_products(self, repository: InMemoryRepository):
        result = find_substitutes_for_product(repository, "NOPE")
        assert result.status is SubstitutionStatus.NO_PRODUCTS

    def test_results_are_deterministic(self, repository: InMemoryRepository):
        runs = {
            tuple(
                s.product.product_id
                for s in find_substitutes_for_molecule(
                    repository, "MOL001", form="capsule", strength_value=500, strength_unit="mg"
                ).substitutes
            )
            for _ in range(5)
        }
        assert len(runs) == 1


class TestMaterializedEdges:
    def test_edges_carry_the_savings(self, repository: InMemoryRepository):
        result = find_substitutes_for_product(repository, "PRD003")
        written = materialize_substitute_edges(repository, result)
        assert written == len(result.substitutes)
        edge = repository.substitute_for[("PRD001", "PRD003")]
        assert edge["savings_abs"] == 79.50
        assert edge["savings_pct"] == 70.98

    def test_nothing_is_written_for_an_empty_result(self, repository: InMemoryRepository):
        result = find_substitutes_for_product(repository, "PRD040")
        assert materialize_substitute_edges(repository, result) == 0

    def test_rewriting_is_idempotent(self, repository: InMemoryRepository):
        result = find_substitutes_for_product(repository, "PRD003")
        materialize_substitute_edges(repository, result)
        materialize_substitute_edges(repository, result)
        assert repository.counts()["relationships"]["SUBSTITUTE_FOR"] == len(result.substitutes)


@pytest.mark.parametrize("product_id", ["PRD001", "PRD002", "PRD003", "PRD010", "PRD020"])
def test_no_substitute_is_ever_a_different_molecule(
    repository: InMemoryRepository, product_id: str
):
    result = find_substitutes_for_product(repository, product_id)
    expected = {m["molecule_id"] for m in repository.molecules_for_product(product_id)}
    for substitute in result.substitutes:
        actual = {
            m["molecule_id"]
            for m in repository.molecules_for_product(substitute.product.product_id)
        }
        assert actual == expected
