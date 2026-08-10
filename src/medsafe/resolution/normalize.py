"""String normalization — the canonical comparison key for drug names.

Deterministic, lossless-by-design preprocessing applied identically to every vocabulary (PMBJP,
DDInter, manual, rxnorm_dump) before any comparison: case folding, unicode normalization, whitespace
and punctuation handling, salt/ester and hydrate suffix treatment, dosage-form and strength token
stripping into separate fields, and British/American spelling variants. The output populates
``Alias.normalized_string`` and is what "exact match (post-normalization)" in the locked policy
means — so any change here changes what auto-accepts, and must be re-run against the golden set.
Strength and form extracted here feed ``Product.strength_raw`` / ``Product.form`` and the
``CONTAINS {strength, unit}`` edge.

"Lossless-by-design" means nothing is *discarded*: strength, form and salt are moved onto their own
fields of :class:`NormalizedName`, never silently dropped. Only the comparison key is reduced.

Two deliberate boundaries:

* **Orthographic variants only.** ``sulphate``/``sulfate`` and ``cephalexin``/``cefalexin`` are the
  same word spelled two ways, so they are folded here. ``paracetamol``/``acetaminophen`` and
  ``adrenaline``/``epinephrine`` are different words for the same molecule — those are
  ``Alias``/bridge-table entries, not normalization rules. Folding synonyms here would hide a
  curation decision inside a string function.
* **Salt stripping never empties the key.** ``sodium chloride`` is a drug, not a salt of
  nothing, so
  if every token is a salt token the tokens are kept. Salt-stripping is INN-level by intent
  (``betamethasone valerate`` and ``betamethasone dipropionate`` share a ``Molecule``); the salt is
  preserved on ``NormalizedName.salts``, and the distinguishing form and strength stay on the
  ``Product``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

__all__ = [
    "NormalizedName",
    "normalize",
    "normalize_key",
    "canonical_strength",
    "SALT_TOKENS",
    "FORM_TOKENS",
    "STRENGTH_UNITS",
]

# --- Vocabularies ------------------------------------------------------------------------------

# Salt, ester and hydrate tokens. Removed from the comparison key and preserved on `.salts`.
SALT_TOKENS: frozenset[str] = frozenset(
    {
        "hcl",
        "hydrochloride",
        "monohydrochloride",
        "dihydrochloride",
        "hydrobromide",
        "hydrate",
        "monohydrate",
        "dihydrate",
        "trihydrate",
        "anhydrous",
        "sodium",
        "disodium",
        "trisodium",
        "potassium",
        "calcium",
        "magnesium",
        "aluminium",
        "zinc",
        "acetate",
        "besilate",
        "besylate",
        "bicarbonate",
        "bitartrate",
        "bromide",
        "carbonate",
        "chloride",
        "citrate",
        "dipropionate",
        "fumarate",
        "furoate",
        "gluconate",
        "iodide",
        "lactate",
        "maleate",
        "malate",
        "mesilate",
        "mesylate",
        "nitrate",
        "oxalate",
        "palmitate",
        "phosphate",
        "propionate",
        "stearate",
        "succinate",
        "sulfate",
        "tartrate",
        "tosylate",
        "valerate",
        "xinafoate",
    }
)

# Dosage-form tokens -> canonical form label. Split out of the name onto `.form`.
FORM_TOKENS: dict[str, str] = {
    "tab": "tablet",
    "tabs": "tablet",
    "tablet": "tablet",
    "tablets": "tablet",
    "cap": "capsule",
    "caps": "capsule",
    "capsule": "capsule",
    "capsules": "capsule",
    "syp": "syrup",
    "syrup": "syrup",
    "susp": "suspension",
    "suspension": "suspension",
    "inj": "injection",
    "injection": "injection",
    "vial": "injection",
    "ampoule": "injection",
    "ampule": "injection",
    "amp": "injection",
    "cream": "cream",
    "ointment": "ointment",
    "gel": "gel",
    "lotion": "lotion",
    "drop": "drops",
    "drops": "drops",
    "solution": "solution",
    "soln": "solution",
    "powder": "powder",
    "sachet": "sachet",
    "granules": "granules",
    "spray": "spray",
    "inhaler": "inhaler",
    "rotacaps": "inhaler",
    "respules": "respules",
    "suppository": "suppository",
    "patch": "patch",
    "infusion": "infusion",
}

# Strength units -> canonical spelling.
STRENGTH_UNITS: dict[str, str] = {
    "mg": "mg",
    "milligram": "mg",
    "milligrams": "mg",
    "g": "g",
    "gm": "g",
    "gram": "g",
    "grams": "g",
    "kg": "kg",
    "mcg": "mcg",
    "ug": "mcg",
    # NFKC folds MICRO SIGN (U+00B5) to GREEK SMALL LETTER MU (U+03BC), so both must be listed:
    # the first is what a source file contains, the second is what survives normalization.
    "\u00b5g": "mcg",
    "\u03bcg": "mcg",
    "microgram": "mcg",
    "micrograms": "mcg",
    "ml": "ml",
    "l": "l",
    "iu": "iu",
    "u": "iu",
    "unit": "iu",
    "units": "iu",
    "%": "%",
    "w/v": "%",
    "w/w": "%",
}

# Packaging / presentation noise carrying no identity information.
_NOISE_TOKENS: frozenset[str] = frozenset(
    {
        "of",
        "each",
        "per",
        "strip",
        "strips",
        "pack",
        "packs",
        "packet",
        "bottle",
        "box",
        "tube",
        "and",
        "with",
        "ip",
        "bp",
        "usp",
        "combipack",
    }
)

# Whole-word orthographic variants that the regex rules below cannot express.
_WORD_VARIANTS: dict[str, str] = {
    "amoxycillin": "amoxicillin",
    "guaiphenesin": "guaifenesin",
    "beclomethasone": "beclometasone",
    "thyroxine": "levothyroxine",
}

# Orthographic rules, applied in order to each token. Each must be idempotent: applying the rules to
# an already-normalized token must be a no-op, or normalize(normalize(x)) != normalize(x).
_SPELLING_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sulph"), "sulf"),  # sulphate -> sulfate, sulphonamide -> sulfonamide
    (re.compile(r"^ceph"), "cef"),  # cephalexin -> cefalexin (BAN -> INN)
    (re.compile(r"haem"), "hem"),  # haemoglobin -> hemoglobin
    (re.compile(r"^oe"), "e"),  # oestradiol -> estradiol
    (re.compile(r"^ae"), "e"),  # aetiology -> etiology
)

# Numeric strength with a unit, e.g. "500mg", "500 MG", "0.5 g", "5%", "40 IU".
_STRENGTH_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>%|w/v|w/w|mcg|\u00b5g|\u03bcg|ug|mg|kg|gm|g|ml|l|iu"
    r"|units?|unit|milligrams?|micrograms?|grams?)(?![a-z])",
    re.IGNORECASE,
)

# Pack-count tokens: "10s", "10's", "x10", "1x10".
_PACK_RE = re.compile(r"^(?:\d+\s*x\s*\d+|\d+'?s|x\d+)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class NormalizedName:
    """The full result of normalization. ``normalized`` is the comparison key.

    Everything stripped out of the key is retained on a dedicated field, so a caller can rebuild the
    original meaning and no information is lost by normalizing.
    """

    raw: str
    normalized: str
    tokens: tuple[str, ...]
    salts: tuple[str, ...] = ()
    form: str | None = None
    strength_value: float | None = None
    strength_unit: str | None = None
    strength_raw: str | None = None

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.normalized


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _clean(value: str) -> str:
    """Unicode-fold, case-fold, and reduce punctuation to whitespace (decimal points survive)."""
    text = _strip_accents(value)
    text = unicodedata.normalize("NFKC", text).casefold()
    # Apostrophes are deleted rather than spaced, so a pack count like "10's" stays one token and
    # is caught by _PACK_RE instead of leaving a stray "s" in the key.
    text = re.sub(r"[\u2018\u2019']", "", text)
    # Protect decimal points, then turn every other separator into a space.
    text = re.sub(r"(?<!\d)\.(?!\d)", " ", text)
    text = re.sub(r"[+&/\\]", " ", text)
    text = re.sub(r"[^\w.%]+", " ", text, flags=re.UNICODE)
    text = text.replace("_", " ")
    return re.sub(r"\s+", " ", text).strip()


def _apply_spelling(token: str) -> str:
    token = _WORD_VARIANTS.get(token, token)
    for pattern, replacement in _SPELLING_RULES:
        token = pattern.sub(replacement, token)
    return _WORD_VARIANTS.get(token, token)


def canonical_strength(value: float | None, unit: str | None) -> tuple[float, str] | None:
    """Convert a strength to a comparable base unit (mg / ml / iu / %).

    Used by :mod:`medsafe.pricing.substitution` so ``0.5 g`` and ``500 mg`` compare equal instead of
    being treated as different strengths.
    """
    if value is None or unit is None:
        return None
    unit = STRENGTH_UNITS.get(unit.lower(), unit.lower())
    factors: dict[str, tuple[float, str]] = {
        "kg": (1_000_000.0, "mg"),
        "g": (1_000.0, "mg"),
        "mg": (1.0, "mg"),
        "mcg": (0.001, "mg"),
        "l": (1_000.0, "ml"),
        "ml": (1.0, "ml"),
        "iu": (1.0, "iu"),
        "%": (1.0, "%"),
    }
    if unit not in factors:
        return None
    factor, base_unit = factors[unit]
    return round(value * factor, 6), base_unit


def normalize(raw: str) -> NormalizedName:
    """Normalize a raw drug string into its comparison key plus the fields split out of it.

    Deterministic and side-effect free: the same input always produces the same output, in every
    vocabulary, and ``normalize(normalize(x).normalized).normalized == normalize(x).normalized``.
    """
    if raw is None:
        raw = ""
    original = str(raw)
    text = _clean(original)

    # 1. Strength — extracted before tokenization so "500mg" and "500 mg" behave identically.
    strength_matches = list(_STRENGTH_RE.finditer(text))
    strength_value: float | None = None
    strength_unit: str | None = None
    strength_raw: str | None = None
    if strength_matches:
        parts = []
        for match in strength_matches:
            unit = STRENGTH_UNITS.get(match.group("unit").lower(), match.group("unit").lower())
            parts.append(f"{match.group('value')}{unit}")
        strength_raw = "/".join(parts)
        first = strength_matches[0]
        strength_value = float(first.group("value"))
        strength_unit = STRENGTH_UNITS.get(
            first.group("unit").lower(), first.group("unit").lower()
        )
        text = _STRENGTH_RE.sub(" ", text)

    # 2. Tokenize and drop packaging noise, bare numbers, and leftover unit tokens.
    raw_tokens = [t for t in re.split(r"\s+", text) if t]
    tokens: list[str] = []
    for token in raw_tokens:
        if token in _NOISE_TOKENS or _PACK_RE.match(token):
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", token):
            continue
        if token in STRENGTH_UNITS:
            continue
        tokens.append(token)

    # 3. Dosage form.
    form: str | None = None
    kept: list[str] = []
    for token in tokens:
        mapped = FORM_TOKENS.get(token)
        if mapped is not None and form is None:
            form = mapped
            continue
        if mapped is not None:
            continue
        kept.append(token)
    tokens = kept

    # 4. Orthographic variants, applied before salt detection so "sulphate" is seen as a salt.
    tokens = [_apply_spelling(token) for token in tokens]

    # 5. Salts / esters / hydrates. Never strip them all: a name made only of salt tokens
    #    ("sodium chloride") is a drug in its own right.
    salts = tuple(token for token in tokens if token in SALT_TOKENS)
    base = [token for token in tokens if token not in SALT_TOKENS]
    if not base:
        base, salts = tokens, ()

    return NormalizedName(
        raw=original,
        normalized=" ".join(base),
        tokens=tuple(base),
        salts=salts,
        form=form,
        strength_value=strength_value,
        strength_unit=strength_unit,
        strength_raw=strength_raw,
    )


def normalize_key(raw: str) -> str:
    """Shorthand for ``normalize(raw).normalized`` — the exact-match comparison key."""
    return normalize(raw).normalized
