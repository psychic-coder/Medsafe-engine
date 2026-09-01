"""FastAPI application factory and entry point.

Constructs the ``app``, wires configuration from ``medsafe.config``, manages the Neo4j driver over
the application lifespan (open on startup, close on shutdown), registers the ``resolve``, ``check``,
and ``health`` routers, and installs exception handlers so a resolution failure or an unavailable
graph returns a structured error rather than a bare 500. Served by uvicorn as
``medsafe.api.main:app``.

Startup never fails because the database is down. The driver is constructed lazily and a failure is
recorded, so ``/health`` still answers and ``/health/ready`` reports 503 with the reason — a service
that refuses to boot when its dependency is unavailable cannot tell you *why* it is unavailable.

Backend selection comes from ``MEDSAFE_GRAPH_BACKEND``. Setting it to ``memory`` runs the engine
against :class:`medsafe.graph.repository.InMemoryRepository`, seeded from ``MEDSAFE_SEED_DIR``::

    MEDSAFE_GRAPH_BACKEND=memory MEDSAFE_SEED_DIR=data/demo \\
        uvicorn medsafe.api.main:app --reload
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from medsafe import __version__
from medsafe.api.dependencies import EngineState
from medsafe.api.routes import check as check_routes
from medsafe.api.routes import health as health_routes
from medsafe.api.routes import resolve as resolve_routes
from medsafe.api.schemas import DISCLAIMER
from medsafe.config import Settings, get_settings
from medsafe.errors import MedsafeError
from medsafe.graph.repository import GraphRepository, InMemoryRepository, Neo4jRepository
from medsafe.resolution.blocklist import load_blocklist
from medsafe.resolution.matcher import Matcher
from medsafe.safety.interactions import AtcCoverage

__all__ = ["app", "create_app", "build_engine_state"]

logger = logging.getLogger("medsafe.api")


def _build_repository(settings: Settings) -> GraphRepository:
    """Construct the configured backend. Never raises — an unreachable graph surfaces at /health."""
    if settings.graph_backend == "memory":
        repository = InMemoryRepository()
        if settings.seed_dir is not None:
            from medsafe.graph.loader import load_artifacts

            report = load_artifacts(repository, settings.seed_dir)
            logger.info("Seeded in-memory graph from %s: %s", settings.seed_dir, report.written)
            if report.skipped:
                logger.warning("Seed load skipped stages: %s", report.skipped)
        else:
            repository.apply_schema()
        return repository

    return Neo4jRepository(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
        database=settings.neo4j_database,
    )


def build_engine_state(
    settings: Settings | None = None, repository: GraphRepository | None = None
) -> EngineState:
    """Assemble everything a request needs. ``repository`` may be injected by tests."""
    settings = settings or get_settings()
    repository = repository if repository is not None else _build_repository(settings)
    blocklist = load_blocklist(settings.fuzzy_negative_blocklist)
    coverage = AtcCoverage.from_manifest(settings.coverage_manifest)
    matcher = Matcher(
        repository,
        blocklist,
        candidate_threshold=settings.fuzzy_candidate_threshold,
        max_candidates=settings.fuzzy_max_candidates,
    )
    if blocklist.missing:
        logger.warning("Confusable-pair blocklist missing at %s", settings.fuzzy_negative_blocklist)
    if coverage.missing:
        logger.warning("Coverage manifest missing at %s", settings.coverage_manifest)
    return EngineState(
        settings=settings,
        repository=repository,
        blocklist=blocklist,
        coverage=coverage,
        matcher=matcher,
    )


def _error_response(
    status_code: int, code: str, message: str, detail: object = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "detail": detail}},
    )


def create_app(
    settings: Settings | None = None, repository: GraphRepository | None = None
) -> FastAPI:
    """Build the application. Tests call this with an injected repository."""
    settings = settings or get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            app.state.engine = build_engine_state(settings, repository)
        except Exception:
            # Booting must not depend on the graph; /health/ready reports the failure instead.
            logger.exception("Engine initialisation failed; API will report unready")
            app.state.engine = None
        try:
            yield
        finally:
            state = getattr(app.state, "engine", None)
            if state is not None:
                try:
                    state.close()
                except Exception:  # pragma: no cover - shutdown best effort
                    logger.warning("Error closing graph connection", exc_info=True)
            app.state.engine = None

    app = FastAPI(
        title="medsafe-engine",
        version=__version__,
        summary="Generic medicine substitute and prescription safety decision-support engine",
        description=(
            f"{DISCLAIMER}\n\nGraph schema and entity-resolution policy are locked; see "
            "docs/schema.md. Exact and alias matches auto-accept. Fuzzy matches only ever produce "
            "candidates for human review."
        ),
        lifespan=lifespan,
    )

    # The web UI is served from a different origin (Next.js on :3000) to the API (:8000), so
    # without this every browser request fails at the preflight with an opaque network error
    # rather than an HTTP status. Origins are configurable; the default covers local development.
    origins = settings.cors_origin_list
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_origin_regex=None if "*" not in origins else ".*",
            allow_credentials="*" not in origins,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
        )

    app.include_router(health_routes.router)
    app.include_router(resolve_routes.router)
    app.include_router(check_routes.router)

    # --- Structured errors. No route returns a bare 500 body. ---

    @app.exception_handler(MedsafeError)
    async def _medsafe_error(_: Request, exc: MedsafeError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("%s: %s", exc.code, exc.message, exc_info=True)
        return _error_response(exc.status_code, exc.code, exc.message, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(
            422, "validation_error", "Request failed validation", jsonable(exc.errors())
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error")
        return _error_response(
            500,
            "internal_error",
            "An unexpected internal error occurred",
            {"type": type(exc).__name__},
        )

    return app


def jsonable(value: object) -> object:
    """Best-effort JSON coercion for validation error payloads (they can hold exceptions)."""
    from fastapi.encoders import jsonable_encoder

    try:
        return jsonable_encoder(value)
    except Exception:  # pragma: no cover - defensive
        return str(value)


app = create_app()
