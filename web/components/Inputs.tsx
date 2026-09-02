"use client";

import { useState } from "react";
import { MedicineInput } from "./MedicineInput";

/**
 * The two input modes.
 *
 * Both are built on the same suggesting box, so a name that can be picked in one can be picked in
 * the other, and the "we could not identify that" path is avoided the same way in both.
 */

export function SingleDrugInput({
  onSubmit,
  pending,
  examples,
}: {
  onSubmit: (drug: string) => void;
  pending: boolean;
  examples: string[];
}) {
  const [value, setValue] = useState("");

  return (
    <div>
      <MedicineInput
        label="What medicine do you want to look up?"
        placeholder="Brand name or ingredient — e.g. Ecosprin, or metformin"
        submitLabel="Look it up"
        value={value}
        onChange={setValue}
        onSubmit={(next) => next.trim() && onSubmit(next.trim())}
        pending={pending}
        autoFocus
      />
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="text-tiny text-ink-faint">Or try</span>
        {examples.map((example) => (
          <button
            key={example}
            type="button"
            onClick={() => {
              setValue(example);
              onSubmit(example);
            }}
            className="rounded-control border border-rule bg-surface px-2.5 py-1 text-tiny hover:border-rule-strong"
          >
            {example}
          </button>
        ))}
      </div>
    </div>
  );
}

export function PrescriptionInput({
  drugs,
  setDrugs,
  onSubmit,
  pending,
  examples,
}: {
  drugs: string[];
  setDrugs: (next: string[]) => void;
  onSubmit: () => void;
  pending: boolean;
  examples: string[][];
}) {
  const [value, setValue] = useState("");

  function add(name: string) {
    const trimmed = name.trim();
    if (!trimmed) return;
    if (!drugs.some((drug) => drug.toLowerCase() === trimmed.toLowerCase())) {
      setDrugs([...drugs, trimmed]);
    }
    setValue("");
  }

  return (
    <div>
      <MedicineInput
        label="Add every medicine you take, one at a time"
        placeholder="Brand name or ingredient"
        submitLabel="Add to list"
        value={value}
        onChange={setValue}
        onSubmit={add}
        pending={false}
        autoFocus
      />

      {drugs.length > 0 ? (
        <ul className="mt-4 flex flex-wrap gap-2">
          {drugs.map((drug) => (
            <li
              key={drug}
              className="flex items-center gap-2 rounded-control border border-rule bg-surface py-1 pl-3 pr-1.5 text-base"
            >
              {drug}
              <button
                type="button"
                onClick={() => setDrugs(drugs.filter((item) => item !== drug))}
                aria-label={`Remove ${drug} from the list`}
                className="rounded-control px-1.5 text-ink-faint hover:text-severe"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={onSubmit}
          disabled={pending || drugs.length < 2}
          className="rounded-control bg-ink px-5 py-3 text-base font-semibold text-paper disabled:opacity-40"
        >
          {pending ? "Checking…" : "Check the whole list"}
        </button>
        {drugs.length < 2 ? (
          <span className="text-tiny text-ink-faint">
            Add at least two medicines to compare them against each other.
          </span>
        ) : null}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="text-tiny text-ink-faint">Or load an example</span>
        {examples.map((example) => (
          <button
            key={example.join("+")}
            type="button"
            onClick={() => setDrugs(example)}
            className="rounded-control border border-rule bg-surface px-2.5 py-1 text-tiny hover:border-rule-strong"
          >
            {example.join(" + ")}
          </button>
        ))}
      </div>
    </div>
  );
}
