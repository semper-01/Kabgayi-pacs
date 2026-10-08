import type { ViewingStatus } from "./study";

export interface StudyViewingStatus {
  study_id: string;
  being_viewed: boolean;
}

export type ViewingStatusMap = Record<string, ViewingStatus>;
