import { request } from "./client";
import type { Study, StudyFilters, StudyPage } from "../types/study";

export const WORKLIST_PAGE_SIZE = 20;
const DETAIL_LOOKUP_PAGE_SIZE = 100;

export interface StudyQuery extends Partial<StudyFilters> {
  limit: number;
  offset: number;
}

export function getStudies(
  authorization: string,
  query: StudyQuery,
): Promise<StudyPage> {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      params.set(key, String(value));
    }
  });
  return request<StudyPage>(`/api/studies/?${params.toString()}`, authorization);
}

export async function findStudy(
  authorization: string,
  studyId: string,
): Promise<Study | undefined> {
  let offset = 0;
  let total = Number.POSITIVE_INFINITY;

  while (offset < total) {
    const page = await getStudies(authorization, {
      limit: DETAIL_LOOKUP_PAGE_SIZE,
      offset,
    });
    total = page.count;
    const study = page.results.find((result) => result.study_id === studyId);
    if (study) {
      return study;
    }
    offset += page.results.length;
    if (page.results.length === 0) {
      break;
    }
  }

  return undefined;
}
