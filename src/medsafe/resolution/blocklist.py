"""Confusable-pair blocklist — the hard negative list for fuzzy matching.

Loads and indexes ``fuzzy_negative_blocklist.csv`` (confirmed dangerous confusable pairs in this
vocabulary — look-alike/sound-alike names that fuzzy scoring rates as near-identical but which are
clinically distinct drugs) and exposes a symmetric membership check over normalized strings. Any
pair present here is suppressed from fuzzy candidate output entirely: it is never returned as a
match and never surfaced as a review suggestion. This is a safety control, not a precision tweak —
a miss here is how a wrong drug reaches a patient.

Both members of every pair are stored under their :func:`medsafe.resolution.normalize.normalize_key`
form, so the check is applied to the same key space the matcher compares in. A pair whose two names
normalize to the *same* key is rejected at load time: that means a normalization rule has collapsed
two drugs the blocklist says must stay apart, which is a policy failure, not a data typo.

A missing file yields an empty blocklist and sets :attr:`ConfusablePairBlocklist.missing`, which the
readiness endpoint reports as degraded. It is never a silent no-op.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from medsafe.errors import ConfigurationError
from medsafe.resolution.normalize import normalize_key

__all__ = ["BlocklistEntry", "ConfusablePairBlocklist", "load_blocklist"]

logger = logging.getLogger(__name__)

# The blocklist is maintained by hand and by the curation scan, and the two settled on different
# column names for the same fields ("name_a" vs "molecule_a", "source" vs "origin"). Accepting both
# spellings keeps a hand-written row and a scan-generated row loadable from the same file: a safety
# control that silently loads zero pairs because of a header rename is worse than one that is
# missing outright, because `missing` stays False and readiness still reports it as present.
NAME_A_COLUMNS: tuple[str, ...] = ("name_a", "molecule_a", "drug_a")
NAME_B_COLUMNS: tuple[str, ...] = ("name_b", "molecule_b", "drug_b")
REASON_COLUMNS: tuple[str, ...] = ("reason", "verdict")
SOURCE_COLUMNS: tuple[str, ...] = ("source", "origin")


def _column(row: dict[str, str | None], names: tuple[str, ...]) -> str:
    """First non-empty value among ``names``. Returns ``""`` when none is present."""
    for name in names:
        value = (row.get(name) or "").strip()
        if value:
            return value
    return ""


@dataclass(frozen=True, slots=True)
class BlocklistEntry:
    """One unordered confusable pair, stored in normalized key space."""

    name_a: str
    name_b: str
    key_a: str
    key_b: str
    reason: str = ""
    source: str = ""

    @property
    def key(self) -> tuple[str, str]:
        """The pair as a sorted tuple, so lookup is direction-independent."""
        return (self.key_a, self.key_b) if self.key_a < self.key_b else (self.key_b, self.key_a)


class ConfusablePairBlocklist:
    """Symmetric membership check over normalized drug-name keys."""

    def __init__(
        self,
        entries: Iterable[BlocklistEntry] = (),
        *,
        path: Path | None = None,
        missing: bool = False,
    ) -> None:
        self._entries: dict[tuple[str, str], BlocklistEntry] = {}
        self._partners: dict[str, set[str]] = {}
        self.path = path
        self.missing = missing
        for entry in entries:
            self._add(entry)

    def _add(self, entry: BlocklistEntry) -> None:
        self._entries[entry.key] = entry
        self._partners.setdefault(entry.key_a, set()).add(entry.key_b)
        self._partners.setdefault(entry.key_b, set()).add(entry.key_a)

    # --- construction ---

    @classmethod
    def from_pairs(
        cls, pairs: Iterable[tuple[str, str]], *, source: str = "inline"
    ) -> ConfusablePairBlocklist:
        """Build from raw ``(name_a, name_b)`` tuples. Used by tests and the eval harness."""
        entries = []
        for name_a, name_b in pairs:
            entry = _build_entry(name_a, name_b, source=source)
            if entry is not None:
                entries.append(entry)
        return cls(entries, path=None)

    @classmethod
    def from_csv(cls, path: Path | str) -> ConfusablePairBlocklist:
        """Load from ``fuzzy_negative_blocklist.csv``. ``#`` comment lines are skipped."""
        csv_path = Path(path)
        if not csv_path.is_file():
            logger.warning(
                "Confusable-pair blocklist not found at %s — fuzzy candidates are UNGUARDED",
                csv_path,
            )
            return cls((), path=csv_path, missing=True)

        lines = [
            line
            for line in csv_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        entries: list[BlocklistEntry] = []
        for row in csv.DictReader(lines):
            name_a = _column(row, NAME_A_COLUMNS)
            name_b = _column(row, NAME_B_COLUMNS)
            if not name_a or not name_b:
                continue
            entry = _build_entry(
                name_a,
                name_b,
                reason=_column(row, REASON_COLUMNS),
                source=_column(row, SOURCE_COLUMNS) or "csv",
                origin=str(csv_path),
            )
            if entry is not None:
                entries.append(entry)
        return cls(entries, path=csv_path)

    # --- queries ---

    def contains(self, name_a: str, name_b: str, *, already_normalized: bool = False) -> bool:
        """True if the two names are a confirmed confusable pair. Symmetric."""
        key_a = name_a if already_normalized else normalize_key(name_a)
        key_b = name_b if already_normalized else normalize_key(name_b)
        if not key_a or not key_b:
            return False
        pair = (key_a, key_b) if key_a < key_b else (key_b, key_a)
        return pair in self._entries

    def partners_of(self, name: str, *, already_normalized: bool = False) -> frozenset[str]:
        """Every key confusable with ``name``."""
        key = name if already_normalized else normalize_key(name)
        return frozenset(self._partners.get(key, ()))

    def entry_for(self, name_a: str, name_b: str) -> BlocklistEntry | None:
        key_a, key_b = normalize_key(name_a), normalize_key(name_b)
        pair = (key_a, key_b) if key_a < key_b else (key_b, key_a)
        return self._entries.get(pair)

    @property
    def entries(self) -> tuple[BlocklistEntry, ...]:
        return tuple(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, pair: object) -> bool:
        if not isinstance(pair, tuple) or len(pair) != 2:
            return False
        return self.contains(str(pair[0]), str(pair[1]))

    def __repr__(self) -> str:  # pragma: no cover - debugging convenience
        return (
            f"<ConfusablePairBlocklist pairs={len(self)} "
            f"path={self.path} missing={self.missing}>"
        )


def _build_entry(
    name_a: str,
    name_b: str,
    *,
    reason: str = "",
    source: str = "",
    origin: str | None = None,
) -> BlocklistEntry | None:
    key_a, key_b = normalize_key(name_a), normalize_key(name_b)
    if not key_a or not key_b:
        logger.warning("Blocklist row normalizes to an empty key, skipped: %r / %r", name_a, name_b)
        return None
    if key_a == key_b:
        # Not a data typo: normalization has merged two names the blocklist says are distinct
        # drugs. Every downstream safety guarantee rests on those keys differing.
        raise ConfigurationError(
            "Blocklisted confusable pair normalizes to a single key — normalization is "
            "conflating two distinct drugs",
            detail={"name_a": name_a, "name_b": name_b, "key": key_a, "source": origin},
        )
    return BlocklistEntry(
        name_a=name_a, name_b=name_b, key_a=key_a, key_b=key_b, reason=reason, source=source
    )


@lru_cache(maxsize=4)
def _load_cached(path_str: str) -> ConfusablePairBlocklist:
    return ConfusablePairBlocklist.from_csv(path_str)


def load_blocklist(path: Path | str | None = None) -> ConfusablePairBlocklist:
    """Load the blocklist, defaulting to the configured path. Cached per path."""
    if path is None:
        from medsafe.config import get_settings

        path = get_settings().fuzzy_negative_blocklist
    return _load_cached(str(path))
