"""Dependency providers for the route modules.

The engine components (graph repository, matcher, blocklist, coverage manifest) are built once per
application in ``medsafe.api.main`` and stored on ``app.state``. Routes reach them through the
providers here rather than importing ``main``, which keeps the import graph acyclic and gives tests
a single seam: ``app.dependency_overrides[get_repository] = lambda: fake``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from medsafe.config import Settings, get_settings
from medsafe.errors import GraphUnavailableError
from medsafe.graph.repository import GraphRepository
from medsafe.resolution.blocklist import ConfusablePairBlocklist
from medsafe.resolution.matcher import Matcher
from medsafe.safety.interactions import AtcCoverage

__all__ = [
    "EngineState",
    "get_engine_state",
    "get_repository",
    "get_matcher",
    "get_blocklist",
    "get_coverage",
    "get_app_settings",
    "RepositoryDep",
    "MatcherDep",
    "CoverageDep",
    "SettingsDep",
]


@dataclass
class EngineState:
    """Everything a request needs, assembled once at startup."""

    settings: Settings
    repository: GraphRepository
    blocklist: ConfusablePairBlocklist
    coverage: AtcCoverage
    matcher: Matcher

    def close(self) -> None:
        self.repository.close()


def get_engine_state(request: Request) -> EngineState:
    state: EngineState | None = getattr(request.app.state, "engine", None)
    if state is None:
        raise GraphUnavailableError("Engine is not initialised; application startup did not run")
    return state


def get_repository(request: Request) -> GraphRepository:
    return get_engine_state(request).repository


def get_matcher(request: Request) -> Matcher:
    return get_engine_state(request).matcher


def get_blocklist(request: Request) -> ConfusablePairBlocklist:
    return get_engine_state(request).blocklist


def get_coverage(request: Request) -> AtcCoverage:
    return get_engine_state(request).coverage


def get_app_settings(request: Request) -> Settings:
    state: EngineState | None = getattr(request.app.state, "engine", None)
    return state.settings if state is not None else get_settings()


RepositoryDep = Annotated[GraphRepository, Depends(get_repository)]
MatcherDep = Annotated[Matcher, Depends(get_matcher)]
CoverageDep = Annotated[AtcCoverage, Depends(get_coverage)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
