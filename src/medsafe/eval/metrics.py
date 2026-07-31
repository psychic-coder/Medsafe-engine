"""Evaluation metrics.

Defines what is measured and how it is aggregated: resolution precision/recall by match path,
coverage (share of inputs auto-accepted vs. routed to review), candidate quality (is the true
molecule present in the candidate list, and at what rank), and — weighted above all of them — the
false-accept rate, particularly any blocklisted confusable pair surfacing as a match. A false accept
is not traded off against coverage here; it is reported as a hard failure. Also reports interaction
coverage-gap rates so the share of "not checked" results stays visible.

# TODO: implement alongside Phases 2, 4, 5
"""
