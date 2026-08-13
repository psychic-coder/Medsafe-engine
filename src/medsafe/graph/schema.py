"""Neo4j schema definition, constraints, and indexes.

Declares the graph structure locked in ``docs/schema.md`` and the DDL to apply it: uniqueness
constraints on ``Molecule.molecule_id``, ``Product.product_id`` and ``Alias.normalized_string``;
indexes supporting alias lookup and product-by-molecule traversal; and the enum values that are
validated on write — ``Molecule.category`` in {small_molecule, biologic, herbal, vaccine},
``Product.source`` in {PMBJP, branded_csv}, ``Alias.source`` in {ddinter, pmbjp, manual,
rxnorm_dump}. Also documents the canonical-ordering invariant for ``INTERACTS_WITH``
(``molecule_id_a < molecule_id_b``, no duplicate reverse edges), which the loader must enforce.

Nothing here talks to a driver: these are constants plus pure validation helpers, so the in-memory
backend enforces exactly the same rules as Neo4j.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from medsafe.errors import SchemaViolationError

__all__ = [
    "MoleculeCategory",
    "ProductSource",
    "AliasSource",
    "LABEL_MOLECULE",
    "LABEL_PRODUCT",
    "LABEL_ALIAS",
    "REL_CONTAINS",
    "REL_ALIAS_OF",
    "REL_INTERACTS_WITH",
    "REL_SUBSTITUTE_FOR",
    "MOLECULE_PROPERTIES",
    "PRODUCT_PROPERTIES",
    "ALIAS_PROPERTIES",
    "CONSTRAINTS",
    "INDEXES",
    "SCHEMA_STATEMENTS",
    "canonical_pair",
    "validate_molecule",
    "validate_product",
    "validate_alias",
    "validate_interaction",
]


class MoleculeCategory(StrEnum):
    """``Molecule.category`` — locked enum."""

    SMALL_MOLECULE = "small_molecule"
    BIOLOGIC = "biologic"
    HERBAL = "herbal"
    VACCINE = "vaccine"


class ProductSource(StrEnum):
    """``Product.source`` — locked enum."""

    PMBJP = "PMBJP"
    BRANDED_CSV = "branded_csv"


class AliasSource(StrEnum):
    """``Alias.source`` — locked enum."""

    DDINTER = "ddinter"
    PMBJP = "pmbjp"
    MANUAL = "manual"
    RXNORM_DUMP = "rxnorm_dump"


LABEL_MOLECULE = "Molecule"
LABEL_PRODUCT = "Product"
LABEL_ALIAS = "Alias"

REL_CONTAINS = "CONTAINS"
REL_ALIAS_OF = "ALIAS_OF"
REL_INTERACTS_WITH = "INTERACTS_WITH"
REL_SUBSTITUTE_FOR = "SUBSTITUTE_FOR"

MOLECULE_PROPERTIES: tuple[str, ...] = ("molecule_id", "inn_name", "category", "ddinter_anchor")
PRODUCT_PROPERTIES: tuple[str, ...] = (
    "product_id",
    "source",
    "generic_name_raw",
    "form",
    "strength_raw",
    "mrp",
)
ALIAS_PROPERTIES: tuple[str, ...] = ("raw_string", "normalized_string", "source")

# --- DDL -------------------------------------------------------------------------------------
# Applied by graph.loader.apply_schema(). Every statement is IF NOT EXISTS, so re-running is a
# no-op and a partially-applied schema converges rather than erroring.

CONSTRAINTS: tuple[str, ...] = (
    "CREATE CONSTRAINT molecule_id_unique IF NOT EXISTS "
    "FOR (m:Molecule) REQUIRE m.molecule_id IS UNIQUE",
    "CREATE CONSTRAINT product_id_unique IF NOT EXISTS "
    "FOR (p:Product) REQUIRE p.product_id IS UNIQUE",
    "CREATE CONSTRAINT alias_normalized_unique IF NOT EXISTS "
    "FOR (a:Alias) REQUIRE a.normalized_string IS UNIQUE",
)

INDEXES: tuple[str, ...] = (
    # Exact lookup path: normalized query string -> Molecule.inn_name.
    "CREATE INDEX molecule_inn_name_index IF NOT EXISTS FOR (m:Molecule) ON (m.inn_name)",
    # Alias lookup path (normalized_string is already unique-constrained; raw_string aids audit).
    "CREATE INDEX alias_raw_string_index IF NOT EXISTS FOR (a:Alias) ON (a.raw_string)",
    # Product-by-molecule traversal and substitute ranking.
    "CREATE INDEX product_source_index IF NOT EXISTS FOR (p:Product) ON (p.source)",
    "CREATE INDEX product_form_index IF NOT EXISTS FOR (p:Product) ON (p.form)",
)

SCHEMA_STATEMENTS: tuple[str, ...] = CONSTRAINTS + INDEXES


# --- Invariants and validation ----------------------------------------------------------------


def canonical_pair(molecule_id_a: str, molecule_id_b: str) -> tuple[str, str]:
    """Return the pair in canonical order (``molecule_id_a < molecule_id_b``).

    Every ``INTERACTS_WITH`` edge is stored exactly once in this order, so a lookup never has to
    try both directions and a reverse duplicate can never be created.
    """
    if molecule_id_a == molecule_id_b:
        raise SchemaViolationError(
            "INTERACTS_WITH requires two distinct molecules",
            detail={"molecule_id": molecule_id_a},
        )
    if molecule_id_a < molecule_id_b:
        return molecule_id_a, molecule_id_b
    return molecule_id_b, molecule_id_a


def _require(row: dict[str, Any], keys: tuple[str, ...], what: str) -> None:
    missing = [k for k in keys if row.get(k) in (None, "")]
    if missing:
        raise SchemaViolationError(
            f"{what} is missing required properties", detail={"missing": missing, "row": row}
        )


def _require_enum(value: Any, enum_cls: type[StrEnum], field: str) -> str:
    allowed = {member.value for member in enum_cls}
    if value not in allowed:
        raise SchemaViolationError(
            f"Invalid {field}", detail={"value": value, "allowed": sorted(allowed)}
        )
    return str(value)


def validate_molecule(row: dict[str, Any]) -> dict[str, Any]:
    """Validate and coerce a ``Molecule`` row. ddinter_anchor is optional."""
    _require(row, ("molecule_id", "inn_name", "category"), "Molecule")
    return {
        "molecule_id": str(row["molecule_id"]),
        "inn_name": str(row["inn_name"]),
        "category": _require_enum(row["category"], MoleculeCategory, "Molecule.category"),
        "ddinter_anchor": str(row["ddinter_anchor"]) if row.get("ddinter_anchor") else None,
    }


def validate_product(row: dict[str, Any]) -> dict[str, Any]:
    """Validate and coerce a ``Product`` row. ``mrp`` is required and must be non-negative."""
    _require(row, ("product_id", "source", "generic_name_raw"), "Product")
    if row.get("mrp") is None:
        raise SchemaViolationError("Product.mrp is required", detail={"row": row})
    try:
        mrp = float(row["mrp"])
    except (TypeError, ValueError) as exc:
        raise SchemaViolationError(
            "Product.mrp must be numeric", detail={"value": row.get("mrp")}
        ) from exc
    if mrp < 0:
        raise SchemaViolationError("Product.mrp must be non-negative", detail={"value": mrp})
    return {
        "product_id": str(row["product_id"]),
        "source": _require_enum(row["source"], ProductSource, "Product.source"),
        "generic_name_raw": str(row["generic_name_raw"]),
        "form": str(row["form"]) if row.get("form") else None,
        "strength_raw": str(row["strength_raw"]) if row.get("strength_raw") else None,
        "mrp": mrp,
    }


def validate_alias(row: dict[str, Any]) -> dict[str, Any]:
    """Validate and coerce an ``Alias`` row; ``molecule_id`` is the ``ALIAS_OF`` target."""
    _require(row, ALIAS_PROPERTIES, "Alias")
    _require(row, ("molecule_id",), "Alias (ALIAS_OF target)")
    return {
        "raw_string": str(row["raw_string"]),
        "normalized_string": str(row["normalized_string"]),
        "source": _require_enum(row["source"], AliasSource, "Alias.source"),
        "molecule_id": str(row["molecule_id"]),
    }


def validate_interaction(row: dict[str, Any]) -> dict[str, Any]:
    """Validate an ``INTERACTS_WITH`` row and force it into canonical ordering."""
    _require(row, ("molecule_id_a", "molecule_id_b", "severity"), "INTERACTS_WITH")
    left, right = canonical_pair(str(row["molecule_id_a"]), str(row["molecule_id_b"]))
    return {
        "molecule_id_a": left,
        "molecule_id_b": right,
        "severity": str(row["severity"]),
        "mechanism": str(row["mechanism"]) if row.get("mechanism") else None,
        "provenance": str(row["provenance"]) if row.get("provenance") else None,
    }
