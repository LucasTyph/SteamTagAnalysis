import { useEffect } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

const links = [
  { to: "/explore", label: "Tag Explorer" },
  { to: "/gems", label: "Hidden Gems" },
  { to: "/timelines", label: "Timelines" },
  { to: "/findings", label: "Findings" },
  { to: "/methodology", label: "Methodology" },
];

export function App() {
  const { pathname } = useLocation();
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
      <main>
        <Outlet />
      </main>
      <footer className="footer muted">
        Data from the Steam store, collected Nov 2026. Not affiliated with Valve.
      </footer>
    </div>
  );
}
