"""Graph access — one semantic contract, two backends.

``GraphRepository`` is the narrow interface every layer above the graph depends on. It is defined
semantically (``find_molecule_by_exact_name``, ``interactions_between``, ...) rather than as
"execute this Cypher", so it can have two implementations that behave identically:

* :class:`Neo4jRepository` — runs the statements in :mod:`medsafe.graph.queries` against a real
  driver. This is the production path.
* :class:`InMemoryRepository` — a deterministic in-process store enforcing the same constraints
  (uniqueness, locked enums, canonical interaction ordering) via
  :mod:`medsafe.graph.schema`. It exists so the test suite, the eval harness, and a local demo can
  run the full pipeline without a database. It is not a Cypher interpreter and is not a substitute
  for integration-testing the real queries.

Both are also the *write* path: the loader merges through this interface, which is what lets the
same idempotency and ordering tests run against either backend.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from medsafe.errors import GraphUnavailableError
from medsafe.graph import queries
from medsafe.graph.schema import (
    canonical_pair,
    validate_alias,
    validate_interaction,
    validate_molecule,
    validate_product,
)

__all__ = ["GraphRepository", "Neo4jRepository", "InMemoryRepository"]

Record = dict[str, Any]


@runtime_checkable
class GraphRepository(Protocol):
    """The graph contract. Read methods return plain dicts; callers map them to Pydantic models."""

    # --- lifecycle / operational ---
    def ping(self) -> bool: ...
    def apply_schema(self) -> list[str]: ...
    def counts(self) -> dict[str, dict[str, int]]: ...
    def close(self) -> None: ...

    # --- write path (idempotent) ---
    def merge_molecules(self, rows: list[Record]) -> int: ...
    def merge_products(self, rows: list[Record]) -> int: ...
    def merge_contains(self, rows: list[Record]) -> int: ...
    def merge_aliases(self, rows: list[Record]) -> int: ...
    def merge_interactions(self, rows: list[Record]) -> int: ...
    def merge_substitute_for(self, rows: list[Record]) -> int: ...

    # --- read path ---
    def find_molecule_by_exact_name(self, normalized_string: str) -> Record | None: ...
    def find_molecule_by_alias(self, normalized_string: str) -> Record | None: ...
    def get_molecule(self, molecule_id: str) -> Record | None: ...
    def get_molecules(self, molecule_ids: list[str]) -> list[Record]: ...
    def all_molecule_names(self) -> list[Record]: ...
    def products_for_molecule(self, molecule_id: str) -> list[Record]: ...
    def get_product(self, product_id: str) -> Record | None: ...
    def molecules_for_product(self, product_id: str) -> list[Record]: ...
    def substitute_candidates(self, product_id: str) -> list[Record]: ...
    def interactions_between(self, molecule_ids: list[str]) -> list[Record]: ...


# ---------------------------------------------------------------------------------------------
# Neo4j
# ---------------------------------------------------------------------------------------------


class Neo4jRepository:
    """Executes :mod:`medsafe.graph.queries` against a Neo4j driver.

    The ``neo4j`` import is deferred to construction so importing this module (and therefore the
    API package) never requires the driver to be installed or a server to be reachable.
    """

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
        driver: Any | None = None,
    ) -> None:
        self.database = database
        if driver is not None:
            self._driver = driver
            return
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:  # pragma: no cover - dependency is declared in pyproject
            raise GraphUnavailableError("neo4j driver is not installed") from exc
        try:
            self._driver = GraphDatabase.driver(uri, auth=(user, password))
        except Exception as exc:
            raise GraphUnavailableError(
                "Could not construct the Neo4j driver", detail={"uri": uri, "error": str(exc)}
            ) from exc

    # --- plumbing ---

    def _run(self, cypher: str, **params: Any) -> list[Record]:
        try:
            with self._driver.session(database=self.database) as session:
                return [dict(record) for record in session.run(cypher, **params)]
        except GraphUnavailableError:
            raise
        except Exception as exc:
            raise GraphUnavailableError(
                "Neo4j query failed", detail={"error": str(exc), "type": type(exc).__name__}
            ) from exc

    def _write_batch(self, cypher: str, rows: list[Record], batch_size: int = 1000) -> int:
        written = 0
        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            result = self._run(cypher, rows=chunk)
            written += int(result[0]["written"]) if result else 0
        return written

    # --- lifecycle ---

    def ping(self) -> bool:
        return bool(self._run(queries.PING))

    def apply_schema(self) -> list[str]:
        from medsafe.graph.schema import SCHEMA_STATEMENTS

        for statement in SCHEMA_STATEMENTS:
            self._run(statement)
        return list(SCHEMA_STATEMENTS)

    def counts(self) -> dict[str, dict[str, int]]:
        nodes = {row["label"]: int(row["count"]) for row in self._run(queries.NODE_COUNTS)}
        rels = {row["type"]: int(row["count"]) for row in self._run(queries.RELATIONSHIP_COUNTS)}
        return {"nodes": nodes, "relationships": rels}

    def close(self) -> None:
        closer = getattr(self._driver, "close", None)
        if callable(closer):
            closer()

    # --- write path ---

    def merge_molecules(self, rows: list[Record]) -> int:
        return self._write_batch(queries.MERGE_MOLECULE, [validate_molecule(r) for r in rows])

    def merge_products(self, rows: list[Record]) -> int:
        return self._write_batch(queries.MERGE_PRODUCT, [validate_product(r) for r in rows])

    def merge_contains(self, rows: list[Record]) -> int:
        return self._write_batch(queries.MERGE_CONTAINS, rows)

    def merge_aliases(self, rows: list[Record]) -> int:
        return self._write_batch(queries.MERGE_ALIAS, [validate_alias(r) for r in rows])

    def merge_interactions(self, rows: list[Record]) -> int:
        return self._write_batch(
            queries.MERGE_INTERACTION, [validate_interaction(r) for r in rows]
        )

    def merge_substitute_for(self, rows: list[Record]) -> int:
        return self._write_batch(queries.MERGE_SUBSTITUTE_FOR, rows)

    # --- read path ---

    def find_molecule_by_exact_name(self, normalized_string: str) -> Record | None:
        rows = self._run(queries.MOLECULE_BY_EXACT_NAME, normalized_string=normalized_string)
        return rows[0] if rows else None

    def find_molecule_by_alias(self, normalized_string: str) -> Record | None:
        rows = self._run(queries.MOLECULE_BY_ALIAS, normalized_string=normalized_string)
        return rows[0] if rows else None

    def get_molecule(self, molecule_id: str) -> Record | None:
        rows = self._run(queries.MOLECULE_BY_ID, molecule_id=molecule_id)
        return rows[0] if rows else None

    def get_molecules(self, molecule_ids: list[str]) -> list[Record]:
        return self._run(queries.MOLECULES_BY_IDS, molecule_ids=molecule_ids)

    def all_molecule_names(self) -> list[Record]:
        return self._run(queries.ALL_MOLECULE_NAMES)

    def products_for_molecule(self, molecule_id: str) -> list[Record]:
        return self._run(queries.PRODUCTS_FOR_MOLECULE, molecule_id=molecule_id)

    def get_product(self, product_id: str) -> Record | None:
        rows = self._run(queries.PRODUCT_BY_ID, product_id=product_id)
        return rows[0] if rows else None

    def molecules_for_product(self, product_id: str) -> list[Record]:
        return self._run(queries.MOLECULES_FOR_PRODUCT, product_id=product_id)

    def substitute_candidates(self, product_id: str) -> list[Record]:
        return self._run(queries.SUBSTITUTE_CANDIDATES, product_id=product_id)

    def interactions_between(self, molecule_ids: list[str]) -> list[Record]:
        if len(molecule_ids) < 2:
            return []
        return self._run(queries.INTERACTIONS_BETWEEN, molecule_ids=list(molecule_ids))


# ---------------------------------------------------------------------------------------------
# In-memory
# ---------------------------------------------------------------------------------------------


class InMemoryRepository:
    """Deterministic in-process graph with the same semantics as :class:`Neo4jRepository`.

    Uniqueness is enforced by keying on the constrained property (``molecule_id``, ``product_id``,
    ``Alias.normalized_string``), which makes every merge idempotent by construction. Interaction
    edges are keyed on the canonical pair, so loading ``(a,b)`` and ``(b,a)`` yields exactly one
    edge — the same invariant the loader relies on in Neo4j.
    """

    def __init__(self) -> None:
        self.molecules: dict[str, Record] = {}
        self.products: dict[str, Record] = {}
        self.aliases: dict[str, Record] = {}
        self.contains: dict[tuple[str, str], Record] = {}
        self.interactions: dict[tuple[str, str], Record] = {}
        self.substitute_for: dict[tuple[str, str], Record] = {}
        self._schema_applied: list[str] = []
        self.available = True

    # --- lifecycle ---

    def ping(self) -> bool:
        if not self.available:
            raise GraphUnavailableError("In-memory graph marked unavailable")
        return True

    def apply_schema(self) -> list[str]:
        from medsafe.graph.schema import SCHEMA_STATEMENTS

        self._schema_applied = list(SCHEMA_STATEMENTS)
        return self._schema_applied

    @property
    def applied_constraints(self) -> list[str]:
        return list(self._schema_applied)

    def counts(self) -> dict[str, dict[str, int]]:
        self.ping()
        return {
            "nodes": {
                "Molecule": len(self.molecules),
                "Product": len(self.products),
                "Alias": len(self.aliases),
            },
            "relationships": {
                "CONTAINS": len(self.contains),
                "ALIAS_OF": len(self.aliases),
                "INTERACTS_WITH": len(self.interactions),
                "SUBSTITUTE_FOR": len(self.substitute_for),
            },
        }

    def close(self) -> None:
        return None

    # --- write path ---

    def merge_molecules(self, rows: list[Record]) -> int:
        self.ping()
        for row in rows:
            record = validate_molecule(row)
            self.molecules[record["molecule_id"]] = record
        return len(rows)

    def merge_products(self, rows: list[Record]) -> int:
        self.ping()
        for row in rows:
            record = validate_product(row)
            self.products[record["product_id"]] = record
        return len(rows)

    def merge_contains(self, rows: list[Record]) -> int:
        self.ping()
        for row in rows:
            product_id, molecule_id = str(row["product_id"]), str(row["molecule_id"])
            if product_id not in self.products or molecule_id not in self.molecules:
                # MATCH-based MERGE in Cypher is a silent no-op when an endpoint is absent; mirror
                # that so a dangling edge behaves identically on both backends.
                continue
            self.contains[(product_id, molecule_id)] = {
                "product_id": product_id,
                "molecule_id": molecule_id,
                "strength": row.get("strength"),
                "unit": row.get("unit"),
            }
        return len(rows)

    def merge_aliases(self, rows: list[Record]) -> int:
        self.ping()
        for row in rows:
            record = validate_alias(row)
            if record["molecule_id"] not in self.molecules:
                continue
            self.aliases[record["normalized_string"]] = record
        return len(rows)

    def merge_interactions(self, rows: list[Record]) -> int:
        self.ping()
        for row in rows:
            record = validate_interaction(row)
            key = (record["molecule_id_a"], record["molecule_id_b"])
            if key[0] not in self.molecules or key[1] not in self.molecules:
                continue
            self.interactions[key] = record
        return len(rows)

    def merge_substitute_for(self, rows: list[Record]) -> int:
        self.ping()
        for row in rows:
            key = (str(row["substitute_product_id"]), str(row["product_id"]))
            self.substitute_for[key] = dict(row)
        return len(rows)

    # --- read path ---

    def _molecule_projection(self, molecule_id: str) -> Record:
        molecule = self.molecules[molecule_id]
        return {
            "molecule_id": molecule["molecule_id"],
            "inn_name": molecule["inn_name"],
            "category": molecule["category"],
        }

    def find_molecule_by_exact_name(self, normalized_string: str) -> Record | None:
        self.ping()
        matches = sorted(
            (m for m in self.molecules.values() if m["inn_name"] == normalized_string),
            key=lambda m: m["molecule_id"],
        )
        return self._molecule_projection(matches[0]["molecule_id"]) if matches else None

    def find_molecule_by_alias(self, normalized_string: str) -> Record | None:
        self.ping()
        alias = self.aliases.get(normalized_string)
        if alias is None or alias["molecule_id"] not in self.molecules:
            return None
        record = self._molecule_projection(alias["molecule_id"])
        record.update(
            {
                "alias_raw_string": alias["raw_string"],
                "alias_normalized_string": alias["normalized_string"],
                "alias_source": alias["source"],
            }
        )
        return record

    def get_molecule(self, molecule_id: str) -> Record | None:
        self.ping()
        if molecule_id not in self.molecules:
            return None
        return self._molecule_projection(molecule_id)

    def get_molecules(self, molecule_ids: list[str]) -> list[Record]:
        self.ping()
        return [
            self._molecule_projection(mid)
            for mid in sorted(set(molecule_ids))
            if mid in self.molecules
        ]

    def all_molecule_names(self) -> list[Record]:
        self.ping()
        out: list[Record] = []
        for molecule_id in sorted(self.molecules):
            alias_strings = sorted(
                a["normalized_string"]
                for a in self.aliases.values()
                if a["molecule_id"] == molecule_id
            )
            record = self._molecule_projection(molecule_id)
            record["alias_strings"] = alias_strings
            out.append(record)
        return out

    def _molecule_count(self, product_id: str) -> int:
        return sum(1 for (pid, _) in self.contains if pid == product_id)

    def _product_projection(self, product_id: str, edge: Record | None = None) -> Record:
        product = self.products[product_id]
        record = {
            "product_id": product["product_id"],
            "source": product["source"],
            "generic_name_raw": product["generic_name_raw"],
            "form": product["form"],
            "strength_raw": product["strength_raw"],
            "mrp": product["mrp"],
            "molecule_count": self._molecule_count(product_id),
        }
        if edge is not None:
            record["strength"] = edge.get("strength")
            record["unit"] = edge.get("unit")
            record["molecule_id"] = edge.get("molecule_id")
        return record

    def products_for_molecule(self, molecule_id: str) -> list[Record]:
        self.ping()
        rows = [
            self._product_projection(pid, edge)
            for (pid, mid), edge in self.contains.items()
            if mid == molecule_id and pid in self.products
        ]
        return sorted(rows, key=lambda r: (r["mrp"], r["product_id"]))

    def get_product(self, product_id: str) -> Record | None:
        self.ping()
        if product_id not in self.products:
            return None
        return self._product_projection(product_id)

    def molecules_for_product(self, product_id: str) -> list[Record]:
        self.ping()
        rows = []
        for (pid, mid), edge in self.contains.items():
            if pid != product_id or mid not in self.molecules:
                continue
            record = self._molecule_projection(mid)
            record.update({"strength": edge.get("strength"), "unit": edge.get("unit")})
            rows.append(record)
        return sorted(rows, key=lambda r: r["molecule_id"])

    def substitute_candidates(self, product_id: str) -> list[Record]:
        self.ping()
        if product_id not in self.products or self._molecule_count(product_id) != 1:
            return []
        molecule_id = next(mid for (pid, mid) in self.contains if pid == product_id)
        rows = [
            self._product_projection(pid, edge)
            for (pid, mid), edge in self.contains.items()
            if mid == molecule_id and pid != product_id and pid in self.products
            and self._molecule_count(pid) == 1
        ]
        return sorted(rows, key=lambda r: (r["mrp"], r["product_id"]))

    def interactions_between(self, molecule_ids: list[str]) -> list[Record]:
        self.ping()
        wanted = set(molecule_ids)
        if len(wanted) < 2:
            return []
        rows: list[Record] = []
        for (left, right), edge in self.interactions.items():
            if left not in wanted or right not in wanted:
                continue
            left_c, right_c = canonical_pair(left, right)
            rows.append(
                {
                    "molecule_id_a": left_c,
                    "inn_name_a": self.molecules[left_c]["inn_name"],
                    "molecule_id_b": right_c,
                    "inn_name_b": self.molecules[right_c]["inn_name"],
                    "severity": edge["severity"],
                    "mechanism": edge.get("mechanism"),
                    "provenance": edge.get("provenance"),
                }
            )
        return sorted(rows, key=lambda r: (r["molecule_id_a"], r["molecule_id_b"]))
