export function Loading({ label = "Loading data…" }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}
    </div>
  );
}

export function ErrorNote({ error }: { error: Error }) {
  return (
    <div className="error" role="alert">
      Something went wrong loading the data: {error.message}
    </div>
  );
}
