import { Link, isRouteErrorResponse, useRouteError } from "react-router-dom";
import { usePageMeta } from "../lib/pageMeta";

export function RouteError() {
  const error = useRouteError();
  const message = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : error instanceof Error
      ? error.message
      : "Unknown error";
  return (
    <div className="shell">
      <section className="page">
        <h1>Something broke</h1>
        <p className="lede">{message}</p>
        <p>
          <Link to="/">Back to the start</Link>
        </p>
      </section>
    </div>
  );
}

export function NotFound() {
  usePageMeta("Page not found");
  return (
    <section className="page">
      <h1>Page not found</h1>
      <p className="lede">
        That page doesn&apos;t exist. Try the <Link to="/explore">Tag Explorer</Link> or the{" "}
        <Link to="/findings">findings</Link>.
      </p>
    </section>
  );
}
