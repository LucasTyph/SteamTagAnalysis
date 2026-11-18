import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider, createHashRouter } from "react-router-dom";
import { App } from "./App";
import { Placeholder } from "./pages/Placeholder";
import { Loading } from "./components/Loading";
import { RouteError } from "./pages/RouteError";
import "./styles.css";

// Data-heavy pages (DuckDB-WASM, charts) load on demand.
const TagExplorer = lazy(() => import("./pages/TagExplorer").then((m) => ({ default: m.TagExplorer })));
const HiddenGems = lazy(() => import("./pages/HiddenGems").then((m) => ({ default: m.HiddenGems })));
const page = (el: JSX.Element) => <Suspense fallback={<Loading label="Loading page…" />}>{el}</Suspense>;

// Hash routing keeps deep links working on GitHub Pages with no server config.
const router = createHashRouter([
  {
    path: "/",
    element: <App />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Placeholder title="Steam Tag Analysis" /> },
      { path: "explore", element: page(<TagExplorer />) },
      { path: "gems", element: page(<HiddenGems />) },
      { path: "timelines", element: <Placeholder title="Review Timelines" /> },
      { path: "findings", element: <Placeholder title="Findings" /> },
      { path: "methodology", element: <Placeholder title="Methodology" /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
