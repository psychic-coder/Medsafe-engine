"use client";

import { useEffect, useState } from "react";
import { fetchReadiness } from "@/lib/api";
import type { Readiness } from "@/lib/types";

type State =
  | { kind: "loading" }
  | { kind: "unreachable" }
  | { kind: "loaded"; readiness: Readiness };

/**
 * Live engine state.
 *
 * This is not decoration. Three of the engine's data files fail *open* — without the coverage
 * manifest no pair can be reported as checked, without the blocklist fuzzy output is unguarded,
 * and without the combination index multi-ingredient packs do not resolve. In every case the
 * engine still answers, so the only way a user can know they are looking at degraded output is if
 * the page says so.
 *
 * It says so in the user's terms. "Coverage manifest is not loaded" told a patient nothing about
 * whether to trust the screen; the point of the warning is that this session cannot confirm
 * anything was checked, so that is what it now says.
 */
export function EngineStatus() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetchReadiness()
      .then((readiness) => {
        if (!cancelled) setState({ kind: "loaded", readiness });
      })
      .catch(() => {
        if (!cancelled) setState({ kind: "unreachable" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.kind === "loading") {
    return <span className="text-tiny text-ink-faint">Checking…</span>;
  }

  if (state.kind === "unreachable") {
    return (
      <span className="inline-flex items-center gap-2 text-tiny text-severe">
        <span aria-hidden className="h-2 w-2 rounded-full bg-severe" />
        Not connected — results are unavailable
      </span>
    );
  }

  const { readiness } = state;
  const warnings: string[] = [];
  if (!readiness.coverage_manifest_loaded) {
    warnings.push(
      "Interaction data is missing on this server, so nothing on this page can confirm a combination was checked.",
    );
  }
  if (!readiness.blocklist_loaded) {
    warnings.push(
      "The look-alike name guard is not loaded, so similar names are not being screened.",
    );
  }
  if (!readiness.combinations_loaded) {
    warnings.push("Combination pack names will not be recognised on this server.");
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <span
        className={`inline-flex items-center gap-2 text-tiny ${
          readiness.ready ? "text-verified" : "text-severe"
        }`}
      >
        <span
          aria-hidden
          className={`h-2 w-2 rounded-full ${
            readiness.ready ? "bg-verified" : "bg-severe"
          }`}
        />
        {readiness.ready ? "Connected" : "Not ready"}
      </span>
      {warnings.map((warning) => (
        <span key={warning} className="max-w-sm text-right text-tiny text-caution">
          {warning}
        </span>
      ))}
    </div>
  );
}
