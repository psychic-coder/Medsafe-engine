"""``/suggest`` — type-ahead over the names the engine actually knows.

Most "not identified" results are not the engine failing to recognise a drug. They are a person
typing a name the catalogue does not carry, or carries under a different spelling, and then having
no way to find out which. The console can offer candidates after the fact, but by then the user has
already been told no, and the natural reading of that is "something is wrong with my medicine"
rather than "try a different word".

Suggesting while they type removes the guess entirely: they pick a name the engine is guaranteed to
resolve, so the failure never happens. That makes this endpoint the largest single usability lever
in the project, and it is why it exists.

Why this is not the fuzzy matcher
---------------------------------
It looks like the same problem and it is not. The matcher decides *whether a string is a drug*, and
the whole resolution policy exists to stop it guessing: a fuzzy hit is never an identification, and
the confusable-pair blocklist suppresses look-alikes so a machine never picks between hydralazine
and hydroxyzine.

Suggestion is prefix search shown to a person who then chooses, with the pack in their hand. The
decision-maker is different, and so is the right treatment of a confusable pair.

Confusable names are flagged, not withheld
------------------------------------------
The matcher's rule is to drop both members of a blocklisted pair, and that rule is free there: a
suppressed candidate simply goes unoffered, and the drug can still resolve by exact match. Applying
it here is not free. Metoprolol, methotrexate and dexamethasone are all blocklisted against some
near neighbour, so a blanket suppression means typing "met" returns a list with all three missing —
the user cannot find their own medicine, concludes the tool does not know it, and gets nothing.

So each suggestion carries the names it is confusable with, and the console shows that warning on
the row. This gives the reader *more* information at exactly the moment it matters, rather than
less: they are holding the box, they can check the spelling against it, and they are the only party
in the system able to do so. Hiding the row removes the one thing that would have made them look
twice.

The blocklist is still doing its job — it is what supplies the warning. It is applied as a caution
to a human, not as a veto on a machine.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from medsafe.api.dependencies import CombinationsDep, MatcherDep
from medsafe.api.schemas import ErrorResponse, SuggestionOut, SuggestResponse
from medsafe.resolution.normalize import normalize_key

router = APIRouter(tags=["suggest"])

MAX_LIMIT = 25


@router.get(
    "/suggest",
    response_model=SuggestResponse,
    responses={422: {"model": ErrorResponse, "description": "Invalid input"}},
    summary="Type-ahead over known drug and brand names",
)
def suggest(
    matcher: MatcherDep,
    combinations: CombinationsDep,
    q: str = Query(min_length=1, max_length=100, description="Partial name as typed"),
    limit: int = Query(default=8, ge=1, le=MAX_LIMIT),
) -> SuggestResponse:
    """Names starting with, then containing, ``q``.

    Ranked so a prefix match always outranks a substring match, and shorter names outrank longer
    ones at equal rank — typing "met" should offer metformin before metoclopramide, and neither
    before something that merely contains "met" in the middle.
    """
    key = normalize_key(q)
    if not key:
        return SuggestResponse(query=q, suggestions=())

    seen: set[str] = set()
    scored: list[tuple[int, int, str, SuggestionOut]] = []

    def offer(label: str, kind: str, ingredient: str | None, molecule_id: str | None) -> None:
        candidate = label.strip()
        if not candidate:
            return
        lowered = candidate.casefold()
        if lowered in seen:
            return
        haystack = normalize_key(candidate)
        if haystack.startswith(key):
            rank = 0
        elif key in haystack:
            rank = 1
        else:
            return
        seen.add(lowered)
        scored.append(
            (
                rank,
                len(candidate),
                lowered,
                SuggestionOut(
                    label=candidate,
                    kind=kind,
                    ingredient=ingredient,
                    molecule_id=molecule_id,
                ),
            )
        )

    for entry in matcher._vocab():
        inn_name = str(entry.get("inn_name") or "")
        molecule_id = str(entry.get("molecule_id") or "")
        offer(inn_name, "ingredient", None, molecule_id)
        for alias in entry.get("alias_strings") or []:
            if alias:
                offer(str(alias), "other_name", inn_name, molecule_id)

    for combination in combinations:
        offer(
            combination.brand_raw,
            "combination",
            " + ".join(component.inn_name for component in combination.components),
            None,
        )

    scored.sort(key=lambda item: (item[0], item[1], item[2]))
    ordered = [item[3] for item in scored]

    # Annotate each suggestion with the names it is easy to confuse, drawn from the same blocklist
    # the matcher uses as a veto. Here it is a caution: the reader has the pack and can check.
    labels = [suggestion.label for suggestion in ordered]
    flagged: list[SuggestionOut] = []
    for suggestion in ordered:
        confusable = tuple(
            sorted(
                other
                for other in labels
                if other != suggestion.label
                and matcher.blocklist.contains(suggestion.label, other)
            )
        )
        flagged.append(
            suggestion.model_copy(update={"confusable_with": confusable}) if confusable
            else suggestion
        )

    suggestions = tuple(flagged[:limit])
    any_confusable = any(s.confusable_with for s in suggestions)

    return SuggestResponse(
        query=q,
        suggestions=suggestions,
        note=(
            "Some of these names look alike but are different medicines. Check the spelling "
            "against the pack before choosing."
        )
        if any_confusable
        else None,
    )
