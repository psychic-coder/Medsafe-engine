"""Pydantic v2 request and response models — the API contract.

Defines the wire types shared by all routes: the node projections (``Molecule``, ``Product``,
``Alias``) with their locked enums from ``docs/schema.md``; resolution results that keep an
auto-accepted match (exact or alias) structurally distinct from an unaccepted fuzzy *candidate*
list, so a client cannot mistake one for the other; substitute entries carrying ``savings_pct`` and
``savings_abs``; and interaction entries carrying ``severity``, ``mechanism`` and ``provenance``.

Interaction responses must also carry an explicit coverage field distinguishing "checked, none
found" from "not checked — outside ingested ATC coverage (C/J/N/G/M/S)". That flag is part of the
contract, not an optional extra.

# TODO: implement in Phase 5
"""
