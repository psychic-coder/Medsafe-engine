"""Substitute discovery and savings computation.

Given a ``Product`` (or a resolved ``Molecule``), finds candidate substitutes that share the same
molecule via ``CONTAINS``, subject to equivalence rules: matching molecule, comparable strength and
unit, and compatible dosage form. Computes ``savings_abs`` and ``savings_pct`` from the ``mrp`` of
the source and substitute, ranks results, and materializes or reads the ``SUBSTITUTE_FOR`` edge as
defined in ``docs/schema.md``. Strictly single-molecule in v1 — a multi-molecule (FDC) product must
be reported as out of scope rather than partially substituted, since substituting on one component
of a combination is unsafe.

Two rules make the output conservative rather than merely plausible:

* **Unverifiable equivalence is not equivalence.** If either side's strength cannot be canonicalized
  to a common unit, or either side's form is unknown, the candidate is *excluded* and the reason
  recorded — never included on the assumption that it is probably fine.
* **The savings baseline is explicit.** When the caller supplies only a molecule there is no known
  prescribed product, so the most expensive equivalent is used as the reference and returned in
  :attr:`SubstitutionResult.reference`. Savings are relative to that stated baseline, not to an
  unstated one; a client that shows a saving without showing the baseline is misreporting it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from medsafe.graph.repository import GraphRepository
from medsafe.resolution.normalize import canonical_strength

__all__ = [
    "SubstitutionStatus",
    "ProductRef",
    "Substitute",
    "SubstitutionResult",
    "find_substitutes_for_product",
    "find_substitutes_for_molecule",
    "materialize_substitute_edges",
]


class SubstitutionStatus(StrEnum):
    """Why a substitution result looks the way it does."""

    OK = "ok"
    NO_PRODUCTS = "no_products"
    NO_SUBSTITUTES = "no_substitutes"
    OUT_OF_SCOPE_FDC = "out_of_scope_fdc"


@dataclass(frozen=True, slots=True)
class ProductRef:
    """Projection of a ``Product`` node plus its ``CONTAINS`` edge properties."""

    product_id: str
    source: str
    generic_name_raw: str
    mrp: float
    form: str | None = None
    strength_raw: str | None = None
    strength: float | None = None
    unit: str | None = None
    molecule_count: int = 1

    @property
    def is_fdc(self) -> bool:
        """True for a fixed-dose combination (more than one ``CONTAINS`` edge)."""
        return self.molecule_count > 1

    @property
    def comparable_strength(self) -> tuple[float, str] | None:
        return canonical_strength(_as_float(self.strength), self.unit)

    @classmethod
    def from_record(cls, record: dict) -> ProductRef:
        return cls(
            product_id=str(record["product_id"]),
            source=str(record.get("source") or ""),
            generic_name_raw=str(record.get("generic_name_raw") or ""),
            mrp=float(record.get("mrp") or 0.0),
            form=record.get("form"),
            strength_raw=record.get("strength_raw"),
            strength=_as_float(record.get("strength")),
            unit=record.get("unit"),
            molecule_count=int(record.get("molecule_count") or 1),
        )


@dataclass(frozen=True, slots=True)
class Substitute:
    """One equivalent product, cheaper than the reference, with its savings."""

    product: ProductRef
    savings_abs: float
    savings_pct: float


@dataclass(frozen=True, slots=True)
class SubstitutionResult:
    """Result of a substitution lookup, including why anything was excluded."""

    molecule_id: str
    status: SubstitutionStatus
    reference: ProductRef | None = None
    substitutes: tuple[Substitute, ...] = ()
    excluded: tuple[dict, ...] = ()
    notes: tuple[str, ...] = field(default=())

    @property
    def best_savings_abs(self) -> float:
        return self.substitutes[0].savings_abs if self.substitutes else 0.0


def _as_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _compute_savings(reference_mrp: float, candidate_mrp: float) -> tuple[float, float]:
    savings_abs = round(reference_mrp - candidate_mrp, 2)
    if reference_mrp <= 0:
        return savings_abs, 0.0
    return savings_abs, round((savings_abs / reference_mrp) * 100, 2)


def _equivalent(reference: ProductRef, candidate: ProductRef) -> tuple[bool, str]:
    """Equivalence test. Returns ``(ok, reason_if_not)``; unverifiable means not equivalent."""
    if candidate.is_fdc:
        return False, "candidate is a fixed-dose combination (out of scope in v1)"

    ref_form, cand_form = reference.form, candidate.form
    if not ref_form or not cand_form:
        return False, "dosage form unknown on one side; equivalence not verifiable"
    if ref_form != cand_form:
        return False, f"dosage form differs ({ref_form} vs {cand_form})"

    ref_strength, cand_strength = reference.comparable_strength, candidate.comparable_strength
    if ref_strength is None or cand_strength is None:
        return False, "strength not comparable; equivalence not verifiable"
    if ref_strength != cand_strength:
        return False, (
            f"strength differs ({ref_strength[0]}{ref_strength[1]} vs "
            f"{cand_strength[0]}{cand_strength[1]})"
        )
    return True, ""


def find_substitutes_for_product(
    repository: GraphRepository,
    product_id: str,
    *,
    include_costlier: bool = False,
) -> SubstitutionResult:
    """Find substitutes for a known prescribed product.

    An FDC reference short-circuits to :attr:`SubstitutionStatus.OUT_OF_SCOPE_FDC`: substituting a
    combination on one of its components is unsafe, so v1 reports it rather than partially matching.
    """
    record = repository.get_product(product_id)
    if record is None:
        return SubstitutionResult(
            molecule_id="",
            status=SubstitutionStatus.NO_PRODUCTS,
            notes=(f"product {product_id} not found",),
        )

    reference = ProductRef.from_record(record)
    molecules = repository.molecules_for_product(product_id)

    if reference.is_fdc or len(molecules) > 1:
        return SubstitutionResult(
            molecule_id=molecules[0]["molecule_id"] if molecules else "",
            status=SubstitutionStatus.OUT_OF_SCOPE_FDC,
            reference=reference,
            notes=(
                "fixed-dose combination: substitution is out of scope in v1",
                "substituting on a single component of a combination is unsafe; "
                "FDC-to-FDC substitution is deferred (docs/schema.md)",
            ),
        )
    if not molecules:
        return SubstitutionResult(
            molecule_id="",
            status=SubstitutionStatus.NO_PRODUCTS,
            reference=reference,
            notes=(f"product {product_id} has no CONTAINS edge to any molecule",),
        )

    molecule_id = str(molecules[0]["molecule_id"])
    # The reference's own strength/unit live on its CONTAINS edge, not on the node.
    reference = ProductRef.from_record(
        {
            **record,
            "strength": molecules[0].get("strength"),
            "unit": molecules[0].get("unit"),
        }
    )
    candidates = [ProductRef.from_record(r) for r in repository.substitute_candidates(product_id)]
    return _build_result(reference, molecule_id, candidates, include_costlier=include_costlier)


def find_substitutes_for_molecule(
    repository: GraphRepository,
    molecule_id: str,
    *,
    form: str | None = None,
    strength_value: float | None = None,
    strength_unit: str | None = None,
    reference_product_id: str | None = None,
    include_costlier: bool = False,
    strength_hint: float | None = None,
) -> SubstitutionResult:
    """Find substitutes for a resolved molecule, optionally constrained by form and strength.

    With no ``reference_product_id`` there is no known prescribed product, so the most expensive
    equivalent single-molecule product becomes the stated baseline.

    ``strength_hint`` is a bare number found in the query with no unit attached — the ``500`` in
    "Glycomet 500". Indian pack names carry the strength this way almost universally, but a number
    without a unit is not a measurement, so it is applied as a *preference*: if some product matches
    it in mg, the comparison narrows to those; if none does, it is ignored rather than emptying the
    result. An explicit ``strength_value`` always wins, because that one was actually stated.
    """
    if reference_product_id is not None:
        return find_substitutes_for_product(
            repository, reference_product_id, include_costlier=include_costlier
        )

    records = repository.products_for_molecule(molecule_id)
    products = [ProductRef.from_record(r) for r in records]
    single = [p for p in products if not p.is_fdc]

    if not products:
        return SubstitutionResult(
            molecule_id=molecule_id,
            status=SubstitutionStatus.NO_PRODUCTS,
            notes=("no products contain this molecule",),
        )
    if not single:
        return SubstitutionResult(
            molecule_id=molecule_id,
            status=SubstitutionStatus.OUT_OF_SCOPE_FDC,
            notes=(
                "this molecule appears only in fixed-dose combination products; "
                "FDC substitution is out of scope in v1",
            ),
        )

    wanted_strength = canonical_strength(strength_value, strength_unit)
    pool = single
    notes: list[str] = []
    if form:
        pool = [p for p in pool if p.form == form]
    if wanted_strength is not None:
        pool = [p for p in pool if p.comparable_strength == wanted_strength]
    if not pool:
        return SubstitutionResult(
            molecule_id=molecule_id,
            status=SubstitutionStatus.NO_SUBSTITUTES,
            notes=("no product matches the requested form and strength",),
        )

    if wanted_strength is None and strength_hint is not None:
        hinted = [p for p in pool if p.comparable_strength == (strength_hint, "mg")]
        if hinted:
            pool = hinted
            notes.append(
                f"the query carried a bare '{strength_hint:g}' with no unit; it matched products "
                f"at {strength_hint:g} mg, so the comparison is limited to those"
            )

    # Baseline = most expensive equivalent product. Deterministic on ties via product_id.
    reference = sorted(pool, key=lambda p: (-p.mrp, p.product_id))[0]
    notes.append(
        "no prescribed product was supplied; savings are relative to the most expensive "
        f"equivalent product ({reference.product_id})"
    )
    # Candidates deliberately come from every single-molecule product, not from the constrained
    # pool. A pack at the wrong strength must appear in `excluded` with its reason rather than
    # vanish: "we found a 250 mg pack and it is not the same as your 500 mg" is information, and
    # silently filtering it would make an empty result indistinguishable from an empty catalogue.
    candidates = [p for p in single if p.product_id != reference.product_id]
    result = _build_result(reference, molecule_id, candidates, include_costlier=include_costlier)
    return SubstitutionResult(
        molecule_id=result.molecule_id,
        status=result.status,
        reference=result.reference,
        substitutes=result.substitutes,
        excluded=result.excluded,
        notes=tuple(notes) + result.notes,
    )


def _build_result(
    reference: ProductRef,
    molecule_id: str,
    candidates: list[ProductRef],
    *,
    include_costlier: bool,
) -> SubstitutionResult:
    substitutes: list[Substitute] = []
    excluded: list[dict] = []

    for candidate in candidates:
        ok, reason = _equivalent(reference, candidate)
        if not ok:
            excluded.append({"product_id": candidate.product_id, "reason": reason})
            continue
        savings_abs, savings_pct = _compute_savings(reference.mrp, candidate.mrp)
        if savings_abs <= 0 and not include_costlier:
            excluded.append(
                {"product_id": candidate.product_id, "reason": "not cheaper than the reference"}
            )
            continue
        substitutes.append(
            Substitute(product=candidate, savings_abs=savings_abs, savings_pct=savings_pct)
        )

    # Best saving first; deterministic on ties.
    substitutes.sort(key=lambda s: (-s.savings_abs, s.product.mrp, s.product.product_id))

    notes: tuple[str, ...] = ()
    if reference.mrp <= 0:
        notes += ("reference MRP is zero; savings_pct cannot be computed",)

    status = SubstitutionStatus.OK if substitutes else SubstitutionStatus.NO_SUBSTITUTES
    return SubstitutionResult(
        molecule_id=molecule_id,
        status=status,
        reference=reference,
        substitutes=tuple(substitutes),
        excluded=tuple(excluded),
        notes=notes,
    )


def materialize_substitute_edges(
    repository: GraphRepository, result: SubstitutionResult
) -> int:
    """Write the ``SUBSTITUTE_FOR {savings_pct, savings_abs}`` edges for a computed result.

    Optional: reads are computed on demand, and the edge is a cache of that computation. Prices
    change, so a materialized edge is only valid for as long as both ``mrp`` values hold.
    """
    if result.reference is None or not result.substitutes:
        return 0
    rows = [
        {
            "product_id": result.reference.product_id,
            "substitute_product_id": substitute.product.product_id,
            "savings_abs": substitute.savings_abs,
            "savings_pct": substitute.savings_pct,
        }
        for substitute in result.substitutes
    ]
    return repository.merge_substitute_for(rows)
