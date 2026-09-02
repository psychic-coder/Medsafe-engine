import { severityRank } from "@/lib/format";
import type { CheckResponse, InteractionPair } from "@/lib/types";
import { Details, Field, PlainBlock, StatusMark, type Tone } from "./primitives";

/**
 * The pairwise interaction report.
 *
 * The design problem here is the whole reason the endpoint exists: "no interaction found" and "we
 * did not look" must never read the same. The previous version solved that visually — hatched,
 * hollow, dashed — and then undid it in the copy, which told the reader that "the interaction
 * source covers ATC groups A, B, D, H, L, P, R, V only". Someone who does not know what an ATC
 * group is cannot tell from that sentence whether their prescription was checked, so the careful
 * visual distinction lands on a reader who has already stopped reading.
 *
 * The surfaces are unchanged. The words come from the backend's explain layer, which is tested to
 * never let an unchecked pair read as reassuring, and the coverage bar now labels its segments in
 * the same vocabulary as the rows beneath it.
 */

const PAIR_TONE: Record<InteractionPair["status"], Tone> = {
  interaction: "severe",
  no_known_interaction: "verified",
  not_checked: "unknown",
};

const PAIR_WORD: Record<InteractionPair["status"], string> = {
  interaction: "Known interaction",
  no_known_interaction: "Checked, nothing found",
  not_checked: "Not checked",
};

function label(side: InteractionPair["left"]) {
  const name = side.inn_name ?? side.query;
  return side.from_combination ? `${name} (in ${side.from_combination})` : name;
}

function CoverageBar({ summary }: { summary: CheckResponse["summary"] }) {
  const total = summary.pairs_total || 1;
  const pct = (n: number) => `${(n / total) * 100}%`;

  return (
    <div className="mt-4">
      <div
        className="flex h-2 w-full overflow-hidden rounded-full border border-rule-strong"
        role="img"
        aria-label={`${summary.pairs_total} combinations: ${summary.interactions_found} with a known interaction, ${summary.checked_no_interaction} checked and nothing found, ${summary.not_checked} not checked`}
      >
        <span className="bg-severe" style={{ width: pct(summary.interactions_found) }} />
        <span
          className="bg-verified"
          style={{ width: pct(summary.checked_no_interaction) }}
        />
        <span className="bg-hatch-quiet" style={{ width: pct(summary.not_checked) }} />
      </div>
      <div className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1">
        <StatusMark tone="severe">
          {summary.interactions_found} with a known interaction
        </StatusMark>
        <StatusMark tone="verified">
          {summary.checked_no_interaction} checked, nothing found
        </StatusMark>
        <StatusMark tone="unknown">{summary.not_checked} not checked</StatusMark>
      </div>
    </div>
  );
}

function PairRow({ pair }: { pair: InteractionPair }) {
  const surface =
    pair.status === "not_checked"
      ? "surface-unchecked p-4"
      : pair.status === "interaction"
        ? "surface-known border-l-[3px] border-l-severe p-4"
        : "surface-known p-4";

  return (
    <li className={surface}>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="text-base">
          <span className="font-semibold">{label(pair.left)}</span>
          <span className="mx-2 text-ink-faint">with</span>
          <span className="font-semibold">{label(pair.right)}</span>
        </h3>
        <StatusMark
          tone={PAIR_TONE[pair.status]}
          filled={pair.status === "interaction"}
        >
          {PAIR_WORD[pair.status]}
        </StatusMark>
      </div>

      <PlainBlock plain={pair.plain} tone={PAIR_TONE[pair.status]} size="base" />

      {pair.source ? (
        <p className="mt-3 max-w-measure font-prose text-tiny text-ink-faint">
          {pair.source}
        </p>
      ) : null}

      {pair.severity || pair.mechanism || pair.reason ? (
        <Details summary="Show the technical detail">
          <dl className="divide-y divide-rule/60">
            {pair.severity ? <Field label="Severity">{pair.severity}</Field> : null}
            {pair.mechanism ? <Field label="Mechanism">{pair.mechanism}</Field> : null}
            {pair.reason ? <Field label="Reason">{pair.reason}</Field> : null}
            {pair.provenance ? <Field label="Provenance">{pair.provenance}</Field> : null}
            {pair.left_atc_group || pair.right_atc_group ? (
              <Field label="ATC groups">
                {pair.left_atc_group ?? "—"} / {pair.right_atc_group ?? "—"}
              </Field>
            ) : null}
          </dl>
        </Details>
      ) : null}
    </li>
  );
}

// Interactions first, then unchecked, then clear. A clean pair is the least urgent thing here,
// and burying the gaps under a list of reassuring rows is how a coverage gap gets missed.
const STATUS_ORDER: Record<InteractionPair["status"], number> = {
  interaction: 0,
  not_checked: 1,
  no_known_interaction: 2,
};

// Within the interactions, worst first. A reader scans from the top and may well stop partway, so
// the ordering decides what they are most likely to actually read — which makes it a safety
// property rather than a presentational one. "Unknown" sits above "minor" and below "moderate":
// the row itself says an unrecorded strength is not a reason to assume the interaction is small,
// and sorting it beneath the ones we know to be small would contradict that.
const SEVERITY_ORDER: Record<ReturnType<typeof severityRank>, number> = {
  major: 0,
  moderate: 1,
  unknown: 2,
  minor: 3,
};

export function Interactions({ result }: { result: CheckResponse }) {
  const pairs = [...result.pairs].sort((a, b) => {
    const byStatus = STATUS_ORDER[a.status] - STATUS_ORDER[b.status];
    if (byStatus !== 0) return byStatus;
    if (a.status !== "interaction") return 0;
    return SEVERITY_ORDER[severityRank(a.severity)] - SEVERITY_ORDER[severityRank(b.severity)];
  });
  const expanded = result.inputs.filter((input) => input.from_combination);

  return (
    <div className="space-y-5">
      <section
        className={
          result.coverage_complete ? "surface-known p-5" : "surface-unchecked p-5"
        }
      >
        <PlainBlock plain={result.plain} />
        <CoverageBar summary={result.summary} />

        {expanded.length > 0 ? (
          <p className="mt-4 max-w-measure border-t border-rule pt-4 font-prose text-base text-ink-muted">
            One of your entries is a combination pack, so it appears below under each of
            its ingredients. That is not a duplicate — every ingredient is checked
            separately against everything else on your list.
          </p>
        ) : null}
      </section>

      <ul className="space-y-3">
        {pairs.map((pair, index) => (
          <PairRow
            key={`${pair.left.inn_name ?? pair.left.query}-${pair.right.inn_name ?? pair.right.query}-${index}`}
            pair={pair}
          />
        ))}
      </ul>
    </div>
  );
}
