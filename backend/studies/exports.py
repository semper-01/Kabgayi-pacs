"""Study metadata and rendered-image export helpers."""
import csv
import io
import textwrap
import zipfile
from http.client import HTTPException
from tempfile import SpooledTemporaryFile
from urllib.error import URLError

from core.services.orthanc import (
    OrthancProtocolError,
    OrthancUnavailableError,
)

from .serializers import serialize_study

CSV_FIELDS = (
    "study_id",
    "patient_name",
    "patient_id",
    "study_instance_uid",
    "accession_number",
    "study_date",
    "modality",
    "study_description",
)


def serialize_export_metadata(orthanc, study):
    if not isinstance(study, dict) or not isinstance(study.get("ID"), str):
        raise OrthancProtocolError("Orthanc returned an unexpected response.")
    patient_tags = study.get("PatientMainDicomTags", {}) or {}
    if not patient_tags:
        patient_id = study.get("ParentPatient")
        if patient_id:
            patient = orthanc.get_patient(patient_id)
            if not isinstance(patient, dict):
                raise OrthancProtocolError("Orthanc returned an unexpected response.")
            patient_tags = patient.get("MainDicomTags", {}) or {}

    projected_study = dict(study)
    projected_study["PatientMainDicomTags"] = patient_tags
    return serialize_study(
        projected_study,
        modalities=orthanc.get_study_modalities(study["ID"]),
    )


def create_csv(metadata):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, lineterminator="\r\n")
    writer.writeheader()
    writer.writerow(
        {
            field: _spreadsheet_safe(metadata.get(field, ""))
            for field in CSV_FIELDS
        }
    )
    return output.getvalue().encode("utf-8")


def create_pdf(metadata):
    """Build a small one-page, metadata-only PDF without a new dependency."""
    rows = [
        "Study information summary",
        "Metadata summary only - not a clinical report.",
        "",
    ]
    rows.extend(
        f"{label}: {metadata.get(field, '') or 'Not available'}"
        for field, label in (
            ("patient_name", "Patient name"),
            ("patient_id", "Patient ID"),
            ("study_date", "Study date"),
            ("accession_number", "Accession number"),
            ("modality", "Modality"),
            ("study_description", "Study description"),
            ("study_id", "Study identifier"),
        )
    )
    lines = []
    for row in rows:
        lines.extend(textwrap.wrap(str(row), width=82) or [""])
    lines = lines[:42]

    commands = ["BT", "/F1 17 Tf", "50 755 Td", f"({_pdf_text(lines[0])}) Tj"]
    commands.extend(["/F1 10 Tf"])
    for line in lines[1:]:
        commands.extend(["0 -16 Td", f"({_pdf_text(line)}) Tj"])
    commands.append("ET")
    stream = "\n".join(commands).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]

    document = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{number} 0 obj\n".encode("ascii"))
        document.extend(body)
        document.extend(b"\nendobj\n")
    xref_offset = len(document)
    document.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    document.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    document.extend(
        (
            f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(document)


def create_rendered_archive(orthanc, instance_ids, image_format):
    extension = "png" if image_format == "png" else "jpg"
    accept = "image/png" if image_format == "png" else "image/jpeg"
    archive = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    try:
        with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            for index, instance_id in enumerate(instance_ids, start=1):
                path = f"/instances/{instance_id}/preview"
                with orthanc.open_binary(path, headers={"Accept": accept}) as source:
                    _verify_image_response(source, accept)
                    entry = zip_file.open(
                        f"instance_{index:06d}.{extension}",
                        mode="w",
                    )
                    try:
                        while True:
                            try:
                                chunk = source.read(64 * 1024)
                            except (HTTPException, OSError, URLError) as exc:
                                raise OrthancUnavailableError(
                                    "Unable to retrieve an Orthanc image."
                                ) from exc
                            if not chunk:
                                break
                            entry.write(chunk)
                    finally:
                        entry.close()
    except Exception:
        archive.close()
        raise

    archive.seek(0)
    return archive


def _verify_image_response(response, expected_type):
    headers = getattr(response, "headers", None)
    content_type = headers.get_content_type() if headers else expected_type
    if content_type != expected_type:
        raise OrthancProtocolError("Orthanc returned an unexpected image format.")


def _spreadsheet_safe(value):
    value = str(value or "")
    if value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def _pdf_text(value):
    safe = str(value).encode("ascii", errors="replace").decode("ascii")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
