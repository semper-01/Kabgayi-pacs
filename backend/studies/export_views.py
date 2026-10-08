"""Authenticated study export endpoint backed by Orthanc."""
import re
from urllib.parse import quote

from django.http import FileResponse, HttpResponse
from rest_framework import status
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.services.orthanc import (
    OrthancAuthenticationError,
    OrthancError,
    OrthancHttpError,
    OrthancNotFoundError,
    OrthancProtocolError,
    OrthancService,
    OrthancUnavailableError,
)

from .exports import (
    create_csv,
    create_pdf,
    create_rendered_archive,
    serialize_export_metadata,
)

STUDY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
SUPPORTED_FORMATS = {"dicom", "png", "jpeg", "pdf", "csv"}


@api_view(["GET"])
@authentication_classes([BasicAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def study_export(request, study_id):
    if not STUDY_ID_PATTERN.fullmatch(study_id):
        return Response(
            {"error": "Invalid study identifier."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    export_format = request.query_params.get("format", "").lower()
    if export_format not in SUPPORTED_FORMATS:
        return Response(
            {"error": "Unsupported format. Use dicom, png, jpeg, pdf, or csv."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    orthanc = OrthancService()
    try:
        study = orthanc.get_study(study_id)
        if not isinstance(study, dict) or study.get("ID") != study_id:
            raise OrthancProtocolError("Orthanc returned an unexpected response.")
        if export_format == "dicom":
            source = orthanc.open_binary(f"/studies/{quote(study_id, safe='')}/archive")
            return FileResponse(
                source,
                as_attachment=True,
                filename=f"study-{study_id}.zip",
                content_type="application/zip",
                headers={"Cache-Control": "private, no-store"},
            )

        if export_format in {"png", "jpeg"}:
            instance_ids = orthanc.get_study_instances(study_id)
            if not instance_ids:
                return Response(
                    {"error": "The study contains no exportable images."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", item) for item in instance_ids):
                raise OrthancProtocolError("Orthanc returned an unexpected response.")
            archive = create_rendered_archive(orthanc, instance_ids, export_format)
            return FileResponse(
                archive,
                as_attachment=True,
                filename=f"study-{study_id}-{export_format}.zip",
                content_type="application/zip",
                headers={"Cache-Control": "private, no-store"},
            )

        metadata = serialize_export_metadata(orthanc, study)
        if export_format == "csv":
            return HttpResponse(
                create_csv(metadata),
                content_type="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="study-{study_id}.csv"',
                    "Cache-Control": "private, no-store",
                },
            )
        return HttpResponse(
            create_pdf(metadata),
            content_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="study-{study_id}.pdf"',
                "Cache-Control": "private, no-store",
            },
        )
    except OrthancNotFoundError:
        return Response(
            {"error": "The requested study was not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    except OrthancUnavailableError:
        return _orthanc_error(status.HTTP_503_SERVICE_UNAVAILABLE)
    except (
        OrthancAuthenticationError,
        OrthancHttpError,
        OrthancProtocolError,
    ):
        return _orthanc_error(status.HTTP_502_BAD_GATEWAY)
    except OrthancError:
        return _orthanc_error(status.HTTP_502_BAD_GATEWAY)


def _orthanc_error(http_status):
    return Response(
        {"error": "The image archive could not process the export."},
        status=http_status,
    )
