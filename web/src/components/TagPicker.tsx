import { useMemo, useRef, useState } from "react";
import type { Tag } from "../data/queries";
import type { TagIndex } from "../lib/hooks";

interface Props {
  tags: TagIndex;
  selected: Tag[];
  onChange: (tags: Tag[]) => void;
  max?: number;
  placeholder?: string;
}

export function TagPicker({ tags, selected, onChange, max = 4, placeholder }: Props) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const full = selected.length >= max;

  const suggestions = useMemo(() => {
    const taken = new Set(selected.map((t) => t.tagid));
    const q = text.trim().toLowerCase();
    return tags.list
      .filter((t) => !taken.has(t.tagid) && (!q || t.name.toLowerCase().includes(q)))
      .sort((a, b) => {
        // Prefix matches first, then by popularity
        const pa = q && a.name.toLowerCase().startsWith(q) ? 0 : 1;
        const pb = q && b.name.toLowerCase().startsWith(q) ? 0 : 1;
        return pa - pb || b.n_games - a.n_games;
      })
      .slice(0, 8);
  }, [tags, selected, text]);

  const add = (t: Tag) => {
    onChange([...selected, t]);
    setText("");
    setActive(0);
    inputRef.current?.focus();
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((a) => Math.min(a + 1, suggestions.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter" && open && suggestions[active]) {
      e.preventDefault();
      add(suggestions[active]);
    } else if (e.key === "Backspace" && !text && selected.length) {
      onChange(selected.slice(0, -1));
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div className="tag-picker">
      <div className="tag-picker-box" onClick={() => inputRef.current?.focus()}>
        {selected.map((t) => (
          <span className="chip chip-selected" key={t.tagid}>
            {t.name}
            <button
              type="button"
              aria-label={`Remove ${t.name}`}
              onClick={(e) => {
                e.stopPropagation();
                onChange(selected.filter((s) => s.tagid !== t.tagid));
              }}
            >
              ×
            </button>
          </span>
        ))}
        {!full && (
          <input
            ref={inputRef}
            value={text}
            placeholder={selected.length ? "Add another tag…" : (placeholder ?? "Type a tag…")}
            onChange={(e) => {
              setText(e.target.value);
              setOpen(true);
              setActive(0);
            }}
            onFocus={() => setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 120)}
            onKeyDown={onKeyDown}
            role="combobox"
            aria-expanded={open}
            aria-controls="tag-suggestions"
            aria-autocomplete="list"
          />
        )}
      </div>
      {open && !full && suggestions.length > 0 && (
        <ul className="tag-suggestions" id="tag-suggestions" role="listbox">
          {suggestions.map((t, i) => (
            <li
              key={t.tagid}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : undefined}
              onMouseDown={(e) => {
                e.preventDefault();
                add(t);
              }}
              onMouseEnter={() => setActive(i)}
            >
              <span>{t.name}</span>
              <span className="muted">{t.n_games.toLocaleString("en-US")} games</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
