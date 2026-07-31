"""Interaction checking and coverage reporting.

Takes a set of resolved molecules and returns the pairwise ``INTERACTS_WITH {severity, mechanism,
provenance}`` edges between them, matching each pair under the canonical ordering
(``molecule_id_a < molecule_id_b``) so direction never affects the result.

Critically, it also reports *coverage*, not just hits. The DDInter bulk source covers ATC groups
A, B, D, H, L, P, R, V only; C/J/N/G/M/S (cardiovascular, anti-infective, CNS, and others) are not
covered by bulk ingestion. This module must distinguish "checked, no known interaction" from "not
checked — molecule falls outside ingested coverage" and return that distinction per pair, so Phase 5
response composition can flag the gap explicitly. Collapsing the two into a bare "no interactions"
is the failure mode this module exists to prevent.

# TODO: implement in Phase 5
"""
