import { request } from "./client";
import type { StudyViewingStatus, ViewingStatusMap } from "../types/status";

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
