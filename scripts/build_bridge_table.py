"""Build the alias/bridge table joining the PMBJP and DDInter vocabularies.

Consumes the processed outputs of the two ingestion scripts plus any manual mappings in
``data/manual/``, normalizes every surface form, and produces the canonical ``Molecule`` list
together with the ``Alias`` rows (``raw_string``, ``normalized_string``, ``source`` ∈ {ddinter,
pmbjp, manual, rxnorm_dump}) that link each vocabulary's names to a single ``molecule_id``.

Joins are made on exact normalized equality and curated manual mappings only. Fuzzy similarity may
be used to *propose* unresolved-name candidates into a review file for a human to accept into
``data/manual/`` — it never writes an alias directly. Blocklisted confusable pairs are excluded from
proposals entirely. This is the script where a wrong join silently becomes a wrong substitution, so
it reports unjoined names loudly rather than guessing.

# TODO: implement in Phase 2
"""
