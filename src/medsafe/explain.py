"""Plain-English rendering of engine states.

Every state this engine can be in already has a precise name — ``not_checked``, ``needs_review``,
``out_of_scope_fdc``, ATC group ``C``. Those names are correct and they are the right vocabulary for
the API contract. They are also unreadable to the person the answer is *for*, and the failure mode
is not that they find it confusing. It is that they guess, and the guesses run in the dangerous
direction: "not checked" gets read as "checked, fine", and "no match" gets read as "this medicine is
not safe" rather than "we could not read the name".

So the translation lives here rather than in the web console, for three reasons:

* **The wording is a safety control, not presentation.** The whole engine is built so that
  "unchecked" cannot be mistaken for "clear". If the last step before a human reads it happens in a
  React component, that guarantee ends at the API boundary and every client re-implements it,
  differently, from the enum names.
* **It is testable.** ``tests/test_explain.py`` asserts that no unchecked state renders with
  reassuring language. That test cannot exist if the sentence is a JSX fragment.
* **Other clients get it too.** A pharmacist's terminal, an SMS gateway or a screen reader all need
  the same sentence, and none of them can run the console's markup.

Three fields, always the same shape
-----------------------------------
``headline``  What happened, in one short line. Never hedged, never jargon.
``detail``    The reasoning, in one or two sentences, in the second person.
``action``    What the reader should actually *do*. ``None`` when there is nothing to do.

Two rules govern all of them, and the tests enforce both:

1. **An unchecked or unidentified state never gets reassuring language.** No "fine", "safe", "no
   problem", "all clear". The absence of a finding is reported as an absence of a *look*.
2. **A known interaction never gets softened.** No "might", "possibly", "may be worth mentioning"
   in the headline of a real finding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from medsafe.pricing.substitution import SubstitutionStatus
from medsafe.resolution.matcher import ResolutionStatus
from medsafe.safety.interactions import PairStatus

__all__ = [
    "Explanation",
    "ATC_GROUP_LABELS",
    "SEVERITY_LABELS",
    "explain_resolution",
    "explain_pair",
    "explain_substitution",
    "explain_coverage",
    "readable_provenance",
    "severity_label",
]


@dataclass(frozen=True, slots=True)
class Explanation:
    """One state, rendered for a reader with no clinical training."""

    headline: str
    detail: str
    action: str | None = None


# ATC first levels, named the way a patient would describe the shelf they came from rather than by
# the WHO title. "Cardiovascular system" is accurate and means nothing to most readers; "heart and
# blood-pressure medicines" is the same set, recognisable.
ATC_GROUP_LABELS: dict[str, str] = {
    "A": "stomach, gut and diabetes medicines",
    "B": "blood and blood-thinning medicines",
    "C": "heart and blood-pressure medicines",
    "D": "skin medicines",
    "G": "urinary and reproductive-health medicines",
    "H": "hormone medicines, including steroids and thyroid",
    "J": "antibiotics and other infection medicines",
    "L": "cancer and immune-system medicines",
    "M": "bone, joint and painkiller medicines",
    "N": ("brain and nervous-system medicines, including painkillers and antidepressants"),
    "P": "antiparasitic medicines",
    "R": "lung and breathing medicines, including allergy tablets",
    "S": "eye and ear medicines",
    "V": "various other medicines",
}

SEVERITY_LABELS: dict[str, tuple[str, str]] = {
    "major": (
        "Serious — talk to a doctor or pharmacist before taking these together",
        "These two are known to cause a serious problem when taken together.",
    ),
    "moderate": (
        "Worth checking with a doctor or pharmacist",
        "These two are known to affect each other. It is often still fine to take them, but "
        "someone qualified should decide that, not this page.",
    ),
    "minor": (
        "Known to interact, usually in a small way",
        "These two are recorded as affecting each other slightly. It is usually manageable, and "
        "worth mentioning at your next appointment.",
    ),
    "unknown": (
        "Known to interact — the strength is not recorded",
        "Our source lists these two as interacting but does not say how strongly. Treat that as a "
        "reason to ask, not a reason to assume it is small.",
    ),
}

# ``ddinter_downloads_code_B.csv`` is a filename from somebody else's server. It is real provenance
# and should not be hidden, but on its own it tells a reader nothing about who checked what.
_PROVENANCE_CODE = re.compile(r"ddinter_downloads_code_([A-Za-z])\.csv")


def severity_label(severity: str | None) -> str:
    """Bucket a free-text DDInter severity into the four keys of :data:`SEVERITY_LABELS`."""
    value = (severity or "").strip().lower()
    if "major" in value or "severe" in value:
        return "major"
    if "moderate" in value:
        return "moderate"
    if "minor" in value:
        return "minor"
    return "unknown"


def readable_provenance(provenance: str | None) -> str | None:
    """Turn source filenames into a sentence naming who published the data and which list it was in.

    Returns ``None`` for empty provenance rather than a placeholder: an invented source line is
    worse than no source line.
    """
    if not provenance or not provenance.strip():
        return None
    groups = sorted({code.upper() for code in _PROVENANCE_CODE.findall(provenance)})
    if not groups:
        return f"Source: {provenance.strip()}"
    named = [ATC_GROUP_LABELS.get(group, f"group {group}") for group in groups]
    if len(named) == 1:
        return f"From DDInter, an open drug-interaction database — its list of {named[0]}."
    joined = ", ".join(named[:-1]) + f" and {named[-1]}"
    return f"From DDInter, an open drug-interaction database — its lists of {joined}."


def _group_phrase(group: str | None) -> str:
    """A readable name for an ATC group, falling back to the bare letter if it is unfamiliar."""
    if not group:
        return "medicines of this kind"
    return ATC_GROUP_LABELS.get(group.upper(), f"medicines in group {group.upper()}")


# --- resolution ---------------------------------------------------------------------------------


def explain_resolution(
    status: ResolutionStatus | str,
    *,
    query: str,
    inn_name: str | None = None,
    alias_raw_string: str | None = None,
    component_names: tuple[str, ...] = (),
    candidate_names: tuple[str, ...] = (),
    read_as: str | None = None,
) -> Explanation:
    """Explain what the engine made of a drug name the user typed."""
    status = ResolutionStatus(status)

    if status is ResolutionStatus.RESOLVED:
        name = inn_name or query
        if alias_raw_string and alias_raw_string.strip().lower() != name.lower():
            detail = (
                f"“{query}” is a brand name. The active ingredient in it is {name}, which is what "
                "the rest of this page is about — the ingredient is what determines both the price "
                "of an equivalent and how it interacts with anything else you take."
            )
        else:
            detail = (
                f"“{query}” was matched to the ingredient {name}. Any medicine containing the same "
                "ingredient at the same strength does the same job."
            )
        return Explanation(
            headline=f"This is {name}",
            detail=detail,
            action=None,
        )

    if status is ResolutionStatus.COMBINATION:
        names = list(component_names)
        joined = ", ".join(names[:-1]) + f" and {names[-1]}" if len(names) > 1 else "".join(names)
        return Explanation(
            headline=f"This pack contains {len(names)} ingredients: {joined}",
            detail=(
                "Combination packs put more than one medicine in a single tablet. Every ingredient "
                "is included in the interaction check below. We do not suggest a cheaper swap for "
                "these, because a generic containing only one of the ingredients is not the same "
                "medicine, even though the name looks similar."
            ),
            action=(
                "If you want to compare prices, ask your pharmacist about each ingredient "
                "separately."
            ),
        )

    if status is ResolutionStatus.NEEDS_REVIEW:
        suggestions = ", ".join(candidate_names[:3])
        return Explanation(
            headline=f"We are not sure what “{query}” is",
            detail=(
                f"It looks close to {suggestions}, but not close enough for us to be certain, and "
                "medicine names that look alike are often completely different drugs. We will not "
                "guess between them."
            ),
            action=(
                "Check the spelling against the pack, or pick the right one with your pharmacist."
            ),
        )

    read_note = f" We read it as “{read_as}”." if read_as and read_as != query.lower() else ""
    return Explanation(
        headline=f"We could not identify “{query}”",
        detail=(
            "This does not mean the medicine is unsafe or unavailable — only that this name is not "
            f"in our catalogue, so we have nothing to tell you about it.{read_note}"
        ),
        action=(
            "Try the ingredient name printed in small type on the pack, usually under the brand "
            "name, or check the spelling."
        ),
    )


# --- interaction pairs --------------------------------------------------------------------------


def explain_pair(
    status: PairStatus | str,
    *,
    left: str,
    right: str,
    severity: str | None = None,
    mechanism: str | None = None,
    left_resolved: bool = True,
    right_resolved: bool = True,
    left_group: str | None = None,
    right_group: str | None = None,
    coverage_missing: bool = False,
) -> Explanation:
    """Explain one pair of medicines checked against each other."""
    status = PairStatus(status)

    if status is PairStatus.INTERACTION:
        headline, detail = SEVERITY_LABELS[severity_label(severity)]
        if mechanism:
            detail = f"{detail} Recorded effect: {mechanism.strip().rstrip('.')}."
        return Explanation(
            headline=headline,
            detail=detail,
            action=(
                f"Do not stop either medicine on your own. Tell your doctor or pharmacist that "
                f"you take both {left} and {right}."
            ),
        )

    if status is PairStatus.NO_KNOWN_INTERACTION:
        return Explanation(
            headline="Checked — nothing known between these two",
            detail=(
                "Both of these are in the part of our source we can search, and it lists no "
                "interaction between them. That is a real check, not a blank result. It still only "
                "covers what that source records."
            ),
            action=None,
        )

    # not_checked — the state the entire codebase exists to keep distinct.
    unnamed = [name for name, ok in ((left, left_resolved), (right, right_resolved)) if not ok]
    if unnamed:
        which = " and ".join(f"“{name}”" for name in unnamed)
        return Explanation(
            headline="Not checked — we could not identify one of these",
            detail=(
                f"We do not know what {which} is, so we could not look for anything between them. "
                "No result here means no search happened, and it is not a verdict on the "
                "combination."
            ),
            action="Add the ingredient name from the pack and check again.",
        )

    if coverage_missing:
        return Explanation(
            headline="Not checked — our interaction data is not loaded",
            detail=(
                "The file listing which medicines we can check is missing on this server, so we "
                "cannot confirm any pair was searched. This is a fault on our side, not something "
                "about your medicines."
            ),
            action="Nothing you can do here. Ask a pharmacist to check this pair.",
        )

    outside = [
        (name, group)
        for name, group in ((left, left_group), (right, right_group))
        if group and group.upper() not in {"A", "B", "D", "H", "L", "P", "R", "V"}
    ]
    if outside:
        name, group = outside[0]
        return Explanation(
            headline="Not checked — this kind of medicine is outside our data",
            detail=(
                f"Our interaction list does not include {_group_phrase(group)}, and {name} is one "
                "of those. So we did not search this pair at all. An empty result here tells you "
                "nothing about whether they interact."
            ),
            action=f"Ask a pharmacist specifically about {left} together with {right}.",
        )

    return Explanation(
        headline="Not checked",
        detail=(
            "We could not confirm that this pair is inside the part of our source we can search, "
            "so we did not report it either way. Treat this as unknown, not as clear."
        ),
        action=f"Ask a pharmacist about {left} together with {right}.",
    )


# --- coverage summary ---------------------------------------------------------------------------


def explain_coverage(
    *,
    pairs_total: int,
    interactions_found: int,
    checked_clear: int,
    not_checked: int,
    coverage_missing: bool = False,
) -> Explanation:
    """Explain the check as a whole — the first thing a reader sees, so it must not oversell."""
    if pairs_total == 0:
        return Explanation(
            headline="Nothing to compare yet",
            detail="Add at least two medicines and we will check each combination of them.",
            action="Add another medicine above.",
        )

    if coverage_missing:
        return Explanation(
            headline="We could not check any of these combinations",
            detail=(
                "The data file that says which medicines we are able to check is missing on this "
                "server. Until it is restored, nothing on this page can tell you a combination is "
                "clear."
            ),
            action="Ask a pharmacist to review the full list.",
        )

    one = pairs_total == 1
    pairs_word = "combination" if one else "combinations"

    if interactions_found:
        found = (
            "1 known interaction"
            if interactions_found == 1
            else f"{interactions_found} known interactions"
        )
        detail = f"We looked at {pairs_total} {pairs_word} and found {found}."
        if not_checked:
            detail += (
                f" {not_checked} of them could not be checked at all, so there may be more that "
                "we did not see."
            )
        return Explanation(
            headline=f"Found {found} — read these with a pharmacist",
            detail=detail,
            action="Take this list to your doctor or pharmacist before changing anything.",
        )

    if not_checked and checked_clear:
        return Explanation(
            headline=f"{checked_clear} checked and clear, {not_checked} we could not check",
            detail=(
                f"Of {pairs_total} {pairs_word}, we searched {checked_clear} and found nothing "
                f"recorded between them. The other {not_checked} fall outside the data we have, so "
                "they were not searched. This page cannot tell you the whole list has been cleared."
            ),
            action="Ask a pharmacist about the combinations marked as not checked.",
        )

    if not_checked:
        return Explanation(
            headline=(
                "We could not check this combination"
                if one
                else "We could not check these combinations"
            ),
            detail=(
                "This pair falls outside the data we have, so it was not searched at all. "
                "That is not a clean result — it is no result."
                if one
                else f"All {pairs_total} {pairs_word} fall outside the data we have, so none of "
                "them were searched. That is not a clean result — it is no result."
            ),
            action="Ask a pharmacist to review these together.",
        )

    return Explanation(
        headline=(
            "1 combination checked, nothing known between them"
            if one
            else f"All {pairs_total} {pairs_word} checked, nothing known between them"
        ),
        detail=(
            "We searched every combination on this list and our source records no interaction "
            "between any of them. That covers known, recorded interactions only — it is not a "
            "guarantee, and it does not account for your dose, your other conditions, or anything "
            "you take that is not on this list."
        ),
        action="Keep this list up to date and show it at appointments.",
    )


# --- substitution -------------------------------------------------------------------------------


def explain_substitution(
    status: SubstitutionStatus | str,
    *,
    inn_name: str,
    substitute_count: int = 0,
    best_savings_pct: float | None = None,
    reference_price: float | None = None,
    best_price: float | None = None,
) -> Explanation:
    """Explain the substitute search — including, importantly, when there is nothing to report."""
    status = SubstitutionStatus(status)

    if status is SubstitutionStatus.OUT_OF_SCOPE_FDC:
        return Explanation(
            headline="We do not suggest swaps for combination medicines",
            detail=(
                "This product contains more than one active ingredient. A cheaper pack "
                "containing only one of them is a different medicine, even where the name is "
                "nearly identical, so comparing them on price would be misleading."
            ),
            action="Ask your pharmacist whether the ingredients are available separately.",
        )

    if status is SubstitutionStatus.NO_PRODUCTS:
        return Explanation(
            headline="No products in our catalogue contain this ingredient",
            detail=(
                f"We recognised {inn_name}, but our price catalogue has nothing containing it. Our "
                "catalogue is mostly Janaushadhi generics and does not cover every medicine sold."
            ),
            action="Your pharmacist can tell you whether a generic exists.",
        )

    if status is SubstitutionStatus.NO_SUBSTITUTES:
        return Explanation(
            headline="Nothing we could safely call equivalent",
            detail=(
                f"Our catalogue has products containing {inn_name}, but none matched closely "
                "enough on strength and form to be treated as a like-for-like swap. We would "
                "rather show you nothing than something that is not the same medicine."
            ),
            action="Ask your pharmacist for a generic equivalent.",
        )

    if substitute_count == 0:
        return Explanation(
            headline="No cheaper equivalent found",
            detail=(
                f"We found equivalents of {inn_name} but none cost less than the reference "
                "pack."
            ),
            action=None,
        )

    saving = ""
    if best_savings_pct is not None:
        saving = f" The cheapest is about {round(best_savings_pct)}% less"
        if reference_price is not None and best_price is not None:
            saving += f" — ₹{best_price:,.2f} against ₹{reference_price:,.2f}"
        saving += "."

    plural = "option" if substitute_count == 1 else "options"
    return Explanation(
        headline=f"{substitute_count} cheaper {plural} with the same ingredient",
        detail=(
            f"These all contain {inn_name} at a comparable strength and in a comparable form, so "
            f"they do the same job as the medicine you searched.{saving} Prices are catalogue "
            "prices and what your pharmacy actually charges may differ."
        ),
        action="Show this to your pharmacist — they can confirm and order it in.",
    )
