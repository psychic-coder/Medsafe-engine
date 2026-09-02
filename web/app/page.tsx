"use client";

import { useState } from "react";
import {
  ApiError,
  ApiUnreachableError,
  API_BASE_URL,
  checkPrescription,
  resolveDrug,
} from "@/lib/api";
import type { CheckResponse, ResolveResponse } from "@/lib/types";
import { EngineStatus } from "@/components/EngineStatus";
import { Interactions } from "@/components/Interactions";
import { PrescriptionInput, SingleDrugInput } from "@/components/Inputs";
import { Resolution } from "@/components/Resolution";
import { Substitution } from "@/components/Substitution";

type Mode = "substitute" | "check";

// Every example must resolve against data/processed, the dataset the console is served from. A
// chip on first load that returns "we could not identify that" teaches the reader the tool is
// broken before they have typed anything, which is the opposite of what an example is for.
// One of each shape: a brand with a strength, a bare brand, a combination pack, an ingredient.
const RESOLVE_EXAMPLES = ["Glycomet 500", "Ecosprin", "Augmentin", "Dolo 650"];

const CHECK_EXAMPLES = [
  ["Warfarin", "Ecosprin", "Atorvastatin"],
  ["Metformin", "Omeprazole", "Clopidogrel"],
];

function ErrorSheet({ error }: { error: unknown }) {
  if (error instanceof ApiUnreachableError) {
    return (
      <section className="surface-unchecked p-5">
        <h2 className="text-title font-semibold">Can&rsquo;t reach the service</h2>
        <p className="mt-2 max-w-measure font-prose text-base text-ink-muted">
          Nothing is answering at {API_BASE_URL}. Nothing you did caused this, and no
          result on this page should be relied on until it reconnects.
        </p>
      </section>
    );
  }

  if (error instanceof ApiError) {
    return (
      <section className="surface-unchecked p-5">
        <h2 className="text-title font-semibold">That request didn&rsquo;t work</h2>
        <p className="mt-2 max-w-measure font-prose text-base text-ink-muted">
          {error.message}
        </p>
        <p className="mt-2 font-mono text-tiny text-ink-faint">
          {error.code} · HTTP {error.status}
        </p>
      </section>
    );
  }

  return (
    <section className="surface-unchecked p-5">
      <h2 className="text-title font-semibold">Something stopped that request</h2>
      <p className="mt-2 max-w-measure font-prose text-base text-ink-muted">
        Try again. If it keeps happening, the service may be down.
      </p>
    </section>
  );
}

export default function Console() {
  const [mode, setMode] = useState<Mode>("substitute");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [resolveResult, setResolveResult] = useState<ResolveResponse | null>(null);
  const [checkResult, setCheckResult] = useState<CheckResponse | null>(null);
  const [drugs, setDrugs] = useState<string[]>([]);

  async function runResolve(drug: string) {
    setPending(true);
    setError(null);
    try {
      setResolveResult(await resolveDrug(drug));
    } catch (caught) {
      setError(caught);
      setResolveResult(null);
    } finally {
      setPending(false);
    }
  }

  async function runCheck() {
    setPending(true);
    setError(null);
    try {
      setCheckResult(await checkPrescription(drugs));
    } catch (caught) {
      setError(caught);
      setCheckResult(null);
    } finally {
      setPending(false);
    }
  }

  const tab = (value: Mode, label: string) => (
    <button
      type="button"
      role="tab"
      aria-selected={mode === value}
      onClick={() => {
        setMode(value);
        setError(null);
      }}
      className={`-mb-px border-b-2 px-1 pb-2.5 text-lede transition-colors ${
        mode === value
          ? "border-ink font-semibold text-ink"
          : "border-transparent text-ink-faint hover:text-ink-muted"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="min-h-screen">
      <header className="border-b border-rule bg-surface">
        <div className="mx-auto flex max-w-4xl flex-wrap items-start justify-between gap-x-6 gap-y-2 px-5 py-4">
          <span className="text-title font-bold tracking-tight">medsafe</span>
          <EngineStatus />
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-5 py-8">
        <div className="mb-8">
          <h1 className="mb-3 max-w-measure text-display font-bold">
            Find out what your medicines are, and whether they clash.
          </h1>
          <p className="max-w-measure font-prose text-lede leading-relaxed text-ink-muted">
            Type the name off the pack — the brand name is fine. This tells you which
            ingredient it is, whether a cheaper equivalent exists, and what is known about
            taking it alongside everything else you take.
          </p>
        </div>

        {/* Stated up front rather than as a footnote. A tool that reports coverage gaps
            honestly has to be equally honest about its own limits, and a reader who learns
            them only after a worrying result has learnt them too late. */}
        <section className="mb-8 rounded-sheet border border-rule bg-surface p-5">
          <h2 className="mb-3 text-base font-semibold">
            Before you use this, two things
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <p className="max-w-measure font-prose text-base leading-relaxed text-ink-muted">
              <span className="font-semibold text-ink">
                It cannot tell you a prescription is safe.
              </span>{" "}
              It searches one published list of known interactions. That list does not
              cover every medicine, and when it does not cover yours this page says so
              rather than staying quiet.
            </p>
            <p className="max-w-measure font-prose text-base leading-relaxed text-ink-muted">
              <span className="font-semibold text-ink">
                Never stop or swap a medicine because of this page.
              </span>{" "}
              It is here so you can ask a better question at the pharmacy counter, not so
              you can skip it.
            </p>
          </div>
        </section>

        <div
          role="tablist"
          aria-label="What do you want to do"
          className="mb-6 flex gap-6 border-b border-rule"
        >
          {tab("substitute", "Look up one medicine")}
          {tab("check", "Check my whole list")}
        </div>

        <div className="mb-8">
          {mode === "substitute" ? (
            <SingleDrugInput
              onSubmit={runResolve}
              pending={pending}
              examples={RESOLVE_EXAMPLES}
            />
          ) : (
            <PrescriptionInput
              drugs={drugs}
              setDrugs={setDrugs}
              onSubmit={runCheck}
              pending={pending}
              examples={CHECK_EXAMPLES}
            />
          )}
        </div>

        <div className="space-y-5">
          {error ? <ErrorSheet error={error} /> : null}

          {mode === "substitute" && !error && resolveResult ? (
            <>
              <Resolution result={resolveResult} />
              {resolveResult.substitution ? (
                <Substitution data={resolveResult.substitution} />
              ) : null}
            </>
          ) : null}

          {mode === "check" && !error && checkResult ? (
            <Interactions result={checkResult} />
          ) : null}
        </div>

        <footer className="mt-12 border-t border-rule pt-5">
          <p className="max-w-measure font-prose text-tiny leading-relaxed text-ink-faint">
            This is a decision-support tool, not a diagnostic or dispensing authority. It
            must not be the sole basis for substituting, taking or withholding any
            medicine. Interaction data is incomplete by construction — nothing found is
            not the same as nothing there.
          </p>
        </footer>
      </main>
    </div>
  );
}
