"""Domain exceptions shared by every layer.

Each error carries a stable machine-readable ``code`` and an HTTP ``status_code`` so
``medsafe.api.main`` can translate any of them into a structured error body instead of a bare 500.
Layers below the API raise these; they never import FastAPI.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "MedsafeError",
    "ConfigurationError",
    "GraphUnavailableError",
    "SchemaViolationError",
    "ResolutionError",
    "OutOfScopeError",
]


class MedsafeError(Exception):
    """Base class for every error this engine raises deliberately."""

    code: str = "medsafe_error"
    status_code: int = 500

    def __init__(self, message: str, *, detail: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "detail": self.detail}


class ConfigurationError(MedsafeError):
    """Runtime settings are missing or invalid."""

    code = "configuration_error"
    status_code = 500


class GraphUnavailableError(MedsafeError):
    """The graph backend could not be reached or a query failed at the driver level."""

    code = "graph_unavailable"
    status_code = 503


class SchemaViolationError(MedsafeError):
    """A write violates the locked schema in ``docs/schema.md``.

    Bad enum value, missing required key, or a malformed edge.
    """

    code = "schema_violation"
    status_code = 422


class ResolutionError(MedsafeError):
    """The input could not be processed into a comparison key at all (e.g. empty string)."""

    code = "resolution_error"
    status_code = 422


class OutOfScopeError(MedsafeError):
    """A request is well-formed but outside v1 scope (e.g. FDC-to-FDC substitution)."""

    code = "out_of_scope"
    status_code = 422
