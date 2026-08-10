"""``/health`` — liveness and readiness.

Liveness returns process health without touching the database. Readiness verifies the Neo4j driver
can execute a trivial query and that the expected constraints and node counts exist, so an API
running against an empty or unloaded graph reports unready rather than answering queries with
misleading empty results. Used by the docker-compose healthcheck and any upstream probe.

Readiness also reports the two safety controls that fail *open* if their data files are missing —
the confusable-pair blocklist and the interaction coverage manifest. Without them the engine still
answers, but fuzzy output is unguarded and no pair can be reported as checked, so an operator must
be able to see that state from a probe rather than infer it from responses.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from medsafe import __version__
from medsafe.api.dependencies import get_engine_state
from medsafe.api.schemas import LivenessResponse, ReadinessResponse
from medsafe.errors import GraphUnavailableError

router = APIRouter(tags=["health"])


@router.get("/health", response_model=LivenessResponse, summary="Liveness")
def liveness() -> LivenessResponse:
    """Process liveness. Deliberately touches nothing external, so it stays 200 without a graph."""
    return LivenessResponse(version=__version__)


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness",
    responses={503: {"model": ReadinessResponse, "description": "Not ready"}},
)
def readiness(request: Request, response: Response) -> ReadinessResponse:
    """Readiness. Returns 503 when the graph is unreachable or carries no data."""
    notes: list[str] = []
    try:
        state = get_engine_state(request)
    except GraphUnavailableError as exc:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            ready=False,
            graph_backend="unknown",
            graph_reachable=False,
            checks={"engine_initialised": False},
            notes=(exc.message,),
        )

    backend = state.settings.graph_backend
    counts: dict[str, dict[str, int]] = {}
    reachable = False
    try:
        reachable = bool(state.repository.ping())
        counts = state.repository.counts()
    except GraphUnavailableError as exc:
        notes.append(f"graph unreachable: {exc.message}")

    node_counts = counts.get("nodes", {})
    has_molecules = node_counts.get("Molecule", 0) > 0
    has_products = node_counts.get("Product", 0) > 0
    blocklist_loaded = not state.blocklist.missing and len(state.blocklist) > 0
    coverage_loaded = not state.coverage.missing

    if reachable and not has_molecules:
        notes.append(
            "graph is reachable but contains no Molecule nodes — run scripts/load_graph.py"
        )
    if not blocklist_loaded:
        notes.append(
            "confusable-pair blocklist is empty or missing — fuzzy candidates are UNGUARDED"
        )
    if not coverage_loaded:
        notes.append(
            "interaction coverage manifest is missing — every pair will report not_checked"
        )

    checks = {
        "engine_initialised": True,
        "graph_reachable": reachable,
        "molecules_loaded": has_molecules,
        "products_loaded": has_products,
        "blocklist_loaded": blocklist_loaded,
        "coverage_manifest_loaded": coverage_loaded,
    }
    # Data-file gaps are reported but do not gate readiness: the engine degrades loudly rather than
    # refusing traffic. An unreachable or empty graph does gate it — answering from an empty graph
    # produces confidently wrong empty results.
    ready = reachable and has_molecules
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        ready=ready,
        graph_backend=backend,
        graph_reachable=reachable,
        counts=counts,
        blocklist_pairs=len(state.blocklist),
        blocklist_loaded=blocklist_loaded,
        coverage_manifest_loaded=coverage_loaded,
        checks=checks,
        notes=tuple(notes),
    )
