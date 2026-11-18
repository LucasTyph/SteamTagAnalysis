import { Link, isRouteErrorResponse, useRouteError } from "react-router-dom";

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
