"""Neo4j schema definition, constraints, and indexes.

Declares the graph structure locked in ``docs/schema.md`` and the DDL to apply it: uniqueness
constraints on ``Molecule.molecule_id``, ``Product.product_id`` and ``Alias.normalized_string``;
indexes supporting alias lookup and product-by-molecule traversal; and the enum values that are
validated on write — ``Molecule.category`` ∈ {small_molecule, biologic, herbal, vaccine},
``Product.source`` ∈ {PMBJP, branded_csv}, ``Alias.source`` ∈ {ddinter, pmbjp, manual, rxnorm_dump}.
Also documents the canonical-ordering invariant for ``INTERACTS_WITH`` (``molecule_id_a <
molecule_id_b``, no duplicate reverse edges), which the loader must enforce.

# TODO: implement in Phase 1
"""
