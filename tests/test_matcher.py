"""Tests for ``medsafe.resolution.matcher``.

# TODO: TestExactMatch — normalized string matching an INN resolves, auto-accepted, path="exact"
# TODO: TestAliasResolvedMatch — string resolving only via the Alias/bridge table auto-accepts,
#       path="alias", and returns the molecule the alias points at
# TODO: TestFuzzyCandidateGeneration — a near-miss returns ranked candidates with scores,
#       and the result is typed as unresolved / needs-review
# TODO: TestFuzzyNeverAutoAccepts — even at score 99, a fuzzy hit is never returned as a match;
#       no threshold setting can turn a candidate into an auto-accept
# TODO: TestBlocklistedPairNeverReturned — neither member of a confirmed confusable pair appears
#       as a match or as a candidate for the other, at any score
# TODO: TestNoMatch — unknown string returns unresolved with an empty candidate list, not an error
# TODO: TestMatchPathPrecedence — exact wins over alias; alias wins over fuzzy candidates
# TODO: TestCandidateOrdering — candidates ranked by score, deterministic on ties
"""
