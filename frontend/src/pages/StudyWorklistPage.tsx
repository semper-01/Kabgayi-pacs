import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getErrorMessage } from "../api/client";
import { getViewingStatuses } from "../api/status";
import { getStudies, WORKLIST_PAGE_SIZE } from "../api/studies";
import { useAuth } from "../auth/AuthContext";
import { StudySearchForm } from "../components/search/StudySearchForm";
import { ViewingStatusBadge } from "../components/status/ViewingStatusBadge";
import {
  EMPTY_FILTERS,
  type Study,
  type StudyFilters,
  type StudyPage,
  type ViewingStatus,
} from "../types/study";

export function StudyWorklistPage() {
  const { authorization } = useAuth();
  const [filters, setFilters] = useState<StudyFilters>({ ...EMPTY_FILTERS });
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<StudyPage | null>(null);
  const [statuses, setStatuses] = useState<Record<string, ViewingStatus>>({});
  const [loading, setLoading] = useState(true);
  const [statusWarning, setStatusWarning] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!authorization) return;
    let active = true;
    setLoading(true);
    setError("");
    getStudies(authorization, { ...filters, limit: WORKLIST_PAGE_SIZE, offset })
      .then(async (result) => {
        if (!active) return;
        setPage(result);
        try {
          const currentStatuses = await getViewingStatuses(
            authorization,
            result.results.map((study) => study.study_id),
          );
          if (active) {
            setStatuses(currentStatuses);
            setStatusWarning(false);
          }
        } catch {
          if (active) {
            setStatuses({});
            setStatusWarning(true);
          }
        }
      })
      .catch((requestError: unknown) => {
        if (active) setError(getErrorMessage(requestError, "Unable to load studies."));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [authorization, filters, offset]);

  function search(nextFilters: StudyFilters) {
    setFilters({ ...nextFilters });
    setOffset(0);
  }

  function viewingStatus(study: Study): ViewingStatus {
    return statuses[study.study_id] ?? "unavailable";
  }

  const firstResult = page && page.count > 0 ? offset + 1 : 0;
  const lastResult = page ? Math.min(offset + page.results.length, page.count) : 0;

  return (
    <section className="worklist-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">Radiology</p>
          <h1>Study worklist</h1>
          <p className="page-subtitle">Search and review imaging study records.</p>
        </div>
      </div>

      <StudySearchForm onSearch={search} busy={loading} />

      <section className="results-section" aria-labelledby="results-heading">
        <div className="results-heading">
          <div>
            <h2 id="results-heading">Studies</h2>
            {!loading && page && <p className="result-count">{page.count} studies found</p>}
          </div>
        </div>

        {statusWarning && !loading && (
          <p className="notice-message" role="status">
            Viewing status is temporarily unavailable. Study results are still shown.
          </p>
        )}
        {error && <p className="error-message" role="alert">{error}</p>}
        {loading && <p className="loading-message" role="status">Loading studies…</p>}
        {!loading && !error && page?.results.length === 0 && (
          <div className="empty-state">
            <h3>No studies found</h3>
            <p>Try changing or clearing your search filters.</p>
          </div>
        )}
        {!loading && !error && page && page.results.length > 0 && (
          <>
            <div className="table-scroll">
              <table className="study-table">
                <thead>
                  <tr>
                    <th scope="col">Patient name</th>
                    <th scope="col">Patient ID</th>
                    <th scope="col">Study date</th>
                    <th scope="col">Modality</th>
                    <th scope="col">Description</th>
                    <th scope="col">Accession number</th>
                    <th scope="col">Viewing status</th>
                    <th scope="col"><span className="visually-hidden">Action</span></th>
                  </tr>
                </thead>
                <tbody>
                  {page.results.map((study) => (
                    <tr key={study.study_id}>
                      <td data-label="Patient name">{study.patient_name || "—"}</td>
                      <td data-label="Patient ID">{study.patient_id || "—"}</td>
                      <td data-label="Study date">{formatStudyDate(study.study_date)}</td>
                      <td data-label="Modality">{study.modality || "—"}</td>
                      <td data-label="Description">{study.study_description || "—"}</td>
                      <td data-label="Accession number">{study.accession_number || "—"}</td>
                      <td data-label="Viewing status">
                        <ViewingStatusBadge status={viewingStatus(study)} />
                      </td>
                      <td data-label="Action">
                        <Link
                          className="button button-small button-secondary"
                          to={`/studies/${encodeURIComponent(study.study_id)}`}
                          state={{ study }}
                        >
                          Details
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <nav className="pagination" aria-label="Study results pages">
              <p className="pagination-summary">
                Showing {firstResult}–{lastResult} of {page.count}
              </p>
              <div className="pagination-actions">
                <button
                  className="button button-secondary"
                  type="button"
                  disabled={offset === 0 || loading}
                  onClick={() => setOffset(Math.max(0, offset - WORKLIST_PAGE_SIZE))}
                >
                  Previous
                </button>
                <button
                  className="button button-secondary"
                  type="button"
                  disabled={!page.next || loading}
                  onClick={() => setOffset(offset + WORKLIST_PAGE_SIZE)}
                >
                  Next
                </button>
              </div>
            </nav>
          </>
        )}
      </section>
    </section>
  );
}

function formatStudyDate(value: string): string {
  if (!/^\d{8}$/.test(value)) return value || "—";
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
}
