"""Tests for the ``scripts/`` entry points.

They run the whole ingest -> bridge -> load pipeline on synthetic raw files, which is the only place
the scripts are exercised together. The real PMBJP and DDInter sources are not redistributable, so
the fixtures here stand in for them; the point is the wiring and the failure modes, not the data.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_script(name: str):
    """Import a script by path — ``scripts/`` is not a package."""
    spec = importlib.util.spec_from_file_location(f"script_{name}", SCRIPTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ingest_pmbjp():
    return load_script("ingest_pmbjp")


@pytest.fixture(scope="module")
def ingest_ddinter():
    return load_script("ingest_ddinter")


@pytest.fixture(scope="module")
def build_bridge_table():
    return load_script("build_bridge_table")


@pytest.fixture(scope="module")
def load_graph():
    return load_script("load_graph")


@pytest.fixture
def raw_pmbjp(tmp_path: Path) -> Path:
    path = tmp_path / "pmbjp.csv"
    path.write_text(
        "Drug Code,Generic Name,Unit Size,MRP\n"
        "P001,Amoxicillin 500mg Capsule,10 Capsules,32.50\n"
        "P002,Metformin Hydrochloride 500mg Tablet,10 Tablets,\u20b98.00\n"
        "P003,Warfarin Sodium 5mg Tablet,10 Tablets,\"1,200.00\"\n"
        "P004,,10 Tablets,15.00\n"
        "P005,Aspirin 75mg Tablet,10 Tablets,not-a-price\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def raw_ddinter(tmp_path: Path) -> Path:
    path = tmp_path / "ddinter.csv"
    path.write_text(
        "Drug_A,Drug_B,Level,Description\n"
        "Warfarin,Aspirin,Major,Additive bleeding risk\n"
        "Aspirin,Warfarin,Major,Additive bleeding risk\n"  # reverse duplicate
        "Metformin,Metformin,Minor,self pair\n"  # self-pair
        "Amoxicillin,Warfarin,Moderate,Enhanced anticoagulant effect\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def raw_atc(tmp_path: Path) -> Path:
    path = tmp_path / "atc.csv"
    path.write_text(
        "drug_name,atc_code\n"
        "Warfarin,B01AA03\n"
        "Aspirin,B01AC06\n"
        "Metformin,A10BA02\n"
        "Amoxicillin,J01CA04\n",
        encoding="utf-8",
    )
    return path


class TestIngestPmbjp:
    def test_column_mapping_is_matched_not_hard_coded(self, ingest_pmbjp):
        mapping, _ = ingest_pmbjp.build_column_map(
            ["Drug Code", "Generic Name", "Unit Size", "MRP"]
        )
        assert mapping["generic_name_raw"] == "Generic Name"
        assert mapping["mrp"] == "MRP"

    def test_a_pack_size_column_is_not_mistaken_for_form_or_strength(self, ingest_pmbjp):
        # "Unit Size" holds "10 Capsules" — a pack count. Reading it as Product.form would break
        # every substitution equivalence check, so it is reported rather than guessed at.
        mapping, unrecognised = ingest_pmbjp.build_column_map(
            ["Drug Code", "Generic Name", "Unit Size", "MRP"]
        )
        assert "form" not in mapping
        assert "strength_raw" not in mapping
        assert unrecognised == ["Unit Size"]

    def test_unrecognised_headers_are_reported_by_name(self, ingest_pmbjp):
        _, unrecognised = ingest_pmbjp.build_column_map(["Generic Name", "MRP", "Mystery Column"])
        assert unrecognised == ["Mystery Column"]

    def test_products_and_aliases_are_written(self, ingest_pmbjp, raw_pmbjp, tmp_path):
        out = tmp_path / "processed"
        report = ingest_pmbjp.ingest(raw_pmbjp, out)
        assert report["products"] == 3
        assert (out / "products.csv").is_file()
        assert (out / "pmbjp_aliases.csv").is_file()

    def test_currency_symbols_and_separators_are_parsed(self, ingest_pmbjp, raw_pmbjp, tmp_path):
        out = tmp_path / "processed"
        ingest_pmbjp.ingest(raw_pmbjp, out)
        rows = (out / "products.csv").read_text(encoding="utf-8")
        assert "8.0" in rows
        assert "1200.0" in rows

    def test_unparsed_rows_are_reported_not_dropped_silently(
        self, ingest_pmbjp, raw_pmbjp, tmp_path
    ):
        out = tmp_path / "processed"
        report = ingest_pmbjp.ingest(raw_pmbjp, out)
        assert report["unparsed"] == 2  # the blank name and the bad price
        assert (out / "pmbjp_unparsed.csv").is_file()

    def test_form_and_strength_are_recovered_from_the_name(self, ingest_pmbjp, raw_pmbjp, tmp_path):
        out = tmp_path / "processed"
        ingest_pmbjp.ingest(raw_pmbjp, out)
        text = (out / "products.csv").read_text(encoding="utf-8")
        assert "capsule" in text
        assert "500mg" in text

    def test_a_missing_input_exits_with_guidance(self, ingest_pmbjp, tmp_path, capsys):
        code = ingest_pmbjp.main(["--input", str(tmp_path / "absent.csv")])
        assert code == 2
        assert "not redistributable" in capsys.readouterr().out


class TestIngestDdinter:
    def test_reverse_duplicates_collapse_to_one_row(self, ingest_ddinter, raw_ddinter, tmp_path):
        report = ingest_ddinter.ingest(raw_ddinter, tmp_path / "processed", None)
        assert report["interactions"] == 2  # warfarin/aspirin once, plus amoxicillin/warfarin

    def test_self_pairs_are_skipped(self, ingest_ddinter, raw_ddinter, tmp_path):
        report = ingest_ddinter.ingest(raw_ddinter, tmp_path / "processed", None)
        assert report["skipped"] == 1

    def test_rows_are_written_in_canonical_order(self, ingest_ddinter, raw_ddinter, tmp_path):
        out = tmp_path / "processed"
        ingest_ddinter.ingest(raw_ddinter, out, None)
        import csv

        with (out / "interactions.csv").open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                assert row["molecule_id_a"] < row["molecule_id_b"]

    def test_the_coverage_manifest_is_always_written(self, ingest_ddinter, raw_ddinter, tmp_path):
        out = tmp_path / "processed"
        ingest_ddinter.ingest(raw_ddinter, out, None)
        manifest = json.loads((out / "ddinter_coverage.json").read_text(encoding="utf-8"))
        assert manifest["molecule_atc_groups"] == {}
        assert set(manifest["uncovered_atc_groups"]) == {"C", "G", "J", "M", "N", "S"}

    def test_the_atc_map_is_reduced_to_first_levels(
        self, ingest_ddinter, raw_ddinter, raw_atc, tmp_path
    ):
        out = tmp_path / "processed"
        ingest_ddinter.ingest(raw_ddinter, out, raw_atc)
        manifest = json.loads((out / "ddinter_coverage.json").read_text(encoding="utf-8"))
        assert manifest["molecule_atc_groups"]["warfarin"] == "B"
        assert manifest["molecule_atc_groups"]["amoxicillin"] == "J"

    def test_an_empty_manifest_makes_everything_unchecked(
        self, ingest_ddinter, raw_ddinter, tmp_path
    ):
        from medsafe.safety.interactions import AtcCoverage

        out = tmp_path / "processed"
        ingest_ddinter.ingest(raw_ddinter, out, None)
        coverage = AtcCoverage.from_manifest(out / "ddinter_coverage.json")
        assert coverage.covers("warfarin") is False

    def test_canonical_row_normalizes_names(self, ingest_ddinter):
        row = ingest_ddinter.canonical_row("Warfarin Sodium 5mg", "Aspirin Tablet", "Major", "x")
        assert row["molecule_id_a"] == "aspirin"
        assert row["molecule_id_b"] == "warfarin"
        assert row["provenance"] == "ddinter"

    def test_a_self_pair_returns_none(self, ingest_ddinter):
        assert ingest_ddinter.canonical_row("Warfarin", "Warfarin Sodium", "Major", "") is None


class TestBuildBridgeTable:
    @pytest.fixture
    def processed(self, ingest_pmbjp, ingest_ddinter, raw_pmbjp, raw_ddinter, raw_atc, tmp_path):
        out = tmp_path / "processed"
        ingest_pmbjp.ingest(raw_pmbjp, out)
        ingest_ddinter.ingest(raw_ddinter, out, raw_atc)
        return out

    def test_molecule_ids_are_deterministic(self, build_bridge_table):
        first = build_bridge_table.assign_molecule_ids(["b", "a", "c"])
        second = build_bridge_table.assign_molecule_ids(["c", "b", "a"])
        assert first == second
        assert first["a"] == "MOL000001"

    def test_the_bridge_joins_the_two_vocabularies(
        self, build_bridge_table, processed, tmp_path
    ):
        report = build_bridge_table.build(processed, tmp_path / "manual", propose=False)
        assert report["molecules"] == 3  # warfarin, aspirin, amoxicillin from DDInter
        assert report["contains"] >= 1

    def test_interaction_rows_are_rekeyed_to_molecule_ids(
        self, build_bridge_table, processed, tmp_path
    ):
        # ingest_ddinter emits name-keyed rows; without this rewrite the loader matches no
        # endpoints and every edge is silently dropped.
        report = build_bridge_table.build(processed, tmp_path / "manual", propose=False)
        assert report["interactions"] == 2
        text = (processed / "interactions.csv").read_text(encoding="utf-8")
        assert "MOL0000" in text
        assert "warfarin" not in text

    def test_the_coverage_manifest_is_rekeyed_to_molecule_ids(
        self, build_bridge_table, processed, tmp_path
    ):
        report = build_bridge_table.build(processed, tmp_path / "manual", propose=False)
        manifest = json.loads((processed / "ddinter_coverage.json").read_text(encoding="utf-8"))
        assert report["coverage_molecules"] == 3
        assert all(key.startswith("MOL") for key in manifest["molecule_atc_groups"])
        assert manifest["molecule_atc_groups_keyed_by"] == "molecule_id"

    def test_unjoined_products_are_reported_not_guessed(
        self, build_bridge_table, processed, tmp_path
    ):
        report = build_bridge_table.build(processed, tmp_path / "manual", propose=False)
        # Metformin appears in PMBJP but has no DDInter interaction row, so it has no molecule.
        assert report["unjoined_products"] >= 1
        text = (processed / "unjoined_names.csv").read_text(encoding="utf-8")
        assert "metformin" in text

    def test_proposals_go_to_a_separate_review_file(
        self, build_bridge_table, processed, tmp_path
    ):
        build_bridge_table.build(processed, tmp_path / "manual", propose=True)
        assert (processed / "review_candidates.csv").is_file()
        aliases = (processed / "aliases.csv").read_text(encoding="utf-8")
        assert "PENDING_HUMAN_REVIEW" not in aliases

    def test_a_proposal_is_marked_pending_not_accepted(self, build_bridge_table, tmp_path):
        unjoined = [
            {
                "product_id": "P1",
                "generic_name_raw": "Amoxicilin 500mg",
                "normalized_string": "amoxicilin",
            }
        ]
        written = build_bridge_table.write_proposals(tmp_path, unjoined, ["amoxicillin"])
        assert written == 1
        text = (tmp_path / "review_candidates.csv").read_text(encoding="utf-8")
        assert "PENDING_HUMAN_REVIEW" in text
        assert "amoxicillin" in text

    def test_blocklisted_pairs_are_excluded_from_proposals(self, build_bridge_table, tmp_path):
        # "hydralazin" is a near-miss for hydroxyzine, which is a confirmed confusable.
        unjoined = [
            {
                "product_id": "P1",
                "generic_name_raw": "Hydralazin 10mg",
                "normalized_string": "hydralazin",
            }
        ]
        written = build_bridge_table.write_proposals(
            tmp_path, unjoined, ["hydroxyzine", "hydralazine"]
        )
        text = (tmp_path / "review_candidates.csv").read_text(encoding="utf-8")
        assert "hydroxyzine" not in text
        assert written >= 0


class TestLoadGraph:
    def test_a_dry_run_validates_without_writing(self, load_graph, demo_dir, capsys):
        code = load_graph.main(["--processed-dir", str(demo_dir), "--dry-run"])
        assert code == 0
        out = capsys.readouterr().out
        assert "dry run" in out
        assert "Molecule" in out

    def test_a_partial_load_exits_non_zero(self, load_graph, tmp_path, capsys):
        (tmp_path / "molecules.csv").write_text(
            "molecule_id,inn_name,category\nM1,warfarin,small_molecule\n", encoding="utf-8"
        )
        code = load_graph.main(["--processed-dir", str(tmp_path), "--dry-run"])
        assert code == 1, "a partial load must not look clean to the caller"
        assert "SKIPPED" in capsys.readouterr().out

    def test_a_missing_directory_is_reported(self, load_graph, tmp_path, capsys):
        code = load_graph.main(["--processed-dir", str(tmp_path / "absent"), "--dry-run"])
        assert code == 2
        assert "does not exist" in capsys.readouterr().out

    def test_json_output_is_machine_readable(self, load_graph, demo_dir, capsys):
        load_graph.main(["--processed-dir", str(demo_dir), "--dry-run", "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["complete"] is True
        assert payload["counts_after"]["nodes"]["Molecule"] == 15


class TestFullPipeline:
    def test_ingest_then_bridge_then_load(
        self,
        ingest_pmbjp,
        ingest_ddinter,
        build_bridge_table,
        raw_pmbjp,
        raw_ddinter,
        raw_atc,
        tmp_path,
    ):
        from medsafe.graph.loader import load_artifacts
        from medsafe.graph.repository import InMemoryRepository
        from medsafe.resolution.blocklist import ConfusablePairBlocklist
        from medsafe.resolution.matcher import Matcher, MatchPath

        processed = tmp_path / "processed"
        ingest_pmbjp.ingest(raw_pmbjp, processed)
        ingest_ddinter.ingest(raw_ddinter, processed, raw_atc)
        build_bridge_table.build(processed, tmp_path / "manual", propose=False)

        repo = InMemoryRepository()
        report = load_artifacts(repo, processed)
        assert report.counts_after["nodes"]["Molecule"] == 3
        assert report.counts_after["relationships"]["INTERACTS_WITH"] == 2

        matcher = Matcher(
            repo, ConfusablePairBlocklist(), candidate_threshold=88, max_candidates=5
        )
        result = matcher.resolve("Warfarin Sodium 5mg Tablet")
        assert result.path is MatchPath.EXACT
        assert result.molecule.inn_name == "warfarin"
