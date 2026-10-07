# Phase 4 — Study Query & Search Layer (Specification)

## 1. Purpose & scope

Phase 4 turns the basic Orthanc integration layer (Phase 3) into a usable study
**search API** for the future hospital UI. This document specifies the behaviour
of that API, the accepted parameters, validation rules, ordering, pagination,
error semantics, and the Orthanc integration decisions that shape them.

Architectural contract (unchanged):

```
React (future UI)
    ↓ GET /api/studies/?filters
Django (query / validation / API / serialization layer)
    ↓
OrthancService
    ↓
Orthanc REST API        ← Orthanc is the source of truth for DICOM data
```

Django does **not** store or model DICOM data. There are no Patient, Study,
Series, or Image models. All search remains an Orthanc operation; Django only
queries, validates, exposes, and serializes.

## 2. Endpoint

A single endpoint is used for listing, searching, and patient history:

```
GET /api/studies/
```

- **Listing**: `/api/studies/`
- **Patient history**: `/api/studies/?patient_id=P001` (results ordered most recent first)
- No separate search or patient-history endpoints exist.

### 2.1 Query parameters

| Parameter            | Type          | Expected format   | Orthanc tag        | Notes |
|----------------------|---------------|-------------------|--------------------|-------|
| `patient_name`       | string        | free text         | `PatientName`      | exact match (see §7) |
| `patient_id`         | string        | free text         | `PatientID`        | exact match |
| `accession_number`   | string        | free text         | `AccessionNumber`  | exact match |
| `study_description`  | string        | free text         | `StudyDescription` | exact match |
| `study_date`         | date          | `YYYY-MM-DD` only | `StudyDate`        | converted to `YYYYMMDD` for Orthanc |
| `modality`           | string        | DICOM modality    | (series-level)     | matched against series of each study (§7) |
| `limit`              | integer ≥ 1   | default `20`      | —                  | clamped to max `100` |
| `offset`             | integer ≥ 0   | default `0`       | —                  | pagination offset |

Multiple filters may be combined (AND semantics), e.g.
`/api/studies/?patient_id=P001&modality=CT&study_date=2026-10-07`.

Unknown parameters are rejected with `HTTP 400`.

### 2.2 Response

```
HTTP 200
{
  "count": 3,                       // total matches (ignores limit/offset)
  "next": "…/api/studies/?limit=2&offset=2",   // null when no further page
  "previous": null,                 // null on the first page
  "results": [
    {
      "study_id": "<orthanc-study-id>",
## 3. Validation rules

- Unknown query parameter → **400** with the offending names.
- `study_date` must be a valid ISO date `YYYY-MM-DD`. Non-hyphenated or
  unparseable values (e.g. `20261007`, `10-07-2026`) → **400**.
- `limit`/`offset` must be integers within bounds (`limit ≥ 1`, `offset ≥ 0`).
  Non-numeric or negative → **400**. `limit > 100` is clamped to `100`.
- Erroneous requests never crash the endpoint and never leak internal
  exceptions or connection secrets.

## 4. Ordering

Results are ordered by **study date descending (most recent first)**, with the
study **time** as a tiebreaker. Studies with no date sort last. Ordering is
performed in Django's serialization layer because Orthanc 1.13's `SortBy` /
`SortDirection` did not reorder results in this environment (see §7).

## 5. Pagination metadata

- `count` = total matches (before slicing) so clients can render page controls.
- `limit`/`offset` control the window; the default page size is 20 and is
  capped at 100 to avoid returning thousands of studies.
- `next`/`previous` are absolute URLs to the adjacent pages (or `null`).

## 6. Error semantics

| Condition                               | HTTP   | Body |
|-----------------------------------------|--------|------|
| Unknown parameter / bad value / bad date| 400    | `{ "error": "…" }` |
| Orthanc unreachable / timeout           | 503    | `{ "error": "The image archive is currently unavailable." }` |
| Orthanc authentication/upstream failure | 502    | `{ "error": "…" }` |

Credentials are never placed in error bodies.

## 7. Orthanc integration facts & decisions (verified against Orthanc 1.13.0)

1. **Search is an Orthanc operation**: Django sends study-level DICOM tags to
   `POST /tools/find` (`Level: Study`, `Query`, `Expand: true`) and Orthanc
   performs the matching.
2. **Exact matching**: Orthanc's advanced find matches string tags exactly
   (verified: `PatientName=Anonym` → 0 hits, `PatientName=Anonymized` →
   1 hit). The API forwards the raw value; fuzzy/substring search is a later
   enhancement (e.g. wildcard support).
3. **Modality is series-level**: `Modality` cannot be matched by a study-level
   `Query` (verified: `Query:{Modality:"PX"}` → `[]`). It is therefore excluded
   from the find `Query` and handled by inspecting each study's series via
   `/studies/{id}/series`. The `modality` filter keeps studies whose series
   contain the requested modality; the `modality` field reports the comma-joined
   unique series modalities.
4. **Orthanc sort is unreliable here**: `SortBy`/`SortDirection` did not reorder;
   chronological ordering happens in Django's serialization layer.
5. **Orthanc resource ID vs `StudyInstanceUID`**: the service/API uses Orthanc
   resource IDs for REST lookups (`/studies/{id}`, `…/series`) and exposes
   `study_instance_uid` purely from DICOM metadata. No database mapping between
   these identifiers is created.

## 8. Out of scope (Phase 4)

Explicitly **not** implemented: React UI, authentication/authorization changes,
audit logging, study status, export, OHIF embedding, image viewing, reporting,
AI, OpenMRS integration, deployment, and any additional database models. All
remain later phases.
      "patient_name": "…",
      "patient_id": "…",
      "study_instance_uid": "…",
      "accession_number": "…",
      "study_date": "YYYYMMDD",
      "modality": "CT, MR",         // comma-joined unique series modalities
      "study_description": "…"
    }
  ]
}
```

Response wrap (`count`/`next`/`previous`/`results`) is used to carry pagination
metadata. The fields are projected from Orthanc's expanded study resource and
never mapped from an Orthanc raw dump verbatim. Empty values are returned as
empty strings; the API never invents metadata.