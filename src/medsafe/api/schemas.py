"""Pydantic v2 request and response models — the API contract.

Defines the wire types shared by all routes: the node projections (``Molecule``, ``Product``,
``Alias``) with their locked enums from ``docs/schema.md``; resolution results that keep an
auto-accepted match (exact or alias) structurally distinct from an unaccepted fuzzy *candidate*
list, so a client cannot mistake one for the other; substitute entries carrying ``savings_pct`` and
``savings_abs``; and interaction entries carrying ``severity``, ``mechanism`` and ``provenance``.

Interaction responses must also carry an explicit coverage field distinguishing "checked, none
found" from "not checked — outside ingested ATC coverage (C/J/N/G/M/S)". That flag is part of the
contract, not an optional extra.

How the distinctions are enforced in the schema itself, not just in prose:

* ``match`` is ``null`` on any non-resolved response, and its ``path`` is typed
  ``Literal["exact", "alias"]`` — the generated OpenAPI schema has no way to express a fuzzy match.
* Every :class:`CandidateOut` carries ``requires_human_review: true`` and ``auto_accepted: false``
  as ``Literal`` constants, so a client reading only the candidate object still sees its status.
* :class:`InteractionPairOut.status` is a three-valued enum. There is no boolean "interactions
  found" field anywhere, because a boolean cannot represent "not checked".
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from medsafe.explain import (
    Explanation,
    explain_coverage,
    explain_pair,
    explain_resolution,
    explain_substitution,
    readable_provenance,
)
from medsafe.graph.schema import AliasSource, MoleculeCategory, ProductSource
from medsafe.pricing.substitution import SubstitutionResult, SubstitutionStatus
from medsafe.resolution.matcher import ResolutionResult, ResolutionStatus
from medsafe.safety.interactions import InteractionReport, PairStatus

__all__ = [
    "DISCLAIMER",
    "ErrorDetail",
    "ErrorResponse",
    "MoleculeOut",
    "NormalizationOut",
    "PlainOut",
    "CombinationOut",
    "MatchOut",
    "CandidateOut",
    "SuppressedOut",
    "ProductOut",
    "SubstituteOut",
    "SubstitutionOut",
    "ResolveRequest",
    "ResolveResponse",
    "CheckRequest",
    "CheckResponse",
    "DrugInputOut",
    "InteractionPairOut",
    "SuggestionOut",
    "SuggestResponse",
    "LivenessResponse",
    "ReadinessResponse",
]

DISCLAIMER = (
    "Decision support only. Not a diagnostic or dispensing authority. An absent interaction is "
    "not evidence of safety — check the coverage fields."
)


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- Errors -------------------------------------------------------------------------------------


class ErrorDetail(_Base):
    code: str = Field(description="Stable machine-readable error code")
    message: str
    detail: Any = None


class ErrorResponse(_Base):
    """The body of every non-2xx response. No route ever returns a bare 500 body."""

    error: ErrorDetail


# --- Node projections ---------------------------------------------------------------------------


class PlainOut(_Base):
    """The same state as the enum beside it, written for someone with no clinical training.

    Carried on the response rather than left to each client, because the wording is a safety
    control: the distinction between "we checked and found nothing" and "we did not check" only
    survives to the reader if something guarantees it, and an enum name does not.
    """

    headline: str
    detail: str
    action: str | None = None

    @classmethod
    def from_domain(cls, explanation: Explanation) -> PlainOut:
        return cls(
            headline=explanation.headline,
            detail=explanation.detail,
            action=explanation.action,
        )


class MoleculeOut(_Base):
    molecule_id: str
    inn_name: str
    category: MoleculeCategory | None = None

    @classmethod
    def from_domain(cls, molecule: Any) -> MoleculeOut:
        return cls(
            molecule_id=molecule.molecule_id,
            inn_name=molecule.inn_name,
            category=molecule.category,
        )


class ProductOut(_Base):
    product_id: str
    source: ProductSource
    generic_name_raw: str
    mrp: float
    form: str | None = None
    strength_raw: str | None = None
    strength: float | None = None
    unit: str | None = None
    molecule_count: int = 1
    is_fdc: bool = False

    @classmethod
    def from_domain(cls, product: Any) -> ProductOut:
        return cls(
            product_id=product.product_id,
            source=product.source,
            generic_name_raw=product.generic_name_raw,
            mrp=product.mrp,
            form=product.form,
            strength_raw=product.strength_raw,
            strength=product.strength,
            unit=product.unit,
            molecule_count=product.molecule_count,
            is_fdc=product.is_fdc,
        )


class NormalizationOut(_Base):
    """What normalization extracted. Nothing is discarded — every part is reported."""

    normalized: str
    salts: tuple[str, ...] = ()
    form: str | None = None
    strength_value: float | None = None
    strength_unit: str | None = None
    strength_raw: str | None = None
    strength_hint: float | None = None

    @classmethod
    def from_domain(cls, normalized: Any) -> NormalizationOut:
        return cls(
            normalized=normalized.normalized,
            salts=normalized.salts,
            form=normalized.form,
            strength_value=normalized.strength_value,
            strength_unit=normalized.strength_unit,
            strength_raw=normalized.strength_raw,
            strength_hint=normalized.strength_hint,
        )


# --- Resolution ---------------------------------------------------------------------------------


class MatchOut(_Base):
    """An auto-accepted match. ``path`` cannot express a fuzzy result."""

    path: Literal["exact", "alias"]
    molecule: MoleculeOut
    normalized_query: str
    alias_raw_string: str | None = None
    alias_source: AliasSource | None = None
    auto_accepted: Literal[True] = True


class CandidateOut(_Base):
    """An unaccepted fuzzy suggestion for the human-review queue."""

    molecule: MoleculeOut
    score: float = Field(ge=0, le=100)
    matched_string: str
    matched_on: Literal["inn_name", "alias"]
    requires_human_review: Literal[True] = True
    auto_accepted: Literal[False] = False


class CombinationOut(_Base):
    """A pack name that contains several molecules. Structurally distinct from ``MatchOut``.

    A combination is an identification, but not one that licenses substitution, so it is a separate
    field rather than a ``MatchOut`` with a longer list. A client that only knows about ``match``
    sees ``null`` and treats the input as unidentified, which is the safe reading.
    """

    brand_raw: str
    brand_key: str
    components: tuple[MoleculeOut, ...]
    substitutable: Literal[False] = False


class SuppressedOut(_Base):
    """A candidate withheld by the confusable-pair blocklist. Reported for audit only."""

    molecule_id: str
    inn_name: str
    score: float
    reason: str
    confusable_with: str


class SubstituteOut(_Base):
    product: ProductOut
    savings_abs: float
    savings_pct: float


class SubstitutionOut(_Base):
    status: SubstitutionStatus
    molecule_id: str
    reference: ProductOut | None = None
    substitutes: tuple[SubstituteOut, ...] = ()
    excluded: tuple[dict[str, str], ...] = ()
    plain: PlainOut | None = None
    notes: tuple[str, ...] = ()

    @classmethod
    def from_domain(
        cls, result: SubstitutionResult, inn_name: str | None = None
    ) -> SubstitutionOut:
        best = max(result.substitutes, key=lambda s: s.savings_pct, default=None)
        plain = PlainOut.from_domain(
            explain_substitution(
                result.status,
                inn_name=inn_name or result.molecule_id,
                substitute_count=len(result.substitutes),
                best_savings_pct=best.savings_pct if best else None,
                reference_price=result.reference.mrp if result.reference else None,
                best_price=best.product.mrp if best else None,
            )
        )
        return cls(
            status=result.status,
            molecule_id=result.molecule_id,
            plain=plain,
            reference=ProductOut.from_domain(result.reference) if result.reference else None,
            substitutes=tuple(
                SubstituteOut(
                    product=ProductOut.from_domain(s.product),
                    savings_abs=s.savings_abs,
                    savings_pct=s.savings_pct,
                )
                for s in result.substitutes
            ),
            excluded=result.excluded,
            notes=result.notes,
        )


class ResolveRequest(_Base):
    drug: str = Field(min_length=1, max_length=300, description="Raw prescribed drug string")
    include_substitutes: bool = True


class ResolveResponse(_Base):
    """Resolution outcome. ``match`` is populated only when ``status == "resolved"``."""

    query: str
    normalized: NormalizationOut
    status: ResolutionStatus
    match: MatchOut | None = None
    combination: CombinationOut | None = None
    candidates: tuple[CandidateOut, ...] = ()
    suppressed: tuple[SuppressedOut, ...] = ()
    substitution: SubstitutionOut | None = None
    plain: PlainOut
    notes: tuple[str, ...] = ()
    disclaimer: str = DISCLAIMER

    @classmethod
    def from_domain(
        cls, result: ResolutionResult, substitution: SubstitutionResult | None = None
    ) -> ResolveResponse:
        match = None
        if result.match is not None:
            match = MatchOut(
                path=result.match.path.value,
                molecule=MoleculeOut.from_domain(result.match.molecule),
                normalized_query=result.match.normalized_query,
                alias_raw_string=result.match.alias_raw_string,
                alias_source=result.match.alias_source,
            )

        combination = None
        if result.combination is not None:
            combination = CombinationOut(
                brand_raw=result.combination.brand_raw,
                brand_key=result.combination.brand_key,
                components=tuple(
                    MoleculeOut.from_domain(c) for c in result.combination.components
                ),
            )

        plain = PlainOut.from_domain(
            explain_resolution(
                result.status,
                query=result.query,
                inn_name=result.match.molecule.inn_name if result.match else None,
                alias_raw_string=result.match.alias_raw_string if result.match else None,
                component_names=tuple(c.inn_name for c in result.combination.components)
                if result.combination
                else (),
                candidate_names=tuple(c.molecule.inn_name for c in result.candidates),
                read_as=result.normalized.normalized,
            )
        )

        return cls(
            query=result.query,
            normalized=NormalizationOut.from_domain(result.normalized),
            status=result.status,
            match=match,
            combination=combination,
            plain=plain,
            candidates=tuple(
                CandidateOut(
                    molecule=MoleculeOut.from_domain(c.molecule),
                    score=c.score,
                    matched_string=c.matched_string,
                    matched_on=c.matched_on,
                )
                for c in result.candidates
            ),
            suppressed=tuple(
                SuppressedOut(
                    molecule_id=s.molecule_id,
                    inn_name=s.inn_name,
                    score=s.score,
                    reason=s.reason,
                    confusable_with=s.confusable_with,
                )
                for s in result.suppressed
            ),
            substitution=SubstitutionOut.from_domain(
                substitution,
                inn_name=result.match.molecule.inn_name if result.match else None,
            )
            if substitution
            else None,
            notes=result.notes,
        )


# --- Interaction check --------------------------------------------------------------------------


class CheckRequest(_Base):
    drugs: list[str] = Field(min_length=1, max_length=50)


class DrugInputOut(_Base):
    """One entry in the prescription, as the checker saw it.

    ``from_combination`` marks an input that the checker expanded out of a multi-ingredient pack, so
    a reader can tell why "Augmentin" appears in the report twice under two ingredient names rather
    than assuming a duplicate.
    """

    query: str
    resolved: bool
    molecule_id: str | None = None
    inn_name: str | None = None
    from_combination: str | None = None


class InteractionPairOut(_Base):
    """One pair. ``status`` is three-valued: ``not_checked`` is never folded into a clean result."""

    status: PairStatus
    left: DrugInputOut
    right: DrugInputOut
    severity: str | None = None
    mechanism: str | None = None
    provenance: str | None = None
    reason: str | None = None
    source: str | None = Field(
        default=None,
        description="Human-readable provenance. `provenance` keeps the raw source filenames.",
    )
    plain: PlainOut
    left_atc_group: str | None = None
    right_atc_group: str | None = None


class CheckResponse(_Base):
    inputs: tuple[DrugInputOut, ...]
    resolutions: tuple[ResolveResponse, ...]
    pairs: tuple[InteractionPairOut, ...]
    summary: dict[str, int]
    coverage_complete: bool = Field(
        description="False when any pair was not checked. False does NOT mean interactions exist."
    )
    covered_atc_groups: tuple[str, ...] = ()
    plain: PlainOut
    notes: tuple[str, ...] = ()
    disclaimer: str = DISCLAIMER

    @classmethod
    def from_domain(
        cls,
        report: InteractionReport,
        resolutions: tuple[ResolveResponse, ...],
        coverage_missing: bool = False,
    ) -> CheckResponse:
        def _input(molecule: Any) -> DrugInputOut:
            return DrugInputOut(
                query=molecule.query,
                resolved=molecule.resolved,
                molecule_id=molecule.molecule_id,
                inn_name=molecule.inn_name,
                from_combination=getattr(molecule, "from_combination", None),
            )

        summary = report.summary
        plain = PlainOut.from_domain(
            explain_coverage(
                pairs_total=summary["pairs_total"],
                interactions_found=summary["interactions_found"],
                checked_clear=summary["checked_no_interaction"],
                not_checked=summary["not_checked"],
                coverage_missing=coverage_missing,
            )
        )

        return cls(
            inputs=tuple(_input(m) for m in report.inputs),
            resolutions=resolutions,
            pairs=tuple(
                InteractionPairOut(
                    status=p.status,
                    left=_input(p.left),
                    right=_input(p.right),
                    severity=p.severity,
                    mechanism=p.mechanism,
                    provenance=p.provenance,
                    reason=p.reason,
                    source=readable_provenance(p.provenance),
                    plain=PlainOut.from_domain(
                        explain_pair(
                            p.status,
                            left=p.left.label,
                            right=p.right.label,
                            severity=p.severity,
                            mechanism=p.mechanism,
                            left_resolved=p.left.resolved,
                            right_resolved=p.right.resolved,
                            left_group=p.left_atc_group,
                            right_group=p.right_atc_group,
                            coverage_missing=coverage_missing,
                        )
                    ),
                    left_atc_group=p.left_atc_group,
                    right_atc_group=p.right_atc_group,
                )
                for p in report.pairs
            ),
            summary=summary,
            coverage_complete=report.coverage_complete,
            covered_atc_groups=report.covered_atc_groups,
            plain=plain,
            notes=report.notes,
        )


# --- Suggestions -------------------------------------------------------------------------------


class SuggestionOut(_Base):
    """One type-ahead entry.

    ``kind`` lets the console show a brand differently from an ingredient, so a user can tell that
    "Ecosprin" and "acetylsalicylic acid" are the same thing rather than two options to choose
    between.
    """

    label: str
    kind: Literal["ingredient", "other_name", "combination"]
    ingredient: str | None = None
    molecule_id: str | None = None
    confusable_with: tuple[str, ...] = Field(
        default=(),
        description=(
            "Names on this list that are known look-alikes of this one. Shown as a warning rather "
            "than used to hide the row: the reader has the pack and can check the spelling."
        ),
    )


class SuggestResponse(_Base):
    query: str
    suggestions: tuple[SuggestionOut, ...] = ()
    note: str | None = None


# --- Health -------------------------------------------------------------------------------------


class LivenessResponse(_Base):
    status: Literal["ok"] = "ok"
    service: str = "medsafe-engine"
    version: str


class ReadinessResponse(_Base):
    """Readiness. ``ready`` is false on an unreachable or unloaded graph."""

    ready: bool
    graph_backend: str
    graph_reachable: bool
    counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    blocklist_pairs: int = 0
    blocklist_loaded: bool = False
    coverage_manifest_loaded: bool = False
    combinations_loaded: bool = False
    combination_brands: int = 0
    checks: dict[str, bool] = Field(default_factory=dict)
    notes: tuple[str, ...] = ()
