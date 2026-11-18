import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider, createHashRouter } from "react-router-dom";
import { App } from "./App";
import { Placeholder } from "./pages/Placeholder";
import "./styles.css";

// Hash routing keeps deep links working on GitHub Pages with no server config.
const router = createHashRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <Placeholder title="Steam Tag Analysis" /> },
      { path: "explore", element: <Placeholder title="Tag Explorer" /> },
      { path: "gems", element: <Placeholder title="Hidden Gems" /> },
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
