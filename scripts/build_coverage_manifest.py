"""Rebuild the interaction coverage manifest from artifacts already in the repository.

``scripts/ingest_ddinter.py`` emits ``ddinter_coverage.json`` alongside the interaction table, but
only when it is handed the raw per-drug ATC file. That file lives under ``data/raw/`` and is not
redistributable, so a clone that ships only ``data/processed/`` has an interaction table and no
manifest — and a missing manifest makes ``AtcCoverage`` fail closed, so *every* pair reports
``not_checked``. The engine is then technically correct and practically useless: it cannot tell a
user that anything was checked, including pairs it demonstrably did check.

This script reconstructs the manifest without the raw file, from three sources of evidence that are
already in the repository, in descending order of authority. The tier that supplied each molecule's
group is recorded in the manifest, so the result is auditable rather than a black box.

Tier 1 — ``data/manual/ddinter_anchor_profile.csv``, anchors only (grants coverage)
    DDInter is distributed as one file per ATC first level. A drug appears in a file either as that
    file's *anchor* — the drug whose ATC group the file is named for — or merely as the partner in
    someone else's row. Only the first says anything about the drug's own group.

    The Phase-0 recon profile records exactly this discriminator in ``anchor_concentration``, and
    the signal is unambiguous: warfarin, amoxicillin and metformin sit at 1.0 and are genuinely in
    covered groups; atorvastatin (0.44), amlodipine (0.34) and atenolol (0.37) sit far below and
    are cardiovascular drugs in group C, which DDInter never shipped. They appear in the covered
    files only because something else in the row anchored them.

    So a covered group is granted only at full anchor concentration. Everything below stays unknown
    and therefore not checked, which costs a little coverage and forecloses the alternative:
    crediting a partner appearance as proof a drug was checked, and reporting an unchecked pair as
    clean.

Tier 2 — ``data/manual/atc_stem_rules.csv`` (inference, and *only* toward not-covered)
    WHO INN stems: ``-statin`` is C, ``-cillin`` is J, ``-azepam`` is N. Every group these rules can
    produce is one DDInter does not cover, so a tier-2 assignment can only ever move a molecule from
    "unknown, therefore not checked" to "known to be outside coverage, therefore not checked". The
    outcome is identical; only the explanation the user reads improves. A stem rule can never make a
    pair look checked, which is why inference is admissible in this tier at all.

Deliberately *not* a tier — the ``provenance`` column on the interaction table
    ``interactions.provenance`` preserves the source filenames, and reading a molecule's group off
    them is the obvious shortcut. It is also wrong in the one direction that matters: it cannot tell
    an anchor from a partner, so it reports atorvastatin as covered group L on the strength of rows
    anchored by something else. It is left unused on purpose.

Anything still unassigned is left out of ``molecule_atc_groups`` entirely, and ``AtcCoverage``
treats an absent molecule as not covered. The fail-closed default is preserved end to end: this
script can only ever *add* provable coverage, never assume it.

Usage::

    python scripts/build_coverage_manifest.py
    python scripts/build_coverage_manifest.py --processed-dir data/demo
    python scripts/build_coverage_manifest.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from medsafe.config import get_settings  # noqa: E402
from medsafe.resolution.normalize import normalize_key  # noqa: E402
from medsafe.safety.interactions import (  # noqa: E402
    DDINTER_COVERED_ATC_GROUPS,
    DDINTER_UNCOVERED_ATC_GROUPS,
)

logger = logging.getLogger("medsafe.build_coverage_manifest")

# ``ddinter_downloads_code_B.csv`` -> "B". The letter is the ATC first level of the source extract.
_PROVENANCE_CODE = re.compile(r"ddinter_downloads_code_([A-Za-z])\.csv")

TIER_ANCHOR = "ddinter_anchor"
TIER_STEM = "atc_stem_rule"

# Ordered most to least authoritative. A molecule keeps the group from the first tier that has one.
TIER_ORDER: tuple[str, ...] = (TIER_ANCHOR, TIER_STEM)

# Minimum ``anchor_concentration`` at which a drug counts as an anchor of its top file rather than
# a partner appearing in someone else's row. Set at the top of the range on purpose: this is the
# single value that decides whether a pair may be reported as checked.
ANCHOR_CONCENTRATION_FLOOR = 1.0

csv.field_size_limit(10_000_000)


# --- readers -----------------------------------------------------------------------------------


def _resolve(directory: Path, *stems: str) -> Path | None:
    """First existing ``<stem>.csv`` in ``directory``, mirroring the loader's stage resolution."""
    for stem in stems:
        candidate = directory / f"{stem}.csv"
        if candidate.is_file():
            return candidate
    return None


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [
            {(k or "").strip(): (v or "") for k, v in row.items()}
            for row in csv.DictReader(handle)
        ]


def read_molecules(processed_dir: Path) -> dict[str, str]:
    """``{molecule_id: inn_name}`` from the molecule catalogue."""
    path = _resolve(processed_dir, "molecules", "molecule_catalog")
    if path is None:
        raise SystemExit(
            f"No molecule catalogue in {processed_dir} "
            "(expected molecules.csv or molecule_catalog.csv)"
        )
    return {
        row["molecule_id"].strip(): row["inn_name"].strip()
        for row in _rows(path)
        if row.get("molecule_id") and row.get("inn_name")
    }


def groups_from_anchor_profile(
    path: Path, name_to_id: dict[str, str], *, floor: float = ANCHOR_CONCENTRATION_FLOOR
) -> tuple[dict[str, str], int]:
    """Tier 1. ``({molecule_id: group}, n_rejected)`` for drugs that anchor their top file.

    Rows below ``floor`` are dropped rather than downgraded. A partial anchor tells us the drug was
    *seen* in a covered extract, which is not the same claim as the drug being in that ATC group,
    and only the second licenses reporting a pair as checked.
    """
    if not path.is_file():
        logger.warning("No anchor profile at %s — no molecule can be reported as covered", path)
        return {}, 0

    groups: dict[str, str] = {}
    rejected = 0
    for row in _rows(path):
        group = (row.get("top_file") or "").strip().upper()[:1]
        molecule_id = name_to_id.get(normalize_key(row.get("drug") or ""))
        if not molecule_id or not group.isalpha():
            continue
        try:
            concentration = float(row.get("anchor_concentration") or 0.0)
        except ValueError:
            concentration = 0.0
        if concentration < floor:
            rejected += 1
            continue
        groups.setdefault(molecule_id, group)
    return groups, rejected


def groups_from_stem_rules(path: Path, molecules: dict[str, str]) -> dict[str, str]:
    """Tier 3. ``{molecule_id: group}`` by WHO INN stem.

    Rejects any rule that would assign a *covered* group. The tier's safety argument is that it can
    only ever produce "not checked", and a rule granting coverage by inference would break it.
    """
    if not path.is_file():
        logger.warning("No stem rules at %s — tier 3 evidence unavailable", path)
        return {}

    rules: list[tuple[re.Pattern[str], str]] = []
    for row in _rows(path):
        pattern = (row.get("stem_pattern") or "").strip()
        group = (row.get("atc_group") or "").strip().upper()
        if not pattern or not group:
            continue
        if group in DDINTER_COVERED_ATC_GROUPS:
            logger.error(
                "Stem rule %r assigns covered group %s; refusing to infer coverage from a stem",
                pattern,
                group,
            )
            continue
        rules.append((re.compile(pattern, re.IGNORECASE), group))

    groups: dict[str, str] = {}
    for molecule_id, inn_name in molecules.items():
        for pattern, group in rules:
            if pattern.search(inn_name):
                groups[molecule_id] = group
                break
    return groups


# --- assembly ----------------------------------------------------------------------------------


def build_manifest(
    processed_dir: Path,
    manual_dir: Path,
    *,
    source_label: str = "DDInter bulk (reconstructed from repository artifacts)",
) -> dict[str, Any]:
    """Assemble the manifest, recording which tier supplied each molecule's group."""
    molecules = read_molecules(processed_dir)
    name_to_id = {normalize_key(name): mid for mid, name in molecules.items()}

    anchored, partial_anchors = groups_from_anchor_profile(
        manual_dir / "ddinter_anchor_profile.csv", name_to_id
    )
    by_tier: dict[str, dict[str, str]] = {
        TIER_ANCHOR: anchored,
        TIER_STEM: groups_from_stem_rules(manual_dir / "atc_stem_rules.csv", molecules),
    }

    molecule_groups: dict[str, str] = {}
    evidence: dict[str, str] = {}
    for tier in TIER_ORDER:
        for molecule_id, group in by_tier[tier].items():
            if molecule_id in molecule_groups or molecule_id not in molecules:
                continue
            molecule_groups[molecule_id] = group
            evidence[molecule_id] = tier

    # A covered group reached by inference would silently turn "not checked" into "clear". The tier
    # rules forbid it; this asserts it on the assembled result rather than trusting them.
    leaked = sorted(
        mid
        for mid, group in molecule_groups.items()
        if group in DDINTER_COVERED_ATC_GROUPS and evidence[mid] != TIER_ANCHOR
    )
    if leaked:
        raise SystemExit(
            f"{len(leaked)} molecule(s) were granted a covered ATC group by an inference tier "
            f"(first: {leaked[0]}). Coverage may only come from direct anchor evidence."
        )

    covered = sum(1 for g in molecule_groups.values() if g in DDINTER_COVERED_ATC_GROUPS)
    tier_counts = Counter(evidence.values())

    return {
        "source": source_label,
        "covered_atc_groups": sorted(DDINTER_COVERED_ATC_GROUPS),
        "uncovered_atc_groups": sorted(DDINTER_UNCOVERED_ATC_GROUPS),
        "molecule_atc_groups": dict(sorted(molecule_groups.items())),
        "group_evidence": dict(sorted(evidence.items())),
        "stats": {
            "molecules_total": len(molecules),
            "molecules_with_group": len(molecule_groups),
            "molecules_covered": covered,
            "molecules_not_covered": len(molecule_groups) - covered,
            "molecules_unknown": len(molecules) - len(molecule_groups),
            "partial_anchors_rejected": partial_anchors,
            "by_evidence_tier": {tier: tier_counts.get(tier, 0) for tier in TIER_ORDER},
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    settings = get_settings()
    parser.add_argument("--processed-dir", type=Path, default=settings.data_processed_dir)
    parser.add_argument("--manual-dir", type=Path, default=settings.data_manual_dir)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Defaults to <processed-dir>/ddinter_coverage.json",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report without writing")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s"
    )

    processed_dir = args.processed_dir
    if not processed_dir.is_dir():
        parser.error(f"--processed-dir {processed_dir} does not exist")

    manifest = build_manifest(processed_dir, args.manual_dir)
    stats = manifest["stats"]

    print("coverage manifest")
    print(f"  molecules in catalogue   {stats['molecules_total']:>6}")
    print(f"  with an ATC group        {stats['molecules_with_group']:>6}")
    print(
        f"    within DDInter cover   {stats['molecules_covered']:>6}"
        "  -> pairs can report CHECKED"
    )
    print(
        f"    outside DDInter cover  {stats['molecules_not_covered']:>6}"
        "  -> pairs report not checked"
    )
    print(
        f"  no group derivable       {stats['molecules_unknown']:>6}"
        "  -> pairs report not checked"
    )
    print(
        f"  partial anchors rejected {stats['partial_anchors_rejected']:>6}"
        "  -> not provably covered"
    )
    print("  evidence tiers")
    for tier, count in stats["by_evidence_tier"].items():
        print(f"    {tier:<24} {count:>6}")

    if args.dry_run:
        print("\ndry run — nothing written")
        return 0

    output = args.output or (processed_dir / "ddinter_coverage.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"\nwrote {output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
