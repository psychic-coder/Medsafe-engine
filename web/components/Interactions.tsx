import { PAIR_LABEL, severityRank } from "@/lib/format";
import type { CheckResponse, InteractionPair } from "@/lib/types";
import { Prose, SheetHeading, StatusMark, type Tone } from "./primitives";

/**
 * The pairwise interaction report.
 *
 * The design problem here is the whole reason the endpoint exists: "no interaction found" and
 * "we did not look" must never read the same. So unchecked pairs are rendered hollow and hatched
 * rather than merely tinted a different colour, and the coverage bar shows the unchecked share as
 * an unfilled segment — the eye reads it as missing, which is exactly what it is.
 */

const PAIR_TONE: Record<InteractionPair["status"], Tone> = {
  interaction: "severe",
  no_known_interaction: "verified",
  not_checked: "unknown",
};

function CoverageBar({ summary }: { summary: CheckResponse["summary"] }) {
  const total = summary.pairs_total || 1;
  const pct = (n: number) => `${(n / total) * 100}%`;

  return (
    <div>
      <div
        className="flex h-2 w-full overflow-hidden rounded-full border border-rule-strong"
        role="img"
        aria-label={`${summary.pairs_total} pairs: ${summary.interactions_found} with a known interaction, ${summary.checked_no_interaction} checked and clear, ${summary.not_checked} not checked`}
      >
        <span
          className="bg-severe"
          style={{ width: pct(summary.interactions_found) }}
        />
        <span
          className="bg-verified"
          style={{ width: pct(summary.checked_no_interaction) }}
        />
        <span
          className="bg-hatch-quiet"
          style={{ width: pct(summary.not_checked) }}
        />
      </div>
      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1">
        <StatusMark tone="severe">
          {summary.interactions_found} with a known interaction
        </StatusMark>
        <StatusMark tone="verified">
          {summary.checked_no_interaction} checked and clear
        </StatusMark>
        <StatusMark tone="unknown">{summary.not_checked} not checked</StatusMark>
      </div>
    </div>
  );
}

function PairRow({ pair }: { pair: InteractionPair }) {
  const tone = PAIR_TONE[pair.status];
  const rank = severityRank(pair.severity);

  return (
    <li
      className={
        pair.status === "not_checked"
          ? "surface-unchecked p-4"
          : pair.status === "interaction"
            ? "surface-known border-l-[3px] border-l-severe p-4"
            : "surface-known p-4"
      }
    >
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="text-base font-semibold">
          {pair.left.inn_name ?? pair.left.query}
          <span className="mx-2 font-normal text-ink-faint">with</span>
          {pair.right.inn_name ?? pair.right.query}
        </h3>
        <StatusMark tone={tone} filled={pair.status === "interaction"}>
          {pair.status === "interaction" && pair.severity
            ? `${pair.severity} interaction`
            : PAIR_LABEL[pair.status]}
        </StatusMark>
      </div>

      {pair.status === "interaction" ? (
        <>
          {pair.mechanism ? (
            <p
              className={`max-w-measure font-prose text-base ${
                rank === "major" ? "text-ink" : "text-ink-muted"
              }`}
            >
              {pair.mechanism}
            </p>
          ) : null}
          {pair.provenance ? (
            <p className="mt-2 text-tiny text-ink-faint">
              Source: {pair.provenance}
            </p>
          ) : null}
        </>
      ) : (
        <Prose>{pair.reason}</Prose>
      )}
    </li>
  );
}

export function Interactions({ result }: { result: CheckResponse }) {
  const unresolved = result.inputs.filter((input) => !input.resolved);

  // Interactions first, then unchecked, then clear. A clean pair is the least urgent thing here,
  // and burying the gaps under a list of reassuring rows is how a coverage gap gets missed.
  const order: Record<InteractionPair["status"], number> = {
    interaction: 0,
    not_checked: 1,
    no_known_interaction: 2,
  };
  const pairs = [...result.pairs].sort(
    (a, b) => order[a.status] - order[b.status],
  );

  return (
    <div className="space-y-5">
      <section className="surface-known p-5">
        <SheetHeading
          title="What was checked"
          aside={`${result.summary.pairs_total} pair${
            result.summary.pairs_total === 1 ? "" : "s"
          } from ${result.inputs.length} medicines`}
        />
        <CoverageBar summary={result.summary} />

        {!result.coverage_complete ? (
          <div className="mt-4 rule-hair pt-4">
            <Prose>
              Some pairs were not checked, so this report cannot tell you the
              prescription is clear. The interaction source covers ATC groups{" "}
              {result.covered_atc_groups.join(", ")} only; anything outside that
              is listed below as not checked.
            </Prose>
          </div>
        ) : null}

        {unresolved.length > 0 ? (
          <div className="mt-4 rule-hair pt-4">
            <Prose>
              {unresolved.length === 1
                ? `“${unresolved[0].query}” could not be identified, so every pair involving it is unchecked.`
                : `${unresolved.length} entries could not be identified, so every pair involving them is unchecked.`}
            </Prose>
          </div>
        ) : null}
      </section>

      <ul className="space-y-3">
        {pairs.map((pair, index) => (
          <PairRow key={`${pair.left.query}-${pair.right.query}-${index}`} pair={pair} />
        ))}
      </ul>
    </div>
  );
}
