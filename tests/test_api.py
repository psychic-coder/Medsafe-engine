"""Tests for the FastAPI surface (httpx client against ``medsafe.api.main:app``).

# TODO: TestHealth — liveness returns 200 without a database; readiness reports unready on an
#       empty or unreachable graph rather than 200
# TODO: TestResolveExact — resolved response states the match path and the molecule
# TODO: TestResolveAlias — alias-resolved input returns a resolved response, path="alias"
# TODO: TestResolveFuzzyCandidates — near-miss returns unresolved + candidates, and the response
#       shape makes it impossible to read a candidate as an accepted match
# TODO: TestResolveBlocklisted — a confusable input never returns its blocklisted partner
# TODO: TestResolveSubstitutes — resolved molecule returns substitutes with savings_pct/savings_abs
# TODO: TestSubstituteSingleMoleculeOnly — an FDC product reports out-of-scope, not a partial match
# TODO: TestCheckInteractionFound — pairwise result carries severity, mechanism, provenance
# TODO: TestCheckCoverageGap — a molecule in an uncovered ATC group (C/J/N/G/M/S) returns
#       "not checked", never "no known interaction"
# TODO: TestCheckUnresolvedInput — unresolved drug reported as unchecked, not dropped from the set
# TODO: TestErrorHandling — graph unavailable returns a structured error, not a bare 500
"""
