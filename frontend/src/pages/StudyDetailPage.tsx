import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { exportStudy, type ExportFormat } from "../api/exports";
import { getErrorMessage } from "../api/client";
import { getViewingStatuses } from "../api/status";
import { findStudy } from "../api/studies";
import { useAuth } from "../auth/AuthContext";
import { ViewingStatusBadge } from "../components/status/ViewingStatusBadge";
import type { Study, ViewingStatus } from "../types/study";

const EXPORTS: { format: ExportFormat; label: string }[] = [
  { format: "dicom", label: "DICOM" },
  { format: "png", label: "PNG" },
  { format: "jpeg", label: "JPEG" },
  { format: "pdf", label: "PDF" },
  { format: "csv", label: "CSV" },
];

interface StudyLocationState {
  study?: Study;
}

export function StudyDetailPage() {
  const { studyId = "" } = useParams();
  const location = useLocation();
  const { authorization } = useAuth();
  const routeStudy = (location.state as StudyLocationState | null)?.study;
  const [study, setStudy] = useState<Study | null>(
    routeStudy?.study_id === studyId ? routeStudy : null,
  );
  const [viewingStatus, setViewingStatus] = useState<ViewingStatus>("unavailable");
  const [loading, setLoading] = useState(!routeStudy || routeStudy.study_id !== studyId);
  const [statusWarning, setStatusWarning] = useState(false);
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState<ExportFormat | null>(null);
  const [exportError, setExportError] = useState("");

  useEffect(() => {
    if (!authorization || !studyId) return;
    let active = true;
    const initialStudy = routeStudy?.study_id === studyId ? routeStudy : null;
    setStudy(initialStudy);
    setLoading(!initialStudy);
    setError("");

    const studyRequest = initialStudy
      ? Promise.resolve(initialStudy)
      : findStudy(authorization, studyId);

    studyRequest
      .then(async (result) => {
        if (!active) return;
        if (!result) {
          setError("Study could not be found in the available worklist.");
          return;
        }
        setStudy(result);
        try {
          const statuses = await getViewingStatuses(authorization, [studyId]);
          if (active) {
            setViewingStatus(statuses[studyId] ?? "unavailable");
            setStatusWarning(false);
          }
        } catch {
          if (active) {
            setViewingStatus("unavailable");
            setStatusWarning(true);
          }
        }
      })
      .catch((requestError: unknown) => {
        if (active) setError(getErrorMessage(requestError, "Study could not be loaded."));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [authorization, routeStudy, studyId]);

  async function download(format: ExportFormat) {
    if (!authorization || exporting) return;
    setExporting(format);
    setExportError("");
    try {
      await exportStudy(authorization, studyId, format);
    } catch (requestError) {
      setExportError(getErrorMessage(requestError, "Export failed."));
    } finally {
      setExporting(null);
    }
  }

  return (
    <section className="detail-page">
      <Link className="back-link" to="/">← Back to studies</Link>
      <div className="page-heading detail-heading">
        <div>
          <p className="eyebrow">Study details</p>
          <h1>{study?.patient_name || "Study record"}</h1>
          <p className="page-subtitle">Study ID: {studyId}</p>
        </div>
        {study && <ViewingStatusBadge status={viewingStatus} />}
      </div>

      {loading && <p className="loading-message" role="status">Loading study details…</p>}
      {error && <p className="error-message" role="alert">{error}</p>}
      {statusWarning && study && (
        <p className="notice-message" role="status">Viewing status is temporarily unavailable.</p>
      )}
      {study && !loading && (
        <>
          <section className="detail-section" aria-labelledby="patient-info-heading">
            <h2 id="patient-info-heading">Patient information</h2>
            <dl className="detail-grid">
              <DetailItem label="Patient name" value={study.patient_name} />
              <DetailItem label="Patient ID" value={study.patient_id} />
            </dl>
          </section>
          <section className="detail-section" aria-labelledby="study-info-heading">
            <h2 id="study-info-heading">Study information</h2>
            <dl className="detail-grid">
              <DetailItem label="Study date" value={formatStudyDate(study.study_date)} />
              <DetailItem label="Modality" value={study.modality} />
              <DetailItem label="Accession number" value={study.accession_number} />
              <DetailItem label="Study description" value={study.study_description} />
              <DetailItem label="Study instance UID" value={study.study_instance_uid} />
            </dl>
          </section>
          <section className="detail-section viewer-entry-section" aria-label="Diagnostic image viewing">
            <Link
              className="button button-primary"
              to={`/viewer/${encodeURIComponent(study.study_id)}`}
              state={{ study }}
            >
              Open Viewer
            </Link>
          </section>
          <section className="detail-section export-section" aria-labelledby="export-heading">
            <h2 id="export-heading">Export study</h2>
            <p className="section-help">Download an export generated by the PACS server.</p>
            {exportError && <p className="error-message" role="alert">{exportError}</p>}
            <div className="export-actions">
              {EXPORTS.map(({ format, label }) => (
                <button
                  className="button button-secondary"
                  type="button"
                  key={format}
                  onClick={() => void download(format)}
                  disabled={exporting !== null}
                >
                  {exporting === format ? `Preparing ${label}…` : `Export ${label}`}
                </button>
              ))}
            </div>
          </section>
        </>
      )}
    </section>
  );
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-item">
      <dt>{label}</dt>
      <dd>{value || "—"}</dd>
    </div>
  );
}

function formatStudyDate(value: string): string {
  if (!/^\d{8}$/.test(value)) return value || "—";
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
}
