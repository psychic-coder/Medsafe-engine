"""``/resolve`` — drug string to canonical molecule, with generic substitutes.

Accepts a raw prescribed drug string, runs it through ``resolution.normalize`` and
``resolution.matcher``, and returns either an auto-accepted match (exact or alias-resolved, with the
match path stated) or an unresolved result carrying ranked fuzzy candidates marked as requiring
human review. On a resolved molecule, attaches substitutes from ``pricing.substitution`` with
``savings_pct`` and ``savings_abs``. Candidates are never presented as resolutions, and the response
never implies a fuzzy candidate was accepted.

Substitutes are only ever attached to a *resolved* molecule. A ``needs_review`` result carries no
substitution block at all: pricing a drug the engine has not identified would give the candidate the
appearance of an accepted match, which is the exact confusion the response shape exists to prevent.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from medsafe.api.dependencies import MatcherDep, RepositoryDep
from medsafe.api.schemas import ErrorResponse, ResolveRequest, ResolveResponse
from medsafe.pricing.substitution import find_substitutes_for_molecule

router = APIRouter(tags=["resolve"])

_RESPONSES: dict[int | str, dict] = {
    422: {"model": ErrorResponse, "description": "Invalid input"},
    503: {"model": ErrorResponse, "description": "Graph unavailable"},
}


def _resolve_one(
    matcher: MatcherDep,
    repository: RepositoryDep,
    drug: str,
    include_substitutes: bool,
) -> ResolveResponse:
    result = matcher.resolve(drug)

    substitution = None
    if include_substitutes and result.match is not None:
        # Constrain substitutes by whatever form/strength the input actually specified. When the
        # input said nothing, the pricing layer picks and reports its own baseline.
        substitution = find_substitutes_for_molecule(
            repository,
            result.match.molecule.molecule_id,
            form=result.normalized.form,
            strength_value=result.normalized.strength_value,
            strength_unit=result.normalized.strength_unit,
        )

    return ResolveResponse.from_domain(result, substitution)


@router.get("/resolve", response_model=ResolveResponse, responses=_RESPONSES)
def resolve_get(
    matcher: MatcherDep,
    repository: RepositoryDep,
    drug: str = Query(min_length=1, max_length=300, description="Raw prescribed drug string"),
    include_substitutes: bool = Query(default=True),
) -> ResolveResponse:
    """Resolve a single drug string."""
    return _resolve_one(matcher, repository, drug, include_substitutes)


@router.post("/resolve", response_model=ResolveResponse, responses=_RESPONSES)
def resolve_post(
    payload: ResolveRequest, matcher: MatcherDep, repository: RepositoryDep
) -> ResolveResponse:
    """Resolve a single drug string (POST form, for clients that prefer a body)."""
    return _resolve_one(matcher, repository, payload.drug, payload.include_substitutes)
