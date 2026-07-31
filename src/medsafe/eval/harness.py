"""Evaluation harness — runs the engine against the golden set and reports.

Loads the golden set, executes the relevant pipeline stage for each case (resolution, substitution,
interaction check), scores the outputs with ``metrics``, and emits a comparable run report so
changes to normalization rules, the alias table, or the fuzzy threshold can be evaluated before they
ship. Runnable per phase, from CI or the command line, without requiring a fully loaded graph for
the stages that do not need one.

# TODO: implement alongside Phases 2, 4, 5
"""
