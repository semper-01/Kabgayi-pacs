import type { ViewingStatus } from "../../types/study";

const STATUS_LABELS: Record<ViewingStatus, string> = {
  available: "Available",
  "being-viewed": "Being viewed",
  unavailable: "Status unavailable",
};

export function ViewingStatusBadge({ status }: { status: ViewingStatus }) {
  return (
    <span className={`status-badge status-${status}`} role="status">
      <span className="status-dot" aria-hidden="true" />
      {STATUS_LABELS[status]}
    </span>
  );
}
