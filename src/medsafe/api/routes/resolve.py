"""``/resolve`` — drug string to canonical molecule, with generic substitutes.

Accepts a raw prescribed drug string, runs it through ``resolution.normalize`` and
``resolution.matcher``, and returns either an auto-accepted match (exact or alias-resolved, with the
match path stated) or an unresolved result carrying ranked fuzzy candidates marked as requiring
human review. On a resolved molecule, attaches substitutes from ``pricing.substitution`` with
``savings_pct`` and ``savings_abs``. Candidates are never presented as resolutions, and the response
never implies a fuzzy candidate was accepted.

# TODO: implement in Phase 5
"""
