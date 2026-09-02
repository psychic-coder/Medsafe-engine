import { formatPercent, formatPrice, PRODUCT_SOURCE_LABEL } from "@/lib/format";
import type { Substitution as SubstitutionData } from "@/lib/types";
import { Code, Details, Field, PlainBlock } from "./primitives";

/**
 * Cheaper packs containing the same ingredient.
 *
 * Two things this deliberately does not do.
 *
 * It never shows a saving without its baseline. The engine computes savings against a stated
 * reference product — when no prescribed product was supplied it takes the most expensive
 * equivalent — and a percentage floating free of what it was measured against is a number that
 * cannot be checked. The reference sits beside the figure, not in a footnote.
 *
 * It does not hide an empty result behind an empty list. "We found nothing cheaper" and "we found
 * this ingredient but only one pack contains it" are different answers, and on the current
 * catalogue the second is overwhelmingly the common one: it is a single-source generic list, so
 * there is frequently nothing to compare against. Saying so plainly — and still showing the pack we
 * did find, because knowing which generic to ask for is useful on its own — is more honest than an
 * empty panel that reads as a failure.
 */
export function Substitution({ data }: { data: SubstitutionData }) {
  const reference = data.reference;
  const best = data.substitutes[0];

  return (
    <section className="surface-known p-5">
      {data.plain ? <PlainBlock plain={data.plain} /> : null}

      {best && reference ? (
        <div className="mt-4 border-t border-rule pt-4">
          <ul className="divide-y divide-rule">
            {data.substitutes.map(({ product, savings_abs, savings_pct }) => (
              <li
                key={product.product_id}
                className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 py-3"
              >
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{product.generic_name_raw}</p>
                  <p className="mt-0.5 text-tiny text-ink-faint">
                    {PRODUCT_SOURCE_LABEL[product.source] ?? product.source}
                    {product.form ? ` · ${product.form}` : ""}
                    {product.strength_raw ? ` · ${product.strength_raw}` : ""}
                  </p>
                </div>
                <div className="flex items-baseline gap-4 tabular-nums">
                  <span className="text-title font-semibold">
                    {formatPrice(product.mrp)}
                  </span>
                  <span className="w-28 text-right text-tiny text-verified">
                    saves {formatPrice(savings_abs)}
                    <span className="block text-ink-faint">
                      {formatPercent(savings_pct)} less
                    </span>
                  </span>
                </div>
              </li>
            ))}
          </ul>
          <p className="mt-3 max-w-measure font-prose text-tiny text-ink-faint">
            Measured against {reference.generic_name_raw} at{" "}
            {formatPrice(reference.mrp)}.
          </p>
        </div>
      ) : null}

      {!best && reference ? (
        <div className="mt-4 border-t border-rule pt-4">
          <p className="mb-2 text-base text-ink-muted">
            This is the pack we found containing that ingredient:
          </p>
          <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
            <div className="min-w-0 flex-1">
              <p className="font-medium">{reference.generic_name_raw}</p>
              <p className="mt-0.5 text-tiny text-ink-faint">
                {PRODUCT_SOURCE_LABEL[reference.source] ?? reference.source}
                {reference.form ? ` · ${reference.form}` : ""}
                {reference.strength_raw ? ` · ${reference.strength_raw}` : ""}
              </p>
            </div>
            <span className="text-title font-semibold tabular-nums">
              {formatPrice(reference.mrp)}
            </span>
          </div>
          <p className="mt-3 max-w-measure font-prose text-tiny text-ink-faint">
            Catalogue price, not a quote. What a pharmacy charges can differ.
          </p>
        </div>
      ) : null}

      {data.excluded.length > 0 || data.notes.length > 0 ? (
        <Details summary="Show what was left out, and why">
          <dl className="divide-y divide-rule/60">
            {data.excluded.map((item) => (
              <Field key={item.product_id} label="Excluded">
                <Code>{item.product_id}</Code> — {item.reason}
              </Field>
            ))}
          </dl>
          {data.notes.length > 0 ? (
            <ul className="mt-3 space-y-1">
              {data.notes.map((note) => (
                <li key={note} className="font-prose text-tiny text-ink-faint">
                  {note}
                </li>
              ))}
            </ul>
          ) : null}
        </Details>
      ) : null}
    </section>
  );
}
