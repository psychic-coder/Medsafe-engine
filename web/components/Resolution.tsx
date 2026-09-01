import { formatScore, formatStrength, RESOLUTION_LABEL } from "@/lib/format";
import type { ResolveResponse } from "@/lib/types";
import { Code, Field, Prose, SheetHeading, StatusMark } from "./primitives";

/**
 * How a drug string was read.
 *
 * The three outcomes get three different surfaces, and the difference is deliberately not subtle.
 * A `needs_review` result sits on a hatched surface with no molecule name presented as a heading,
 * because the whole point of the backend's design is that a fuzzy candidate must never be able to
 * pass for an identification at a glance.
 */
export function Resolution({ result }: { result: ResolveResponse }) {
  const { normalized } = result;
  const strength = formatStrength(
    normalized.strength_value,
    normalized.strength_unit,
  );

  return (
    <section
      className={
        result.status === "resolved"
          ? "surface-known p-5"
          : result.status === "needs_review"
            ? "surface-review p-5"
            : "surface-unchecked p-5"
      }
    >
      <SheetHeading
        title={
          result.match
            ? result.match.molecule.inn_name
            : `No match for “${result.query}”`
        }
        aside={
          <StatusMark
            tone={
              result.status === "resolved"
                ? "verified"
                : result.status === "needs_review"
                  ? "caution"
                  : "unknown"
            }
          >
            {RESOLUTION_LABEL[result.status]}
          </StatusMark>
        }
      />

      {result.match ? (
        <dl className="mb-4 divide-y divide-rule/60">
          <Field label="Molecule">
            <Code>{result.match.molecule.molecule_id}</Code>
            {result.match.molecule.category ? (
              <span className="ml-2 text-ink-faint">
                {result.match.molecule.category.replace("_", " ")}
              </span>
            ) : null}
          </Field>
          <Field label="Matched by">
            {result.match.path === "exact"
              ? "Exact name match"
              : `Alias table${
                  result.match.alias_source
                    ? ` (${result.match.alias_source})`
                    : ""
                }`}
            {result.match.alias_raw_string ? (
              <span className="text-ink-faint">
                {" "}
                — listed as “{result.match.alias_raw_string}”
              </span>
            ) : null}
          </Field>
          <Field label="Read as">
            {normalized.normalized}
            {normalized.form ? ` · ${normalized.form}` : ""}
            {strength ? ` · ${strength}` : ""}
            {normalized.salts.length > 0
              ? ` · salt: ${normalized.salts.join(", ")}`
              : ""}
          </Field>
        </dl>
      ) : (
        <div className="mb-4">
          <Prose>
            {result.status === "needs_review"
              ? "The engine could not identify this with certainty. The suggestions below are not accepted matches — a pharmacist has to choose."
              : "Nothing in the catalogue matches this closely enough to suggest. Check the spelling, or search for the molecule name rather than the brand."}
          </Prose>
          <p className="mt-3 text-tiny text-ink-faint">
            Read as “{normalized.normalized}”
            {normalized.form ? ` · ${normalized.form}` : ""}
            {strength ? ` · ${strength}` : ""}
          </p>
        </div>
      )}

      {result.candidates.length > 0 ? (
        <div className="rule-hair pt-4">
          <p className="mb-3 font-prose text-base text-ink-muted">
            Possible matches, none accepted:
          </p>
          <ul className="space-y-2">
            {result.candidates.map((candidate) => (
              <li
                key={candidate.molecule.molecule_id}
                className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border border-caution/30 bg-surface/70 rounded-sheet px-3 py-2"
              >
                <span className="font-medium">
                  {candidate.molecule.inn_name}{" "}
                  <Code>{candidate.molecule.molecule_id}</Code>
                </span>
                <span className="text-tiny text-ink-faint tabular-nums">
                  {formatScore(candidate.score)} similarity · matched on{" "}
                  {candidate.matched_on === "inn_name" ? "name" : "alias"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {result.suppressed.length > 0 ? (
        <div className="mt-4 rule-hair pt-4">
          <p className="mb-2 text-tiny text-ink-faint">
            Withheld as known look-alike names
          </p>
          <ul className="space-y-1.5">
            {result.suppressed.map((item) => (
              <li key={item.molecule_id} className="font-prose text-tiny text-ink-muted">
                <span className="font-display font-medium text-ink">
                  {item.inn_name}
                </span>{" "}
                scored {formatScore(item.score)} against “{item.confusable_with}”
                and was withheld — {item.reason}.
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {result.notes.length > 0 ? (
        <div className="mt-4 space-y-1">
          {result.notes.map((note) => (
            <p key={note} className="font-prose text-tiny text-ink-faint">
              {note}
            </p>
          ))}
        </div>
      ) : null}
    </section>
  );
}
