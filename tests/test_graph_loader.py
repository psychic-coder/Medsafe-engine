"""Tests for ``medsafe.graph.loader`` and ``medsafe.graph.schema``.

These run against :class:`medsafe.graph.repository.InMemoryRepository`, which enforces the same
constraints as Neo4j (uniqueness by constrained key, locked enums, canonical interaction ordering)
through the same ``graph.schema`` validators the Neo4j path uses. The DDL text itself is asserted
separately, since only a live database can execute it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from medsafe.errors import SchemaViolationError
from medsafe.graph.loader import ArtifactSet, load_artifacts, load_records, read_artifact
from medsafe.graph.repository import InMemoryRepository
from medsafe.graph.schema import (
    CONSTRAINTS,
    INDEXES,
    SCHEMA_STATEMENTS,
    AliasSource,
    MoleculeCategory,
    ProductSource,
    canonical_pair,
    validate_interaction,
    validate_molecule,
    validate_product,
)


class TestConstraintsApplied:
    def test_schema_declares_the_three_uniqueness_constraints(self):
        ddl = " ".join(CONSTRAINTS)
        assert "m.molecule_id IS UNIQUE" in ddl
        assert "p.product_id IS UNIQUE" in ddl
        assert "a.normalized_string IS UNIQUE" in ddl

    def test_every_statement_is_rerunnable(self):
        # Re-running the loader must not fail on an already-applied schema.
        assert all("IF NOT EXISTS" in statement for statement in SCHEMA_STATEMENTS)

    def test_indexes_support_the_lookup_paths(self):
        ddl = " ".join(INDEXES)
        assert "m.inn_name" in ddl, "exact lookup path"
        assert "a.raw_string" in ddl, "alias audit path"

    def test_apply_schema_is_recorded(self, empty_repository: InMemoryRepository):
        applied = empty_repository.apply_schema()
        assert len(applied) == len(SCHEMA_STATEMENTS)

    def test_molecule_id_uniqueness_is_enforced(self, empty_repository: InMemoryRepository):
        rows = [{"molecule_id": "M1", "inn_name": "warfarin", "category": "small_molecule"}]
        empty_repository.merge_molecules(rows)
        empty_repository.merge_molecules(rows)
        assert empty_repository.counts()["nodes"]["Molecule"] == 1

    def test_alias_normalized_string_uniqueness_is_enforced(
        self, empty_repository: InMemoryRepository
    ):
        empty_repository.merge_molecules(
            [{"molecule_id": "M1", "inn_name": "warfarin", "category": "small_molecule"}]
        )
        alias = {
            "raw_string": "Coumadin",
            "normalized_string": "coumadin",
            "source": "manual",
            "molecule_id": "M1",
        }
        empty_repository.merge_aliases([alias, {**alias, "raw_string": "COUMADIN"}])
        assert empty_repository.counts()["nodes"]["Alias"] == 1


class TestMoleculeLoad:
    def test_nodes_are_created_with_a_valid_category(self, loaded_repository: InMemoryRepository):
        molecule = loaded_repository.get_molecule("M1")
        assert molecule["inn_name"] == "warfarin"
        assert molecule["category"] == MoleculeCategory.SMALL_MOLECULE

    def test_invalid_category_is_rejected(self):
        with pytest.raises(SchemaViolationError) as exc:
            validate_molecule(
                {"molecule_id": "M9", "inn_name": "foo", "category": "not_a_category"}
            )
        assert exc.value.detail["allowed"] == sorted(m.value for m in MoleculeCategory)

    def test_missing_required_property_is_rejected(self):
        with pytest.raises(SchemaViolationError):
            validate_molecule({"molecule_id": "M9", "category": "small_molecule"})

    def test_inn_name_is_stored_in_normalized_key_space(self):
        # The loader re-normalizes on write so the graph cannot drift from the current rules.
        repo = InMemoryRepository()
        load_records(
            repo,
            ArtifactSet(
                molecules=[
                    {
                        "molecule_id": "M1",
                        "inn_name": "Amoxicillin Trihydrate",
                        "category": "small_molecule",
                    }
                ]
            ),
        )
        assert repo.get_molecule("M1")["inn_name"] == "amoxicillin"
        assert repo.find_molecule_by_exact_name("amoxicillin") is not None


class TestProductLoad:
    def test_source_enum_is_enforced(self):
        for source in (ProductSource.PMBJP, ProductSource.BRANDED_CSV):
            validate_product(
                {
                    "product_id": "P1",
                    "source": source.value,
                    "generic_name_raw": "x",
                    "mrp": 1.0,
                }
            )
        with pytest.raises(SchemaViolationError):
            validate_product(
                {"product_id": "P1", "source": "amazon", "generic_name_raw": "x", "mrp": 1.0}
            )

    def test_mrp_and_strength_raw_are_preserved(self, loaded_repository: InMemoryRepository):
        product = loaded_repository.get_product("P1")
        assert product["mrp"] == 10.0
        assert product["strength_raw"] == "5mg"
        assert product["form"] == "tablet"

    def test_mrp_must_be_numeric_and_non_negative(self):
        with pytest.raises(SchemaViolationError):
            validate_product(
                {"product_id": "P1", "source": "PMBJP", "generic_name_raw": "x", "mrp": "free"}
            )
        with pytest.raises(SchemaViolationError):
            validate_product(
                {"product_id": "P1", "source": "PMBJP", "generic_name_raw": "x", "mrp": -1}
            )

    def test_missing_mrp_is_rejected(self):
        with pytest.raises(SchemaViolationError):
            validate_product({"product_id": "P1", "source": "PMBJP", "generic_name_raw": "x"})


class TestContainsEdge:
    def test_edge_carries_strength_and_unit(self, loaded_repository: InMemoryRepository):
        edges = loaded_repository.molecules_for_product("P1")
        assert len(edges) == 1
        assert edges[0]["strength"] == "5"
        assert edges[0]["unit"] == "mg"

    def test_edge_to_a_missing_endpoint_is_not_created(self, empty_repository):
        empty_repository.merge_contains(
            [{"product_id": "nope", "molecule_id": "also_nope", "strength": "1", "unit": "mg"}]
        )
        assert empty_repository.counts()["relationships"]["CONTAINS"] == 0

    def test_molecule_count_reflects_the_number_of_edges(self, repository: InMemoryRepository):
        assert repository.get_product("PRD001")["molecule_count"] == 1
        assert repository.get_product("PRD040")["molecule_count"] == 2


class TestAliasLoad:
    def test_alias_node_and_edge_are_created(self, loaded_repository: InMemoryRepository):
        resolved = loaded_repository.find_molecule_by_alias("coumadin")
        assert resolved["molecule_id"] == "M1"
        assert resolved["alias_raw_string"] == "Coumadin"

    def test_source_enum_is_enforced(self, empty_repository: InMemoryRepository):
        empty_repository.merge_molecules(
            [{"molecule_id": "M1", "inn_name": "warfarin", "category": "small_molecule"}]
        )
        for source in AliasSource:
            empty_repository.merge_aliases(
                [
                    {
                        "raw_string": f"x-{source.value}",
                        "normalized_string": f"x {source.value}",
                        "source": source.value,
                        "molecule_id": "M1",
                    }
                ]
            )
        with pytest.raises(SchemaViolationError):
            empty_repository.merge_aliases(
                [
                    {
                        "raw_string": "y",
                        "normalized_string": "y",
                        "source": "wikipedia",
                        "molecule_id": "M1",
                    }
                ]
            )

    def test_alias_key_is_normalized_on_write(self):
        repo = InMemoryRepository()
        load_records(
            repo,
            ArtifactSet(
                molecules=[
                    {"molecule_id": "M1", "inn_name": "warfarin", "category": "small_molecule"}
                ],
                aliases=[
                    {
                        "raw_string": "Coumadin 5mg Tablet",
                        "normalized_string": "Coumadin 5mg Tablet",
                        "source": "manual",
                        "molecule_id": "M1",
                    }
                ],
            ),
        )
        assert repo.find_molecule_by_alias("coumadin") is not None


class TestInteractionCanonicalOrdering:
    def test_pair_is_stored_with_the_lower_id_first(self):
        assert canonical_pair("M2", "M1") == ("M1", "M2")
        assert canonical_pair("M1", "M2") == ("M1", "M2")

    def test_reverse_input_is_normalized_on_write(self):
        row = validate_interaction(
            {"molecule_id_a": "M2", "molecule_id_b": "M1", "severity": "major"}
        )
        assert (row["molecule_id_a"], row["molecule_id_b"]) == ("M1", "M2")

    def test_self_pair_is_rejected(self):
        with pytest.raises(SchemaViolationError):
            canonical_pair("M1", "M1")

    def test_lookup_is_direction_independent(self, loaded_repository: InMemoryRepository):
        forward = loaded_repository.interactions_between(["M1", "M2"])
        backward = loaded_repository.interactions_between(["M2", "M1"])
        assert forward == backward
        assert len(forward) == 1
        assert forward[0]["severity"] == "major"
        assert forward[0]["provenance"] == "ddinter"


class TestNoDuplicateReverseEdge:
    def test_loading_both_directions_yields_one_edge(self, empty_repository: InMemoryRepository):
        empty_repository.merge_molecules(
            [
                {"molecule_id": "M1", "inn_name": "warfarin", "category": "small_molecule"},
                {"molecule_id": "M2", "inn_name": "aspirin", "category": "small_molecule"},
            ]
        )
        empty_repository.merge_interactions(
            [
                {"molecule_id_a": "M1", "molecule_id_b": "M2", "severity": "major"},
                {"molecule_id_a": "M2", "molecule_id_b": "M1", "severity": "major"},
            ]
        )
        assert empty_repository.counts()["relationships"]["INTERACTS_WITH"] == 1
        assert len(empty_repository.interactions_between(["M1", "M2"])) == 1

    def test_the_write_cypher_relies_on_pre_ordered_rows(self):
        from medsafe.graph.queries import MERGE_INTERACTION

        # The MERGE is directed; correctness depends on rows arriving canonically ordered, which
        # validate_interaction guarantees.
        assert "MERGE (a)-[r:INTERACTS_WITH]->(b)" in MERGE_INTERACTION


class TestIdempotentReload:
    def test_reloading_does_not_duplicate_nodes_or_edges(self, demo_dir: Path):
        repo = InMemoryRepository()
        first = load_artifacts(repo, demo_dir)
        second = load_artifacts(repo, demo_dir)
        assert first.counts_after == second.counts_after

    def test_a_third_run_is_still_stable(self, demo_dir: Path):
        repo = InMemoryRepository()
        load_artifacts(repo, demo_dir)
        load_artifacts(repo, demo_dir)
        counts = load_artifacts(repo, demo_dir).counts_after
        assert counts["nodes"]["Molecule"] == 15
        assert counts["nodes"]["Product"] == 13
        assert counts["relationships"]["INTERACTS_WITH"] == 5

    def test_reload_after_a_price_change_updates_rather_than_duplicates(
        self, repository: InMemoryRepository
    ):
        repository.merge_products(
            [
                {
                    "product_id": "PRD001",
                    "source": "PMBJP",
                    "generic_name_raw": "Amoxicillin 500mg Capsule",
                    "form": "capsule",
                    "strength_raw": "500mg",
                    "mrp": 35.0,
                }
            ]
        )
        assert repository.counts()["nodes"]["Product"] == 13
        assert repository.get_product("PRD001")["mrp"] == 35.0


class TestPartialLoadReporting:
    def test_counts_are_reported_per_label(self, demo_dir: Path):
        repo = InMemoryRepository()
        report = load_artifacts(repo, demo_dir)
        assert report.counts_after["nodes"]["Molecule"] == 15
        assert report.counts_after["relationships"]["CONTAINS"] == 14
        assert report.written["interactions"] == 5

    def test_a_missing_artifact_is_reported_not_fatal(self, tmp_path: Path):
        (tmp_path / "molecules.csv").write_text(
            "molecule_id,inn_name,category\nM1,warfarin,small_molecule\n", encoding="utf-8"
        )
        repo = InMemoryRepository()
        report = load_artifacts(repo, tmp_path)
        assert report.written["molecules"] == 1
        assert set(report.skipped) == {
            "products",
            "contains",
            "aliases",
            "brand_aliases",
            "interactions",
        }
        assert not report.complete

    def test_an_incomplete_load_is_visible_in_the_summary(self, tmp_path: Path):
        repo = InMemoryRepository()
        report = load_artifacts(repo, tmp_path)
        assert "INCOMPLETE LOAD" in "\n".join(report.summary_lines())

    def test_a_bad_row_is_rejected_and_reported_without_aborting(self, tmp_path: Path):
        (tmp_path / "molecules.csv").write_text(
            "molecule_id,inn_name,category\n"
            "M1,warfarin,small_molecule\n"
            "M2,aspirin,not_a_category\n"
            "M3,metformin,small_molecule\n",
            encoding="utf-8",
        )
        repo = InMemoryRepository()
        report = load_artifacts(repo, tmp_path, strict=False)
        assert report.written["molecules"] == 2
        assert len(report.rejected) == 1
        assert report.rejected[0]["stage"] == "molecules"
        assert not report.complete

    def test_strict_mode_raises_instead_of_rejecting(self, tmp_path: Path):
        (tmp_path / "molecules.csv").write_text(
            "molecule_id,inn_name,category\nM1,warfarin,not_a_category\n", encoding="utf-8"
        )
        with pytest.raises(SchemaViolationError):
            load_artifacts(InMemoryRepository(), tmp_path, strict=True)

    def test_json_artifacts_are_accepted(self, tmp_path: Path):
        (tmp_path / "molecules.json").write_text(
            json.dumps(
                [{"molecule_id": "M1", "inn_name": "warfarin", "category": "small_molecule"}]
            ),
            encoding="utf-8",
        )
        assert read_artifact(tmp_path, "molecules") == [
            {"molecule_id": "M1", "inn_name": "warfarin", "category": "small_molecule"}
        ]

    def test_read_artifact_returns_none_when_absent(self, tmp_path: Path):
        assert read_artifact(tmp_path, "molecules") is None
