# Phase 4 requirement: `is_priceable` guard on substitution/savings logic

## Why this exists
`pmbjp_final_clean.csv` has 415 products (16.7% of 2,479) with a literal `₹0.00` MRP in the
source — not a parse failure, the government source publishes zero for these. If substitution
logic computes `savings_pct = (branded_price - generic_price) / branded_price` without excluding
these, any zero-MRP generic will show as a 100% saving, which is a false claim in a
safety/decision-support product, not a cosmetic bug.

## What to implement
1. `pmbjp_final_clean_v2.csv` now carries an `is_priceable` boolean column (`mrp > 0`). Load this
   into `(:Product)` as a property, or equivalently compute it at query time — either is fine, but
   it must exist somewhere queryable before Phase 4 ships.
2. **Hard precondition in the substitution query** (`src/medsafe/pricing/substitution.py`): any
   `(:Product)-[:SUBSTITUTE_FOR]->(:Product)` comparison must filter both sides on
   `is_priceable = true` (or `mrp > 0` if computed inline). A product with `is_priceable = false`
   must never appear as either side of a savings comparison.
3. **API response contract**: if a resolved molecule's only PMBJP product(s) are all
   `is_priceable = false`, the `/check` or `/resolve` response must say something like
   `"substitution": "price_not_available"` — not silently omit the field, and not show `$0` or
   `100%` savings. The absence of a price is a data-coverage fact the user should see, same
   principle as the DDInter coverage gap in Phase 5.
4. Add a test case for this explicitly: a mock product with `mrp = 0` must never produce a
   populated `savings_pct` in test output. This is the one test that matters most here — write it
   before the substitution logic, not after.

## Don't do
- Don't backfill a zero MRP with an estimated or interpolated price.
- Don't drop the 415 rows from the dataset — they're still valid products for interaction
  checking, just not for price comparison. Filter at the substitution layer, not the data layer.
