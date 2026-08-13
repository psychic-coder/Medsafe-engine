# Data Layer — Final Report

Generic Medicine Substitute & Prescription Safety Engine (India). Phase 0 output.
Build date: 2026-08-11. Every number below was computed from the attached files;
nothing is estimated, rounded up, or carried over from a previous pass without
being recomputed.

---

## 1. Sources and provenance

| Source | Identifier | Provenance | Date |
|---|---|---|---|
| DDInter bulk interactions | `ddinter_downloads_code_{A,B,D,H,L,P,R,V}.csv` (8 files) | Supplied directly by the requester, downloaded manually. No URL recorded. | Not recorded |
| PMBJP product list | `jan_aushadhi_medicine_list_with_price.csv` | **Unverified provenance** — exact source URL and access date are not known and have not been guessed. | Unknown |
| NPPA ceiling prices | `Compendium-Prices-2022pdf-464b22085495ff4e3f8700c0e00cf45d.pdf` — NPPA, *Compendium of Ceiling Prices of Scheduled Drugs as on 10.08.2022*, Schedule-I / NLEM 2015, Dept. of Pharmaceuticals, Ministry of Chemicals & Fertilizers, GoI. PDF internal ref `91333/2022/NPPA`, produced by iText, 31 pages, created 2022-09-22. | Supplied directly. Document self-identifies; disclaimer directs to Gazette notifications via nppaindia.nic.in for the official version. | **10.08.2022** |

### NPPA staleness — stated plainly

The compendium is dated **10 August 2022**. As of today (11 August 2026) it is
**almost exactly four years old**. Its prices are effective 1 April 2022, revised
by WPI at 10.76607%, mostly notified under S.O. 1499(E) dated 30.03.2022.
NPPA revises ceiling prices annually by WPI and issues new notifications
continuously, so **every figure in `ceiling_price.csv` is four annual revision
cycles behind current law**. Currency has been carried through exactly as
printed — not inflated, indexed, or rounded up. Any user-facing "you are being
overcharged versus the ceiling price" claim built on this file would be
asserting a legal threshold that has since moved. Treat these as historical
reference values until a current compendium is sourced.

---

## 2. Row counts at each stage

### Task 1 — PMBJP (`pmbjp_final_clean.csv`)

| Stage | Rows |
|---|---|
| Source rows | 2,479 |
| Rows written (no row dropped) | 2,479 |
| Flagged non-drug | 348 |
| Drug rows | 2,131 |
| FDC rows (all) | 776 |
| FDC rows (drug only) | 748 |
| **FDC decomposed cleanly** | **726 — 97.06% of drug FDCs** |
| Residue rows | 48 |
| Distinct molecules recovered | 1,018 |
| MRP present but ₹0.00 in source | 415 |
| MRP missing/unparseable | 0 |

European decimal format parsed as specified (`"10,00"` → ₹10.00, `"1.234,50"` →
₹1234.50). `Drug Code` uses the same convention (`"9.067"` → 9067); all 2,479
codes are unique, max 9,067, with gaps — consistent with your description.

**415 rows carry a literal `0,00` MRP in the source.** These are not parse
failures — the source publishes zero. They are preserved as `0.00` and must be
excluded from savings arithmetic downstream or they will produce 100%-saving
substitution claims.

#### Tail-of-file row corruption — checked, not present

The row-2338-style corruption from the previous mirror **did not recur**. Longest
`Generic Name` is exactly 200 characters; nothing exceeds it. I read all eight
longest rows rather than assuming: every one is a genuine multi-ingredient
product (a 13-active throat spray, a 12-component amino-acid/vitamin tablet, a
pancreatin digestive-enzyme tablet with bracketed enzyme activities). No manual
repair was warranted and none was made.

#### Normalizer bug fixes — all three implemented and regression-tested

1. **FDC comma-split before punctuation stripping, with percentage gate.**
   Split points are gated on `\d+(\.\d+)?\s*(mg|mcg|g|ml|iu|units|…)` **or**
   `\d+(\.\d+)?%\s*(w/w|w/v|v/v)?`. Verified:
   `Clobetasol 0.05% w/w, Ofloxacin 0.75% w/w, Ornidazole 2% w/w and Terbinafine 1% w/w Cream`
   → 4 distinct molecules. Without the percentage arm this fuses to one phantom
   molecule. Commas inside parentheses are masked before splitting so bracketed
   ingredient lists are never split on.
2. **Pack-size truncation guard.** Every candidate pack-size removal is tested:
   if the text that would be lost still contains a component separator or another
   dose token, the removal is refused. Verified:
   `Amoxycillin 1g and Potassium Clavulanate 200mg Powder for Injection 1 Vial`
   → `amoxycillin` + `potassium clavulanate`, both surviving. **The guard fired
   9 times on real rows** (logged) — meaning nine products would otherwise have
   silently lost text.
3. **Word-boundary form stripping.** All ~90 dosage-form tokens are `\b`-anchored.
   Verified: `gelatin` survives intact; `capecitabine` is not eaten by `cap`.

#### Residue (`fdc_decomposition_residue.csv`, 48 rows)

| Reason | Rows |
|---|---|
| Opaque blend — trivial name carries no component molecule names | 27 |
| Insulin preparation — strength/mix ratio not decomposable from name | 11 |
| Component did not reduce to a molecule-length string | 5 |
| Component too short to be a molecule | 2 |
| Suspected component fusion (1 molecule but ≥2 dose tokens) | 2 |
| No component normalized to a molecule | 1 |

This matches the predicted profile: insulins, vitamin-B-complex blends, and
combination products whose trivial name omits the components.

### Task 2 — DDInter (`ddinter_final_clean.csv`)

| Source file | Rows |
|---|---|
| A | 56,367 |
| B | 15,140 |
| D | 25,681 |
| H | 11,727 |
| L | 65,389 |
| P | 5,492 |
| R | 30,563 |
| V | 12,024 |
| **Total raw** | **222,383** |

| Stage | Value |
|---|---|
| Self-pair rows removed | 0 |
| **Unique unordered pairs after dedupe** | **160,235** |
| Duplicate rows collapsed | 62,148 |
| Pairs appearing in more than one ATC file | 43,826 |
| **Pairs with a severity conflict across files** | **0** |
| Distinct drugs | 1,939 |

Zero severity conflicts across 43,826 cross-file pairs — DDInter is internally
consistent, so the dedupe is lossless with respect to severity.

**Severity distribution**

| Tier | Pairs | % |
|---|---|---|
| Moderate | 96,675 | 60.33% |
| Unknown | 29,813 | 18.61% |
| Major | 26,914 | 16.80% |
| Minor | 6,833 | 4.26% |

`drugbank_id_a` / `drugbank_id_b` are present but **empty**, as specified — the
bulk files carry `DDInterID`, not DrugBank IDs. The DDInter IDs are preserved in
`ddinter_id_a` / `ddinter_id_b` so the crosswalk has an anchor when it is done.
`mechanism` is empty for all 160,235 rows: the bulk export does not carry it,
and it is only available from per-drug page scrapes, which are out of scope.
**Consequence: the `INTERACTS_WITH.mechanism` property will be null on every
edge at load time.**

### Task 3 — Alias bridge (`alias_bridge_table_final.csv`, 164 rows)

| Origin | Rows |
|---|---|
| India-specific naming seed | 133 |
| Benign spelling variant surfaced by the real PMBJP scan | 27 |
| Orthographic bridge PMBJP→DDInter | 4 |

115 of the 164 aliases resolve into the DDInter vocabulary.

**Finding: 13 seed aliases pointed the wrong way.** DDInter carries INN/British
spellings, not USAN. It has `salbutamol` not `albuterol`, `rifampicin` not
`rifampin`, `cephalexin` not `cefalexin`, `nicotinamide` not `niacinamide`,
`dicyclomine` not `dicycloverine`, `norethisterone` not `norethindrone`,
`clavulanic acid` not `clavulanate`, `leucovorin` not `folinic acid`,
`benzylpenicillin` not `penicillin g`, `phenoxymethylpenicillin` not
`penicillin v`, `ethinylestradiol` not `ethinyl estradiol`, `methylergometrine`
not `methylergonovine`, `ergometrine` not `ergonovine`. Direction is now decided
by the real target vocabulary at build time rather than by the seed's own
assumption, so this cannot silently rot if either vocabulary changes.

16 orthographic bridges were generated by a deterministic spelling-system rule
(ph↔f, oe/ae↔e, y↔i, doubled letters, hyphen/space); 4 were new, 12 duplicated
entries already added from the benign-variant scan. Each was required to have
**exactly one** unambiguous DDInter target, was checked against the blocklist,
and was blocked from crossing a letter-designator or enantiomer-prefix boundary.
All 16 are listed in the build log and are plain spelling pairs
(`cefalexin→cephalexin`, `sulphacetamide→sulfacetamide`,
`valacyclovir→valaciclovir`, …).

### Task 6 — NPPA (`ceiling_price.csv`)

| Stage | Value |
|---|---|
| Formulation rows extracted | 1,102 |
| Rows with a notified ceiling price | 996 |
| Rows without one (kept, price left empty) | 106 |
| Distinct NPPA medicines | 371 |
| Distinct normalized NPPA molecules | 365 |
| **PMBJP molecules with an NPPA ceiling price** | **228 — 22.40% of 1,018** |
| PMBJP molecules with no NPPA match | 790 |

Columns are exactly as locked: `molecule_or_normalized_string`,
`dosage_form_strength`, `ceiling_price`, `nlem_section`,
`source_url_or_document`, `source_date`, plus provenance extras
(`medicine_raw`, `unit_pack_size`, `so_no`, `date_of_notification`,
`pdf_page`, `is_fdc`, `matches_pmbjp_molecule`). **No `brand_name` or
`manufacturer` field exists and none was sourced** — NPPA ceiling prices are
brand-agnostic and the commercial-pricing scrape stays ruled out.

The 106 unpriced rows are formulations NLEM lists but for which NPPA has not
notified a ceiling price (e.g. `Nystatin Tablet 500,000 IU`,
`Midazolam Tablet 15 mg`). They are retained with an empty `ceiling_price`
rather than dropped; filter on non-empty downstream.

**22.40% coverage is expected and fine.** NPPA regulates only scheduled
formulations; the PMBJP basket is far broader. The full list of 790 uncovered
molecules is in `data/manual/pmbjp_without_ceiling_price.txt`.

#### Two PDF extraction artifacts found and fixed

The Section 22.3 vaccine policy notes are free prose spanning the table columns.
On the first pass two records absorbed that prose, producing the phantom
molecules `"lyophilized polyvalent dpt opv measles hepatitis will be deemed to
be included virus vaccine are pneumococcal"` and — via forward-fill —
`"bioresorbable vascular scaffold biodegradable stents vaccine"`, which
misclassified a **coronary stent as a vaccine**. Fixed by adding prose-block
suppression: once a note paragraph starts, lines are skipped until a genuine
data row (an NLEM code, or a price with an S.O. number) resumes. Distinct
medicines went 374 → 371; **row count held at 1,102 with 996 priced**, so the
fix removed only the artifacts, not data. A third artifact — a Mefloquine
footnote bleeding into the dosage column — was also trimmed.

---

## 3. Task 4 — Fuzzy-match safety scan

`fuzzy_negative_blocklist.csv` — 85 rows. `fuzzy_benign_variants.csv` — 27 rows.

| Metric | Value |
|---|---|
| Molecules scanned (full PMBJP normalized list) | 1,018 |
| Candidate pairs at Levenshtein ≤ 2 | 111 |
| Classified **dangerous** → blocklist | 85 |
| Classified **benign spelling variant** | 27 |
| **Auto-accepted by fuzzy distance** | **0** |

### Carried-forward dangerous pairs — confirmed, not assumed

| Pair | Distance | Both in PMBJP | Result |
|---|---|---|---|
| pantoprazole ↔ lansoprazole | 2 | yes | **CONFIRMED blocked by live scan** |
| esomeprazole ↔ omeprazole | 2 | yes | **CONFIRMED blocked** |
| clonazepam ↔ lorazepam | 2 | yes | **CONFIRMED blocked** |
| citalopram ↔ escitalopram | 2 | yes | **CONFIRMED blocked** |
| linagliptin ↔ sitagliptin | 2 | yes | **CONFIRMED blocked** |
| saxagliptin ↔ sitagliptin | 2 | yes | **CONFIRMED blocked** |
| vitamin d ↔ vitamin k | 1 | yes | **CONFIRMED blocked** |
| vitamin a ↔ vitamin d | 1 | yes | **CONFIRMED blocked** |
| vitamin b ↔ vitamin d | 1 | yes | **CONFIRMED blocked** |
| vitamin e ↔ vitamin d | 1 | yes | **CONFIRMED blocked** |
| **amlodipine ↔ s-amlodipine** | 2 | yes | **CONFIRMED blocked** |
| linagliptin ↔ saxagliptin | 3 | yes | Out of Lev≤2 reach — carried into blocklist explicitly |
| vildagliptin ↔ sitagliptin | 3 | yes | Out of reach — carried in explicitly |
| alogliptin ↔ sitagliptin | >3 | yes | Out of reach — carried in explicitly |
| teneligliptin ↔ sitagliptin | >3 | yes | Out of reach — carried in explicitly |
| prednisolone ↔ prednisone | 2 | **no** | Unreachable — prednisone is not in the PMBJP basket. Carried in explicitly. |

Two things worth your attention. First, **four gliptin pairs sit beyond edit
distance 2**, so a Lev≤2 scan cannot find them — they are in the blocklist only
because they were carried forward. A distance threshold is not a safety
mechanism for this class. Second, `prednisolone ↔ prednisone` is unreachable
from this data because prednisone is absent from PMBJP; the blocklist entry is
carried forward and marked as such.

### A false-benign my own scan produced, and the fix

My first classifier passed **`vitamin k ↔ vitamin-c` as a benign spelling
variant**. The orthographic reduction maps k→c, so both collapsed to
`vitaminc`. That is precisely the short-name vitamin-abbreviation cluster you
flagged — and it would have entered the alias table as an auto-accept path.
Fixed by making single-letter-designator differences outrank orthographic
reduction: any pair sharing a stem but differing in a trailing letter
designator is dangerous by construction, before spelling rules are considered.
`amphotericin b`, `polymyxin b`, `hepatitis b` and `vitamin d` all survive as
distinct molecules under the same rule.

The 27 benign variants are all genuine (`guaifenesin↔guaiphenesin`,
`selenium sulfide↔selenium sulphide`, `nortriptyline↔nortryptyline`,
`povidone iodine↔povidone-iodine`, …) and were reviewed individually.

---

## 4. Task 5 — The real join

| Metric | Count | % of 1,018 PMBJP molecules |
|---|---|---|
| **Exact match** (post-normalization) | **536** | **52.65%** |
| Alias/bridge match | 25 | 2.46% |
| **Total auto-accepted** | **561** | **55.11%** |
| Unmatched | 457 | 44.89% |
| Fuzzy review queue (never auto-accepted) | 25 | — |
| Fuzzy candidates suppressed by blocklist | 34 | — |

Reverse direction: **1,225 of 1,774** normalized DDInter drugs (69.05%) have no
PMBJP counterpart — expected, since DDInter is a global pharmacopoeia and PMBJP
is one national generic basket.

Full unmatched lists in both directions are in `join_result_final.json`
(`unmatched_pmbjp_molecules`, `unmatched_ddinter_drugs`), along with every
alias-bridged pair. The 25-row review queue is in
`data/manual/fuzzy_review_queue.csv`, every row marked
`decision=HUMAN_REVIEW_REQUIRED`, `auto_accepted=false`.

### The DDInter ATC coverage gap — in real percentage terms

**The gap is not a vocabulary gap. It is a pair-coverage gap, and that is worse.**

I initially assumed the six missing groups meant those drugs were absent. They
are not. `atorvastatin`, `amlodipine`, `metoprolol`, `telmisartan`,
`amoxicillin`, `azithromycin`, `levofloxacin`, `sertraline` and `clonazepam` are
**all present** in the merged vocabulary. A bulk file for group X contains every
interaction with at least one participant in X, so C/J/N/G/M/S drugs arrive as
the partner side of interactions anchored elsewhere. File A alone spans 1,757 of
the 1,939 distinct drugs.

What is missing is the set of pairs where **neither** side is anchored in a
downloaded group. Nothing pulls those in.

I measured this without inventing a classification, using only file membership.
A drug anchored in a downloaded group has **100% of its partners inside that one
group's file** — that is what being in the group looks like. A drug whose own
group was never downloaded appears only as a partner, scattered across files,
with a truncated edge list. The test validates cleanly: every probe it calls
partner-only is a C/J/N/S drug (atorvastatin, amlodipine, metoprolol,
telmisartan, sertraline, clonazepam, azithromycin, timolol); every probe it
calls anchored sits in A/B/H/L/R. Amoxicillin and levofloxacin correctly come
back anchored — both carry legitimate A02BD (H. pylori) codes alongside J.

**Of the 549 PMBJP molecules that resolved into DDInter, 273 (47.56%) are
partner-only** — their interaction lists are structurally truncated. Mean degree
is 320.3 for anchored molecules versus 162.4 for partner-only ones.

Pair density over the PMBJP basket:

| Region | Possible pairs | Present | Coverage |
|---|---|---|---|
| Both sides partner-only | 37,128 | 345 | **0.93%** |
| One side anchored | 75,348 | 22,717 | 30.15% |
| Both sides anchored | 37,950 | 9,799 | 25.82% |

**Coverage collapses to 0.93% where neither drug's ATC group was downloaded —
roughly a 30-fold deficit against the rest of the graph. 24.68% of the PMBJP
pair space (37,128 of 150,426 pairs) sits in that near-zero region.**

Two independent cross-checks, both from real data, agree the exposure is large:

- **WHO INN stem rules** (table shipped as `data/manual/atc_stem_rules.csv` so
  it is auditable): **354 of 1,018 PMBJP molecules — 34.77% — sit in C/J/N/G/M/S**
  (C 69, J 108, N 96, G 36, M 32, S 13).
- **NLEM section cross-check**, using the NPPA compendium's own printed section
  headings rather than any rule of mine: of the 228 PMBJP molecules with an NLEM
  section, **134 — 58.77% — fall in the uncovered therapeutic areas**.

What this means clinically: the pairs in the 0.93% region are exactly
statin × macrolide, SSRI × triptan, ACE-inhibitor × NSAID, antipsychotic ×
antiarrhythmic — same-group and cross-uncovered-group combinations that carry a
large share of the serious interaction burden and are among the highest-traffic
prescriptions in the PMBJP basket. **A "no interactions found" response for a
cardiovascular + anti-infective + CNS combination is, in this data, almost
always an artifact of missing files rather than a clean result.**

---

## 5. Task 7 — Molecule category classification

`molecule_catalog.csv` — 2,327 molecules across PMBJP, DDInter and NPPA, each
classified against the locked rules. **Nothing was left defaulted without being
checked.**

| Category | All sources | PMBJP subset |
|---|---|---|
| small_molecule | 2,206 | 999 |
| biologic | 92 | 14 |
| vaccine | 29 | 5 |
| herbal | 0 | 0 |

Rules applied exactly as locked: `-mab` suffix → `biologic`; all insulin
preparations → `biologic` (insulin glargine, aspart, lispro, glulisine,
degludec, detemir, isophane, soluble, premix); vaccine-identifiable names →
`vaccine`; everything else → `small_molecule`.

**One thing to flag: `herbal` is never assigned.** The locked ruleset routes
everything that is not `-mab` / insulin / vaccine to `small_molecule`, but the
PMBJP basket contains genuine botanicals — *Tinospora cordifolia* extract,
*Boswellia serrata* extract, *Ginkgo biloba* extract, evening primrose oil,
carica papaya leaf extract. These are currently `small_molecule`, which is
factually wrong. I applied the rule as locked rather than inventing a fourth
branch. **This needs a decision from you** — either add a rule or accept that
the enum value stays unpopulated.

---

## 6. Deliverables

| File | Location | Rows |
|---|---|---|
| `pmbjp_final_clean.csv` | `data/processed/` | 2,479 |
| `ddinter_final_clean.csv` | `data/processed/` | 160,235 |
| `alias_bridge_table_final.csv` | `data/processed/` | 164 |
| `join_result_final.json` | `data/processed/` | — |
| `molecule_catalog.csv` | `data/processed/` | 2,327 |
| `fuzzy_negative_blocklist.csv` | `data/manual/` | 85 |
| `fdc_decomposition_residue.csv` | `data/manual/` | 48 |
| `ceiling_price.csv` | `data/manual/` | 1,102 |
| `fuzzy_review_queue.csv` | `data/manual/` | 25 |
| `fuzzy_benign_variants.csv` | `data/manual/` | 27 |
| `atc_stem_rules.csv` | `data/manual/` | 38 |
| `ddinter_anchor_profile.csv` | `data/manual/` | 1,774 |
| `pmbjp_without_ceiling_price.txt` | `data/manual/` | 790 |

`molecule_catalog.csv` is an addition beyond the specified list — the locked
Neo4j schema needs `(:Molecule {molecule_id, inn_name, category})` and nothing
else in the deliverable set carries `molecule_id`. Build scripts are in
`scripts/` so every number here is reproducible.

### Column mapping to the locked schema

- `(:Molecule)` ← `molecule_catalog.csv` (`molecule_id`, `inn_name`, `category`)
- `(:Product)` ← `pmbjp_final_clean.csv` (`product_id`, `source=PMBJP`,
  `generic_name_raw`, `form`, `strength_raw`, `mrp`)
- `(:Alias)` ← `alias_bridge_table_final.csv` (`raw_string`,
  `normalized_string`, `source ∈ {ddinter, pmbjp, manual}`)
- `(:Product)-[:CONTAINS]->(:Molecule)` ← `pmbjp_final_clean.components`
  (pipe-separated). **`strength` and `unit` on the relationship are not
  populated per-component** — `strength_raw` holds the product-level dose
  string, but strengths are not bound to individual FDC components.
- `(:Molecule)-[:INTERACTS_WITH]->(:Molecule)` ← `ddinter_final_clean.csv`
  (`severity`; `mechanism` null throughout; `provenance` = `source_file`)
- `(:Product)-[:SUBSTITUTE_FOR]->(:Product)` — not built; Phase 4.
- `source ∈ {PMBJP, branded_csv}` — only `PMBJP` exists. No branded product
  file was produced, correctly, since `branded_mrp.csv` was replaced by
  `ceiling_price.csv`.

---

## 7. Ready for Neo4j load: **yes, with two constraints that must be enforced at load time**

The data layer is structurally sound and loadable. All seven artifacts parse,
column names map cleanly onto the locked schema, no row was silently dropped at
any stage, the three known normalizer bugs are fixed and regression-tested, and
every carried-forward dangerous confusable pair is either confirmed caught by
the live scan or explicitly carried in with its unreachability documented.
Nothing is auto-accepted on fuzzy distance anywhere in the pipeline. The two
PDF extraction artifacts and the one false-benign my own classifier produced
were found, fixed, and are documented above rather than papered over.

The constraints are not defects in the load — they are properties of the source
data that the application must not paper over. **First: the interaction graph is
not safe to present as complete.** With coverage at 0.93% in the region where
neither drug's ATC group was downloaded, and 24.68% of the PMBJP pair space
sitting in that region, a null result from `INTERACTS_WITH` carries almost no
information for cardiovascular, anti-infective, CNS, genito-urinary,
musculoskeletal and ophthalmic combinations. Phase 5 response composition must
distinguish "no interaction found" from "this pair is outside our coverage" —
the `ddinter_anchor_profile.csv` anchor flag is the field to drive that with,
and it should gate the copy before launch, not after. **Second: pricing is
four years stale and 415 PMBJP rows carry a ₹0.00 MRP**; savings arithmetic
must exclude zero-MRP products and ceiling-price comparisons must be labelled
with the 10.08.2022 source date rather than presented as current law.

Both are load-time application constraints, not blockers on the load itself.
The remaining open question needing your decision is the `herbal` category in
§5.
