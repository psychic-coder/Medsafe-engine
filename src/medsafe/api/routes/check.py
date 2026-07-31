"""``/check`` — interaction check across a set of prescribed drugs.

Accepts multiple drug strings, resolves each via ``resolution``, and calls ``safety.interactions``
for the pairwise ``INTERACTS_WITH`` edges, returning severity, mechanism, and provenance per pair.

Response composition here owns the coverage-gap requirement from ``docs/schema.md``: pairs involving
molecules outside DDInter's ingested ATC groups (C/J/N/G/M/S are not covered) must be reported as
"not checked", never folded into "no known interaction". Unresolved inputs are likewise reported as
unchecked rather than silently dropped from the pairwise set.

# TODO: implement in Phase 5
"""
