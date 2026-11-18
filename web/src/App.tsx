import { NavLink, Outlet } from "react-router-dom";

const links = [
  { to: "/", label: "Home" },
  { to: "/explore", label: "Tag Explorer" },
  { to: "/gems", label: "Hidden Gems" },
  { to: "/timelines", label: "Timelines" },
  { to: "/findings", label: "Findings" },
  { to: "/methodology", label: "Methodology" },
];

export function App() {
  return (
    <div className="shell">
      <header className="nav">
        {links.map((l) => (
          <NavLink key={l.to} to={l.to} end={l.to === "/"}>
            {l.label}
          </NavLink>
        ))}
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
