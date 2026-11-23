import base64
from io import BytesIO

import qrcode
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from accounts.authz import has_perm
from accounts.lab_zone import hour12
from accounts.models import LabConfig
from audit.services import record
from lims.models import Sample
from lims.workflow import samples_visible_to
from .models import CertStatus, Certificate
from .serializers import CertificateSerializer
from .services import (
    SignError,
    can_open_copy,
    copy_was_opened,
    integrity_problems,
    record_print,
    require_intact,
    return_to_analyst,
    sign_as_analyst,
    sign_stage,
    signature_chain,
    withdraw_certificate,
)


def _err(e: SignError):
    return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


def _not_your_sample(request, cert: Certificate):
    """
    Without sample.view.all, a user may only touch samples assigned to
    them, waiting for their role's signature, or already signed by them.
    """
    if not samples_visible_to(request.user).filter(pk=cert.sample_id).exists():
        return Response({"detail": "Not your sample."}, status=status.HTTP_403_FORBIDDEN)
    return None


def _stage_order(request) -> int | None:
    """The stage the caller's screen showed; None if the client did not say."""
    value = request.data.get("stage")
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise SignError("Unknown review stage.")


def _fresh(request, cert: Certificate, code=status.HTTP_200_OK):
    cert.refresh_from_db()
    return Response(CertificateSerializer(cert, context={"request": request}).data, status=code)


@api_view(["POST"])
def sign_analyst_view(request, pk):
    sample = get_object_or_404(Sample, pk=pk)
    try:
        cert = sign_as_analyst(sample, request.user, request.data.get("password", ""))
    except SignError as e:
        return _err(e)
    return _fresh(request, cert, status.HTTP_201_CREATED)


@api_view(["GET"])
def certificate_detail(request, pk):
    cert = get_object_or_404(Certificate, pk=pk)
    denied = _not_your_sample(request, cert)
    if denied:
        return denied
    return Response(CertificateSerializer(cert, context={"request": request}).data)


@api_view(["POST"])
def sign_view(request, pk):
    """Sign the review stage the certificate is waiting at."""
    cert = get_object_or_404(Certificate, pk=pk)
    try:
        sign_stage(cert, request.user, request.data.get("password", ""), _stage_order(request))
    except SignError as e:
        return _err(e)
    return _fresh(request, cert)


@api_view(["POST"])
def return_view(request, pk):
    """Send the work back to the analyst from the stage it is waiting at."""
    cert = get_object_or_404(Certificate, pk=pk)
    try:
        return_to_analyst(cert, request.user, request.data.get("comment", ""), _stage_order(request))
    except SignError as e:
        return _err(e)
    return _fresh(request, cert)


@api_view(["POST"])
def withdraw_view(request, pk):
    cert = get_object_or_404(Certificate, pk=pk)
    denied = _not_your_sample(request, cert)
    if denied:
        return denied
    try:
        withdraw_certificate(cert, request.user, request.data.get("password", ""), request.data.get("reason", ""))
    except SignError as e:
        return _err(e)
    return _fresh(request, cert)


@api_view(["POST"])
def print_view_post(request, pk):
    cert = get_object_or_404(Certificate, pk=pk)
    denied = _not_your_sample(request, cert)
    if denied:
        return denied
    try:
        pe = record_print(cert, request.user)
    except SignError as e:
        return _err(e)
    return Response({"copy_number": pe.copy_number})


def _logo_data_uri(cert, cfg) -> str:
    """The logo the certificate was signed with, inlined so a printed page carries it with no fetch."""
    frozen = cert.content.get("letterhead")
    name = frozen["logo"] if frozen else (cfg.logo.name if cfg.logo else "")
    if not name:
        return ""
    try:
        with cfg.logo.storage.open(name, "rb") as handle:
            return "data:image/png;base64," + base64.b64encode(handle.read()).decode()
    except (FileNotFoundError, OSError):
        return ""


def qr_data_uri(text: str) -> str:
    img = qrcode.make(text, box_size=4, border=2)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


@api_view(["GET"])
def print_view_get(request, pk):
    """Printable COA page for an already-recorded print (copy=N)."""
    cert = get_object_or_404(Certificate, pk=pk)
    denied = _not_your_sample(request, cert)
    if denied:
        return denied
    try:
        copy_number = int(request.query_params.get("copy", "0"))
    except ValueError:
        copy_number = 0
    if not has_perm(request.user, "cert.print"):
        record(request.user, "PRINT_REFUSED_NO_PERMISSION", "certificate", cert.id, sample=cert.sample.sample_no)
        return Response({"detail": "You do not have permission to print certificates."},
                        status=status.HTTP_403_FORBIDDEN)
    pe = cert.prints.filter(copy_number=copy_number).first()
    if cert.status != CertStatus.APPROVED or pe is None:
        return Response(
            {"detail": "This copy has not been issued. Use the Print button first."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    # Each recorded copy opens once: otherwise the original could be printed
    # again and again with the record still saying one copy exists.
    if copy_was_opened(cert.id, copy_number):
        return Response(
            {"detail": f"Copy {copy_number} has already been opened. Print a new numbered copy instead."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not can_open_copy(pe, request.user):
        return Response(
            {"detail": f"Copy {copy_number} can only be opened by whoever printed it, within a day. "
                       "Print a new numbered copy instead."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        require_intact(cert, request.user)
    except SignError as e:
        return _err(e)
    record(request.user, "CERT_COPY_OPENED", "certificate", cert.id, sample=cert.sample.sample_no, copy=copy_number)
    cfg = LabConfig.get()
    verify_url = request.build_absolute_uri(f"/verify/{cert.verification_uuid}/")
    return render(
        request,
        "certificates/coa.html",
        {
            "cert": cert,
            "c": cert.content,
            "lh": cert.content.get("letterhead") or cfg,
            "received_on": timezone.localtime(cert.sample.received_at),
            "issued_on": timezone.localtime(cert.signatures.order_by("signed_at").last().signed_at),
            # Signature times on the lab's clock: 02:05 PM, or 14:05.
            "hour12": hour12(),
            # Embedded rather than linked: the print page must be
            # self-contained so the logo appears even when the browser
            # prints without fetching, and in a saved PDF.
            "logo": _logo_data_uri(cert, cfg),
            "copy_number": copy_number,
            "is_original": copy_number == 1,
            # Every signature the sample's workflow required, in order.
            "chain": signature_chain(cert),
            "qr": qr_data_uri(verify_url),
            "verify_url": verify_url,
        },
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def verify(request, uuid):
    """
    Public read-only page behind the QR code: confirms the certificate is
    genuine and whether it is current, and shows what it says, so paper that
    has been altered can be told from the record. The link is only on the
    certificate itself.
    """
    cert = Certificate.objects.filter(verification_uuid=uuid).first()
    cfg = LabConfig.get()
    problems = integrity_problems(cert) if cert else []
    if problems:
        record(None, "CERT_INTEGRITY_FAILED", "certificate", cert.sample.sample_no, version=cert.version,
               problems=problems)
    return render(
        request,
        "certificates/verify.html",
        {"cert": cert, "c": cert.content if cert else None, "cfg": cfg, "intact": not problems},
        status=200 if cert else 404,
    )
