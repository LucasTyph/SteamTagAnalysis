import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider, createHashRouter } from "react-router-dom";
import { App } from "./App";
import { Home } from "./pages/Home";
import { Loading } from "./components/Loading";
import { NotFound, RouteError } from "./pages/RouteError";
import "./styles.css";
import "./pages.css";

// Data-heavy pages (DuckDB-WASM, charts) load on demand.
const TagExplorer = lazy(() => import("./pages/TagExplorer").then((m) => ({ default: m.TagExplorer })));
const Timelines = lazy(() => import("./pages/Timelines").then((m) => ({ default: m.Timelines })));
const Releases = lazy(() => import("./pages/Releases").then((m) => ({ default: m.Releases })));
const Findings = lazy(() => import("./pages/Findings").then((m) => ({ default: m.Findings })));
const Methodology = lazy(() => import("./pages/Methodology").then((m) => ({ default: m.Methodology })));
const Games = lazy(() => import("./pages/Games").then((m) => ({ default: m.Games })));
const WriteUp = lazy(() => import("./pages/WriteUp").then((m) => ({ default: m.WriteUp })));
const HiddenGems = lazy(() => import("./pages/HiddenGems").then((m) => ({ default: m.HiddenGems })));
const page = (el: JSX.Element) => <Suspense fallback={<Loading label="Loading page…" />}>{el}</Suspense>;

// Hash routing keeps deep links working on GitHub Pages with no server config.
const router = createHashRouter([
  {
    path: "/",
    element: <App />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Home /> },
      { path: "explore", element: page(<TagExplorer />) },
      { path: "gems", element: page(<HiddenGems />) },
      { path: "games", element: page(<Games />) },
      { path: "games/:appid", element: page(<Games />) },
      { path: "timelines", element: page(<Timelines />) },
      { path: "releases", element: page(<Releases />) },
      { path: "findings", element: page(<Findings />) },
      { path: "methodology", element: page(<Methodology />) },
      { path: "writeup", element: page(<WriteUp />) },
      { path: "*", element: <NotFound /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
