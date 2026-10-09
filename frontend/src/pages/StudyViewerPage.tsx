import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { closeViewingSession, heartbeatViewingSession, openViewingSession } from "../api/status";
import { getErrorMessage } from "../api/client";
import { findStudy } from "../api/studies";
import { issueViewerGrant, revokeViewerGrant } from "../api/viewerAccess";
import { useAuth } from "../auth/AuthContext";
import type { Study } from "../types/study";

const VIEWER_GRANT_REFRESH_SECONDS = 240;
const OHIF_BASE_URL =
  import.meta.env.VITE_OHIF_BASE_URL ||
  `${window.location.protocol}//${window.location.hostname}:8080`;

interface ViewerLocationState {
  study?: Study;
}

export function StudyViewerPage() {
  const { studyId = "" } = useParams();
  const location = useLocation();
  const { authorization } = useAuth();
  const routeStudy = (location.state as ViewerLocationState | null)?.study;
  const [study, setStudy] = useState<Study | null>(null);
  const [viewerUrl, setViewerUrl] = useState("");
  const [loading, setLoading] = useState(true);
  const [viewerLoaded, setViewerLoaded] = useState(false);
  const [error, setError] = useState("");
  const [statusNotice, setStatusNotice] = useState("");
  const [heartbeatWarning, setHeartbeatWarning] = useState(false);
  const activeEffects = useRef(0);
  const preparation = useRef<{ key: string; promise: Promise<Study> } | null>(null);

  useEffect(() => {
    if (!authorization || !studyId) return;

    let active = true;
    let sessionId: string | null = null;
    let heartbeatTimer: number | undefined;
    let grantRefreshTimer: number | undefined;
    let heartbeatPending = false;
    activeEffects.current += 1;
    const preparationKey = `${authorization}:${studyId}`;

    if (preparation.current?.key !== preparationKey) {
      preparation.current = {
        key: preparationKey,
        promise: (async () => {
          const selectedStudy =
            routeStudy?.study_id === studyId
              ? routeStudy
              : await findStudy(authorization, studyId);
          if (!selectedStudy) {
            throw new Error("Study could not be found in the available worklist.");
          }
          if (!selectedStudy.study_instance_uid) {
            throw new Error("This study does not include a Study Instance UID.");
          }
          await issueViewerGrant(authorization);
          return selectedStudy;
        })(),
      };
    }

    const preparedStudy = preparation.current.promise;
    preparedStudy
      .then(async (selectedStudy) => {
        if (!active) return;
        setStudy(selectedStudy);
        const directStudyUrl = new URL("/viewer", OHIF_BASE_URL);
        directStudyUrl.searchParams.set(
          "StudyInstanceUIDs",
          selectedStudy.study_instance_uid,
        );
        setViewerUrl(directStudyUrl.toString());

        grantRefreshTimer = window.setInterval(() => {
          void issueViewerGrant(authorization).catch(() => {
            if (active) {
              setStatusNotice(
                "Viewer access could not be refreshed. Leave the viewer and reopen the study.",
              );
            }
          });
        }, VIEWER_GRANT_REFRESH_SECONDS * 1000);

        try {
          const session = await openViewingSession(authorization, studyId);
          if (!active) {
            void closeViewingSession(authorization, session.session_id, true).catch(() => {
              console.error("Unable to close the PACS viewing session.");
            });
            return;
          }
          sessionId = session.session_id;
          heartbeatTimer = window.setInterval(() => {
            if (heartbeatPending || !sessionId) return;
            heartbeatPending = true;
            void heartbeatViewingSession(authorization, sessionId)
              .then(() => {
                if (active) setHeartbeatWarning(false);
              })
              .catch(() => {
                if (active) setHeartbeatWarning(true);
              })
              .finally(() => {
                heartbeatPending = false;
              });
          }, session.heartbeat_interval_seconds * 1000);
        } catch {
          if (active) {
            setStatusNotice(
              "Viewing status could not be started. The study viewer may still be available.",
            );
          }
        }

        if (active) setLoading(false);
      })
      .catch((requestError: unknown) => {
        if (active) {
          setError(getErrorMessage(requestError, "Unable to prepare the diagnostic viewer."));
          setLoading(false);
        }
      });

    return () => {
      active = false;
      activeEffects.current -= 1;
      if (heartbeatTimer !== undefined) window.clearInterval(heartbeatTimer);
      if (grantRefreshTimer !== undefined) window.clearInterval(grantRefreshTimer);

      if (sessionId) {
        void closeViewingSession(authorization, sessionId, true).catch(() => {
          console.error("Unable to close the PACS viewing session.");
        });
      }

      window.setTimeout(() => {
        if (activeEffects.current === 0) {
          void revokeViewerGrant(authorization, true).catch(() => {
            console.error("Unable to revoke the PACS viewer access grant.");
          });
        }
      }, 0);
    };
  }, [authorization, routeStudy, studyId]);

  return (
    <section className="viewer-page">
      <div className="viewer-toolbar">
        <Link
          className="button button-secondary"
          to={`/studies/${encodeURIComponent(studyId)}`}
          state={study ? { study } : undefined}
        >
          Back to Study
        </Link>
        <div className="viewer-study-heading">
          <p className="eyebrow">Diagnostic viewer</p>
          <h1>{study?.patient_name || "Study viewer"}</h1>
          {study && (
            <p className="viewer-study-meta">
              {study.study_date || "Date unavailable"} · {study.modality || "Modality unavailable"}
            </p>
          )}
        </div>
        <span className="viewer-loading-state" role="status">
          {loading ? "Preparing viewer…" : viewerLoaded ? "OHIF loaded" : "Connecting to OHIF…"}
        </span>
      </div>

      {error && (
        <p className="error-message" role="alert">
          {error}
        </p>
      )}
      {statusNotice && (
        <p className="notice-message" role="status">
          {statusNotice}
        </p>
      )}
      {heartbeatWarning && (
        <p className="notice-message" role="status">
          Viewing status could not be refreshed. The session will expire automatically if it remains inactive.
        </p>
      )}
      {!error && viewerUrl && (
        <iframe
          className="ohif-frame"
          src={viewerUrl}
          title="OHIF diagnostic image viewer"
          allow="fullscreen"
          allowFullScreen
          onLoad={() => setViewerLoaded(true)}
          onError={() => setError("The OHIF viewer could not be loaded.")}
        />
      )}
    </section>
  );
}
