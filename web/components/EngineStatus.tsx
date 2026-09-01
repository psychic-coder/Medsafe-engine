"use client";

import { useEffect, useState } from "react";
import { fetchReadiness } from "@/lib/api";
import type { Readiness } from "@/lib/types";

type State =
  | { kind: "loading" }
  | { kind: "unreachable" }
  | { kind: "loaded"; readiness: Readiness };

/**
 * Live engine state in the header.
 *
 * This is not decoration. Two of the engine's safety controls fail *open* — a missing
 * confusable-pair blocklist leaves fuzzy output unguarded, and a missing coverage manifest makes
 * every pair report as unchecked. In both cases the engine still answers, so the only way a user
 * can know they are looking at degraded output is if the console says so up front.
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
    return <span className="text-tiny text-ink-faint">Checking engine…</span>;
  }

  if (state.kind === "unreachable") {
    return (
      <span className="inline-flex items-center gap-2 text-tiny text-severe">
        <span aria-hidden className="h-2 w-2 rounded-full bg-severe" />
        Engine unreachable
      </span>
    );
  }

  const { readiness } = state;
  const molecules = readiness.counts?.nodes?.Molecule ?? 0;
  const degraded =
    !readiness.blocklist_loaded || !readiness.coverage_manifest_loaded;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-tiny">
      <span
        className={`inline-flex items-center gap-2 ${
          readiness.ready ? "text-verified" : "text-severe"
        }`}
      >
        <span
          aria-hidden
          className={`h-2 w-2 rounded-full ${
            readiness.ready ? "bg-verified" : "bg-severe"
          }`}
        />
        {readiness.ready ? "Engine ready" : "Engine not ready"}
      </span>

      <span className="text-ink-faint">
        {molecules.toLocaleString()} molecules · {readiness.blocklist_pairs}{" "}
        confusable pairs · {readiness.graph_backend}
      </span>

      {degraded ? (
        <span className="text-caution">
          {!readiness.blocklist_loaded
            ? "Confusable-pair guard is not loaded"
            : "Coverage manifest is not loaded"}
        </span>
      ) : null}
    </div>
  );
}
