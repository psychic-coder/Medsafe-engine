"""Substitute discovery and savings computation.

Given a ``Product`` (or a resolved ``Molecule``), finds candidate substitutes that share the same
molecule via ``CONTAINS``, subject to equivalence rules: matching molecule, comparable strength and
unit, and compatible dosage form. Computes ``savings_abs`` and ``savings_pct`` from the ``mrp`` of
the source and substitute, ranks results, and materializes or reads the ``SUBSTITUTE_FOR`` edge as
defined in ``docs/schema.md``. Strictly single-molecule in v1 — a multi-molecule (FDC) product must
be reported as out of scope rather than partially substituted, since substituting on one component
of a combination is unsafe.

# TODO: implement in Phase 4
"""
