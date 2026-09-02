/**
 * Wire types for the medsafe-engine API.
 *
 * These mirror `src/medsafe/api/schemas.py` field for field. Two of the distinctions below are
 * enforced by the backend's own type system and must survive the trip into the UI intact:
 *
 *   - `MatchOut.path` can only be "exact" or "alias". There is deliberately no value meaning
 *     "resolved by fuzzy", so a `Candidate` can never be typed as a `Match` here either.
 *   - `PairStatus` is three-valued. There is no boolean "interactions found" anywhere, because a
 *     boolean cannot represent "not checked", and a client reading one would show a coverage gap
 *     as a clean result.
 */

export type MoleculeCategory =
  | "small_molecule"
  | "biologic"
  | "herbal"
  | "vaccine";

export type ProductSource = "PMBJP" | "branded_csv";

export type AliasSource = "ddinter" | "pmbjp" | "manual" | "rxnorm_dump";

export type ResolutionStatus =
  | "resolved"
  | "combination"
  | "needs_review"
  | "unresolved";

export type SubstitutionStatus =
  | "ok"
  | "no_products"
  | "no_substitutes"
  | "out_of_scope_fdc";

export type PairStatus = "interaction" | "no_known_interaction" | "not_checked";

/**
 * The same state as the enum beside it, written for a reader with no clinical training.
 *
 * Rendered by the backend, not here. The distinction between "we checked and found nothing" and
 * "we did not check" is the property the whole engine is built to preserve, and it only reaches a
 * human if one place owns the sentence. `src/medsafe/explain.py` owns it, and `tests/test_explain.py`
 * asserts that no unchecked state ever reads as reassuring. This interface is the wire shape.
 */
export interface Plain {
  headline: string;
  detail: string;
  action: string | null;
}

export interface Molecule {
  molecule_id: string;
  inn_name: string;
  category: MoleculeCategory | null;
}

export interface Product {
  product_id: string;
  source: ProductSource;
  generic_name_raw: string;
  mrp: number;
  form: string | null;
  strength_raw: string | null;
  strength: number | null;
  unit: string | null;
  molecule_count: number;
  is_fdc: boolean;
}

export interface Normalization {
  normalized: string;
  salts: string[];
  form: string | null;
  strength_value: number | null;
  strength_unit: string | null;
  strength_raw: string | null;
  /** A bare number in the name with no unit — the `500` in "Glycomet 500". A hint, not a dose. */
  strength_hint: number | null;
}

/** An auto-accepted match. `path` cannot express a fuzzy result. */
export interface Match {
  path: "exact" | "alias";
  molecule: Molecule;
  normalized_query: string;
  alias_raw_string: string | null;
  alias_source: AliasSource | null;
  auto_accepted: true;
}

/** An unaccepted fuzzy suggestion for the human-review queue. Never a match. */
export interface Candidate {
  molecule: Molecule;
  score: number;
  matched_string: string;
  matched_on: "inn_name" | "alias";
  requires_human_review: true;
  auto_accepted: false;
}

/**
 * A pack name meaning two or more molecules. Structurally separate from `Match`, because a
 * combination is an identification that does NOT license substitution.
 */
export interface Combination {
  brand_raw: string;
  brand_key: string;
  components: Molecule[];
  substitutable: false;
}

/** A candidate withheld by the confusable-pair blocklist. Shown for audit only. */
export interface Suppressed {
  molecule_id: string;
  inn_name: string;
  score: number;
  reason: string;
  confusable_with: string;
}

export interface Substitute {
  product: Product;
  savings_abs: number;
  savings_pct: number;
}

export interface Substitution {
  status: SubstitutionStatus;
  molecule_id: string;
  reference: Product | null;
  substitutes: Substitute[];
  excluded: { product_id: string; reason: string }[];
  plain: Plain | null;
  notes: string[];
}

export interface ResolveResponse {
  query: string;
  normalized: Normalization;
  status: ResolutionStatus;
  match: Match | null;
  combination: Combination | null;
  candidates: Candidate[];
  suppressed: Suppressed[];
  substitution: Substitution | null;
  plain: Plain;
  notes: string[];
  disclaimer: string;
}

export interface DrugInput {
  query: string;
  resolved: boolean;
  molecule_id: string | null;
  inn_name: string | null;
  /** Set when this entry was expanded out of a multi-ingredient pack, naming that pack. */
  from_combination: string | null;
}

export interface InteractionPair {
  status: PairStatus;
  left: DrugInput;
  right: DrugInput;
  severity: string | null;
  mechanism: string | null;
  provenance: string | null;
  reason: string | null;
  /** Human-readable provenance. `provenance` keeps the raw source filenames. */
  source: string | null;
  plain: Plain;
  left_atc_group: string | null;
  right_atc_group: string | null;
}

export interface CheckSummary {
  pairs_total: number;
  interactions_found: number;
  checked_no_interaction: number;
  not_checked: number;
}

export interface CheckResponse {
  inputs: DrugInput[];
  resolutions: ResolveResponse[];
  pairs: InteractionPair[];
  summary: CheckSummary;
  /** False when any pair was not checked. False does NOT mean interactions exist. */
  coverage_complete: boolean;
  covered_atc_groups: string[];
  plain: Plain;
  notes: string[];
  disclaimer: string;
}

export interface Suggestion {
  label: string;
  kind: "ingredient" | "other_name" | "combination";
  ingredient: string | null;
  molecule_id: string | null;
  /** Look-alike names also on this list. A warning on the row, never a reason to hide it. */
  confusable_with: string[];
}

export interface SuggestResponse {
  query: string;
  suggestions: Suggestion[];
  note: string | null;
}

export interface Readiness {
  ready: boolean;
  graph_backend: string;
  graph_reachable: boolean;
  counts: {
    nodes?: Record<string, number>;
    relationships?: Record<string, number>;
  };
  blocklist_pairs: number;
  blocklist_loaded: boolean;
  coverage_manifest_loaded: boolean;
  combinations_loaded: boolean;
  combination_brands: number;
  checks: Record<string, boolean>;
  notes: string[];
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    detail?: unknown;
  };
}
