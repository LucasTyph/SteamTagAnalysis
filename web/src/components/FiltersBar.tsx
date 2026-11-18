import type { Filters } from "../data/queries";

const YEARS = Array.from({ length: 2026 - 2006 + 1 }, (_, i) => 2006 + i);

interface Props {
  filters: Filters;
  onChange: (f: Filters) => void;
}

export function FiltersBar({ filters, onChange }: Props) {
  const set = <K extends keyof Filters>(k: K, v: Filters[K]) => onChange({ ...filters, [k]: v });
  const year = (v: string) => (v === "" ? null : Number(v));
  return (
    <div className="filters" role="group" aria-label="Filters">
      <label>
        From
        <select value={filters.yearFrom ?? ""} onChange={(e) => set("yearFrom", year(e.target.value))}>
          <option value="">any year</option>
          {YEARS.map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>
      </label>
      <label>
        To
        <select value={filters.yearTo ?? ""} onChange={(e) => set("yearTo", year(e.target.value))}>
          <option value="">any year</option>
          {YEARS.map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>
      </label>
      <label>
        Price
        <select
          value={filters.price}
          onChange={(e) => set("price", e.target.value as Filters["price"])}
        >
          <option value="any">any</option>
          <option value="paid">paid</option>
          <option value="free">free to play</option>
        </select>
      </label>
      <label>
        Early access
        <select
          value={filters.earlyAccess}
          onChange={(e) => set("earlyAccess", e.target.value as Filters["earlyAccess"])}
        >
          <option value="any">include</option>
          <option value="exclude">exclude</option>
          <option value="only">only</option>
        </select>
      </label>
      <label>
        Min. reviews
        <select
          value={filters.minReviews}
          onChange={(e) => set("minReviews", Number(e.target.value))}
        >
          {[20, 100, 500, 2000].map((n) => (
            <option key={n} value={n}>
              {n}+
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
