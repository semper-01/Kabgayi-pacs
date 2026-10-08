import { requestFile } from "./client";

export type ExportFormat = "dicom" | "png" | "jpeg" | "pdf" | "csv";

export function exportStudy(
  authorization: string,
  studyId: string,
  format: ExportFormat,
): Promise<void> {
  return requestFile(
    `/api/studies/${encodeURIComponent(studyId)}/export/?format=${format}`,
    authorization,
  );
}
