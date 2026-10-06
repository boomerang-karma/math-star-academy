import { ApiError } from "../api/client";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p className="muted" role="status">
      {label}
    </p>
  );
}

function describe(error: unknown): { title: string; detail: string; requestId: string | null } {
  if (error instanceof ApiError) {
    if (error.status === 403) {
      const missing = error.details?.["missing"];
      return {
        title: "You do not have access to this",
        detail: Array.isArray(missing) ? `Missing permission: ${missing.join(", ")}` : error.message,
        requestId: error.requestId,
      };
    }
    if (error.status === 404) {
      return {
        title: "Not found",
        detail: "It does not exist, or it is outside your territory.",
        requestId: error.requestId,
      };
    }
    return { title: `Request failed (${error.status})`, detail: error.message, requestId: error.requestId };
  }
  return {
    title: "Something went wrong",
    detail: error instanceof Error ? error.message : String(error),
    requestId: null,
  };
}

export function ErrorNotice({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { title, detail, requestId } = describe(error);
  return (
    <div className="notice notice-error" role="alert">
      <strong>{title}</strong>
      <p>{detail}</p>
      {requestId ? <p className="muted small">Request id: {requestId}</p> : null}
      {onRetry ? (
        <button type="button" className="button" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}
