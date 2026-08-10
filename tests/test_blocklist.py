"""Tests for ``medsafe.resolution.blocklist``.

This is a safety control, so the tests are about the guarantees rather than the parsing: the check
is symmetric, it operates in normalized key space (so catalogue noise cannot evade it), and a
missing file is loud rather than a silent no-op.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from medsafe.errors import ConfigurationError
from medsafe.resolution.blocklist import ConfusablePairBlocklist


class TestLoading:
    def test_the_shipped_blocklist_loads(self, blocklist: ConfusablePairBlocklist):
        assert len(blocklist) > 0
        assert blocklist.missing is False

    def test_comment_lines_are_skipped(self, blocklist: ConfusablePairBlocklist):
        names = {entry.name_a for entry in blocklist.entries}
        assert not any(name.startswith("#") for name in names)

    def test_a_missing_file_yields_an_empty_but_flagged_blocklist(self, tmp_path: Path):
        absent = ConfusablePairBlocklist.from_csv(tmp_path / "nope.csv")
        assert len(absent) == 0
        assert absent.missing is True, "a missing safety control must be visible, not silent"

    def test_rows_with_a_blank_name_are_skipped(self, tmp_path: Path):
        path = tmp_path / "bl.csv"
        path.write_text("name_a,name_b\nwarfarin,\n,aspirin\nfoo,bar\n", encoding="utf-8")
        assert len(ConfusablePairBlocklist.from_csv(path)) == 1

    def test_a_pair_that_normalizes_to_one_key_is_rejected_loudly(self, tmp_path: Path):
        path = tmp_path / "bl.csv"
        path.write_text(
            "name_a,name_b\nMetformin Hydrochloride,Metformin HCl\n", encoding="utf-8"
        )
        with pytest.raises(ConfigurationError):
            ConfusablePairBlocklist.from_csv(path)


class TestMembership:
    def test_the_check_is_symmetric(self, blocklist: ConfusablePairBlocklist):
        assert blocklist.contains("hydralazine", "hydroxyzine")
        assert blocklist.contains("hydroxyzine", "hydralazine")

    def test_unrelated_drugs_are_not_blocklisted(self, blocklist: ConfusablePairBlocklist):
        assert not blocklist.contains("warfarin", "amoxicillin")

    def test_the_check_operates_in_normalized_key_space(self, blocklist: ConfusablePairBlocklist):
        # Catalogue noise must not let a confusable slip past the guard.
        assert blocklist.contains("HYDROXYZINE HCl 25mg Tablet", "  Hydralazine 10 MG  ")

    def test_partners_are_listed_in_both_directions(self, blocklist: ConfusablePairBlocklist):
        assert "prednisone" in blocklist.partners_of("prednisolone")
        assert "prednisolone" in blocklist.partners_of("prednisone")

    def test_an_unknown_name_has_no_partners(self, blocklist: ConfusablePairBlocklist):
        assert blocklist.partners_of("zzzznotadrug") == frozenset()

    def test_empty_input_is_not_a_match(self, blocklist: ConfusablePairBlocklist):
        assert not blocklist.contains("", "hydralazine")

    def test_the_in_operator_works(self, blocklist: ConfusablePairBlocklist):
        assert ("hydralazine", "hydroxyzine") in blocklist
        assert ("warfarin", "amoxicillin") not in blocklist

    def test_the_entry_carries_its_reason(self, blocklist: ConfusablePairBlocklist):
        entry = blocklist.entry_for("hydralazine", "hydroxyzine")
        assert entry is not None
        assert entry.reason


class TestFromPairs:
    def test_pairs_can_be_supplied_inline(self):
        inline = ConfusablePairBlocklist.from_pairs([("Foo Sodium", "Bar Tablet")])
        assert inline.contains("foo", "bar")
        assert len(inline) == 1

    def test_an_empty_blocklist_matches_nothing(self):
        assert not ConfusablePairBlocklist().contains("a", "b")
