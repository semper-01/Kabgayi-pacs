"""Administrator-only APIs for PACS operations and staged configuration."""
import ipaddress
import re
import socket
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from pydicom import dcmread
from pydicom.errors import InvalidDicomError
from pydicom.uid import UID

from audit.models import AuditEvent
from audit.services import record_event
from core.services.orthanc import (
    OrthancAuthenticationError,
    OrthancError,
    OrthancHttpError,
    OrthancProtocolError,
    OrthancService,
    OrthancUnavailableError,
)
from studies.models import ViewingSession

from .models import (
    ConfigurationChange,
    Machine,
    OperationalConfiguration,
    StudyMachineAssociation,
)

MAX_IMPORT_FILES = 50
MAX_IMPORT_FILE_SIZE = 128 * 1024 * 1024
MAX_IMPORT_BATCH_SIZE = 512 * 1024 * 1024
AE_TITLE_PATTERN = re.compile(r"^[A-Z0-9 _-]{1,16}$")
MACHINE_FIELDS = {
    "display_name",
    "modality",
    "remote_ae_title",
    "ip_address",
    "port",
    "enabled",
}
NETWORK_FIELDS = {"ae_title", "dicom_port", "lan_ip"}


def administrator_required(view):
    """Reject every account except the existing Administrator account type."""
    view = authentication_classes([BasicAuthentication, SessionAuthentication])(view)
    view = permission_classes([IsAuthenticated])(view)
    return view


def _is_administrator(request):
    return request.user.is_authenticated and (
        request.user.account_type == "administrator"
    )


def _forbidden(request):
    if not _is_administrator(request):
        return Response(
            {"error": "Administrator access is required."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


def _audit_display(event):
    return {
        "id": f"audit-{event.pk}",
        "event_type": event.event_type,
        "label": event.get_event_type_display(),
        "outcome": event.outcome,
        "username": event.username,
        "source_ip": event.source_ip,
        "details": event.details,
        "created_at": event.created_at.isoformat(),
    }


def _machine_payload(machine):
    return {
        "id": machine.pk,
        "display_name": machine.display_name,
        "modality": machine.modality,
        "remote_ae_title": machine.remote_ae_title,
        "ip_address": machine.ip_address,
        "port": machine.port,
        "enabled": machine.enabled,
        "registration": "enabled" if machine.enabled else "disabled",
        "connectivity": machine.connectivity_status,
        "last_connectivity_check": (
            machine.last_connectivity_check.isoformat()
            if machine.last_connectivity_check
            else None
        ),
        "ingestion": machine.ingestion_status,
    }


def _configuration_payload(configuration):
    return {
        "ae_title": configuration.ae_title,
        "dicom_port": configuration.dicom_port,
        "lan_ip": configuration.lan_ip or "",
        "updated_at": configuration.updated_at.isoformat(),
    }


def _change_payload(change):
    return {
        "id": change.pk,
        "change_type": change.change_type,
        "proposed_values": change.proposed_values,
        "state": change.state,
        "validation_errors": change.validation_errors,
        "restart_required": change.restart_required,
        "restart_confirmed": change.restart_confirmed,
        "created_by": change.created_by.get_username(),
        "reviewed_by": (
            change.reviewed_by.get_username() if change.reviewed_by else None
        ),
        "created_at": change.created_at.isoformat(),
    }


@api_view(["GET"])
@administrator_required
def overview(request):
    denied = _forbidden(request)
    if denied:
        return denied
    from core.views import overview_counts

    counts = overview_counts()
    total_studies = None
    try:
        study_ids = OrthancService().get_studies()
        if not isinstance(study_ids, list):
            raise OrthancProtocolError("Orthanc returned an unexpected study list.")
        total_studies = len(study_ids)
    except OrthancError:
        pass
    recent = [
        _audit_display(event)
        for event in AuditEvent.objects.select_related("user")[:8]
    ]
    return Response(
        {
            "total_studies": total_studies,
            **counts,
            "recent_activity": recent,
            "service_health": _service_health(),
        }
    )


@api_view(["GET", "POST"])
@administrator_required
def users(request):
    denied = _forbidden(request)
    if denied:
        return denied
    User = get_user_model()
    if request.method == "GET":
        result = User.objects.order_by("username")
        return Response(
            [
                {
                    "id": user.pk,
                    "username": user.get_username(),
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "account_type": user.account_type,
                    "is_active": user.is_active,
                    "date_joined": user.date_joined.isoformat(),
                    "last_login": (
                        user.last_login.isoformat() if user.last_login else None
                    ),
                }
                for user in result
            ]
        )

    username = str(request.data.get("username", "")).strip()
    email = str(request.data.get("email", "")).strip()
    account_type = request.data.get("account_type", "staff")
    password = request.data.get("password", "")
    if not username or account_type not in ("staff", "administrator"):
        return Response(
            {"error": "A username and an existing account type are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not isinstance(password, str) or not password:
        return Response(
            {"error": "An initial password is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    user = User(
        username=username,
        email=email,
        account_type=account_type,
        is_active=True,
    )
    try:
        user.full_clean(exclude=["password"])
        validate_password(password, user=user)
    except ValidationError as exc:
        return Response({"error": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
    user.set_password(password)
    try:
        user.save()
    except IntegrityError:
        return Response(
            {"error": "A user with this username already exists."},
            status=status.HTTP_409_CONFLICT,
        )
    record_event(
        AuditEvent.EventType.ADMIN_CHANGE,
        user=request.user,
        request=request,
        details={"action": "user_created", "target_user": user.get_username()},
    )
    return Response(
        {
            "id": user.pk,
            "username": user.get_username(),
            "account_type": user.account_type,
            "is_active": user.is_active,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["PATCH", "POST"])
@administrator_required
def user_action(request, user_id):
    denied = _forbidden(request)
    if denied:
        return denied
    User = get_user_model()
    try:
        target = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "PATCH":
        if set(request.data) != {"is_active"} or not isinstance(
            request.data.get("is_active"), bool
        ):
            return Response(
                {"error": "Only the is_active boolean can be changed here."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        active = request.data["is_active"]
        if not active and target.pk == request.user.pk:
            return Response(
                {"error": "You cannot deactivate your own account."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if (
            not active
            and target.account_type == "administrator"
            and User.objects.filter(
                account_type="administrator", is_active=True
            ).count()
            <= 1
        ):
            return Response(
                {"error": "The last active administrator cannot be deactivated."},
                status=status.HTTP_409_CONFLICT,
            )
        target.is_active = active
        target.save(update_fields=["is_active"])
        action = "user_activated" if active else "user_deactivated"
        record_event(
            AuditEvent.EventType.ADMIN_CHANGE,
            user=request.user,
            request=request,
            details={"action": action, "target_user": target.get_username()},
        )
        return Response({"id": target.pk, "is_active": target.is_active})

    new_password = request.data.get("new_password")
    if not isinstance(new_password, str) or not new_password:
        return Response(
            {"error": "A new_password is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        validate_password(new_password, user=target)
    except ValidationError as exc:
        return Response({"error": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
    target.set_password(new_password)
    target.save(update_fields=["password"])
    record_event(
        AuditEvent.EventType.PASSWORD_RESET,
        user=request.user,
        request=request,
        details={"target_user": target.get_username()},
    )
    return Response({"id": target.pk, "password_reset": True})


@api_view(["GET"])
@administrator_required
def activity(request):
    denied = _forbidden(request)
    if denied:
        return denied
    events = [_audit_display(event) for event in AuditEvent.objects.all()[:100]]
    sessions = ViewingSession.objects.select_related("user").order_by("-opened_at")[:100]
    events.extend(
        {
            "id": f"view-{session.pk}",
            "event_type": AuditEvent.EventType.VIEWING,
            "label": "Viewing",
            "outcome": "active" if session.is_active else "closed",
            "username": session.user.get_username(),
            "source_ip": None,
            "details": {"study_id": session.study_id},
            "created_at": session.opened_at.isoformat(),
        }
        for session in sessions
    )
    events.sort(key=lambda event: event["created_at"], reverse=True)
    return Response(
        {
            "results": events[:150],
            "audit_gaps": [
                "The Orthanc DICOM receiver is not wired to report incoming AE/IP origins.",
                "Failed sign-in attempts are not recorded by the existing Basic-authentication boundary.",
                "Legacy login/viewing events from before Phase 9 are not available.",
            ],
        }
    )


@api_view(["GET"])
@administrator_required
def service_health(request):
    denied = _forbidden(request)
    if denied:
        return denied
    return Response(_service_health())


def _service_health():
    services = [
        {"name": "Django", "status": "healthy", "message": "API request is responding."}
    ]
    try:
        connection.ensure_connection()
        services.append({"name": "PostgreSQL", "status": "healthy", "message": "Database connection succeeded."})
    except DatabaseError:
        services.append({"name": "PostgreSQL", "status": "offline", "message": "Database connection failed."})
    try:
        OrthancService().get_system()
        services.append({"name": "Orthanc", "status": "healthy", "message": "Orthanc REST API responded."})
    except OrthancUnavailableError:
        services.append({"name": "Orthanc", "status": "offline", "message": "Orthanc could not be reached."})
    except (OrthancAuthenticationError, OrthancHttpError, OrthancProtocolError):
        services.append({"name": "Orthanc", "status": "warning", "message": "Orthanc responded with an API or configuration error."})
    ohif_url = getattr(settings, "OHIF_HEALTH_URL", "http://localhost:8080")
    try:
        with urlopen(ohif_url, timeout=3) as response:
            http_status = response.status
        health = "healthy" if http_status < 400 else "warning"
        message = f"OHIF endpoint returned HTTP {http_status}."
    except HTTPError as exc:
        health = "warning" if exc.code < 500 else "offline"
        message = f"OHIF endpoint returned HTTP {exc.code}."
    except (URLError, TimeoutError, OSError):
        health = "offline"
        message = "OHIF endpoint could not be reached."
    services.append({"name": "OHIF", "status": health, "message": message})
    return {
        "overall": (
            "offline"
            if any(service["status"] == "offline" for service in services)
            else (
                "warning"
                if any(service["status"] == "warning" for service in services)
                else "healthy"
            )
        ),
        "services": services,
        "checked_at": timezone.now().isoformat(),
    }


@api_view(["GET", "POST"])
@administrator_required
def machines(request):
    denied = _forbidden(request)
    if denied:
        return denied
    if request.method == "GET":
        return Response([_machine_payload(machine) for machine in Machine.objects.all()])
    data = request.data
    change_type = data.get("change_type")
    values = data.get("values")
    if change_type not in ("machine_create", "machine_update") or not isinstance(
        values, dict
    ):
        return Response(
            {"error": "Provide a machine_create or machine_update change and values."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    change = ConfigurationChange.objects.create(
        change_type=change_type,
        proposed_values=values,
        created_by=request.user,
    )
    return Response(_change_payload(change), status=status.HTTP_201_CREATED)


@api_view(["POST"])
@administrator_required
def machine_connectivity(request, machine_id):
    denied = _forbidden(request)
    if denied:
        return denied
    try:
        machine = Machine.objects.get(pk=machine_id)
    except Machine.DoesNotExist:
        return Response({"error": "Machine not found."}, status=status.HTTP_404_NOT_FOUND)
    if not machine.enabled:
        result = "warning"
        message = "Machine is registered but disabled."
    else:
        try:
            with socket.create_connection(
                (machine.ip_address, machine.port), timeout=3
            ):
                result = "healthy"
                message = "TCP connectivity test succeeded; DICOM ingestion is not verified."
        except (OSError, TimeoutError):
            result = "offline"
            message = "TCP connectivity test failed."
    machine.connectivity_status = result
    machine.last_connectivity_check = timezone.now()
    machine.save(update_fields=["connectivity_status", "last_connectivity_check"])
    record_event(
        AuditEvent.EventType.MACHINE_CONFIGURATION,
        user=request.user,
        request=request,
        outcome=result,
        details={"action": "connectivity_test", "machine": machine.display_name},
    )
    return Response(
        {
            **_machine_payload(machine),
            "connectivity_test": result,
            "message": message,
        }
    )


@api_view(["POST"])
@administrator_required
def machine_ingestion_check(request):
    denied = _forbidden(request)
    if denied:
        return denied
    ae_title = request.data.get("remote_ae_title")
    ip_address = request.data.get("ip_address")
    try:
        if (
            not isinstance(ae_title, str)
            or not AE_TITLE_PATTERN.fullmatch(ae_title)
            or not isinstance(ip_address, str)
        ):
            raise ValueError
        ip_address = str(ipaddress.ip_address(ip_address))
        machine = Machine.objects.filter(
            remote_ae_title=ae_title,
            ip_address=ip_address,
            enabled=True,
        ).first()
    except ValueError:
        machine = None
    if machine is None:
        record_event(
            AuditEvent.EventType.UNKNOWN_MACHINE,
            user=request.user,
            request=request,
            outcome="rejected",
            details={
                "remote_ae_title": str(ae_title or "")[:16],
                "ip_address": str(ip_address or "")[:45],
            },
        )
        return Response(
            {"registered": False, "enabled": False, "ingestion": "rejected"},
            status=status.HTTP_403_FORBIDDEN,
        )
    return Response(
        {
            "registered": True,
            "enabled": True,
            "ingestion": machine.ingestion_status,
            "message": "Identity matches an enabled registration; this API check does not gate Orthanc receiver traffic.",
        }
    )


@api_view(["GET"])
@administrator_required
def machine_studies(request, machine_id):
    denied = _forbidden(request)
    if denied:
        return denied
    try:
        machine = Machine.objects.get(pk=machine_id)
    except Machine.DoesNotExist:
        return Response({"error": "Machine not found."}, status=status.HTTP_404_NOT_FOUND)
    associations = StudyMachineAssociation.objects.filter(
        machine=machine,
        source_ae_title=machine.remote_ae_title,
        source_ip_address=machine.ip_address,
    )
    return Response(
        {
            "machine": _machine_payload(machine),
            "results": [
                {
                    "study_id": item.study_id,
                    "validated_at": item.validated_at.isoformat(),
                }
                for item in associations
            ],
        }
    )


@api_view(["POST"])
@administrator_required
def sync_machine_studies(request, machine_id):
    denied = _forbidden(request)
    if denied:
        return denied
    try:
        machine = Machine.objects.get(pk=machine_id, enabled=True)
    except Machine.DoesNotExist:
        return Response(
            {"error": "An enabled registered machine is required."},
            status=status.HTTP_404_NOT_FOUND,
        )
    study_ids = request.data.get("study_ids")
    if (
        not isinstance(study_ids, list)
        or not study_ids
        or len(study_ids) > 100
        or any(
            not isinstance(study_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", study_id)
            for study_id in study_ids
        )
    ):
        return Response(
            {"error": "Provide 1 to 100 Orthanc study IDs to verify."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    orthanc = OrthancService()
    matched = []
    rejected = []
    try:
        for study_id in study_ids:
            orthanc.get_study(study_id)
            origins = []
            for instance_id in orthanc.get_study_instances(study_id):
                origin = (orthanc.get_instance(instance_id).get("Origin") or {})
                origins.append(origin)
            verified = any(
                origin.get("RemoteAet") == machine.remote_ae_title
                and origin.get("RemoteIp") == machine.ip_address
                for origin in origins
            )
            if verified:
                StudyMachineAssociation.objects.update_or_create(
                    study_id=study_id,
                    machine=machine,
                    defaults={
                        "source_ae_title": machine.remote_ae_title,
                        "source_ip_address": machine.ip_address,
                    },
                )
                matched.append(study_id)
            else:
                rejected.append(study_id)
                record_event(
                    AuditEvent.EventType.UNKNOWN_MACHINE,
                    user=request.user,
                    request=request,
                    outcome="rejected",
                    details={"action": "origin_verification_failed", "study_id": str(study_id)[:128]},
                )
    except OrthancError:
        return Response(
            {"error": "Orthanc could not verify the selected study origins."},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    machine.ingestion_status = "verified" if matched else "unverified"
    machine.save(update_fields=["ingestion_status", "updated_at"])
    return Response({"associated_studies": matched, "rejected_studies": rejected})


@api_view(["GET"])
@administrator_required
def operational_configuration(request):
    denied = _forbidden(request)
    if denied:
        return denied
    configuration, _ = OperationalConfiguration.objects.get_or_create(pk=1)
    return Response(_configuration_payload(configuration))


@api_view(["GET", "POST"])
@administrator_required
def configuration_changes(request):
    denied = _forbidden(request)
    if denied:
        return denied
    if request.method == "GET":
        return Response(
            [
                _change_payload(change)
                for change in ConfigurationChange.objects.select_related(
                    "created_by", "reviewed_by"
                )[:50]
            ]
        )
    change_type = request.data.get("change_type")
    values = request.data.get("values")
    if change_type not in ("network", "machine_create", "machine_update") or not isinstance(
        values, dict
    ):
        return Response(
            {"error": "A supported change_type and values object are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    change = ConfigurationChange.objects.create(
        change_type=change_type,
        proposed_values=values,
        created_by=request.user,
    )
    return Response(_change_payload(change), status=status.HTTP_201_CREATED)


@api_view(["POST"])
@administrator_required
def validate_configuration_change(request, change_id):
    denied = _forbidden(request)
    if denied:
        return denied
    try:
        change = ConfigurationChange.objects.get(pk=change_id)
    except ConfigurationChange.DoesNotExist:
        return Response({"error": "Change not found."}, status=status.HTTP_404_NOT_FOUND)
    if change.state != ConfigurationChange.State.EDIT:
        return Response(
            {"error": "Only changes in Edit state can be validated."},
            status=status.HTTP_409_CONFLICT,
        )
    errors = _validate_change(change)
    change.validation_errors = errors
    change.state = (
        ConfigurationChange.State.VALIDATED
        if not errors
        else ConfigurationChange.State.EDIT
    )
    change.restart_required = change.change_type == "network"
    change.save(update_fields=["validation_errors", "state", "restart_required"])
    return Response(_change_payload(change))


def _validate_change(change):
    values = change.proposed_values
    errors = []
    if change.change_type == "network":
        if set(values) != NETWORK_FIELDS:
            errors.append("Network changes must contain AE Title, DICOM Port, and LAN IP only.")
            return errors
        if not isinstance(values["ae_title"], str) or not AE_TITLE_PATTERN.fullmatch(
            values["ae_title"]
        ):
            errors.append("AE Title must contain 1-16 uppercase DICOM characters.")
        try:
            if isinstance(values["dicom_port"], bool):
                raise ValueError
            port = int(values["dicom_port"])
            if not 1 <= port <= 65535:
                raise ValueError
        except (TypeError, ValueError):
            errors.append("DICOM Port must be between 1 and 65535.")
        try:
            if values["lan_ip"]:
                ipaddress.ip_address(values["lan_ip"])
        except (ValueError, TypeError):
            errors.append("LAN IP must be a valid IPv4 or IPv6 address.")
    elif change.change_type == "machine_create":
        if set(values) != MACHINE_FIELDS:
            errors.append("Machine changes must contain all supported machine fields.")
            return errors
        try:
            if isinstance(values.get("port"), bool):
                raise ValueError
            machine = Machine(**values)
            machine.full_clean()
        except (ValidationError, TypeError, ValueError) as exc:
            errors.extend(
                exc.messages
                if isinstance(exc, ValidationError)
                else [str(exc) or "Invalid machine field values."]
            )
        if Machine.objects.filter(remote_ae_title=values.get("remote_ae_title")).exists():
            errors.append("That Remote AE Title is already registered.")
        if not isinstance(values.get("remote_ae_title"), str) or not AE_TITLE_PATTERN.fullmatch(
            values["remote_ae_title"]
        ):
            errors.append("Remote AE Title must contain 1-16 uppercase DICOM characters.")
    elif change.change_type == "machine_update":
        if set(values) - (MACHINE_FIELDS | {"id"}) or "id" not in values:
            errors.append("Machine updates require an id and supported machine fields only.")
            return errors
        machine = Machine.objects.filter(pk=values["id"]).first()
        if machine is None:
            errors.append("The machine to update does not exist.")
        else:
            try:
                if isinstance(values.get("port"), bool):
                    raise ValueError
                for name, value in values.items():
                    if name != "id":
                        setattr(machine, name, value)
                machine.full_clean()
            except (ValidationError, TypeError, ValueError) as exc:
                errors.extend(
                    exc.messages
                    if isinstance(exc, ValidationError)
                    else [str(exc) or "Invalid machine field values."]
                )
            if Machine.objects.exclude(pk=machine.pk).filter(
                remote_ae_title=machine.remote_ae_title
            ).exists():
                errors.append("That Remote AE Title is already registered.")
            if not isinstance(machine.remote_ae_title, str) or not AE_TITLE_PATTERN.fullmatch(
                machine.remote_ae_title
            ):
                errors.append("Remote AE Title must contain 1-16 uppercase DICOM characters.")
    return list(dict.fromkeys(errors))


@api_view(["POST"])
@administrator_required
def review_configuration_change(request, change_id):
    denied = _forbidden(request)
    if denied:
        return denied
    try:
        change = ConfigurationChange.objects.get(pk=change_id)
    except ConfigurationChange.DoesNotExist:
        return Response({"error": "Change not found."}, status=status.HTTP_404_NOT_FOUND)
    if change.state != ConfigurationChange.State.VALIDATED:
        return Response(
            {"error": "Only validated changes can be reviewed."},
            status=status.HTTP_409_CONFLICT,
        )
    change.state = ConfigurationChange.State.REVIEWED
    change.reviewed_by = request.user
    change.save(update_fields=["state", "reviewed_by"])
    return Response(_change_payload(change))


@api_view(["POST"])
@administrator_required
def apply_configuration_change(request, change_id):
    denied = _forbidden(request)
    if denied:
        return denied
    try:
        change = ConfigurationChange.objects.get(pk=change_id)
    except ConfigurationChange.DoesNotExist:
        return Response({"error": "Change not found."}, status=status.HTTP_404_NOT_FOUND)
    if change.state != ConfigurationChange.State.REVIEWED:
        return Response(
            {"error": "Only reviewed changes can be applied."},
            status=status.HTTP_409_CONFLICT,
        )
    confirmed = request.data.get("confirm_restart") is True
    if change.restart_required and not confirmed:
        return Response(
            {
                "error": "Applying these network settings requires a manual PACS restart.",
                "impact": "The DICOM listener may be unavailable during the restart. No automatic restart will be performed.",
                "confirmation_required": True,
            },
            status=status.HTTP_409_CONFLICT,
        )

    with transaction.atomic():
        values = change.proposed_values
        if change.change_type == "network":
            configuration, _ = OperationalConfiguration.objects.get_or_create(pk=1)
            configuration.ae_title = values["ae_title"]
            configuration.dicom_port = int(values["dicom_port"])
            configuration.lan_ip = values["lan_ip"] or None
            configuration.updated_by = request.user
            configuration.save()
        elif change.change_type == "machine_create":
            Machine.objects.create(**values)
        else:
            machine = Machine.objects.get(pk=values["id"])
            for key, value in values.items():
                if key != "id":
                    setattr(machine, key, value)
            machine.save()
        change.state = ConfigurationChange.State.APPLIED
        change.applied_by = request.user
        change.applied_at = timezone.now()
        change.restart_confirmed = confirmed
        change.save(
            update_fields=[
                "state",
                "applied_by",
                "applied_at",
                "restart_confirmed",
            ]
        )
    event_type = (
        AuditEvent.EventType.NETWORK_CONFIGURATION
        if change.change_type == "network"
        else AuditEvent.EventType.MACHINE_CONFIGURATION
    )
    record_event(
        event_type,
        user=request.user,
        request=request,
        details={
            "action": "configuration_applied",
            "change_id": change.pk,
            "change_type": change.change_type,
        },
    )
    if change.restart_required:
        record_event(
            AuditEvent.EventType.RESTART,
            user=request.user,
            request=request,
            details={
                "action": "manual_restart_confirmed",
                "impact": "DICOM listener may be unavailable during manual restart.",
                "automatic_restart_performed": False,
            },
        )
    return Response(
        {
            **_change_payload(change),
            "restart_performed": False,
            "restart_required": change.restart_required,
            "message": (
                "Settings were applied to the PACS configuration record. Restart manually; no restart was performed."
                if change.restart_required
                else "Machine registration settings were applied."
            ),
        }
    )


@api_view(["POST"])
@administrator_required
def validate_dicom_import(request):
    denied = _forbidden(request)
    if denied:
        return denied
    files, error = _uploaded_files(request)
    if error:
        return error
    orthanc = OrthancService()
    results = []
    try:
        seen_sop_uids = set()
        for uploaded, content, sop_instance_uid in files:
            matches = orthanc.lookup_dicom(content)
            if not isinstance(matches, list):
                raise OrthancProtocolError("Orthanc returned an unexpected lookup response.")
            duplicates = [
                {"type": item.get("Type"), "id": item.get("ID")}
                for item in matches
                if isinstance(item, dict) and item.get("Type") == "Instance"
            ]
            if sop_instance_uid in seen_sop_uids:
                duplicates.append({"type": "BatchDuplicate", "id": sop_instance_uid})
            else:
                seen_sop_uids.add(sop_instance_uid)
            results.append(
                {
                    "filename": uploaded.name,
                    "valid": True,
                    "duplicates": duplicates,
                }
            )
    except OrthancUnavailableError:
        return Response(
            {"error": "Orthanc is unavailable; files were not imported."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except OrthancError:
        return Response(
            {"error": "One or more files were not accepted as valid DICOM by Orthanc."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return Response(
        {
            "files": results,
            "duplicate_count": sum(bool(item["duplicates"]) for item in results),
            "imported": False,
        }
    )


@api_view(["POST"])
@administrator_required
def import_dicom(request):
    denied = _forbidden(request)
    if denied:
        return denied
    files, error = _uploaded_files(request)
    if error:
        return error
    orthanc = OrthancService()
    inspected = []
    try:
        seen_sop_uids = set()
        for uploaded, content, sop_instance_uid in files:
            matches = orthanc.lookup_dicom(content)
            if not isinstance(matches, list):
                raise OrthancProtocolError("Orthanc returned an unexpected lookup response.")
            duplicates = [
                item
                for item in matches
                if isinstance(item, dict) and item.get("Type") == "Instance"
            ]
            if sop_instance_uid in seen_sop_uids:
                duplicates.append(
                    {"Type": "BatchDuplicate", "ID": sop_instance_uid}
                )
            else:
                seen_sop_uids.add(sop_instance_uid)
            inspected.append((uploaded.name, content, duplicates))
    except OrthancUnavailableError:
        return Response(
            {"error": "Orthanc is unavailable; files were not imported."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except OrthancError:
        return Response(
            {"error": "One or more files were not accepted as valid DICOM by Orthanc."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    policy = request.data.get("duplicate_policy", "")
    has_duplicates = any(duplicates for _, _, duplicates in inspected)
    if has_duplicates and policy not in ("skip", "overwrite"):
        return Response(
            {
                "error": "A duplicate decision is required.",
                "choices": ["skip", "overwrite"],
            },
            status=status.HTTP_409_CONFLICT,
        )
    if policy and policy not in ("skip", "overwrite"):
        return Response(
            {"error": "duplicate_policy must be skip or overwrite."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    summary = []
    duplicate_ids = {
        duplicate.get("ID")
        for _, _, duplicates in inspected
        for duplicate in duplicates
        if duplicate.get("Type") == "Instance" and duplicate.get("ID")
    }
    backups = {}
    imported_ids = []
    try:
        if policy == "overwrite":
            for instance_id in duplicate_ids:
                with orthanc.get_instance_file(instance_id) as response:
                    backup = response.read(MAX_IMPORT_FILE_SIZE + 1)
                if len(backup) > MAX_IMPORT_FILE_SIZE:
                    return Response(
                        {
                            "error": "An existing duplicate exceeds the safe overwrite backup limit. Choose Skip or arrange a controlled manual replacement."
                        },
                        status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    )
                backups[instance_id] = backup
            for instance_id in duplicate_ids:
                orthanc.delete_instance(instance_id)
        for filename, content, duplicates in inspected:
            if duplicates and policy == "skip":
                summary.append({"filename": filename, "result": "skipped_duplicate"})
                continue
            if any(item.get("Type") == "BatchDuplicate" for item in duplicates):
                summary.append({"filename": filename, "result": "skipped_duplicate"})
                continue
            stored = orthanc.store_dicom(content)
            if not isinstance(stored, dict) or not stored.get("ID"):
                raise OrthancProtocolError("Orthanc returned an unexpected import response.")
            imported_ids.append(stored["ID"])
            verified = orthanc.get_instance(stored["ID"])
            summary.append(
                {
                    "filename": filename,
                    "result": "imported",
                    "instance_id": stored["ID"],
                    "study_id": verified.get("ParentStudy", ""),
                }
            )
    except OrthancUnavailableError:
        recovery_errors = _rollback_import(orthanc, imported_ids, backups)
        record_event(
            AuditEvent.EventType.DICOM_IMPORT,
            user=request.user,
            request=request,
            outcome="failed",
            details={
                "file_count": len(files),
                "imported_count": len(imported_ids),
                "rollback_failed": bool(recovery_errors),
            },
        )
        return Response(
            {
                "error": "Orthanc became unavailable during import.",
                "summary": summary,
                "rollback_errors": recovery_errors,
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except OrthancError:
        recovery_errors = _rollback_import(orthanc, imported_ids, backups)
        record_event(
            AuditEvent.EventType.DICOM_IMPORT,
            user=request.user,
            request=request,
            outcome="failed",
            details={
                "file_count": len(files),
                "imported_count": len(imported_ids),
                "rollback_failed": bool(recovery_errors),
            },
        )
        return Response(
            {
                "error": "Orthanc could not complete or verify every import.",
                "summary": summary,
                "rollback_errors": recovery_errors,
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )
    record_event(
        AuditEvent.EventType.DICOM_IMPORT,
        user=request.user,
        request=request,
        details={
            "file_count": len(files),
            "imported_count": sum(item["result"] == "imported" for item in summary),
            "skipped_count": sum(
                item["result"] == "skipped_duplicate" for item in summary
            ),
            "duplicate_policy": policy or None,
        },
    )
    return Response(
        {
            "summary": summary,
            "verification": {
                "verified_count": len(
                    [item for item in summary if item["result"] == "imported"]
                ),
                "failed": False,
            },
        }
    )


def _rollback_import(orthanc, imported_ids, backups):
    errors = []
    for instance_id in reversed(imported_ids):
        try:
            orthanc.delete_instance(instance_id)
        except OrthancError:
            errors.append(f"Could not remove partial import {instance_id}.")
    for instance_id, backup in backups.items():
        try:
            restored = orthanc.store_dicom(backup)
            if not isinstance(restored, dict) or not restored.get("ID"):
                errors.append(f"Could not restore duplicate instance {instance_id}.")
        except OrthancError:
            errors.append(f"Could not restore duplicate instance {instance_id}.")
    return errors


def _uploaded_files(request):
    uploaded = request.FILES.getlist("files")
    if not uploaded:
        return None, Response(
            {"error": "Upload one or more individual DICOM files or folder files."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if len(uploaded) > MAX_IMPORT_FILES:
        return None, Response(
            {"error": f"At most {MAX_IMPORT_FILES} files may be imported at once."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    files = []
    batch_size = 0
    for item in uploaded:
        if item.name.lower().endswith(".zip"):
            return None, Response(
                {"error": "ZIP imports are not supported. Select DICOM files or a folder."},
                status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )
        if item.size > MAX_IMPORT_FILE_SIZE:
            return None, Response(
                {"error": f"{item.name} exceeds the per-file size limit."},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        batch_size += item.size
        if batch_size > MAX_IMPORT_BATCH_SIZE:
            return None, Response(
                {"error": "The upload exceeds the batch size limit."},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        content = item.read()
        if content.startswith(b"PK"):
            return None, Response(
                {"error": "ZIP imports are not supported."},
                status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )
        try:
            dataset = dcmread(BytesIO(content), stop_before_pixels=True, force=True)
            sop_uid = str(dataset.SOPInstanceUID)
            if not UID(sop_uid).is_valid:
                raise ValueError("A valid SOP Instance UID is required.")
        except (InvalidDicomError, OSError, ValueError, EOFError, AttributeError):
            return None, Response(
                {"error": f"{item.name} is not a valid DICOM instance."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        files.append((item, content, sop_uid))
    return files, None
