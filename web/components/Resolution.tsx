import { formatScore, formatStrength } from "@/lib/format";
import type { ResolveResponse } from "@/lib/types";
import { Code, Details, Field, PlainBlock, StatusMark, type Tone } from "./primitives";

/**
 * What the engine made of the name the user typed.
 *
 * The rewrite from the previous version is not cosmetic. That one led with the molecule's INN name
 * as a bare heading and explained itself in terms of match paths and alias tables — correct, and
 * addressed to somebody who already knew what an alias table was. A patient reading "No match for
 * Glycomet 500" has no way to tell whether the problem is their spelling, their medicine, or the
 * tool, and the most natural reading of the three is the alarming one.
 *
 * So the plain sentence leads, the surface still carries the epistemic status, and every technical
 * field survives one disclosure down for the pharmacist who needs to audit the answer.
 */

const TONE: Record<ResolveResponse["status"], Tone> = {
  resolved: "verified",
  combination: "verified",
  needs_review: "caution",
  unresolved: "unknown",
};

const STATUS_WORD: Record<ResolveResponse["status"], string> = {
  resolved: "Identified",
  combination: "Identified — combination pack",
  needs_review: "Not certain",
  unresolved: "Not found",
};

const SURFACE: Record<ResolveResponse["status"], string> = {
  resolved: "surface-known",
  combination: "surface-known",
  needs_review: "surface-review",
  unresolved: "surface-unchecked",
};

export function Resolution({ result }: { result: ResolveResponse }) {
  const { normalized } = result;
  const strength = formatStrength(normalized.strength_value, normalized.strength_unit);

  return (
    <section className={`${SURFACE[result.status]} p-5`}>
      <div className="mb-1 flex justify-end">
        <StatusMark tone={TONE[result.status]}>{STATUS_WORD[result.status]}</StatusMark>
      </div>

      <PlainBlock plain={result.plain} />

      {result.combination ? (
        <ul className="mt-4 space-y-1.5 border-t border-rule pt-4">
          {result.combination.components.map((component, index) => (
            <li key={component.molecule_id} className="flex items-baseline gap-3">
              <span className="w-5 shrink-0 text-tiny tabular-nums text-ink-faint">
                {index + 1}
              </span>
              <span className="text-base font-medium">{component.inn_name}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {result.candidates.length > 0 ? (
        <div className="mt-4 border-t border-rule pt-4">
          <p className="mb-3 max-w-measure text-base text-ink-muted">
            Did you mean one of these? Nothing has been chosen for you — check the pack
            and search again with the exact name.
          </p>
          <ul className="space-y-2">
            {result.candidates.map((candidate) => (
              <li
                key={candidate.molecule.molecule_id}
                className="rounded-sheet border border-caution/30 bg-surface/70 px-3 py-2 text-base font-medium"
              >
                {candidate.molecule.inn_name}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {result.suppressed.length > 0 ? (
        <div className="mt-4 border-t border-rule pt-4">
          <p className="max-w-measure font-prose text-base text-ink-muted">
            {result.suppressed.length === 1
              ? "One similar name was left out because it is a known look-alike of a different medicine, and guessing between them is how the wrong drug gets taken."
              : `${result.suppressed.length} similar names were left out because they are known look-alikes of different medicines, and guessing between them is how the wrong drug gets taken.`}
          </p>
        </div>
      ) : null}

      <Details summary="Show the technical detail">
        <dl className="divide-y divide-rule/60">
          {result.match ? (
            <>
              <Field label="Ingredient">
                {result.match.molecule.inn_name}{" "}
                <Code>{result.match.molecule.molecule_id}</Code>
              </Field>
              <Field label="Matched by">
                {result.match.path === "exact"
                  ? "Exact name match"
                  : `Alias table${
                      result.match.alias_source ? ` (${result.match.alias_source})` : ""
                    }`}
                {result.match.alias_raw_string
                  ? ` — listed as “${result.match.alias_raw_string}”`
                  : ""}
              </Field>
            </>
          ) : null}
          {result.combination
            ? result.combination.components.map((component) => (
                <Field key={component.molecule_id} label="Component">
                  {component.inn_name} <Code>{component.molecule_id}</Code>
                </Field>
              ))
            : null}
          <Field label="Read as">
            {normalized.normalized || "—"}
            {normalized.form ? ` · ${normalized.form}` : ""}
            {strength ? ` · ${strength}` : ""}
            {normalized.strength_hint !== null && !strength
              ? ` · bare number ${normalized.strength_hint} used as a strength hint`
              : ""}
            {normalized.salts.length > 0 ? ` · salt: ${normalized.salts.join(", ")}` : ""}
          </Field>
          {result.candidates.map((candidate) => (
            <Field key={candidate.molecule.molecule_id} label="Candidate">
              {candidate.molecule.inn_name} · {formatScore(candidate.score)} similarity on{" "}
              {candidate.matched_on === "inn_name" ? "name" : "alias"} · requires human
              review
            </Field>
          ))}
          {result.suppressed.map((item) => (
            <Field key={item.molecule_id} label="Withheld">
              {item.inn_name} scored {formatScore(item.score)} against “
              {item.confusable_with}” — {item.reason}
            </Field>
          ))}
        </dl>
        {result.notes.length > 0 ? (
          <ul className="mt-3 space-y-1">
            {result.notes.map((note) => (
              <li key={note} className="font-prose text-tiny text-ink-faint">
                {note}
              </li>
            ))}
          </ul>
        ) : null}
      </Details>
    </section>
  );
}
