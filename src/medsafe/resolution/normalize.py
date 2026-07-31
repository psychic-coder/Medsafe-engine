"""String normalization — the canonical comparison key for drug names.

Deterministic, lossless-by-design preprocessing applied identically to every vocabulary (PMBJP,
DDInter, manual, rxnorm_dump) before any comparison: case folding, unicode normalization, whitespace
and punctuation handling, salt/ester and hydrate suffix treatment, dosage-form and strength token
stripping into separate fields, and British/American spelling variants. The output populates
``Alias.normalized_string`` and is what "exact match (post-normalization)" in the locked policy
means — so any change here changes what auto-accepts, and must be re-run against the golden set.
Strength and form extracted here feed ``Product.strength_raw`` / ``Product.form`` and the
``CONTAINS {strength, unit}`` edge.

# TODO: implement in Phase 2
"""
