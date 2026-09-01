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
import { Prose } from "@/components/primitives";

type Mode = "substitute" | "check";

const RESOLVE_EXAMPLES = [
  "Amoxicillin 500mg Capsule",
  "Glycomet 500",
  "Ecosprin",
  "hydralazine",
];

const CHECK_EXAMPLES = [
  ["Warfarin", "Ecosprin", "Atorvastatin"],
  ["Metformin", "Omeprazole", "Clopidogrel"],
];

function ErrorSheet({ error }: { error: unknown }) {
  if (error instanceof ApiUnreachableError) {
    return (
      <section className="surface-unchecked p-5">
        <h2 className="mb-2 text-title font-semibold">
          The engine is not answering
        </h2>
        <Prose>
          Nothing is running at {API_BASE_URL}. Start the API, then try again. If
          it is running, add this page&rsquo;s address to CORS_ALLOW_ORIGINS in
          the API environment so the browser is allowed to call it.
        </Prose>
      </section>
    );
  }

  if (error instanceof ApiError) {
    return (
      <section className="surface-unchecked p-5">
        <h2 className="mb-2 text-title font-semibold">
          The engine refused that request
        </h2>
        <Prose>{error.message}</Prose>
        <p className="mt-2 font-mono text-tiny text-ink-faint">
          {error.code} · HTTP {error.status}
        </p>
      </section>
    );
  }

  return (
    <section className="surface-unchecked p-5">
      <h2 className="mb-2 text-title font-semibold">That did not work</h2>
      <Prose>An unexpected error stopped the request. Try again.</Prose>
    </section>
  );
}

export default function Console() {
  const [mode, setMode] = useState<Mode>("substitute");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [resolveResult, setResolveResult] = useState<ResolveResponse | null>(
    null,
  );
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

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
  }

  const tab = (value: Mode, label: string) => (
    <button
      type="button"
      role="tab"
      aria-selected={mode === value}
      onClick={() => switchMode(value)}
      className={`-mb-px border-b-2 px-1 pb-2.5 text-base transition-colors ${
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
        <div className="mx-auto flex max-w-4xl flex-wrap items-baseline justify-between gap-x-6 gap-y-2 px-5 py-4">
          <div className="flex items-baseline gap-3">
            <span className="text-title font-bold tracking-tight">medsafe</span>
            <span className="text-tiny text-ink-faint">
              substitutes and interactions
            </span>
          </div>
          <EngineStatus />
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-5 py-8">
        <div className="mb-8">
          <h1 className="mb-3 max-w-measure text-display font-bold">
            Check what a prescription costs, and what it might do together.
          </h1>
          <Prose>
            Enter a medicine as it is written on the prescription. The engine
            identifies the molecule, finds equivalents that cost less, and
            reports which interactions it has actually checked — and which it
            has not.
          </Prose>
        </div>

        <div
          role="tablist"
          aria-label="What do you want to do"
          className="mb-5 flex gap-6 border-b border-rule"
        >
          {tab("substitute", "Find a substitute")}
          {tab("check", "Check a prescription")}
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
            Decision support only. This is not a diagnostic or dispensing
            authority, and it must not be the sole basis for substituting or
            withholding any medicine. Interaction data is incomplete by
            construction — an absent interaction is not evidence of safety.
          </p>
        </footer>
      </main>
    </div>
  );
}
