"""Entity resolution layer.

Turns a raw prescribed drug string into a canonical ``Molecule`` under the locked policy in
``docs/schema.md``: ``normalize`` produces the comparison key, ``matcher`` performs exact and
alias/bridge-table lookup (the only auto-accept paths) and generates fuzzy *candidates* for human
review, and ``blocklist`` guards the 67 confirmed dangerous confusable pairs. Fuzzy matches are
never auto-merged.

# TODO: implement in Phase 2
"""
