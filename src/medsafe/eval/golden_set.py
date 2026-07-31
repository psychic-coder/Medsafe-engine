"""Golden set — labelled evaluation fixtures and their loader.

Defines the case schema and reads the hand-labelled fixtures from ``data/manual/``: raw drug strings
with their expected canonical molecule and expected match path (exact / alias / unresolved), strings
that must produce candidates but never an auto-accept, every pair from
``fuzzy_negative_blocklist.csv`` as a must-never-match case, substitution cases with expected
savings, and interaction cases including molecules in the uncovered ATC groups whose expected result
is "not checked" rather than "no interaction". The negative cases are as load-bearing as the
positive ones.

# TODO: implement alongside Phases 2, 4, 5
"""
