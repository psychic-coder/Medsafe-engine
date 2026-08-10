"""``/check`` — interaction check across a set of prescribed drugs.

Accepts multiple drug strings, resolves each via ``resolution``, and calls ``safety.interactions``
for the pairwise ``INTERACTS_WITH`` edges, returning severity, mechanism, and provenance per pair.

Response composition here owns the coverage-gap requirement from ``docs/schema.md``: pairs involving
molecules outside DDInter's ingested ATC groups (C/J/N/G/M/S are not covered) must be reported as
"not checked", never folded into "no known interaction". Unresolved inputs are likewise reported as
unchecked rather than silently dropped from the pairwise set.

The response carries no boolean "safe" or "interactions found" field. A boolean cannot represent
the third outcome, and a client reading one would read "not checked" as "clean" — so the only way
to read this response is through the three-valued per-pair ``status`` and ``coverage_complete``.
"""

from __future__ import annotations

from fastapi import APIRouter

from medsafe.api.dependencies import CoverageDep, MatcherDep, RepositoryDep
from medsafe.api.schemas import CheckRequest, CheckResponse, ErrorResponse, ResolveResponse
from medsafe.safety.interactions import MoleculeInput, check_interactions

router = APIRouter(tags=["check"])


@router.post(
    "/check",
    response_model=CheckResponse,
    responses={
        422: {"model": ErrorResponse, "description": "Invalid input"},
        503: {"model": ErrorResponse, "description": "Graph unavailable"},
    },
)
def check(
    payload: CheckRequest,
    matcher: MatcherDep,
    repository: RepositoryDep,
    coverage: CoverageDep,
) -> CheckResponse:
    """Check every unordered pair of the supplied drugs for known interactions."""
    results = matcher.resolve_many(payload.drugs)

    inputs = [
        MoleculeInput(
            query=result.query,
            molecule_id=result.match.molecule.molecule_id if result.match else None,
            inn_name=result.match.molecule.inn_name if result.match else None,
            resolved=result.is_resolved,
        )
        for result in results
    ]

    report = check_interactions(repository, inputs, coverage)

    # Resolutions are echoed so a caller can see *why* an input was unchecked — and, for a
    # needs_review input, the candidates a human would triage. Substitutes are omitted: /check is a
    # safety endpoint, and pricing is not its job.
    resolutions = tuple(ResolveResponse.from_domain(result) for result in results)
    return CheckResponse.from_domain(report, resolutions)
