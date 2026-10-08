export interface Study {
  study_id: string;
  patient_name: string;
  patient_id: string;
  study_instance_uid: string;
  accession_number: string;
  study_date: string;
  modality: string;
  study_description: string;
}

export interface StudyPage {
  count: number;
  next: string | null;
  previous: string | null;
  results: Study[];
}

export interface StudyFilters {
  patient_name: string;
  patient_id: string;
  accession_number: string;
  study_date: string;
  modality: string;
  study_description: string;
}

export type ViewingStatus = "available" | "being-viewed" | "unavailable";

export const EMPTY_FILTERS: StudyFilters = {
  patient_name: "",
  patient_id: "",
  accession_number: "",
  study_date: "",
  modality: "",
  study_description: "",
};
