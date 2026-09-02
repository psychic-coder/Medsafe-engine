"use client";

import { useEffect, useId, useRef, useState } from "react";
import { fetchSuggestions } from "@/lib/api";
import type { Suggestion } from "@/lib/types";

/**
 * A medicine-name box that suggests as you type.
 *
 * This is the single largest usability lever in the console, and it is worth being clear about
 * why. Almost every "we could not identify that" is a spelling problem, not a knowledge problem —
 * and the person who hit it has no way to find the right spelling, because the thing they would
 * search with is the thing they got wrong. Suggesting while they type means they pick a name the
 * engine is guaranteed to resolve, so the dead end never happens.
 *
 * Two details that carry meaning rather than polish:
 *
 * - **Look-alike names are shown with a warning, never hidden.** The engine's blocklist knows that
 *   prednisone and prednisolone are confusable. The matcher's rule is to refuse both, because a
 *   machine must not choose. Here a person chooses, with the box in their hand, so hiding the row
 *   would remove their own medicine from the list and tell them nothing. The warning is the useful
 *   half of the blocklist for a reader who can actually check the spelling.
 * - **An "other name" row names the ingredient it stands for.** Someone typing "Ecosprin" needs to
 *   see that it *is* acetylsalicylic acid, not be offered the two as rival options.
 */

const KIND_LABEL: Record<Suggestion["kind"], string> = {
  ingredient: "Ingredient",
  other_name: "Also called",
  combination: "Combination pack",
};

export function MedicineInput({
  value,
  onChange,
  onSubmit,
  placeholder = "Type a medicine name",
  label,
  submitLabel,
  pending = false,
  autoFocus = false,
}: {
  value: string;
  onChange: (next: string) => void;
  onSubmit: (value: string) => void;
  placeholder?: string;
  label: string;
  submitLabel: string;
  pending?: boolean;
  autoFocus?: boolean;
}) {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const listId = useId();
  const boxRef = useRef<HTMLDivElement>(null);
  // Set while a suggestion is being applied, so the resulting value change does not immediately
  // reopen the list with the very name the user just picked.
  const justPicked = useRef(false);

  useEffect(() => {
    if (justPicked.current) {
      justPicked.current = false;
      return;
    }
    const query = value.trim();
    const controller = new AbortController();

    // Clearing goes through the same debounced path as fetching rather than being applied
    // synchronously. Setting state directly in the effect body makes React re-render before the
    // effect settles, and it also made a short query clear the list on a different schedule from
    // the one that repopulates it — so deleting back to one character flickered.
    const timer = setTimeout(() => {
      if (query.length < 2) {
        setSuggestions([]);
        setNote(null);
        setActive(-1);
        return;
      }
      fetchSuggestions(query, controller.signal).then((response) => {
        setSuggestions(response.suggestions);
        setNote(response.note);
        setActive(-1);
      });
    }, 140);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [value]);

  useEffect(() => {
    function onPointerDown(event: MouseEvent) {
      if (!boxRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, []);

  const visible = open && suggestions.length > 0;

  function choose(suggestion: Suggestion) {
    justPicked.current = true;
    onChange(suggestion.label);
    setOpen(false);
    setSuggestions([]);
    onSubmit(suggestion.label);
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (!visible) {
      if (event.key === "Enter") {
        event.preventDefault();
        onSubmit(value);
      }
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((index) => (index + 1) % suggestions.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => (index <= 0 ? suggestions.length - 1 : index - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (active >= 0) choose(suggestions[active]);
      else {
        setOpen(false);
        onSubmit(value);
      }
    }
  }

  return (
    <div ref={boxRef} className="relative">
      <label htmlFor={`${listId}-input`} className="mb-2 block text-base font-medium">
        {label}
      </label>
      <div className="flex flex-wrap gap-2">
        <input
          id={`${listId}-input`}
          type="text"
          role="combobox"
          aria-expanded={visible}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={
            active >= 0 ? `${listId}-option-${active}` : undefined
          }
          autoComplete="off"
          autoFocus={autoFocus}
          value={value}
          placeholder={placeholder}
          onChange={(event) => {
            onChange(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          className="min-w-0 flex-1 rounded-control border border-rule-strong bg-surface px-3.5 py-3 text-lede placeholder:text-ink-faint"
        />
        <button
          type="button"
          onClick={() => {
            setOpen(false);
            onSubmit(value);
          }}
          disabled={pending || !value.trim()}
          className="rounded-control bg-ink px-5 py-3 text-base font-semibold text-paper disabled:opacity-40"
        >
          {pending ? "Checking…" : submitLabel}
        </button>
      </div>

      {visible ? (
        <div className="absolute z-20 mt-1.5 w-full overflow-hidden rounded-sheet border border-rule-strong bg-surface shadow-lg">
          <ul id={listId} role="listbox" aria-label="Medicine name suggestions">
            {suggestions.map((suggestion, index) => (
              <li
                key={`${suggestion.kind}-${suggestion.label}`}
                id={`${listId}-option-${index}`}
                role="option"
                aria-selected={index === active}
                onMouseEnter={() => setActive(index)}
                onMouseDown={(event) => {
                  event.preventDefault();
                  choose(suggestion);
                }}
                className={`cursor-pointer border-b border-rule/60 px-3.5 py-2.5 last:border-b-0 ${
                  index === active ? "bg-paper" : ""
                }`}
              >
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="text-base font-medium">{suggestion.label}</span>
                  <span className="text-tiny text-ink-faint">
                    {KIND_LABEL[suggestion.kind]}
                  </span>
                </div>
                {suggestion.ingredient ? (
                  <p className="mt-0.5 text-tiny text-ink-muted">
                    Contains {suggestion.ingredient}
                  </p>
                ) : null}
                {suggestion.confusable_with.length > 0 ? (
                  <p className="mt-1 flex items-start gap-1.5 text-tiny text-caution">
                    <span aria-hidden className="mt-[3px] inline-block h-2 w-2 shrink-0 rotate-45 border border-caution" />
                    <span>
                      Easy to confuse with{" "}
                      {suggestion.confusable_with.join(", ")}. These are different
                      medicines — check the pack.
                    </span>
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
          {note ? (
            <p className="border-t border-rule bg-caution-wash px-3.5 py-2 font-prose text-tiny text-caution">
              {note}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
