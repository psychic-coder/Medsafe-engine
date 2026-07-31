"""Matching — resolves a normalized string to a ``Molecule``, or to review candidates.

Implements the locked resolution policy in a strict order. (1) Exact match on the normalized string
against ``Molecule.inn_name`` — auto-accept. (2) Lookup against the ``Alias``/bridge table via
``ALIAS_OF`` — auto-accept. (3) Otherwise, RapidFuzz/Levenshtein scoring over the vocabulary to
produce ranked CANDIDATES for the human-review queue, returned with their scores and clearly typed
as unaccepted. Candidates are filtered through ``blocklist`` first, and no fuzzy result is ever
auto-merged into a match regardless of score — that is a patient-safety bug, not a data-quality
tradeoff (see ``docs/schema.md``). The return type must make "resolved" and "needs review"
impossible to confuse at the call site.

# TODO: implement in Phase 2
"""
