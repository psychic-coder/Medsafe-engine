"""Combination brands — pack names that mean two or more molecules.

Most of what an Indian patient actually holds is a combination. Augmentin is amoxicillin *and*
clavulanic acid; Combiflam is ibuprofen *and* paracetamol; Telma H is telmisartan *and* a diuretic.
The alias table cannot express these, because an ``Alias`` points at exactly one ``Molecule``.

The tempting fix is to map the brand to its "main" ingredient. That is wrong twice over, and both
failures are ones ``docs/schema.md`` names explicitly:

* **The interaction check would silently narrow.** Mapping Combiflam to ibuprofen alone drops
  paracetamol out of the pairwise set, so a paracetamol interaction elsewhere in the prescription is
  never looked for — and the report says "checked", because as far as it knows every input resolved.
  That is the "not checked folded into no interaction" failure, reached by a different route.
* **Substitution would price the wrong thing.** A two-drug product compared against one-drug
  products is not a like-for-like comparison, which is why v1 refuses FDC substitution at all.

So a combination is not an alias and is never collapsed. It resolves to its own status carrying
*all* components, which :mod:`medsafe.api.routes.check` expands into the pairwise set — every
component of every combination is checked against every component of every other drug — and which
the substitution layer refuses with the existing ``out_of_scope_fdc``.

Where the index lives
---------------------
``docs/schema.md`` locks ``Molecule`` / ``Product`` / ``Alias``, and a combination is none of those.
Rather than extend a locked schema, the index is a side artifact loaded at startup, exactly as
:class:`~medsafe.resolution.blocklist.ConfusablePairBlocklist` and
:class:`~medsafe.safety.interactions.AtcCoverage` already are. A missing file yields an empty index
with ``missing`` set: combination brands then fail to resolve and are reported as unidentified,
which is the same fail-closed direction as every other control here.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from medsafe.resolution.normalize import normalize_key

__all__ = ["CombinationComponent", "Combination", "CombinationIndex", "load_combinations"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CombinationComponent:
    """One active ingredient of a combination pack."""

    molecule_id: str
    inn_name: str
    position: int = 1


@dataclass(frozen=True, slots=True)
class Combination:
    """A pack name and every molecule it contains, in label order."""

    brand_key: str
    brand_raw: str
    components: tuple[CombinationComponent, ...]
    kind: str = "brand"

    def __post_init__(self) -> None:
        if len(self.components) < 2:
            raise ValueError(
                f"{self.brand_raw!r} has {len(self.components)} component(s); a combination needs "
                "at least two. A single-ingredient brand belongs in the alias table, where it "
                "resolves to a molecule and can be substituted."
            )

    @property
    def molecule_ids(self) -> tuple[str, ...]:
        return tuple(component.molecule_id for component in self.components)

    @property
    def label(self) -> str:
        """The brand as written plus its ingredients, e.g. ``Augmentin (amoxicillin + …)``."""
        names = " + ".join(component.inn_name for component in self.components)
        return f"{self.brand_raw} ({names})"


@dataclass
class CombinationIndex:
    """Lookup from a normalized pack name to its components.

    ``missing`` is true when no artifact was found, and is surfaced by ``/health/ready`` so a
    degraded load is visible rather than inferred from combination brands failing to resolve.
    """

    by_key: dict[str, Combination] = field(default_factory=dict)
    path: Path | None = None
    missing: bool = False

    def get(self, key: str) -> Combination | None:
        return self.by_key.get(key)

    def lookup(self, raw: str) -> Combination | None:
        """Find a combination by raw pack name, normalizing it the way the matcher does."""
        return self.by_key.get(normalize_key(raw))

    def __len__(self) -> int:
        return len(self.by_key)

    def __iter__(self) -> Iterator[Combination]:
        return iter(self.by_key.values())


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [
            {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            for row in csv.DictReader(handle)
        ]


def load_combinations(path: Path | str | None = None) -> CombinationIndex:
    """Load the combination index from ``combinations.csv``.

    Rows are grouped by ``brand_key`` and ordered by ``position``, so a component list always reads
    in the order the pack prints it. A brand that ends up with fewer than two components is dropped
    with a warning rather than admitted: it would be an alias wearing a combination's clothes, and
    it would wrongly suppress substitution for a drug that can be substituted.
    """
    if path is None:
        from medsafe.config import get_settings

        path = get_settings().combinations_file
    return _load_cached(str(path))


@lru_cache(maxsize=8)
def _load_cached(path_str: str) -> CombinationIndex:
    path = Path(path_str)
    if not path.is_file():
        logger.warning(
            "Combination index not found at %s — combination pack names will not resolve", path
        )
        return CombinationIndex(path=path, missing=True)

    grouped: dict[str, list[dict[str, str]]] = {}
    raw_names: dict[str, str] = {}
    kinds: dict[str, str] = {}
    for row in _read_rows(path):
        key = row.get("brand_key") or normalize_key(row.get("brand_raw", ""))
        if not key or not row.get("molecule_id"):
            continue
        grouped.setdefault(key, []).append(row)
        raw_names.setdefault(key, row.get("brand_raw") or key)
        kinds.setdefault(key, row.get("kind") or "brand")

    index: dict[str, Combination] = {}
    for key, rows in grouped.items():
        rows.sort(key=lambda r: (int(r.get("position") or 0), r.get("inn_name", "")))
        components = tuple(
            CombinationComponent(
                molecule_id=row["molecule_id"],
                inn_name=row.get("inn_name") or row["molecule_id"],
                position=int(row.get("position") or index_position),
            )
            for index_position, row in enumerate(rows, start=1)
        )
        if len(components) < 2:
            logger.warning(
                "Combination %r has %d component(s); skipped — a single-ingredient brand belongs "
                "in the alias table",
                raw_names[key],
                len(components),
            )
            continue
        index[key] = Combination(
            brand_key=key,
            brand_raw=raw_names[key],
            components=components,
            kind=kinds[key],
        )

    logger.info("Loaded %d combination brands from %s", len(index), path)
    return CombinationIndex(by_key=index, path=path)
