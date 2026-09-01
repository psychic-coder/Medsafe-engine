import {
  formatPercent,
  formatPrice,
  PRODUCT_SOURCE_LABEL,
  SUBSTITUTION_NOTE,
} from "@/lib/format";
import type { Substitution as SubstitutionData } from "@/lib/types";
import { Code, Prose, SheetHeading } from "./primitives";

/**
 * Substitutes for a resolved molecule.
 *
 * The baseline is shown as prominently as the savings. The engine computes savings against a
 * stated reference product — when no prescribed product was supplied it uses the most expensive
 * equivalent — and a saving displayed without its baseline is a misreported number, so the
 * reference is part of the heading rather than a footnote.
 */
export function Substitution({ data }: { data: SubstitutionData }) {
  if (data.status !== "ok") {
    return (
      <section className="surface-known p-5">
        <SheetHeading title="Substitutes" />
        <Prose>{SUBSTITUTION_NOTE[data.status]}</Prose>
      </section>
    );
  }

  const reference = data.reference;
  const best = data.substitutes[0];

  return (
    <section className="surface-known p-5">
      <SheetHeading
        title="Substitutes"
        aside={
          reference ? (
            <>
              Compared against {reference.generic_name_raw} at{" "}
              {formatPrice(reference.mrp)}
            </>
          ) : null
        }
      />

      {best ? (
        <p className="mb-4 font-prose text-lede text-ink">
          The cheapest equivalent saves {formatPrice(best.savings_abs)} per pack
          — {formatPercent(best.savings_pct)} off the comparison price.
        </p>
      ) : null}

      <ul className="divide-y divide-rule">
        {data.substitutes.map(({ product, savings_abs, savings_pct }) => (
          <li
            key={product.product_id}
            className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 py-3"
          >
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium">{product.generic_name_raw}</p>
              <p className="mt-0.5 text-tiny text-ink-faint">
                {PRODUCT_SOURCE_LABEL[product.source] ?? product.source}
                {product.form ? ` · ${product.form}` : ""}
                {product.strength_raw ? ` · ${product.strength_raw}` : ""}
                <span className="px-1.5 text-rule-strong">·</span>
                <Code>{product.product_id}</Code>
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

      {data.excluded.length > 0 ? (
        <div className="mt-5 rule-hair pt-4">
          <p className="mb-2 text-tiny text-ink-faint">
            Left out because equivalence could not be established
          </p>
          <ul className="space-y-1">
            {data.excluded.map((item) => (
              <li key={item.product_id} className="font-prose text-tiny text-ink-muted">
                <Code>{item.product_id}</Code> — {item.reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {data.notes.length > 0 ? (
        <div className="mt-4 space-y-1">
          {data.notes.map((note) => (
            <p key={note} className="font-prose text-tiny text-ink-faint">
              {note}
            </p>
          ))}
        </div>
      ) : null}
    </section>
  );
}
