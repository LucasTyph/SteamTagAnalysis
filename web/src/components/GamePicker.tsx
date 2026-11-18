import { useMemo, useRef, useState } from "react";
import type { TimelineSummary } from "../data/timelines";
import { SERIES_COLORS } from "../lib/colors";

interface Props {
  games: TimelineSummary[];
  selected: TimelineSummary[];
  onChange: (games: TimelineSummary[]) => void;
  max?: number;
}

const norm = (s: string) => s.toLowerCase().normalize("NFKD").replace(/[^\p{L}\p{N} ]/gu, "");

export function GamePicker({ games, selected, onChange, max = 4 }: Props) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const full = selected.length >= max;

  const searchable = useMemo(() => games.map((g) => ({ g, key: norm(g.name) })), [games]);
  const suggestions = useMemo(() => {
    const taken = new Set(selected.map((g) => g.appid));
    const q = norm(text.trim());
    if (!q) return [];
    return searchable
      .filter(({ g, key }) => !taken.has(g.appid) && key.includes(q))
      .sort((a, b) => Number(!a.key.startsWith(q)) - Number(!b.key.startsWith(q)) || b.g.reviews - a.g.reviews)
      .slice(0, 8)
      .map(({ g }) => g);
  }, [searchable, selected, text]);

  const add = (g: TimelineSummary) => {
    onChange([...selected, g]);
    setText("");
    setActive(0);
    inputRef.current?.focus();
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, suggestions.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter" && suggestions[active]) {
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
        {selected.map((g, i) => (
          <span className="chip chip-selected" key={g.appid}>
            <span className="series-dot" style={{ background: SERIES_COLORS[i % SERIES_COLORS.length] }} />
            {g.name}
            <button
              type="button"
              aria-label={`Remove ${g.name}`}
              onClick={(e) => {
                e.stopPropagation();
                onChange(selected.filter((s) => s.appid !== g.appid));
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
            placeholder={selected.length ? "Compare with another game…" : "Search the 1,000 most-reviewed games…"}
            onChange={(e) => {
              setText(e.target.value);
              setOpen(true);
              setActive(0);
            }}
            onFocus={() => setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 120)}
            onKeyDown={onKeyDown}
            role="combobox"
            aria-expanded={open && suggestions.length > 0}
            aria-controls="game-suggestions"
            aria-autocomplete="list"
          />
        )}
      </div>
      {open && !full && suggestions.length > 0 && (
        <ul className="tag-suggestions" id="game-suggestions" role="listbox">
          {suggestions.map((g, i) => (
            <li
              key={g.appid}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : undefined}
              onMouseDown={(e) => {
                e.preventDefault();
                add(g);
              }}
              onMouseEnter={() => setActive(i)}
            >
              <span>{g.name}</span>
              <span className="muted">{g.reviews.toLocaleString("en-US")} reviews</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
