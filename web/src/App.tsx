import { useEffect } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { dataAsOf, loadMeta } from "./data/meta";
import { useAsync } from "./lib/hooks";

const links = [
  { to: "/explore", label: "Tag Explorer" },
  { to: "/gems", label: "Hidden Gems" },
  { to: "/games", label: "Games" },
  { to: "/timelines", label: "Timelines" },
  { to: "/releases", label: "New Releases" },
  { to: "/findings", label: "Findings" },
  { to: "/methodology", label: "Methodology" },
];

export function App() {
  const { pathname } = useLocation();
  const meta = useAsync(loadMeta, []);
  const asOf = dataAsOf(meta.data);
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return (
    <div className="shell">
      <header className="nav">
        <NavLink to="/" end className="brand">
          Steam Tag Analysis
        </NavLink>
        <nav aria-label="Main">
          {links.map((l) => (
            <NavLink key={l.to} to={l.to}>
              {l.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <main id="main" tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="footer muted">
        Data from the Steam store{asOf ? `, as of ${asOf}` : ""}, refreshed monthly. Not affiliated with Valve. ·{" "}
        <NavLink to="/methodology">Methodology</NavLink> ·{" "}
        <a href="https://github.com/LucasTyph/SteamTagAnalysis">Source on GitHub</a>
      </footer>
    </div>
  );
}
