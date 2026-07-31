"""Ingest DDInter interaction pairs into a processed interaction table.

Reads the raw DDInter dumps from ``data/raw/`` (gitignored) and emits ``INTERACTS_WITH`` rows with
``severity``, ``mechanism`` and ``provenance``, applying the canonical ordering
(``molecule_id_a < molecule_id_b``) and deduplicating reverse pairs at ingestion so the loader never
sees both directions. Drug names are normalized into ``Alias`` rows with ``source="ddinter"``.

Must also emit a coverage manifest recording which ATC groups this run actually covered: the bulk
source spans A, B, D, H, L, P, R, V only, and C/J/N/G/M/S are absent. That manifest is what lets
``safety.interactions`` distinguish "no known interaction" from "not checked" — without it the gap
becomes invisible downstream.

# TODO: implement in Phase 1
"""
