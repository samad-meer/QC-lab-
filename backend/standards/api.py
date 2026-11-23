"""
The test template library, the specification editor and certificate templates.

A specification moves one way: DRAFT, then EFFECTIVE, then SUPERSEDED. A draft
can be changed freely and affects nothing. Making it effective is a signed act
by someone other than its author, and only samples registered afterwards use it.
"""
import hashlib
import json
import re
from decimal import Decimal

from django.db import transaction
from django.db.models import Max, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.authz import RequiresPermission, has_perm, overrides
from accounts.passwords import confirm_password
from audit.services import record
from batches.stages import test_tracks
from labrecords.models import Method
from labrecords.services import method_problems
from lims.evaluation import ResultValueError, decimals_of, parse_numeric
from lims.models import LimitType, Product, SpecStatus, Specification, TestDefinition
from qclab.listing import filter_by_text, paginated
from .models import CertificateTemplate, TestTemplate

CanManageTemplates = RequiresPermission.of("template.manage")
TEST_FIELDS = ("name", "method", "method_record_id", "unit", "limit_type", "min_value", "max_value", "decimals",
               "text_expected", "limit_text")
MAX_TESTS = 60


def _bad(message: str):
    return Response({"detail": message}, status=status.HTTP_400_BAD_REQUEST)


def _denied(message: str):
    return Response({"detail": message}, status=status.HTTP_403_FORBIDDEN)


def _num(value):
    return None if value is None else f"{value.normalize():f}"


# --- one test, wherever it is defined ------------------------------------------

def _decimal(value, where: str, what: str):
    if value in (None, ""):
        return None
    try:
        return parse_numeric(value)
    except ResultValueError:
        raise ValueError(f"{where}: the {what} must be a number.")


def _limit_text(d: dict) -> str:
    """How the limit reads on a certificate, to the places results are rounded to."""
    unit = f" {d['unit']}" if d["unit"] else ""
    written = lambda value: f"{value:.{d['decimals']}f}"  # noqa: E731
    if d["limit_type"] == LimitType.NUMERIC_RANGE:
        return f"{written(d['min_value'])} – {written(d['max_value'])}{unit}"
    if d["limit_type"] == LimitType.NUMERIC_MIN:
        return f"NLT {written(d['min_value'])}{unit}"
    if d["limit_type"] == LimitType.NUMERIC_MAX:
        return f"NMT {written(d['max_value'])}{unit}"
    if d["limit_type"] == LimitType.TEXT_COMPLIES:
        return d["text_expected"]
    return "Report"


def _worded_limit(raw: dict, d: dict, at: str) -> str:
    """Someone's own wording, as long as it states the limit the system judges."""
    worded = (raw.get("limit_text") or "").strip()[:200]
    if not worded:
        return _limit_text(d)
    stated = {Decimal(n) for n in re.findall(r"\d+(?:\.\d+)?", worded)}
    for limit in (d["min_value"], d["max_value"]):
        if limit is not None and limit not in stated:
            raise ValueError(
                f"{at}: the wording of the limit must state {_num(limit)}, the value results are judged against. "
                "Change the wording, or leave it empty to have it written for you."
            )
    return worded


def _method_record(raw: dict, d: dict, at: str):
    """The method a test names. It can be a draft for now: approving the specification decides."""
    chosen = raw.get("method_record_id")
    if chosen in (None, ""):
        d["method_record_id"] = None
        return
    method = Method.objects.filter(pk=chosen if str(chosen).isdigit() else 0).first()
    if method is None:
        raise ValueError(f"{at}: that method is not in the method master.")
    d["method_record_id"] = method.pk
    d["method"] = d["method"] or str(method)


def clean_test(raw, where: str, in_specification: bool = False) -> dict:
    """
    Validate one test from a screen. Raises ValueError with a readable message.
    A template is a copy to start from, so only a test in a specification names a method record.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"{where} is not valid.")
    name = (raw.get("name") or "").strip()
    at = f"{where} ({name})" if name else where
    if not name:
        raise ValueError(f"{at}: give the test a name.")
    kind = raw.get("limit_type")
    if kind not in LimitType.values:
        raise ValueError(f"{at}: choose the kind of limit.")
    d = {
        "name": name[:200], "method": (raw.get("method") or "").strip()[:200],
        "unit": (raw.get("unit") or "").strip()[:30], "limit_type": kind,
        "min_value": None, "max_value": None, "text_expected": "",
    }
    if kind in (LimitType.NUMERIC_RANGE, LimitType.NUMERIC_MIN):
        d["min_value"] = _decimal(raw.get("min_value"), at, "minimum")
        if d["min_value"] is None:
            raise ValueError(f"{at}: enter the minimum.")
    if kind in (LimitType.NUMERIC_RANGE, LimitType.NUMERIC_MAX):
        d["max_value"] = _decimal(raw.get("max_value"), at, "maximum")
        if d["max_value"] is None:
            raise ValueError(f"{at}: enter the maximum.")
    if d["min_value"] is not None and d["max_value"] is not None and d["min_value"] > d["max_value"]:
        raise ValueError(f"{at}: the minimum is above the maximum.")
    if kind == LimitType.TEXT_COMPLIES:
        d["text_expected"] = (raw.get("text_expected") or "").strip()[:200]
        if not d["text_expected"]:
            raise ValueError(f"{at}: enter the wording a result must match.")
    try:
        d["decimals"] = int(raw.get("decimals", 2))
    except (TypeError, ValueError):
        raise ValueError(f"{at}: decimal places must be a whole number.")
    if not 0 <= d["decimals"] <= 6:
        raise ValueError(f"{at}: decimal places must be between 0 and 6.")
    needed = max(decimals_of(d["min_value"]), decimals_of(d["max_value"]))
    if d["decimals"] < needed:
        raise ValueError(
            f"{at}: the limit is written to {needed} decimal place(s), so results must be rounded to at least that many."
        )
    d["limit_text"] = _worded_limit(raw, d, at)
    if in_specification:
        _method_record(raw, d, at)
    return d


def _test_payload(t) -> dict:
    return {
        "name": t.name, "method": t.method, "method_record_id": getattr(t, "method_record_id", None),
        "unit": t.unit, "limit_type": t.limit_type,
        "min_value": _num(t.min_value), "max_value": _num(t.max_value), "decimals": t.decimals,
        "text_expected": t.text_expected, "limit_text": t.limit_text,
    }


# --- test templates ---------------------------------------------------------------

def _template_payload(t: TestTemplate) -> dict:
    return {
        "id": t.id, "code": t.code, "version": t.version, "is_retired": t.is_retired, "reason": t.reason,
        "created_by": t.created_by.display_name(), "created_at": t.created_at, **_test_payload(t),
    }


def _latest_templates():
    """The newest version of each template: nothing newer exists for the same code."""
    newest = TestTemplate.objects.values("code").annotate(top=Max("version"))
    match = Q(pk__isnull=True)
    for row in newest:
        match |= Q(code=row["code"], version=row["top"])
    return TestTemplate.objects.filter(match).select_related("created_by")


@api_view(["GET", "POST"])
def test_templates(request):
    if request.method == "GET":
        qs = _latest_templates()
        if request.query_params.get("active") == "1":
            qs = qs.filter(is_retired=False)
        qs = filter_by_text(request, qs, ["code", "name", "method"]).order_by("is_retired", "name", "code")
        return paginated(request, qs, lambda rows: [_template_payload(t) for t in rows],
                         limit_types=[{"key": k, "label": v} for k, v in LimitType.choices],
                         can_manage=has_perm(request.user, "spec.manage"))

    if not has_perm(request.user, "spec.manage"):
        return _denied("You do not have permission to manage test templates.")
    code = (request.data.get("code") or "").strip()
    if not code or len(code) > 40:
        return _bad("Give the template a code of up to 40 characters.")
    if TestTemplate.objects.filter(code__iexact=code).exists():
        return _bad(f"A template with the code {code} already exists.")
    try:
        fields = clean_test(request.data, "This template")
    except ValueError as e:
        return _bad(str(e))
    template = TestTemplate.objects.create(code=code, created_by=request.user, **fields)
    record(request.user, "TEST_TEMPLATE_CREATED", "test template", code, name=template.name)
    return Response(_template_payload(template), status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([RequiresPermission.of("spec.manage")])
def test_template_version(request, code):
    """Save a change as a new version. Specifications already using it keep their copy."""
    latest = TestTemplate.objects.filter(code=code).order_by("-version").first()
    if latest is None:
        return Response({"detail": "No such template."}, status=status.HTTP_404_NOT_FOUND)
    reason = (request.data.get("reason") or "").strip()[:500]
    if not reason:
        return _bad("Say why the template is changing — it stays with the version.")
    try:
        fields = clean_test(request.data, "This template")
    except ValueError as e:
        return _bad(str(e))
    retired = bool(request.data.get("is_retired", False))
    template = TestTemplate.objects.create(
        code=code, version=latest.version + 1, created_by=request.user, reason=reason, is_retired=retired, **fields
    )
    record(request.user, "TEST_TEMPLATE_CHANGED", "test template", code, version=template.version, reason=reason)
    return Response(_template_payload(template))


# --- specifications ----------------------------------------------------------------

def _digest(spec: Specification) -> str:
    """What is being approved: every test and limit, exactly."""
    tests = [_test_payload(t) for t in spec.tests.order_by("order", "id")]
    return hashlib.sha256(json.dumps(tests, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _label(spec: Specification) -> str:
    """How the activity log names a version: “PCM-500 v3”, or “PCM-500 Final grain tests v1”."""
    return f"{spec.product.code} {spec.stage_name} tests v{spec.version}" if spec.stage_key \
        else f"{spec.product.code} v{spec.version}"


def _spec_payload(spec: Specification) -> dict:
    return {
        "digest": _digest(spec) if spec.status == SpecStatus.DRAFT else spec.approved_digest,
        "id": spec.id,
        "version": spec.version,
        "stage_key": spec.stage_key,
        "stage_name": spec.stage_name,
        "label": spec.label,
        "status": spec.status,
        "status_label": spec.get_status_display(),
        "effective_date": spec.effective_date if spec.status != SpecStatus.DRAFT else None,
        "review_date": spec.review_date,
        "created_at": spec.created_at,
        "created_by": spec.created_by.display_name() if spec.created_by_id else None,
        "created_by_id": spec.created_by_id,
        "change_reason": spec.change_reason,
        "approved_by": spec.approved_by.display_name() if spec.approved_by_id else None,
        "approved_at": spec.approved_at,
        "sample_count": spec.samples.count(),
        "tests": [
            {**_test_payload(t), "id": t.id, "source": t.source,
             "method_record_label": str(t.method_record) if t.method_record_id else ""}
            for t in spec.tests.select_related("method_record")
        ],
    }


def _tracks(product: Product) -> list[dict]:
    """
    The product's own specification, then each lab-tested stage's own tests, with
    the version in force and whether a draft is open.
    """
    rows = [{"key": "", "name": "Specification", "current": True},
            *({**t, "name": f"{t['name']} tests", "stage": t["name"]} for t in test_tracks(product))]
    state = {r["key"]: {"effective_version": None, "draft": False} for r in rows}
    for key, version, status_ in product.specifications.values_list("stage_key", "version", "status").order_by("version"):
        if key in state and status_ == SpecStatus.EFFECTIVE:
            state[key]["effective_version"] = version
        elif key in state and status_ == SpecStatus.DRAFT:
            state[key]["draft"] = True
    return [{**r, **state[r["key"]]} for r in rows]


def _track_of(product: Product, key) -> dict | None:
    """One of the product's sets of tests, by key: "" is its own specification."""
    key = key if isinstance(key, str) else ""
    return next((t for t in _tracks(product) if t["key"] == key), None)


def _specs_state(request, product: Product, key: str = "") -> Response:
    specs = product.specifications.filter(stage_key=key).select_related(
        "created_by", "approved_by").prefetch_related("tests")
    tracks = _tracks(product)
    return Response({
        "product": {"id": product.id, "code": product.code, "name": product.name},
        # Which set of tests this is: the product's own specification, or one QC stage's.
        "stage_key": key,
        "tracks": tracks,
        "specifications": [_spec_payload(s) for s in specs.order_by("-version")],
        "limit_types": [{"key": k, "label": v} for k, v in LimitType.choices],
        "can_draft": has_perm(request.user, "spec.manage"),
        "can_approve": has_perm(request.user, "spec.approve"),
    })


def _draft_of(pk) -> Specification:
    return get_object_or_404(Specification.objects.select_related("product"), pk=pk, status=SpecStatus.DRAFT)


@api_view(["GET", "POST"])
def product_specifications(request, pk):
    product = get_object_or_404(Product, pk=pk)
    track = _track_of(product, request.query_params.get("stage", "") if request.method == "GET"
                      else request.data.get("stage", ""))
    if track is None:
        return _bad("That is not one of this product's lab-tested QC stages.")
    key = track["key"]
    if request.method == "GET":
        return _specs_state(request, product, key)

    if not has_perm(request.user, "spec.manage"):
        return _denied("You do not have permission to draft specifications.")
    reason = (request.data.get("reason") or "").strip()[:500]
    if not reason:
        return _bad("Say why a new version is needed — it stays with the version.")
    with transaction.atomic():
        Product.objects.select_for_update().get(pk=product.pk)
        mine = product.specifications.filter(stage_key=key)
        draft = mine.filter(status=SpecStatus.DRAFT).first()
        if draft is not None:
            return _bad(f"Version {draft.version} is already a draft. Finish it or discard it first.")
        # A stage's first version starts empty; any later one, from the version in force.
        base = product.current_specification(key)
        version = (mine.aggregate(m=Max("version"))["m"] or 0) + 1
        spec = Specification.objects.create(
            product=product, stage_key=key, stage_name=track.get("stage", ""), version=version,
            status=SpecStatus.DRAFT, effective_date=timezone.localdate(),
            review_date=base.review_date if base else None, created_by=request.user, change_reason=reason,
        )
        if base is not None:
            for t in base.tests.all():
                TestDefinition.objects.create(
                    specification=spec, order=t.order, source=t.source,
                    **{f: getattr(t, f) for f in TEST_FIELDS},
                )
        record(request.user, "SPEC_DRAFTED", "specification", _label(spec), reason=reason)
    return _specs_state(request, product, key)


@api_view(["PUT", "DELETE"])
@permission_classes([RequiresPermission.of("spec.manage")])
def draft_specification(request, pk):
    spec = _draft_of(pk)
    product = spec.product
    label = _label(spec)
    if request.method == "DELETE":
        spec.tests.all().delete()
        spec.delete()
        record(request.user, "SPEC_DISCARDED", "specification", label)
        return _specs_state(request, product, spec.stage_key)

    raw = request.data.get("tests")
    if not isinstance(raw, list):
        return _bad("The tests are not valid.")
    if len(raw) > MAX_TESTS:
        return _bad(f"A specification can have at most {MAX_TESTS} tests.")
    try:
        tests = [clean_test(t, f"Test {i}", in_specification=True) for i, t in enumerate(raw, start=1)]
    except ValueError as e:
        return _bad(str(e))
    review = request.data.get("review_date") or None
    if review is not None:
        try:
            review = parse_date(review)
        except ValueError:
            review = None
        if review is None:
            return _bad("That is not a valid review date.")
    before = [_test_payload(t) for t in spec.tests.all()]
    with transaction.atomic():
        spec.tests.all().delete()
        for order, (d, r) in enumerate(zip(tests, raw), start=1):
            TestDefinition.objects.create(specification=spec, order=order,
                                          source=(r.get("source") or "")[:60], **d)
        spec.review_date = review
        spec.edited_by = request.user
        spec.save(update_fields=["review_date", "edited_by"])
        record(request.user, "SPEC_EDITED", "specification", label, tests=len(tests), was=before,
               now=[_test_payload(t) for t in spec.tests.all()])
    return _specs_state(request, product, spec.stage_key)


@api_view(["POST"])
@permission_classes([RequiresPermission.of("spec.approve")])
def approve_specification(request, pk):
    """A signed act: only samples registered from now on use the new version."""
    spec = _draft_of(pk)
    product = spec.product
    label = _label(spec)
    if not confirm_password(request.user, request.data.get("password") or ""):
        record(request.user, "SIGN_REFUSED_BAD_PASSWORD", "specification", label)
        return _bad("That password is not correct.")
    if request.user.id in (spec.created_by_id, spec.edited_by_id) and not overrides(
        request.user, "A specification is made effective by someone other than the person who drafted it."
    ):
        record(request.user, "SPEC_APPROVAL_REFUSED", "specification", label)
        return _bad("You drafted or changed this version, so someone else must make it effective.")
    digest = _digest(spec)
    if request.data.get("digest") != digest:
        return _bad("This draft has changed since you opened it. Review it again before approving.")
    if not spec.tests.exists():
        return _bad("A specification needs at least one test.")
    problems = method_problems(spec.tests.select_related("method_record"))
    if problems:
        message = " ".join(problems)
        record(request.user, "SPEC_APPROVAL_REFUSED_METHOD", "specification", label, reason=message)
        return _bad(f"{message} Only an effective, validated method can go into an approved specification.")
    with transaction.atomic():
        Product.objects.select_for_update().get(pk=product.pk)
        # Only the version in force of the same set of tests is replaced.
        previous = list(product.specifications.filter(status=SpecStatus.EFFECTIVE, stage_key=spec.stage_key))
        for old in previous:
            old.status = SpecStatus.SUPERSEDED
            old.save(update_fields=["status"])
        spec.status = SpecStatus.EFFECTIVE
        spec.effective_date = timezone.localdate()
        spec.approved_by = request.user
        spec.approved_at = timezone.now()
        spec.approved_digest = digest
        spec.save(update_fields=["status", "effective_date", "approved_by", "approved_at", "approved_digest"])
        record(request.user, "SPEC_APPROVED", "specification", label,
               replaces=f"v{previous[-1].version}" if previous else "nothing")
    return _specs_state(request, product, spec.stage_key)


@api_view(["PATCH"])
@permission_classes([RequiresPermission.of("spec.manage")])
def specification_review_date(request, pk):
    """The date the next review is due: the one thing that can change on an approved version."""
    spec = get_object_or_404(Specification.objects.select_related("product"), pk=pk)
    reason = (request.data.get("reason") or "").strip()[:500]
    if not reason:
        return _bad("Say why the review date is changing.")
    review = None
    raw = request.data.get("review_date")
    if raw:
        try:
            review = parse_date(raw)
        except ValueError:
            review = None
        if review is None:
            return _bad("That is not a valid review date.")
    before = spec.review_date
    spec.review_date = review
    spec.save(update_fields=["review_date"])
    record(request.user, "SPEC_REVIEW_DATE_CHANGED", "specification", _label(spec),
           before=str(before or "—"), after=str(review or "—"), reason=reason)
    return _specs_state(request, spec.product, spec.stage_key)


# --- certificate templates -------------------------------------------------------------

def _certificate_template_payload(t: CertificateTemplate) -> dict:
    return {
        "id": t.id, "name": t.name, "is_default": t.is_default, "title": t.title, "header_note": t.header_note,
        "footer_note": t.footer_note, **{option: getattr(t, option) for option in t.OPTIONS},
        # A product that names no template prints with the default, so those count as its products too.
        "product_count": t.products.count()
        + (Product.objects.filter(certificate_template__isnull=True).count() if t.is_default else 0),
    }


def _clean_certificate_template(data: dict) -> dict:
    out = {}
    if "name" in data:
        out["name"] = (data.get("name") or "").strip()
        if not out["name"] or len(out["name"]) > 100:
            raise ValueError("Give the template a name of up to 100 characters.")
    if "title" in data:
        out["title"] = (data.get("title") or "").strip()
        if not out["title"] or len(out["title"]) > 80:
            raise ValueError("Give the certificate a title of up to 80 characters.")
    if "header_note" in data:
        out["header_note"] = (data.get("header_note") or "").strip()[:200]
    if "footer_note" in data:
        out["footer_note"] = (data.get("footer_note") or "").strip()[:2000]
    for option in CertificateTemplate.OPTIONS:
        if option in data:
            out[option] = bool(data.get(option))
    return out


@api_view(["GET", "POST"])
def certificate_templates(request):
    if request.method == "GET":
        return paginated(request, CertificateTemplate.objects.all(),
                         lambda rows: [_certificate_template_payload(t) for t in rows],
                         can_manage=has_perm(request.user, "template.manage"))
    if not has_perm(request.user, "template.manage"):
        return _denied("You do not have permission to manage certificate templates.")
    try:
        fields = _clean_certificate_template(request.data)
    except ValueError as e:
        return _bad(str(e))
    if not fields.get("name"):
        return _bad("Give the template a name.")
    if CertificateTemplate.objects.filter(name__iexact=fields["name"]).exists():
        return _bad(f"A template called “{fields['name']}” already exists.")
    template = CertificateTemplate.objects.create(**fields)
    record(request.user, "CERT_TEMPLATE_CREATED", "certificate template", template.name)
    return Response(_certificate_template_payload(template), status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
@permission_classes([CanManageTemplates])
def certificate_template_detail(request, pk):
    template = get_object_or_404(CertificateTemplate, pk=pk)
    if request.method == "DELETE":
        name = template.name
        try:
            template.delete()
        except PermissionError as e:
            return _bad(str(e))
        record(request.user, "CERT_TEMPLATE_DELETED", "certificate template", name)
        return Response(status=status.HTTP_204_NO_CONTENT)

    try:
        fields = _clean_certificate_template(request.data)
    except ValueError as e:
        return _bad(str(e))
    if "name" in fields and CertificateTemplate.objects.filter(name__iexact=fields["name"]).exclude(pk=pk).exists():
        return _bad(f"A template called “{fields['name']}” already exists.")
    changed = {f: v for f, v in fields.items() if getattr(template, f) != v}
    with transaction.atomic():
        if request.data.get("is_default") is True and not template.is_default:
            # One default at a time (a DB constraint) — clear the old one first.
            CertificateTemplate.objects.filter(is_default=True).update(is_default=False)
            template.is_default = True
            changed["is_default"] = True
        if changed:
            was = {field: getattr(template, field) for field in changed}
            for field, value in changed.items():
                setattr(template, field, value)
            template.save(update_fields=list(changed))
            record(request.user, "CERT_TEMPLATE_CHANGED", "certificate template", template.name, was=was, changed=changed)
    return Response(_certificate_template_payload(template))
