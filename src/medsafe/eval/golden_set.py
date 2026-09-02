"""Golden set — labelled evaluation fixtures and their loader.

Defines the case schema and reads the hand-labelled fixtures from ``data/manual/``: raw drug strings
with their expected canonical molecule and expected match path (exact / alias / unresolved), strings
that must produce candidates but never an auto-accept, every pair from
``fuzzy_negative_blocklist.csv`` as a must-never-match case, substitution cases with expected
savings, and interaction cases including molecules in the uncovered ATC groups whose expected result
is "not checked" rather than "no interaction". The negative cases are as load-bearing as the
positive ones.

Case files are optional CSVs in ``data/manual/`` (``golden_resolution.csv``,
``golden_substitution.csv``, ``golden_interaction.csv``). When they are absent the built-in cases
below are used, so the harness always runs. The blocklist negatives are *generated* from
``fuzzy_negative_blocklist.csv`` rather than hand-listed: if a pair is added to the blocklist it
becomes an evaluation case in the same commit, with no second file to keep in step.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from medsafe.resolution.blocklist import ConfusablePairBlocklist

__all__ = [
    "ResolutionCase",
    "SubstitutionCase",
    "InteractionCase",
    "GoldenSet",
    "load_golden_set",
    "BUILTIN_RESOLUTION_CASES",
    "BUILTIN_SUBSTITUTION_CASES",
    "BUILTIN_INTERACTION_CASES",
]


@dataclass(frozen=True, slots=True)
class ResolutionCase:
    """One labelled resolution expectation.

    ``expected_path`` is one of ``exact``, ``alias``, ``needs_review`` or ``unresolved``.
    ``forbidden_molecules`` names molecules that must not appear as a match *or* a candidate — this
    is how a blocklisted confusable is expressed as a test.
    """

    query: str
    expected_path: str
    expected_molecule_id: str | None = None
    forbidden_molecules: tuple[str, ...] = ()
    note: str = ""

    @property
    def expects_auto_accept(self) -> bool:
        return self.expected_path in ("exact", "alias")


@dataclass(frozen=True, slots=True)
class SubstitutionCase:
    molecule_id: str
    form: str | None = None
    strength_value: float | None = None
    strength_unit: str | None = None
    expected_status: str = "ok"
    expected_reference_id: str | None = None
    expected_best_savings_abs: float | None = None
    forbidden_product_ids: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True, slots=True)
class InteractionCase:
    drugs: tuple[str, ...]
    expected_statuses: tuple[str, ...]
    note: str = ""


@dataclass
class GoldenSet:
    resolution: list[ResolutionCase] = field(default_factory=list)
    substitution: list[SubstitutionCase] = field(default_factory=list)
    interaction: list[InteractionCase] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.resolution) + len(self.substitution) + len(self.interaction)


# --- Built-in cases, keyed to data/demo ---------------------------------------------------------

BUILTIN_RESOLUTION_CASES: tuple[ResolutionCase, ...] = (
    ResolutionCase("amoxicillin", "exact", "MOL001", note="bare INN"),
    ResolutionCase("Amoxicillin 500mg Capsule", "exact", "MOL001", note="PMBJP catalogue row"),
    ResolutionCase("AMOXYCILLIN 500MG CAP", "exact", "MOL001", note="British spelling"),
    ResolutionCase("Metformin Hydrochloride 0.5g Tab", "exact", "MOL002", note="salt + strength"),
    ResolutionCase("Clavulanic Acid", "exact", "MOL014", note="multi-token INN"),
    ResolutionCase("Albuterol", "alias", "MOL012", note="USAN synonym via rxnorm_dump"),
    ResolutionCase("Ecosprin 75 Tablet", "alias", "MOL005", note="brand + strength noise"),
    ResolutionCase("Glycomet", "alias", "MOL002", note="brand"),
    ResolutionCase("Atorva", "alias", "MOL003", note="alias beats fuzzy"),
    ResolutionCase("amoxicilin", "needs_review", None, note="single-character typo"),
    ResolutionCase("zzzznotadrug", "unresolved", None, note="not in vocabulary"),
    ResolutionCase("500mg tablet", "unresolved", None, note="dosage noise only"),
    ResolutionCase(
        "hydralazine",
        "unresolved",
        None,
        forbidden_molecules=("MOL007",),
        note="must never suggest hydroxyzine",
    ),
)

BUILTIN_SUBSTITUTION_CASES: tuple[SubstitutionCase, ...] = (
    SubstitutionCase(
        "MOL001",
        form="capsule",
        strength_value=500,
        strength_unit="mg",
        expected_reference_id="PRD003",
        expected_best_savings_abs=79.50,
        forbidden_product_ids=("PRD004", "PRD040"),
        note="different strength and the FDC must both be excluded",
    ),
    SubstitutionCase(
        "MOL002",
        form="tablet",
        strength_value=500,
        strength_unit="mg",
        expected_reference_id="PRD012",
        expected_best_savings_abs=23.00,
        note="0.5g and 500mg must compare equal",
    ),
    SubstitutionCase(
        "MOL014", expected_status="out_of_scope_fdc", note="only available inside a combination"
    ),
)

BUILTIN_INTERACTION_CASES: tuple[InteractionCase, ...] = (
    InteractionCase(("Warfarin", "Aspirin"), ("interaction",), note="known DDInter pair"),
    InteractionCase(
        ("Warfarin", "Metformin"), ("no_known_interaction",), note="both in covered groups"
    ),
    InteractionCase(
        ("Warfarin", "Atorvastatin"),
        ("not_checked",),
        note="ATC C is outside bulk coverage — must not read as clean",
    ),
    InteractionCase(
        ("Warfarin", "Amoxicillin"), ("not_checked",), note="ATC J is outside bulk coverage"
    ),
    InteractionCase(
        ("Warfarin", "zzzznotadrug"), ("not_checked",), note="unresolved input is not dropped"
    ),
)


# --- Loading -------------------------------------------------------------------------------------


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            {k: (v or "").strip() for k, v in row.items() if k}
            for row in csv.DictReader(
                line for line in handle if line.strip() and not line.lstrip().startswith("#")
            )
        ]


def _tuple(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split("|") if part.strip())


def _float(value: str) -> float | None:
    return float(value) if value else None


def blocklist_negative_cases(blocklist: ConfusablePairBlocklist) -> list[ResolutionCase]:
    """Turn every blocklist pair into a must-never-match case, in both directions."""
    cases: list[ResolutionCase] = []
    for entry in blocklist.entries:
        for query, forbidden in ((entry.key_a, entry.key_b), (entry.key_b, entry.key_a)):
            cases.append(
                ResolutionCase(
                    query=query,
                    expected_path="any",
                    forbidden_molecules=(f"inn:{forbidden}",),
                    note=f"blocklist: {entry.reason or 'confirmed confusable pair'}",
                )
            )
    return cases


def load_golden_set(
    manual_dir: Path | str | None = None,
    blocklist: ConfusablePairBlocklist | None = None,
    *,
    include_blocklist_negatives: bool = True,
) -> GoldenSet:
    """Load the golden set, falling back to the built-in cases for any file that is absent."""
    if manual_dir is None:
        from medsafe.config import get_settings

        manual_dir = get_settings().data_manual_dir
    directory = Path(manual_dir)
    golden = GoldenSet()

    resolution_path = directory / "golden_resolution.csv"
    if resolution_path.is_file():
        golden.resolution = [
            ResolutionCase(
                query=row["query"],
                expected_path=row["expected_path"],
                expected_molecule_id=row.get("expected_molecule_id") or None,
                forbidden_molecules=_tuple(row.get("forbidden_molecules", "")),
                note=row.get("note", ""),
            )
            for row in _read_csv(resolution_path)
        ]
        golden.sources["resolution"] = str(resolution_path)
    else:
        golden.resolution = list(BUILTIN_RESOLUTION_CASES)
        golden.sources["resolution"] = "builtin"

    substitution_path = directory / "golden_substitution.csv"
    if substitution_path.is_file():
        golden.substitution = [
            SubstitutionCase(
                molecule_id=row["molecule_id"],
                form=row.get("form") or None,
                strength_value=_float(row.get("strength_value", "")),
                strength_unit=row.get("strength_unit") or None,
                expected_status=row.get("expected_status") or "ok",
                expected_reference_id=row.get("expected_reference_id") or None,
                expected_best_savings_abs=_float(row.get("expected_best_savings_abs", "")),
                forbidden_product_ids=_tuple(row.get("forbidden_product_ids", "")),
                note=row.get("note", ""),
            )
            for row in _read_csv(substitution_path)
        ]
        golden.sources["substitution"] = str(substitution_path)
    else:
        golden.substitution = list(BUILTIN_SUBSTITUTION_CASES)
        golden.sources["substitution"] = "builtin"

    interaction_path = directory / "golden_interaction.csv"
    if interaction_path.is_file():
        golden.interaction = [
            InteractionCase(
                drugs=_tuple(row["drugs"]),
                expected_statuses=_tuple(row["expected_statuses"]),
                note=row.get("note", ""),
            )
            for row in _read_csv(interaction_path)
        ]
        golden.sources["interaction"] = str(interaction_path)
    else:
        golden.interaction = list(BUILTIN_INTERACTION_CASES)
        golden.sources["interaction"] = "builtin"

    if include_blocklist_negatives:
        if blocklist is None:
            from medsafe.resolution.blocklist import load_blocklist

            blocklist = load_blocklist()
        negatives = blocklist_negative_cases(blocklist)
        golden.resolution.extend(negatives)
        golden.sources["blocklist_negatives"] = f"{len(negatives)} generated"

    return golden
