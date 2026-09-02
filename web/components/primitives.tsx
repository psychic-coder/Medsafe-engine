import type { ReactNode } from "react";

/**
 * Shared primitives.
 *
 * `StatusMark` is the one piece of vocabulary the whole console shares: a small glyph plus a word,
 * where the glyph shape (not just its colour) carries the meaning, so the three states stay
 * distinguishable in greyscale and for colour-blind readers.
 */

export type Tone = "verified" | "severe" | "caution" | "unknown" | "neutral";

const TONE_TEXT: Record<Tone, string> = {
  verified: "text-verified",
  severe: "text-severe",
  caution: "text-caution",
  unknown: "text-unknown",
  neutral: "text-ink-muted",
};

const TONE_WASH: Record<Tone, string> = {
  verified: "bg-verified-wash text-verified",
  severe: "bg-severe-wash text-severe",
  caution: "bg-caution-wash text-caution",
  unknown: "bg-unknown-wash text-unknown",
  neutral: "bg-paper text-ink-muted",
};

/** Glyphs differ in shape, not only colour: filled, half, and hollow. */
function Glyph({ tone }: { tone: Tone }) {
  if (tone === "unknown") {
    return (
      <span
        aria-hidden
        className="inline-block h-2.5 w-2.5 shrink-0 rounded-full border border-dashed border-current"
      />
    );
  }
  if (tone === "caution") {
    return (
      <span
        aria-hidden
        className="inline-block h-2.5 w-2.5 shrink-0 rounded-full border border-current bg-[linear-gradient(90deg,currentColor_50%,transparent_50%)]"
      />
    );
  }
  return (
    <span
      aria-hidden
      className="inline-block h-2.5 w-2.5 shrink-0 rounded-full bg-current"
    />
  );
}

export function StatusMark({
  tone,
  children,
  filled = false,
}: {
  tone: Tone;
  children: ReactNode;
  filled?: boolean;
}) {
  return (
    <span
      className={`inline-flex items-center gap-2 whitespace-nowrap text-tiny font-medium ${
        filled
          ? `${TONE_WASH[tone]} rounded-control px-2 py-1`
          : TONE_TEXT[tone]
      }`}
    >
      <Glyph tone={tone} />
      {children}
    </span>
  );
}

/** A label/value row. The label is a real word, not a tracked-out caps eyebrow. */
export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-1.5">
      <dt className="w-28 shrink-0 text-tiny text-ink-faint">{label}</dt>
      <dd className="min-w-0 flex-1 text-base">{children}</dd>
    </div>
  );
}

/** Molecule and product identifiers are codes, so they are set in mono. Nothing else is. */
export function Code({ children }: { children: ReactNode }) {
  return (
    <span className="font-mono text-tiny text-ink-faint">{children}</span>
  );
}

export function SheetHeading({
  title,
  aside,
}: {
  title: string;
  aside?: ReactNode;
}) {
  return (
    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
      <h2 className="text-title font-semibold">{title}</h2>
      {aside ? <div className="text-tiny text-ink-faint">{aside}</div> : null}
    </div>
  );
}

/** Explanatory safety prose is set in the serif — it reads as a package insert, and it is the
 *  text a pharmacist must actually weigh, so it gets a different voice from the interface chrome. */
export function Prose({ children }: { children: ReactNode }) {
  return (
    <p className="max-w-measure font-prose text-base leading-relaxed text-ink-muted">
      {children}
    </p>
  );
}

/**
 * The plain-English block the backend renders for every state.
 *
 * Deliberately the loudest thing in any result: headline at title size, reasoning in the serif
 * beneath it, and the "what to do" set apart so it survives skimming. The enum value and the
 * technical detail sit below this, for the reader who wants them — the ordering says the sentence
 * is the answer and the machinery is the footnote, which is the opposite of the old console.
 */
export function PlainBlock({
  plain,
  tone = "neutral",
  size = "title",
}: {
  plain: { headline: string; detail: string; action: string | null };
  tone?: Tone;
  size?: "title" | "base";
}) {
  return (
    <div>
      <h3
        className={`${
          size === "title" ? "text-title" : "text-lede"
        } font-semibold ${tone === "severe" ? "text-severe" : "text-ink"}`}
      >
        {plain.headline}
      </h3>
      <p className="mt-2 max-w-measure font-prose text-base leading-relaxed text-ink-muted">
        {plain.detail}
      </p>
      {plain.action ? (
        <p className="mt-3 flex max-w-measure items-start gap-2.5 border-l-2 border-rule-strong pl-3 text-base text-ink">
          <span className="font-medium">{plain.action}</span>
        </p>
      ) : null}
    </div>
  );
}

/**
 * Detail a curious reader can open, and everyone else never sees.
 *
 * The technical fields are not removed — molecule ids, match paths, similarity scores and
 * exclusion reasons are how a pharmacist audits an answer, and deleting them would make the tool
 * useless to the one reader qualified to overrule it. They are demoted, not dropped.
 */
export function Details({
  summary,
  children,
}: {
  summary: string;
  children: ReactNode;
}) {
  return (
    <details className="group mt-4">
      <summary className="cursor-pointer list-none text-tiny text-ink-faint underline decoration-rule underline-offset-4 hover:text-ink-muted">
        {summary}
      </summary>
      <div className="mt-3">{children}</div>
    </details>
  );
}
