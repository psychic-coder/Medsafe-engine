"""Shared fixtures.

Every fixture is deterministic and offline. The graph is
:class:`medsafe.graph.repository.InMemoryRepository` seeded from ``data/demo/``, which enforces the
same constraints as Neo4j, so the full pipeline is exercised without a database. Settings are
constructed directly rather than through ``load_settings`` so an ambient ``NEO4J_URI`` or ``.env``
in the developer's shell cannot change a test outcome.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from medsafe.config import Settings
from medsafe.errors import GraphUnavailableError
from medsafe.graph.loader import ArtifactSet, load_artifacts, load_records
from medsafe.graph.repository import InMemoryRepository
from medsafe.resolution.blocklist import ConfusablePairBlocklist
from medsafe.resolution.matcher import Matcher
from medsafe.safety.interactions import AtcCoverage

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = REPO_ROOT / "data" / "demo"
BLOCKLIST_PATH = REPO_ROOT / "data" / "manual" / "fuzzy_negative_blocklist.csv"
COVERAGE_PATH = DEMO_DIR / "ddinter_coverage.json"

# The default candidate threshold is high enough that most confusable partners never score into the
# candidate set at all. Tests that exercise the blocklist deliberately use this permissive value, so
# they prove the guard holds rather than that the threshold happened to hide the problem.
PERMISSIVE_THRESHOLD = 70


@pytest.fixture(scope="session")
def demo_dir() -> Path:
    return DEMO_DIR


@pytest.fixture
def repository() -> InMemoryRepository:
    """A graph seeded from the demo artifacts."""
    repo = InMemoryRepository()
    load_artifacts(repo, DEMO_DIR)
    return repo


@pytest.fixture
def empty_repository() -> InMemoryRepository:
    """A schema-applied but unloaded graph."""
    repo = InMemoryRepository()
    repo.apply_schema()
    return repo


@pytest.fixture(scope="session")
def blocklist() -> ConfusablePairBlocklist:
    return ConfusablePairBlocklist.from_csv(BLOCKLIST_PATH)


@pytest.fixture(scope="session")
def coverage() -> AtcCoverage:
    return AtcCoverage.from_manifest(COVERAGE_PATH)


@pytest.fixture
def matcher(repository: InMemoryRepository, blocklist: ConfusablePairBlocklist) -> Matcher:
    """Matcher at the production candidate threshold."""
    return Matcher(repository, blocklist, candidate_threshold=88, max_candidates=5)


@pytest.fixture
def permissive_matcher(
    repository: InMemoryRepository, blocklist: ConfusablePairBlocklist
) -> Matcher:
    """Matcher tuned for maximum fuzzy recall — used to prove the blocklist still holds."""
    return Matcher(
        repository, blocklist, candidate_threshold=PERMISSIVE_THRESHOLD, max_candidates=10
    )


def make_settings(**overrides: Any) -> Settings:
    """Settings pinned to the repo's data files, independent of the ambient environment."""
    values: dict[str, Any] = {
        "graph_backend": "memory",
        "seed_dir": DEMO_DIR,
        "fuzzy_negative_blocklist": BLOCKLIST_PATH,
        "coverage_manifest": COVERAGE_PATH,
        "fuzzy_candidate_threshold": 88,
        "fuzzy_max_candidates": 5,
        "log_level": "WARNING",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


def build_client(repo: Any, **setting_overrides: Any) -> TestClient:
    from medsafe.api.main import create_app

    return TestClient(create_app(make_settings(**setting_overrides), repo))


@pytest.fixture
def client(repository: InMemoryRepository):
    """API client backed by the seeded graph."""
    with build_client(repository) as test_client:
        yield test_client


@pytest.fixture
def permissive_client(repository: InMemoryRepository):
    """API client with a permissive fuzzy threshold, for blocklist assertions."""
    with build_client(repository, fuzzy_candidate_threshold=PERMISSIVE_THRESHOLD) as test_client:
        yield test_client


@pytest.fixture
def empty_client(empty_repository: InMemoryRepository):
    """API client backed by a reachable but unloaded graph."""
    with build_client(empty_repository) as test_client:
        yield test_client


class UnavailableRepository(InMemoryRepository):
    """A graph that is reachable in principle but fails every call, like a downed database."""

    def ping(self) -> bool:
        raise GraphUnavailableError("Neo4j is unreachable", detail={"uri": "bolt://unreachable"})

    def counts(self) -> dict[str, dict[str, int]]:
        raise GraphUnavailableError("Neo4j is unreachable")

    def find_molecule_by_exact_name(self, normalized_string: str):
        raise GraphUnavailableError("Neo4j is unreachable")

    def find_molecule_by_alias(self, normalized_string: str):
        raise GraphUnavailableError("Neo4j is unreachable")

    def all_molecule_names(self):
        raise GraphUnavailableError("Neo4j is unreachable")


@pytest.fixture
def unavailable_client():
    """API client whose graph raises on every query."""
    with build_client(UnavailableRepository()) as test_client:
        yield test_client


@pytest.fixture
def artifacts() -> ArtifactSet:
    """A tiny hand-built artifact set for loader tests."""
    return ArtifactSet(
        molecules=[
            {"molecule_id": "M1", "inn_name": "warfarin", "category": "small_molecule"},
            {"molecule_id": "M2", "inn_name": "aspirin", "category": "small_molecule"},
        ],
        products=[
            {
                "product_id": "P1",
                "source": "PMBJP",
                "generic_name_raw": "Warfarin 5mg Tablet",
                "form": "tablet",
                "strength_raw": "5mg",
                "mrp": "10.00",
            }
        ],
        contains=[{"product_id": "P1", "molecule_id": "M1", "strength": "5", "unit": "mg"}],
        aliases=[
            {
                "raw_string": "Coumadin",
                "normalized_string": "coumadin",
                "source": "manual",
                "molecule_id": "M1",
            }
        ],
        interactions=[
            {
                "molecule_id_a": "M1",
                "molecule_id_b": "M2",
                "severity": "major",
                "mechanism": "additive bleeding risk",
                "provenance": "ddinter",
            }
        ],
    )


@pytest.fixture
def loaded_repository(artifacts: ArtifactSet) -> InMemoryRepository:
    repo = InMemoryRepository()
    load_records(repo, artifacts)
    return repo
