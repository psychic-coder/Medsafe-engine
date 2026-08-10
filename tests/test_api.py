"""Tests for the FastAPI surface (httpx client against ``medsafe.api.main:app``).

The wire contract carries two distinctions that the rest of the engine exists to preserve, so they
are asserted on the JSON itself rather than on the domain objects:

* a fuzzy candidate must be unreadable as an accepted match (``TestResolveFuzzyCandidates``);
* "not checked" must be unreadable as "no known interaction" (``TestCheckCoverageGap``).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import UnavailableRepository, build_client


class TestHealth:
    def test_liveness_returns_200_without_a_database(self, unavailable_client: TestClient):
        response = unavailable_client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_liveness_reports_the_version(self, client: TestClient):
        from medsafe import __version__

        assert client.get("/health").json()["version"] == __version__

    def test_readiness_is_ready_on_a_loaded_graph(self, client: TestClient):
        body = client.get("/health/ready").json()
        assert body["ready"] is True
        assert body["counts"]["nodes"]["Molecule"] == 15

    def test_readiness_reports_unready_on_an_empty_graph(self, empty_client: TestClient):
        response = empty_client.get("/health/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["ready"] is False
        assert body["checks"]["graph_reachable"] is True
        assert body["checks"]["molecules_loaded"] is False
        assert any("no Molecule nodes" in note for note in body["notes"])

    def test_readiness_reports_unready_on_an_unreachable_graph(
        self, unavailable_client: TestClient
    ):
        response = unavailable_client.get("/health/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["ready"] is False
        assert body["graph_reachable"] is False

    def test_readiness_surfaces_the_safety_control_state(self, client: TestClient):
        body = client.get("/health/ready").json()
        assert body["blocklist_loaded"] is True
        assert body["blocklist_pairs"] > 0
        assert body["coverage_manifest_loaded"] is True

    def test_readiness_flags_a_missing_blocklist(self, repository, tmp_path):
        with build_client(
            repository, fuzzy_negative_blocklist=tmp_path / "absent.csv"
        ) as degraded:
            body = degraded.get("/health/ready").json()
            assert body["blocklist_loaded"] is False
            assert any("UNGUARDED" in note for note in body["notes"])


class TestResolveExact:
    def test_resolved_response_states_the_path_and_molecule(self, client: TestClient):
        body = client.get("/resolve", params={"drug": "Amoxicillin 500mg Capsule"}).json()
        assert body["status"] == "resolved"
        assert body["match"]["path"] == "exact"
        assert body["match"]["molecule"]["molecule_id"] == "MOL001"
        assert body["match"]["molecule"]["inn_name"] == "amoxicillin"

    def test_match_is_flagged_auto_accepted(self, client: TestClient):
        body = client.get("/resolve", params={"drug": "amoxicillin"}).json()
        assert body["match"]["auto_accepted"] is True

    def test_normalization_output_is_returned_in_full(self, client: TestClient):
        body = client.get("/resolve", params={"drug": "Amoxicillin Trihydrate 500mg Cap"}).json()
        normalized = body["normalized"]
        assert normalized["normalized"] == "amoxicillin"
        assert normalized["salts"] == ["trihydrate"]
        assert normalized["form"] == "capsule"
        assert normalized["strength_value"] == 500.0
        assert normalized["strength_unit"] == "mg"

    def test_post_form_behaves_the_same(self, client: TestClient):
        body = client.post("/resolve", json={"drug": "amoxicillin"}).json()
        assert body["match"]["path"] == "exact"

    def test_a_resolved_response_carries_no_candidates(self, client: TestClient):
        body = client.get("/resolve", params={"drug": "amoxicillin"}).json()
        assert body["candidates"] == []


class TestResolveAlias:
    def test_alias_input_resolves_with_path_alias(self, client: TestClient):
        body = client.get("/resolve", params={"drug": "Albuterol"}).json()
        assert body["status"] == "resolved"
        assert body["match"]["path"] == "alias"
        assert body["match"]["molecule"]["inn_name"] == "salbutamol"

    def test_alias_provenance_is_reported(self, client: TestClient):
        body = client.get("/resolve", params={"drug": "Albuterol"}).json()
        assert body["match"]["alias_raw_string"] == "Albuterol"
        assert body["match"]["alias_source"] == "rxnorm_dump"

    def test_brand_name_with_catalogue_noise_resolves(self, client: TestClient):
        body = client.get("/resolve", params={"drug": "Ecosprin 75 Tablet"}).json()
        assert body["match"]["path"] == "alias"
        assert body["match"]["molecule"]["molecule_id"] == "MOL005"


class TestResolveFuzzyCandidates:
    def test_near_miss_returns_unresolved_with_candidates(self, client: TestClient):
        body = client.get("/resolve", params={"drug": "amoxicilin"}).json()
        assert body["status"] == "needs_review"
        assert body["match"] is None
        assert len(body["candidates"]) >= 1

    def test_a_candidate_cannot_be_read_as_an_accepted_match(self, client: TestClient):
        body = client.get("/resolve", params={"drug": "amoxicilin"}).json()
        # The only field that could be read as "this is the answer" is `match`, and it is null.
        assert body["match"] is None
        for candidate in body["candidates"]:
            assert candidate["requires_human_review"] is True
            assert candidate["auto_accepted"] is False
            assert "score" in candidate

    def test_no_substitutes_are_priced_for_an_unaccepted_candidate(self, client: TestClient):
        # Pricing a candidate would lend it the appearance of an accepted match.
        body = client.get("/resolve", params={"drug": "amoxicilin"}).json()
        assert body["substitution"] is None

    def test_the_response_says_review_is_required(self, client: TestClient):
        body = client.get("/resolve", params={"drug": "amoxicilin"}).json()
        assert any("human review" in note for note in body["notes"])

    def test_the_schema_cannot_express_a_fuzzy_match_path(self, client: TestClient):
        schema = client.get("/openapi.json").json()["components"]["schemas"]["MatchOut"]
        assert schema["properties"]["path"]["enum"] == ["exact", "alias"]

    def test_unknown_input_is_unresolved_with_no_candidates(self, client: TestClient):
        body = client.get("/resolve", params={"drug": "zzzznotadrug"}).json()
        assert body["status"] == "unresolved"
        assert body["candidates"] == []
        assert body["match"] is None


class TestResolveBlocklisted:
    """A confusable input never returns its blocklisted partner.

    Runs against a client tuned to a permissive fuzzy threshold, where the partner *does* score into
    the candidate set — at the production threshold it would not, and the test would pass without
    exercising the guard at all.
    """

    def test_the_partner_is_absent_from_candidates(self, permissive_client: TestClient):
        body = permissive_client.get("/resolve", params={"drug": "hydralazine"}).json()
        names = {c["molecule"]["inn_name"] for c in body["candidates"]}
        assert "hydroxyzine" not in names
        assert body["match"] is None

    def test_the_suppression_is_disclosed(self, permissive_client: TestClient):
        body = permissive_client.get("/resolve", params={"drug": "hydralazine"}).json()
        suppressed = {s["inn_name"] for s in body["suppressed"]}
        assert "hydroxyzine" in suppressed
        assert body["suppressed"][0]["reason"]

    def test_both_members_of_a_pair_are_withheld(self, permissive_client: TestClient):
        body = permissive_client.get("/resolve", params={"drug": "prednisolon"}).json()
        names = {c["molecule"]["inn_name"] for c in body["candidates"]}
        assert not ({"prednisolone", "prednisone"} & names)

    def test_an_exact_match_still_resolves(self, permissive_client: TestClient):
        body = permissive_client.get("/resolve", params={"drug": "prednisone"}).json()
        assert body["status"] == "resolved"
        assert body["match"]["molecule"]["molecule_id"] == "MOL011"


class TestResolveSubstitutes:
    def test_resolved_molecule_returns_substitutes_with_savings(self, client: TestClient):
        body = client.get("/resolve", params={"drug": "Amoxicillin 500mg Capsule"}).json()
        substitutes = body["substitution"]["substitutes"]
        assert substitutes
        for substitute in substitutes:
            assert "savings_abs" in substitute
            assert "savings_pct" in substitute
            assert substitute["savings_abs"] > 0

    def test_savings_are_arithmetically_consistent_with_the_stated_baseline(
        self, client: TestClient
    ):
        body = client.get("/resolve", params={"drug": "Amoxicillin 500mg Capsule"}).json()
        substitution = body["substitution"]
        reference_mrp = substitution["reference"]["mrp"]
        for substitute in substitution["substitutes"]:
            expected_abs = round(reference_mrp - substitute["product"]["mrp"], 2)
            assert substitute["savings_abs"] == expected_abs
            assert substitute["savings_pct"] == pytest.approx(
                round(expected_abs / reference_mrp * 100, 2)
            )

    def test_the_baseline_is_stated_not_implied(self, client: TestClient):
        body = client.get("/resolve", params={"drug": "Amoxicillin 500mg Capsule"}).json()
        assert body["substitution"]["reference"]["product_id"] == "PRD003"
        assert any("most expensive" in note for note in body["substitution"]["notes"])

    def test_substitutes_are_ranked_by_saving(self, client: TestClient):
        body = client.get("/resolve", params={"drug": "Amoxicillin 500mg Capsule"}).json()
        savings = [s["savings_abs"] for s in body["substitution"]["substitutes"]]
        assert savings == sorted(savings, reverse=True)

    def test_a_different_strength_is_excluded_with_a_reason(self, client: TestClient):
        body = client.get("/resolve", params={"drug": "Amoxicillin 500mg Capsule"}).json()
        excluded = {e["product_id"]: e["reason"] for e in body["substitution"]["excluded"]}
        assert "PRD004" in excluded  # the 250mg pack
        assert "strength differs" in excluded["PRD004"]

    def test_strength_units_are_compared_after_conversion(self, client: TestClient):
        # PRD012 is 0.5g and PRD010/PRD011 are 500mg: the same strength, different units.
        body = client.get("/resolve", params={"drug": "Metformin 500mg Tablet"}).json()
        ids = {s["product"]["product_id"] for s in body["substitution"]["substitutes"]}
        assert {"PRD010", "PRD011"} <= ids

    def test_substitutes_can_be_switched_off(self, client: TestClient):
        body = client.get(
            "/resolve", params={"drug": "amoxicillin", "include_substitutes": False}
        ).json()
        assert body["substitution"] is None


class TestSubstituteSingleMoleculeOnly:
    def test_an_fdc_product_reports_out_of_scope(self, repository):
        from medsafe.pricing.substitution import (
            SubstitutionStatus,
            find_substitutes_for_product,
        )

        result = find_substitutes_for_product(repository, "PRD040")
        assert result.status is SubstitutionStatus.OUT_OF_SCOPE_FDC
        assert result.substitutes == ()

    def test_the_reason_is_stated_not_silent(self, repository):
        from medsafe.pricing.substitution import find_substitutes_for_product

        result = find_substitutes_for_product(repository, "PRD040")
        assert any("combination" in note for note in result.notes)

    def test_an_fdc_never_appears_as_a_substitute_for_a_single_molecule_product(
        self, client: TestClient
    ):
        # PRD040 contains amoxicillin, but substituting a combination for a single agent would
        # silently add clavulanic acid to the patient's regimen.
        body = client.get("/resolve", params={"drug": "Amoxicillin 500mg Capsule"}).json()
        ids = {s["product"]["product_id"] for s in body["substitution"]["substitutes"]}
        assert "PRD040" not in ids

    def test_a_molecule_only_available_as_an_fdc_is_out_of_scope(self, repository):
        from medsafe.pricing.substitution import (
            SubstitutionStatus,
            find_substitutes_for_molecule,
        )

        # MOL014 (clavulanic acid) exists only inside the combination product.
        result = find_substitutes_for_molecule(repository, "MOL014")
        assert result.status is SubstitutionStatus.OUT_OF_SCOPE_FDC


class TestCheckInteractionFound:
    def test_pair_carries_severity_mechanism_and_provenance(self, client: TestClient):
        body = client.post("/check", json={"drugs": ["Warfarin", "Aspirin"]}).json()
        pair = body["pairs"][0]
        assert pair["status"] == "interaction"
        assert pair["severity"] == "major"
        assert pair["mechanism"]
        assert pair["provenance"] == "ddinter"

    def test_direction_does_not_change_the_result(self, client: TestClient):
        forward = client.post("/check", json={"drugs": ["Warfarin", "Aspirin"]}).json()
        backward = client.post("/check", json={"drugs": ["Aspirin", "Warfarin"]}).json()
        assert forward["summary"] == backward["summary"]
        assert forward["pairs"][0]["severity"] == backward["pairs"][0]["severity"]

    def test_aliases_resolve_before_the_pairwise_check(self, client: TestClient):
        body = client.post("/check", json={"drugs": ["Warfarin", "Ecosprin"]}).json()
        assert body["pairs"][0]["status"] == "interaction"

    def test_every_unordered_pair_appears_exactly_once(self, client: TestClient):
        body = client.post(
            "/check", json={"drugs": ["Warfarin", "Aspirin", "Clopidogrel"]}
        ).json()
        assert body["summary"]["pairs_total"] == 3
        assert body["summary"]["interactions_found"] == 3

    def test_a_checked_clean_pair_is_reported_as_such(self, client: TestClient):
        body = client.post("/check", json={"drugs": ["Warfarin", "Metformin"]}).json()
        pair = body["pairs"][0]
        assert pair["status"] == "no_known_interaction"
        assert body["coverage_complete"] is True


class TestCheckCoverageGap:
    def test_an_uncovered_molecule_returns_not_checked(self, client: TestClient):
        body = client.post("/check", json={"drugs": ["Warfarin", "Atorvastatin"]}).json()
        pair = body["pairs"][0]
        assert pair["status"] == "not_checked"
        assert pair["right_atc_group"] == "C"

    def test_not_checked_is_never_reported_as_no_known_interaction(self, client: TestClient):
        body = client.post(
            "/check", json={"drugs": ["Atorvastatin", "Amlodipine", "Metformin"]}
        ).json()
        statuses = {p["status"] for p in body["pairs"]}
        assert "no_known_interaction" not in statuses
        assert body["summary"]["checked_no_interaction"] == 0

    def test_the_reason_names_the_uncovered_group(self, client: TestClient):
        body = client.post("/check", json={"drugs": ["Warfarin", "Atorvastatin"]}).json()
        assert "ATC group C" in body["pairs"][0]["reason"]

    def test_coverage_complete_is_false_when_any_pair_is_unchecked(self, client: TestClient):
        body = client.post("/check", json={"drugs": ["Warfarin", "Atorvastatin"]}).json()
        assert body["coverage_complete"] is False
        assert body["summary"]["not_checked"] == 1

    def test_the_covered_groups_are_disclosed(self, client: TestClient):
        body = client.post("/check", json={"drugs": ["Warfarin", "Aspirin"]}).json()
        assert set(body["covered_atc_groups"]) == {"A", "B", "D", "H", "L", "P", "R", "V"}

    def test_the_response_warns_that_absence_is_not_safety(self, client: TestClient):
        body = client.post("/check", json={"drugs": ["Warfarin", "Atorvastatin"]}).json()
        assert any("not evidence of safety" in note for note in body["notes"])

    def test_there_is_no_boolean_that_could_be_read_as_safe(self, client: TestClient):
        schema = client.get("/openapi.json").json()["components"]["schemas"]["CheckResponse"]
        booleans = {
            name
            for name, prop in schema["properties"].items()
            if prop.get("type") == "boolean"
        }
        # coverage_complete is the only boolean, and it describes coverage, not safety.
        assert booleans == {"coverage_complete"}

    def test_a_missing_manifest_makes_everything_unchecked(self, repository, tmp_path):
        with build_client(repository, coverage_manifest=tmp_path / "absent.json") as degraded:
            body = degraded.post("/check", json={"drugs": ["Warfarin", "Metformin"]}).json()
            assert body["pairs"][0]["status"] == "not_checked"
            assert body["coverage_complete"] is False


class TestCheckUnresolvedInput:
    def test_an_unresolved_drug_stays_in_the_pairwise_set(self, client: TestClient):
        body = client.post("/check", json={"drugs": ["Warfarin", "zzzznotadrug"]}).json()
        assert body["summary"]["pairs_total"] == 1
        assert body["pairs"][0]["status"] == "not_checked"

    def test_the_unresolved_input_is_echoed(self, client: TestClient):
        body = client.post("/check", json={"drugs": ["Warfarin", "zzzznotadrug"]}).json()
        unresolved = [i for i in body["inputs"] if not i["resolved"]]
        assert len(unresolved) == 1
        assert unresolved[0]["query"] == "zzzznotadrug"
        assert unresolved[0]["molecule_id"] is None

    def test_the_reason_names_the_unresolved_string(self, client: TestClient):
        body = client.post("/check", json={"drugs": ["Warfarin", "zzzznotadrug"]}).json()
        assert "zzzznotadrug" in body["pairs"][0]["reason"]

    def test_a_needs_review_input_is_not_treated_as_resolved(self, client: TestClient):
        body = client.post("/check", json={"drugs": ["Warfarin", "amoxicilin"]}).json()
        assert body["pairs"][0]["status"] == "not_checked"
        review = [r for r in body["resolutions"] if r["status"] == "needs_review"]
        assert review and review[0]["candidates"]

    def test_a_mixed_prescription_reports_every_pair(self, client: TestClient):
        body = client.post(
            "/check",
            json={"drugs": ["Warfarin", "Ecosprin", "Atorvastatin", "Metformin", "zzzznotadrug"]},
        ).json()
        assert body["summary"] == {
            "pairs_total": 10,
            "interactions_found": 1,
            "checked_no_interaction": 2,
            "not_checked": 7,
        }


class TestErrorHandling:
    def test_graph_unavailable_returns_a_structured_503(self, unavailable_client: TestClient):
        response = unavailable_client.get("/resolve", params={"drug": "amoxicillin"})
        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "graph_unavailable"
        assert error["message"]

    def test_check_also_returns_a_structured_error(self, unavailable_client: TestClient):
        response = unavailable_client.post("/check", json={"drugs": ["a", "b"]})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "graph_unavailable"

    def test_validation_failures_are_structured(self, client: TestClient):
        response = client.post("/check", json={"drugs": []})
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "validation_error"
        assert error["detail"]

    def test_a_missing_query_parameter_is_structured(self, client: TestClient):
        response = client.get("/resolve")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    def test_an_unexpected_error_is_not_a_bare_500(self, repository):
        class ExplodingRepository(type(repository)):
            def find_molecule_by_exact_name(self, normalized_string: str):
                raise RuntimeError("boom")

        from conftest import make_settings
        from medsafe.api.main import create_app

        exploding = ExplodingRepository()
        app = create_app(make_settings(), exploding)
        with TestClient(app, raise_server_exceptions=False) as unstable:
            response = unstable.get("/resolve", params={"drug": "amoxicillin"})
            assert response.status_code == 500
            error = response.json()["error"]
            assert error["code"] == "internal_error"
            assert "boom" not in response.text, "internal detail must not leak to the client"

    def test_engine_failure_at_startup_does_not_break_liveness(self):
        app_client = build_client(UnavailableRepository())
        with app_client as unstable:
            assert unstable.get("/health").status_code == 200
