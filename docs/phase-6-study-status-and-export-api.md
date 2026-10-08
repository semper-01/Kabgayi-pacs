# Phase 6 — Study status and export API

All endpoints use the existing `/api/` prefix and require an authenticated
user. DRF supports the configured Basic and session authentication schemes.
The DRF query-parameter renderer override is disabled so `format` remains the
export-format selector (the API continues to return JSON for API responses).
Status endpoints return only study/session identifiers, timestamps needed by
the caller, and boolean viewing state; they do not return usernames or DICOM
metadata.

## Viewing sessions

| Method and path | Request | Success |
|---|---|---|
| `POST /api/status/open/` | `{"study_id":"<Orthanc resource ID>"}` | `201`, session ID, study ID, and 30-second heartbeat interval |
| `POST /api/status/heartbeat/` | `{"session_id":"<UUID>"}` | `200`, session ID and updated heartbeat timestamp |
| `POST /api/status/close/` | `{"session_id":"<UUID>"}` | `200`, session ID and inactive state |
| `GET /api/status/?study_ids=ID1,ID2` | 1–100 Orthanc IDs | `200`, ordered `study_id` / `being_viewed` results |

Sessions belong to the authenticated user. Another user receives `404` when
attempting to heartbeat or close a session, avoiding disclosure of whether it
exists. Closing one's already-closed session is idempotent. No exclusive study
lock is used; more than one user can view a study.

`VIEWING_SESSION_TIMEOUT_SECONDS` defaults to `90` and can be set in the
backend environment. Status requests opportunistically close sessions with no
heartbeat before the timeout; stale sessions are not reported as being viewed.
The `ViewingSession.study_id` is a plain Orthanc resource ID, not a foreign key
to a DICOM model. The application database stores no DICOM hierarchy or files.

## Study export

`GET /api/studies/<study_id>/export/?format=<format>` supports:

| Format | Response |
|---|---|
| `dicom` | Streamed original Orthanc study archive ZIP |
| `png` | ZIP of per-instance rendered PNG previews |
| `jpeg` | ZIP of per-instance rendered JPEG previews |
| `csv` | Projected study metadata CSV |
| `pdf` | One-page metadata summary; explicitly not a clinical report |

The study ID must be an Orthanc resource ID composed of letters, numbers,
hyphens, or underscores. Unsupported formats and invalid IDs return `400`;
unknown studies return `404`; upstream unavailability returns `503`; other
upstream failures return `502`. Download names contain only the validated
Orthanc ID, never patient names.

The running Orthanc instance was verified as version **1.13.0**. Export uses
the following documented Orthanc REST endpoints:

* `GET /studies/{id}/archive` — original study instances in a ZIP archive;
  Django streams this response without rewriting the DICOM files.
* `GET /studies/{id}` — study resource and DICOM study metadata.
* `GET /studies/{id}/series` — series and their instance IDs.
* `GET /patients/{id}` — patient tags used in the projected CSV/PDF metadata.
* `GET /instances/{id}/preview` — Orthanc-rendered PNG preview.
* `GET /instances/{id}/preview` with `Accept: image/jpeg` — Orthanc-rendered
  JPEG preview.

Rendered archives are written to a spooled temporary file (memory first, then
disk above 8 MiB) and closed by Django after the response. The CSV contains
only the selected metadata fields and neutralizes formula-leading values for
spreadsheet safety. The PDF is a small generated metadata page and has no
clinical interpretation.
