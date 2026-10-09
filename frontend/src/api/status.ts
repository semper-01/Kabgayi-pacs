import { request } from "./client";
import type { StudyViewingStatus, ViewingStatusMap } from "../types/status";

export interface ViewingSession {
  session_id: string;
  heartbeat_interval_seconds: number;
}

export function openViewingSession(
  authorization: string,
  studyId: string,
): Promise<ViewingSession> {
  return request<ViewingSession>("/api/status/open/", authorization, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ study_id: studyId }),
  });
}

export function heartbeatViewingSession(
  authorization: string,
  sessionId: string,
): Promise<{ session_id: string; last_heartbeat_at: string }> {
  return request("/api/status/heartbeat/", authorization, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
}

export function closeViewingSession(
  authorization: string,
  sessionId: string,
  keepalive = false,
): Promise<{ session_id: string; active: boolean }> {
  return request("/api/status/close/", authorization, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
    keepalive,
  });
}

export async function getViewingStatuses(
  authorization: string,
  studyIds: string[],
): Promise<ViewingStatusMap> {
  if (studyIds.length === 0) {
    return {};
  }

  const params = new URLSearchParams({ study_ids: studyIds.join(",") });
  const response = await request<{ results: StudyViewingStatus[] }>(
    `/api/status/?${params.toString()}`,
    authorization,
  );

  return Object.fromEntries(
    response.results.map(({ study_id, being_viewed }) => [
      study_id,
      being_viewed ? "being-viewed" : "available",
    ]),
  );
}
