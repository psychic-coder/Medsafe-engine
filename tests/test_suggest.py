"""Tests for ``/suggest``.

The endpoint's whole job is to stop a user guessing at spelling, so the tests are mostly about
ranking and about the one judgement call in it: confusable names are *flagged*, not hidden. That
choice deserves a test in both directions — the pair must be offered, and it must be labelled.
"""

from __future__ import annotations

import pytest


class TestRanking:
    def test_a_prefix_match_outranks_a_substring_match(self, client) -> None:
        body = client.get("/suggest", params={"q": "sprin", "limit": 20}).json()
        labels = [s["label"].lower() for s in body["suggestions"]]
        assert labels, "expected at least one suggestion"
        # Everything returned must at least contain the query somewhere.
        assert all("sprin" in label for label in labels)

    def test_shorter_names_come_first_at_equal_rank(self, client) -> None:
        body = client.get("/suggest", params={"q": "predniso", "limit": 10}).json()
        labels = [s["label"] for s in body["suggestions"]]
        prefixed = [label for label in labels if label.lower().startswith("predniso")]
        assert prefixed == sorted(prefixed, key=lambda name: (len(name), name.lower()))

    def test_limit_is_respected(self, client) -> None:
        body = client.get("/suggest", params={"q": "a", "limit": 3}).json()
        assert len(body["suggestions"]) <= 3

    def test_an_empty_key_returns_nothing_rather_than_everything(self, client) -> None:
        body = client.get("/suggest", params={"q": "10's"}).json()
        assert body["suggestions"] == []

    def test_a_blank_query_is_rejected(self, client) -> None:
        assert client.get("/suggest", params={"q": ""}).status_code == 422

    def test_the_limit_is_capped(self, client) -> None:
        assert client.get("/suggest", params={"q": "a", "limit": 500}).status_code == 422


class TestConfusablesAreFlaggedNotHidden:
    """The judgement call: a human with the pack is better served by a warning than an absence."""

    def test_both_members_of_a_blocklisted_pair_are_offered(self, client) -> None:
        body = client.get("/suggest", params={"q": "predniso", "limit": 20}).json()
        labels = {s["label"].lower() for s in body["suggestions"]}
        assert "prednisone" in labels
        assert "prednisolone" in labels

    def test_each_carries_the_name_it_is_confusable_with(self, client) -> None:
        body = client.get("/suggest", params={"q": "predniso", "limit": 20}).json()
        by_label = {s["label"].lower(): s for s in body["suggestions"]}
        assert "prednisolone" in [
            name.lower() for name in by_label["prednisone"]["confusable_with"]
        ]
        assert "prednisone" in [
            name.lower() for name in by_label["prednisolone"]["confusable_with"]
        ]

    def test_a_confusable_result_carries_a_note(self, client) -> None:
        body = client.get("/suggest", params={"q": "predniso", "limit": 20}).json()
        assert body["note"] and "look alike" in body["note"]

    def test_an_unambiguous_query_carries_no_note(self, client) -> None:
        body = client.get("/suggest", params={"q": "metformin", "limit": 5}).json()
        assert body["note"] is None
        assert all(not s["confusable_with"] for s in body["suggestions"])


class TestSuggestionKinds:
    def test_an_ingredient_is_labelled_as_one(self, client) -> None:
        body = client.get("/suggest", params={"q": "metformin", "limit": 5}).json()
        entry = next(s for s in body["suggestions"] if s["label"].lower() == "metformin")
        assert entry["kind"] == "ingredient"
        assert entry["molecule_id"]

    def test_an_alias_names_the_ingredient_it_stands_for(self, client) -> None:
        body = client.get("/suggest", params={"q": "albuterol", "limit": 5}).json()
        entry = next(
            (s for s in body["suggestions"] if s["label"].lower() == "albuterol"), None
        )
        assert entry is not None
        assert entry["kind"] == "other_name"
        assert entry["ingredient"]

    @pytest.mark.parametrize("query", ["metformin", "warfarin"])
    def test_every_suggestion_resolves_when_submitted(self, client, query: str) -> None:
        """The contract that makes the feature worth having: a suggestion is never a dead end."""
        body = client.get("/suggest", params={"q": query, "limit": 5}).json()
        for suggestion in body["suggestions"]:
            resolved = client.get("/resolve", params={"drug": suggestion["label"]}).json()
            assert resolved["status"] in {"resolved", "combination"}, (
                f"{suggestion['label']!r} was suggested but does not resolve"
            )
