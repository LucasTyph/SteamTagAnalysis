import { useEffect, useRef, useState } from "react";
import { type GameHit, searchGames } from "../data/games";
import { fmtInt } from "../lib/format";

interface Props {
  onPick: (g: GameHit) => void;
  placeholder?: string;
  autoFocus?: boolean;
}

/** Name search over every analysed game (DuckDB-WASM), as an accessible combobox. */
export function GameSearch({ onPick, placeholder = "Search any game…", autoFocus }: Props) {
  const [text, setText] = useState("");
  const [hits, setHits] = useState<GameHit[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [busy, setBusy] = useState(false);
  const [searched, setSearched] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!text.trim()) {
      setHits([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      setBusy(true);
      searchGames(text).then(
        (rows) => {
          if (cancelled) return;
          setHits(rows);
          setSearched(text);
          setActive(0);
          setBusy(false);
        },
        () => !cancelled && setBusy(false),
      );
    }, 120);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [text]);

  const pick = (g: GameHit) => {
    setText("");
    setHits([]);
    setOpen(false);
    onPick(g);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, hits.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter" && hits[active]) {
      e.preventDefault();
      pick(hits[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const showList = open && hits.length > 0;
  return (
    <div className="tag-picker">
      <div className="tag-picker-box" onClick={() => inputRef.current?.focus()}>
        <input
          ref={inputRef}
          value={text}
          placeholder={placeholder}
          autoFocus={autoFocus}
          onChange={(e) => {
            setText(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
          onKeyDown={onKeyDown}
          role="combobox"
          aria-label="Search games"
          aria-expanded={showList}
          aria-controls="game-search-results"
          aria-autocomplete="list"
          aria-busy={busy}
        />
      </div>
      {open && !busy && !hits.length && text.trim() !== "" && searched === text && (
        <p className="muted small search-empty" role="status">
          No game with 20+ reviews matches “{text.trim()}”.
        </p>
      )}
      {showList && (
        <ul className="tag-suggestions" id="game-search-results" role="listbox">
          {hits.map((g, i) => (
            <li
              key={g.appid}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : undefined}
              onMouseDown={(e) => {
                e.preventDefault();
                pick(g);
              }}
              onMouseEnter={() => setActive(i)}
            >
              <span>
                {g.name} {g.year != null && <span className="muted">({g.year})</span>}
              </span>
              <span className="muted">{fmtInt(g.review_count)} reviews</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
