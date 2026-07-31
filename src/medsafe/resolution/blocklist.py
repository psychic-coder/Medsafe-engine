"""Confusable-pair blocklist — the hard negative list for fuzzy matching.

Loads and indexes ``fuzzy_negative_blocklist.csv`` (67 confirmed dangerous confusable pairs in this
vocabulary — look-alike/sound-alike names that fuzzy scoring rates as near-identical but which are
clinically distinct drugs) and exposes a symmetric membership check over normalized strings. Any
pair present here is suppressed from fuzzy candidate output entirely: it is never returned as a
match and never surfaced as a review suggestion. This is a safety control, not a precision tweak —
a miss here is how a wrong drug reaches a patient.

# TODO: implement in Phase 2
"""
