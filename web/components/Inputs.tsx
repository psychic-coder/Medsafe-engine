"use client";

import { useState, type FormEvent, type KeyboardEvent } from "react";

const BUTTON =
  "shrink-0 whitespace-nowrap rounded-control bg-ink px-5 py-2.5 text-base font-medium text-paper transition-colors hover:bg-ink-muted disabled:cursor-not-allowed disabled:opacity-40";

const INPUT =
  "w-full rounded-control border border-rule-strong bg-surface px-3.5 py-2.5 text-base placeholder:text-ink-faint focus:border-ink";

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

  function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = value.trim();
    if (trimmed) onSubmit(trimmed);
  }

  return (
    <div>
      <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row">
        <label htmlFor="drug" className="sr-only">
          Medicine as written on the prescription
        </label>
        <input
          id="drug"
          className={INPUT}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Amoxicillin 500mg Capsule"
          autoComplete="off"
          maxLength={300}
        />
        <button type="submit" className={BUTTON} disabled={pending || !value.trim()}>
          {pending ? "Looking up…" : "Find substitutes"}
        </button>
      </form>

      <p className="mt-2.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-tiny text-ink-faint">
        Try
        {examples.map((example) => (
          <button
            key={example}
            type="button"
            className="rounded-control border border-rule px-2 py-0.5 text-ink-muted transition-colors hover:border-ink hover:text-ink"
            onClick={() => {
              setValue(example);
              onSubmit(example);
            }}
          >
            {example}
          </button>
        ))}
      </p>
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
  setDrugs: (drugs: string[]) => void;
  onSubmit: () => void;
  pending: boolean;
  examples: string[][];
}) {
  const [value, setValue] = useState("");

  function add(raw: string) {
    const entry = raw.trim();
    if (!entry || drugs.includes(entry) || drugs.length >= 50) return;
    setDrugs([...drugs, entry]);
    setValue("");
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      add(value);
    } else if (event.key === "Backspace" && !value && drugs.length) {
      setDrugs(drugs.slice(0, -1));
    }
  }

  return (
    <div>
      <div className="flex flex-col gap-2 sm:flex-row">
        <div className="flex-1">
          <label htmlFor="prescription" className="sr-only">
            Add a medicine to the prescription
          </label>
          <input
            id="prescription"
            className={INPUT}
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={onKeyDown}
            onBlur={() => add(value)}
            placeholder={
              drugs.length ? "Add another medicine" : "Warfarin"
            }
            autoComplete="off"
            maxLength={300}
          />
        </div>
        <button
          type="button"
          className={BUTTON}
          onClick={onSubmit}
          disabled={pending || drugs.length < 2}
        >
          {pending ? "Checking…" : "Check prescription"}
        </button>
      </div>

      {drugs.length > 0 ? (
        <ul className="mt-3 flex flex-wrap gap-2">
          {drugs.map((drug) => (
            <li
              key={drug}
              className="inline-flex items-center gap-2 rounded-control border border-rule bg-surface py-1 pl-3 pr-1.5 text-tiny"
            >
              {drug}
              <button
                type="button"
                aria-label={`Remove ${drug}`}
                className="rounded-control px-1.5 text-ink-faint transition-colors hover:bg-paper hover:text-ink"
                onClick={() => setDrugs(drugs.filter((d) => d !== drug))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      <p className="mt-2.5 text-tiny text-ink-faint">
        {drugs.length === 1
          ? "Add at least one more medicine to check for interactions."
          : "Press Enter after each medicine."}
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-tiny text-ink-faint">
        Or load
        {examples.map((example) => (
          <button
            key={example.join()}
            type="button"
            className="rounded-control border border-rule px-2 py-0.5 text-ink-muted transition-colors hover:border-ink hover:text-ink"
            onClick={() => setDrugs(example)}
          >
            {example.join(" + ")}
          </button>
        ))}
      </div>
    </div>
  );
}
