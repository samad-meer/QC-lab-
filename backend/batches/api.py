"""
Batch endpoints: the list, one batch with everything that hangs off it
(its samples, results, certificates, documents and history), the document
store, and the numbering rule.
"""
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from accounts.authz import OVERRIDE, RequiresPermission, has_perm
from accounts.models import Role
from audit.describe import describe
from audit.models import AuditEvent
from audit.services import record
from certificates.models import Certificate
from execution.files import private_file_response
from execution.payloads import person
from lims.evaluation import reported_value
from lims.models import Product, SpecStatus, TestResult
from lims.serializers import SampleListSerializer
from lims.workflow import samples_visible_to
from qclab.listing import filter_by_date, filter_by_text, paginated
from reports.list_export import Col, ListExport
from . import services, stages
from .models import (
    Batch, BatchDocument, BatchNumberRule, CheckpointKind, CheckpointPreset, DispositionDecision, DocumentType,
    QcStagePlan, StageKind,
)
from .records import clean_kind, fields_of, shown
from .numbering import build_id, clean_rule
from .services import BatchError
from .stages import StageError

BATCH_DATES = {"registered": "created_at", "manufactured": "manufacturing_date", "expiry": "expiry_date"}


def _progress_text(b: Batch) -> str:
    """“2 of 4 passed”, for the list and its export. Empty for a batch with no QC stages."""
    p = stages.progress(b)
    if p is None:
        return ""
    return f"{p['passed']} of {p['required']} passed" + (" · one failed" if p["failed"] else "")


def _product_name(value: str) -> str:
    product = Product.objects.filter(pk=value).first() if value.isdigit() else None
    return f"{product.name} ({product.code})" if product else value


BATCH_EXPORT = ListExport(
    key="batches",
    title="Batches",
    columns=[
        Col("Official batch no", lambda b: b.official_batch_no, 1.2),
        Col("Internal ID", lambda b: b.internal_id, 1.1),
        Col("Product", lambda b: b.product.name, 1.8),
        Col("Code", lambda b: b.product.code, 0.8),
        Col("Site", lambda b: b.manufacturing_site, 1.1),
        Col("Batch size", lambda b: b.batch_size, 0.8),
        Col("Manufactured", lambda b: b.manufacturing_date, 0.9),
        Col("Expiry", lambda b: b.expiry_date, 0.9),
        Col("Samples", lambda b: b.sample_count, 0.6),
        Col("QC stages", _progress_text, 1.0),
        Col("Recorded", lambda b: b.created_at, 1.2),
    ],
    filters={"q": "Search", "product": ("Product", _product_name)},
    dates={"registered": "Date recorded", "manufactured": "Date of manufacture", "expiry": "Expiry date"},
    scoped=True,
)
CanManageConfig = RequiresPermission.of("config.manage")


def _bad(message: str):
    return Response({"detail": message}, status=status.HTTP_400_BAD_REQUEST)


def batches_visible_to(user):
    """
    With sample.view.all or batch.view.all (production), every batch; otherwise those
    behind samples you can see.
    """
    qs = Batch.objects.select_related("product__section", "created_by")
    if has_perm(user, "sample.view.all") or has_perm(user, "batch.view.all"):
        return qs
    return qs.filter(pk__in=samples_visible_to(user).exclude(batch=None).values("batch_id"))


def _visible(request, pk) -> Batch:
    batch = batches_visible_to(request.user).filter(pk=pk).first()
    if batch is None:
        raise Http404("No such batch.")
    return batch


def batch_payload(b: Batch) -> dict:
    return {
        "id": b.id,
        "internal_id": b.internal_id,
        "official_batch_no": b.official_batch_no,
        "product": {
            "id": b.product_id, "code": b.product.code, "name": b.product.name,
            "dosage_form": b.product.dosage_form, "strength": b.product.strength,
            "section": b.product.section.code,
        },
        "manufacturing_site": b.manufacturing_site,
        "manufacturing_date": b.manufacturing_date,
        "expiry_date": b.expiry_date,
        "batch_size": b.batch_size,
        "notes": b.notes,
        "created_by": b.created_by.display_name() if b.created_by_id else None,
        "created_at": b.created_at,
        "sample_count": getattr(b, "sample_count", None),
    }


def document_payload(d: BatchDocument) -> dict:
    return {
        "id": d.id,
        "doc_type": d.doc_type,
        "doc_type_label": d.get_doc_type_display(),
        "title": d.title,
        "version": d.version,
        "name": d.original_name,
        "extension": d.extension,
        "size": d.size,
        "sha256": d.sha256,
        "note": d.note,
        "uploaded_by": person(d.uploaded_by),
        "uploaded_at": d.uploaded_at,
        "is_current": d.is_current,
        "replaces_id": d.replaces_id,
        "withdrawn_at": d.withdrawn_at,
        "withdrawn_by": person(d.withdrawn_by),
        "withdraw_reason": d.withdraw_reason,
        "url": f"/api/batch-documents/{d.id}/",
    }


def disposition_payload(batch: Batch, user) -> dict:
    """The batch's status, every decision behind it, and what is in the way of releasing it."""
    decisions = list(batch.dispositions.select_related("decided_by").order_by("-id"))
    latest = decisions[0] if decisions else None
    may = has_perm(user, services.DISPOSITION)
    independent = user.id not in services.tested_by(batch) or has_perm(user, OVERRIDE)
    open_to_decide = latest is None or latest.decision != DispositionDecision.REJECTED
    return {
        "decision": latest.decision if latest else "",
        "label": latest.get_decision_display() if latest else "Not decided",
        "history": [
            {"id": d.id, "decision": d.decision, "label": d.get_decision_display(), "reason": d.reason,
             "decided_by": person(d.decided_by), "decided_at": d.decided_at, "hash": d.basis_hash}
            for d in decisions
        ],
        "choices": [{"value": c.value, "label": c.label} for c in DispositionDecision],
        "can_decide": may and independent and open_to_decide,
        # Someone who tested it is told why they cannot decide, rather than shown nothing.
        "tested_it": may and not independent,
        "release_problems": services.release_problems(batch) if may else [],
    }


def _own_tests(product, keys) -> dict[str, dict]:
    """For each stage key, the effective version of its own tests and whether a draft is open."""
    out: dict[str, dict] = {k: {"version": None, "draft": False} for k in keys}
    for key, version, state in product.specifications.filter(stage_key__in=keys).order_by("version").values_list(
        "stage_key", "version", "status"
    ):
        if state == SpecStatus.EFFECTIVE:
            out[key]["version"] = version
        elif state == SpecStatus.DRAFT:
            out[key]["draft"] = True
    return out


def _template(stage) -> dict:
    """A recorded stage's steps, check points and sign-off columns, as the editor and the batch show them."""
    return {
        "steps": [
            {"id": st.id, "order": st.order, "title": st.title, "instructions": st.instructions, "checkpoints": [
                {"id": cp.id, "order": cp.order, "label": cp.label, "kind": cp.kind, "kind_label": cp.get_kind_display(),
                 "unit": cp.unit, "decimals": cp.decimals, "required": cp.required, "limit_text": cp.limit_text(),
                 "choices": cp.choices, "kind_name": cp.kind_name,
                 "min_value": None if cp.min_value is None else format(cp.min_value.normalize(), "f"),
                 "max_value": None if cp.max_value is None else format(cp.max_value.normalize(), "f")}
                for cp in st.checkpoints.all()
            ]}
            for st in stage.steps.all()
        ],
        "signoffs": [
            {"id": so.id, "order": so.order, "title": so.title, "holder": so.holder, "role_id": so.role_id,
             "role": so.role.name}
            for so in stage.signoffs.all()
        ],
        # Signed under every step, as on the paper record, or once for the stage.
        "sign_each_step": stage.sign_each_step,
    }


def spec_summary(spec) -> dict | None:
    """A specification in force, as a stage shows it: which it is, and its tests and limits."""
    if spec is None:
        return None
    return {
        "id": spec.id, "label": spec.label, "version": spec.version, "own": bool(spec.stage_key),
        "tests": [{"name": t.name, "method": t.method, "limit_text": t.limit_text}
                  for t in spec.tests.order_by("order", "id")],
    }


def plan_payload(plan: QcStagePlan | None) -> dict | None:
    if plan is None:
        return None
    rows = list(plan.stages.order_by("order").prefetch_related("steps__checkpoints", "signoffs__role"))
    own = _own_tests(plan.product, [stages.tests_key(s) for s in rows if s.kind == StageKind.TESTED])
    return {
        "id": plan.id, "version": plan.version, "reason": plan.reason,
        "created_by": plan.created_by.display_name(), "created_at": plan.created_at,
        "stages": [
            {"id": s.id, "order": s.order, "name": s.name, "description": s.description,
             "kind": s.kind, "kind_label": s.get_kind_display(), "required": s.required,
             "after_previous": s.after_previous, "key": stages.tests_key(s),
             # Its own tests: the effective version, if any, and whether one is being drafted.
             "own_tests": own.get(stages.tests_key(s)) if s.kind == StageKind.TESTED else None,
             # The tests its samples are tested on now: its own when in force, else the product's.
             "tests": spec_summary(stages.spec_for(plan.product, s)) if s.kind == StageKind.TESTED else None,
             **_template(s)}
            for s in rows
        ],
    }


def _entry(cp, e) -> dict | None:
    """One value written on the record, raw for the form and as the record shows it."""
    if e is None:
        return None
    value = fields_of(e)
    return {
        "id": e.id,
        "number": None if e.number is None else format(e.number.normalize(), "f"),
        "text": e.text, "date": e.date, "start": e.start, "end": e.end, "yes_no": e.yes_no,
        "shown": shown(cp, value),
        "out_of_limit": e.out_of_limit, "reason": e.reason, "correction": e.correction,
        "entered_by": person(e.entered_by), "entered_at": e.entered_at,
    }


def _signed_columns(batch: Batch, row: dict, user, columns: list[dict], step_row: dict | None = None) -> list[dict]:
    """Sign-off columns with their signatures, and why the person looking cannot sign each one yet."""
    last = columns[-1]["signoff"].pk if columns else None
    out = []
    for column in columns:
        so, signature = column["signoff"], column["signature"]
        out.append({
            "id": so.id, "order": so.order, "title": so.title, "holder": so.holder, "role_id": so.role_id,
            "role": so.role.name,
            "signature": None if signature is None else {
                "by": person(signature.signed_by), "at": signature.signed_at, "comment": signature.comment,
                "acknowledged": signature.acknowledged,
            },
            "blocked": stages.sign_blocker(batch, row, so, user, step_row=step_row) if signature is None else "",
            "acknowledges": so.pk == last,
        })
    return out


def _flagged(pairs) -> list[dict]:
    return [{"label": cp.label, "shown": shown(cp, fields_of(e)), "limit": cp.limit_text(), "reason": e.reason}
            for cp, e in pairs]


def _record_payload(batch: Batch, row: dict, user) -> dict:
    """
    A recorded stage of this batch: every value with its history, and every sign-off
    column. Signed at every step, each step carries its own columns.
    """
    sheet = row["record"]
    template = _template(row["stage"])
    by_step = {st["step"].pk: st for st in sheet["steps"]}
    for st in template["steps"]:
        step_row = by_step[st["id"]]
        points = {p["checkpoint"].pk: p for p in step_row["points"]}
        for cp in st["checkpoints"]:
            point = points[cp["id"]]
            cp["entry"] = _entry(point["checkpoint"], point["entry"])
            cp["history"] = [_entry(point["checkpoint"], e) for e in reversed(point["history"])]
        st["signoffs"] = _signed_columns(batch, row, user, step_row["columns"], step_row) if sheet["per_step"] else []
        st["locked"] = step_row["locked"]
        st["missing"] = [cp.label for cp in step_row["missing"]]
        st["out_of_limit"] = _flagged(step_row["out_of_limit"])
    why_not_fill = stages.fill_blocker(batch, row, user)
    return {
        **template,
        "per_step": sheet["per_step"],
        "signoffs": [] if sheet["per_step"] else _signed_columns(batch, row, user, sheet["columns"]),
        "locked": sheet["locked"],
        "can_fill": not why_not_fill,
        "fill_blocked": why_not_fill if has_perm(user, stages.FILL) else "",
        "missing": [cp.label for cp in sheet["missing"]],
        "out_of_limit": _flagged(sheet["out_of_limit"]),
    }


def _assignment_payload(batch: Batch, row: dict, user, may_assign: bool) -> dict | None:
    """
    Who has a recorded stage of this batch (nobody: anyone who may fill it), its history,
    and, for whoever may assign it, the people it can go to.
    """
    if row["record"] is None:
        return None
    current = row["assignment"]
    blocked = stages.assign_blocker(batch, row, user) if may_assign else ""
    can = may_assign and not blocked
    return {
        "holder": person(current.assignee) if current else None,
        "by": person(current.assigned_by) if current else None,
        "at": current.assigned_at if current else None,
        "note": current.note if current else "",
        "history": [
            {"holder": person(a.assignee), "by": person(a.assigned_by), "at": a.assigned_at, "note": a.note}
            for a in reversed(row["assignments"])
        ],
        # The batch works by assignment (a stage of it is assigned): unassigned, this one waits.
        "required": row["by_assignment"],
        "can_assign": can,
        "people": [{"id": u.id, "name": u.display_name(), "role": u.role.name}
                   for u in stages.assignable(row["stage"])] if can else [],
    }


def _stage_tests(product, stage) -> str:
    """Which tests a lab-tested stage's samples get, in words."""
    if stage.kind != StageKind.TESTED:
        return ""
    spec = stages.spec_for(product, stage)
    return spec.label if spec else ""


def stages_payload(batch: Batch, user, visible: set[int]) -> dict | None:
    """
    The batch's QC stages and where each stands. Samples are listed only where this
    person may see them. None for a batch with no stages, unless this person could add one.
    """
    rows = stages.batch_stages(batch)
    open_batch = stages.final_decision(batch) is None
    may = has_perm(user, stages.RECORD) and open_batch
    may_assign = has_perm(user, stages.ASSIGN) and open_batch
    if not rows and not may:
        return None
    counted = [r for r in rows if r["stage"].required and r["status"] != stages.NOT_APPLICABLE]
    product = batch.product
    tracks = [{"key": "", "name": "The product's specification"}] + [
        {"key": t["key"], "name": f"{t['name']} tests"} for t in stages.test_tracks(product)
    ] if may else []
    return {
        "version": batch.stage_plan.version if batch.stage_plan_id else None,
        "required": len(counted),
        "passed": sum(1 for r in counted if r["status"] == stages.PASSED),
        "can_record": may,
        # The front desk, sent there from a stage with the batch and stage chosen.
        "can_register": has_perm(user, "sample.register") and open_batch,
        "kinds": [{"value": k.value, "label": k.label} for k in StageKind],
        # The tests a stage added to this batch can give its samples.
        "tracks": tracks,
        "stages": [
            {
                "id": r["stage"].id, "order": r["stage"].order, "name": r["stage"].name,
                "description": r["stage"].description, "kind": r["stage"].kind,
                "kind_label": r["stage"].get_kind_display(), "required": r["stage"].required,
                "after_previous": r["stage"].after_previous,
                "waiting_for": [f"{w.order}. {w.name}" for w in r["waiting_for"]],
                "tests": _stage_tests(product, r["stage"]),
                "added_to_batch": r["stage"].batch_id is not None,
                "added_by": person(r["stage"].added_by) if r["stage"].added_by_id else None,
                "added_reason": r["stage"].added_reason,
                "added_at": r["stage"].added_at,
                "applicability": [
                    {"id": m.id, "applies": m.applies, "reason": m.reason, "recorded_by": person(m.recorded_by),
                     "recorded_at": m.recorded_at}
                    for m in reversed(r["applicability"])
                ],
                # Filled and signed on the batch record: its steps, values and sign-off columns.
                "record": _record_payload(batch, r, user) if r["record"] else None,
                # Who fills it and signs its first column, when someone is named.
                "assignment": _assignment_payload(batch, r, user, may_assign),
                "status": r["status"], "status_label": stages.STATUS_LABELS[r["status"]],
                "samples": [
                    {"id": s.id, "sample_no": s.sample_no, "status_label": s.status_label()}
                    for s in r["samples"] if s.id in visible
                ],
                "hidden_samples": sum(1 for s in r["samples"] if s.id not in visible),
                "records": [
                    {"id": x.id, "decision": x.decision, "label": x.get_decision_display(), "remarks": x.remarks,
                     "recorded_by": person(x.recorded_by), "recorded_at": x.recorded_at}
                    for x in reversed(r["records"])
                ],
            }
            for r in rows
        ],
    }


def _detail(request, batch: Batch) -> Response:
    """Everything traceable from one batch, limited to the samples this person may see."""
    samples = samples_visible_to(request.user).filter(batch=batch).order_by("-created_at", "-id")
    results = TestResult.objects.filter(sample__in=samples, is_superseded=False).select_related(
        "sample", "test_definition", "entered_by"
    ).order_by("sample__sample_no", "test_definition__order")
    certificates = Certificate.objects.filter(sample__in=samples).select_related("sample").order_by(
        "sample__sample_no", "version"
    )
    history = AuditEvent.objects.filter(entity="batch", entity_id=batch.internal_id).select_related("actor")[:50]
    return Response({
        **batch_payload(batch),
        "sample_count": samples.count(),
        "samples": SampleListSerializer(samples, many=True, context={"request": request}).data,
        "results": [
            {
                "id": r.id, "sample_id": r.sample_id, "sample_no": r.sample.sample_no,
                "test": r.test_definition.name, "unit": r.test_definition.unit,
                "limit_text": r.test_definition.limit_text,
                "value": reported_value(r),
                "outcome": r.outcome, "entered_by": r.entered_by.display_name(), "entered_at": r.entered_at,
            }
            for r in results
        ],
        "certificates": [
            {
                "id": c.id, "sample_id": c.sample_id, "sample_no": c.sample.sample_no, "version": c.version,
                "status": c.status, "status_label": c.get_status_display(),
                "overall": c.content.get("overall", ""), "created_at": c.created_at,
            }
            for c in certificates
        ],
        "documents": [
            document_payload(d) for d in batch.documents.select_related("uploaded_by", "withdrawn_by")
        ],
        "document_types": [{"key": k, "label": v} for k, v in DocumentType.choices],
        "history": [
            {"id": e.id, "at": e.at, "actor_name": e.actor.display_name() if e.actor_id else "System",
             "sentence": describe(e)["sentence"], "severity": describe(e)["severity"]}
            for e in history
        ],
        "can_manage": has_perm(request.user, "batch.manage"),
        "qc_stages": stages_payload(batch, request.user, set(samples.values_list("id", flat=True))),
        "disposition": disposition_payload(batch, request.user),
    })


class BatchWriteSerializer(serializers.Serializer):
    official_batch_no = serializers.CharField(
        max_length=60, error_messages={"max_length": "The batch number cannot be longer than 60 characters."}
    )
    manufacturing_site = serializers.CharField(max_length=120, required=False, allow_blank=True)
    manufacturing_date = serializers.DateField(required=False, allow_null=True)
    expiry_date = serializers.DateField(required=False, allow_null=True)
    batch_size = serializers.CharField(max_length=60, required=False, allow_blank=True)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)


@api_view(["GET", "POST"])
def batches(request):
    if request.method == "GET":
        qs = batches_visible_to(request.user)
        product = request.query_params.get("product")
        if product and product.isdigit():
            qs = qs.filter(product_id=product)
        qs = filter_by_text(request, qs, ["internal_id", "official_batch_no", "product__name", "product__code"])
        qs = filter_by_date(request, qs, BATCH_DATES).annotate(sample_count=Count("samples"))
        return paginated(request, qs.order_by("-created_at", "-id"),
                         lambda rows: [{**batch_payload(b), "qc_progress": stages.progress(b)} for b in rows],
                         export=BATCH_EXPORT)

    if not has_perm(request.user, "batch.manage"):
        return Response({"detail": "You do not have permission to manage batches."}, status=status.HTTP_403_FORBIDDEN)
    product = get_object_or_404(Product, pk=request.data.get("product_id") or 0)
    ser = BatchWriteSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    d = dict(ser.validated_data)
    try:
        batch = services.create(product, d.pop("official_batch_no"), request.user, **d)
    except BatchError as e:
        return _bad(str(e))
    return _detail(request, _visible(request, batch.pk))


@api_view(["GET"])
def lookup(request):
    """Is this number already a batch of this product? Asked while the front desk types."""
    if not (has_perm(request.user, "sample.register") or has_perm(request.user, "batch.manage")):
        return Response({"detail": "You do not have permission to do this."}, status=status.HTTP_403_FORBIDDEN)
    product = get_object_or_404(Product, pk=request.query_params.get("product") or 0)
    batch = services.find(product, request.query_params.get("official_no", ""))
    if batch is None:
        return Response({"batch": None})
    return Response({"batch": {
        **batch_payload(batch), "sample_count": batch.samples.count(),
        # A known batch keeps the stages it was created with, whatever the product has now,
        # with any added to it; one that does not apply to it is not offered.
        "stage_options": stages.registration_options(product, batch),
    }})


@api_view(["GET", "PATCH"])
def batch_detail(request, pk):
    batch = _visible(request, pk)
    if request.method == "GET":
        return _detail(request, batch)
    if not has_perm(request.user, "batch.manage"):
        return Response({"detail": "You do not have permission to manage batches."}, status=status.HTTP_403_FORBIDDEN)
    ser = BatchWriteSerializer(data=request.data, partial=True)
    ser.is_valid(raise_exception=True)
    try:
        services.update(batch, request.user, dict(ser.validated_data), request.data.get("reason", ""))
    except BatchError as e:
        return _bad(str(e))
    return _detail(request, _visible(request, batch.pk))


@api_view(["POST"])
def disposition(request, pk):
    batch = _visible(request, pk)
    try:
        services.decide_disposition(batch, request.user, request.data.get("decision", ""),
                                    request.data.get("reason", ""), request.data.get("password", ""))
    except BatchError as e:
        return _bad(str(e))
    return _detail(request, _visible(request, batch.pk))


@api_view(["POST"])
def record_stage(request, pk, stage_id):
    batch = _visible(request, pk)
    try:
        stages.record_stage(batch, stage_id, request.user, request.data.get("decision", ""),
                            request.data.get("remarks", ""), request.data.get("password", ""))
    except StageError as e:
        return _bad(str(e))
    return _detail(request, _visible(request, batch.pk))


@api_view(["POST"])
def add_stage(request, pk):
    """A QC stage for this batch alone, signed by QA with a reason."""
    batch = _visible(request, pk)
    try:
        stages.add_stage(batch, request.user, request.data, request.data.get("password", ""))
    except StageError as e:
        return _bad(str(e))
    return _detail(request, _visible(request, batch.pk))


@api_view(["POST"])
def stage_entries(request, pk, stage_id):
    """Values written on a recorded stage of the batch record."""
    batch = _visible(request, pk)
    try:
        stages.save_entries(batch, stage_id, request.user, request.data.get("entries"))
    except StageError as e:
        return _bad(str(e))
    return _detail(request, _visible(request, batch.pk))


@api_view(["POST"])
def stage_sign(request, pk, stage_id):
    """One sign-off column of a recorded stage, signed with a password."""
    batch = _visible(request, pk)
    try:
        stages.sign_stage(batch, stage_id, request.data.get("signoff_id"), request.user,
                          request.data.get("password", ""), request.data.get("comment", ""),
                          request.data.get("acknowledge") is True, step_id=request.data.get("step_id"))
    except StageError as e:
        return _bad(str(e))
    return _detail(request, _visible(request, batch.pk))


@api_view(["POST"])
def stage_assign(request, pk, stage_id):
    """Name the person who fills a recorded stage of this batch and signs its first column, or nobody."""
    batch = _visible(request, pk)
    try:
        stages.assign_stage(batch, stage_id, request.user, request.data.get("assignee_id"),
                            request.data.get("note", ""))
    except StageError as e:
        return _bad(str(e))
    return _detail(request, _visible(request, batch.pk))


@api_view(["POST"])
def stage_applicability(request, pk, stage_id):
    """QA's word that a stage does not apply to this batch, or applies again."""
    batch = _visible(request, pk)
    applies = request.data.get("applies")
    if not isinstance(applies, bool):
        return _bad("Say whether the stage applies to this batch.")
    try:
        stages.set_applicability(batch, stage_id, request.user, applies, request.data.get("reason", ""),
                                 request.data.get("password", ""))
    except StageError as e:
        return _bad(str(e))
    return _detail(request, _visible(request, batch.pk))


def _number(v):
    return None if v is None else format(v.normalize(), "f")


def preset_payload(k: CheckpointPreset) -> dict:
    return {
        "id": k.id, "name": k.name, "kind": k.kind, "kind_label": k.get_kind_display(), "unit": k.unit,
        "min_value": _number(k.min_value), "max_value": _number(k.max_value), "decimals": k.decimals,
        "choices": k.choices, "is_active": k.is_active,
    }


def _clean_preset(data) -> dict:
    name = str(data.get("name") or "").strip()
    if not name:
        raise StageError("Give the kind a name, such as Temperature or Equipment ID.")
    if len(name) > 60:
        raise StageError("Keep the name to 60 characters.")
    if name.lower() in {k.label.lower() for k in CheckpointKind}:
        raise StageError(f"“{name}” is already a built-in kind.")
    return {"name": name, **clean_kind(data, f"“{name}”")}


@api_view(["GET", "POST"])
@permission_classes([RequiresPermission.of("product.manage")])
def checkpoint_presets(request):
    """The lab's own kinds of value: listed, and a new one added."""
    if request.method == "GET":
        qs = CheckpointPreset.objects.all()
        return Response([preset_payload(k) for k in (qs if request.query_params.get("all") else qs.filter(is_active=True))])
    try:
        fields = _clean_preset(request.data)
    except StageError as e:
        return _bad(str(e))
    if CheckpointPreset.objects.filter(name__iexact=fields["name"]).exists():
        return _bad(f"There is already a kind called “{fields['name']}”.")
    kind = CheckpointPreset.objects.create(created_by=request.user, **fields)
    record(request.user, "CHECKPOINT_KIND_CREATED", "checkpoint kind", kind.name, based_on=kind.get_kind_display())
    return Response(preset_payload(kind), status=status.HTTP_201_CREATED)


@api_view(["PATCH"])
@permission_classes([RequiresPermission.of("product.manage")])
def checkpoint_preset_detail(request, pk):
    """Change one of the lab's kinds, or retire it. Stages already saved keep their copy."""
    kind = get_object_or_404(CheckpointPreset, pk=pk)
    before = preset_payload(kind)
    if set(request.data) - {"is_active"}:
        try:
            fields = _clean_preset({**before, **request.data})
        except StageError as e:
            return _bad(str(e))
        if CheckpointPreset.objects.filter(name__iexact=fields["name"]).exclude(pk=kind.pk).exists():
            return _bad(f"There is already a kind called “{fields['name']}”.")
        for k, v in fields.items():
            setattr(kind, k, v)
    if "is_active" in request.data:
        kind.is_active = bool(request.data.get("is_active"))
    kind.save()
    after = preset_payload(kind)
    changed = {k: after[k] for k in after if after[k] != before[k]}
    if changed:
        record(request.user, "CHECKPOINT_KIND_CHANGED", "checkpoint kind", kind.name,
               was={k: before[k] for k in changed}, **changed)
    return Response(after)


def _product_stages(request, product) -> Response:
    versions = product.stage_plans.select_related("created_by").annotate(
        stage_count=Count("stages", distinct=True), batch_count=Count("batches", distinct=True),
    ).order_by("-version")
    return Response({
        "current": plan_payload(product.current_stage_plan()),
        "versions": [
            {"version": v.version, "reason": v.reason, "created_by": v.created_by.display_name(),
             "created_at": v.created_at, "stage_count": v.stage_count, "batch_count": v.batch_count}
            for v in versions
        ],
        "kinds": [{"value": k.value, "label": k.label} for k in StageKind],
        "checkpoint_kinds": [{"value": k.value, "label": k.label} for k in CheckpointKind],
        # The lab's own kinds of value, offered beside the built-in ones.
        "checkpoint_presets": [preset_payload(k) for k in CheckpointPreset.objects.filter(is_active=True)],
        # The product's own specification, shown with the stages that use it.
        "product_spec": spec_summary(product.current_specification()),
        "can_spec": has_perm(request.user, "spec.manage") or has_perm(request.user, "spec.approve"),
        # Who can sign a sign-off column: any active role.
        "roles": [{"id": r.id, "name": r.name} for r in Role.objects.filter(is_active=True).order_by("name")],
        "can_manage": has_perm(request.user, "product.manage"),
    })


@api_view(["GET"])
def product_stage_version(request, pk, version):
    """One version of a product's stages as it was saved, and what it changed from the one before."""
    product = get_object_or_404(Product, pk=pk)
    plan = get_object_or_404(QcStagePlan.objects.select_related("created_by"), product=product, version=version)
    before = product.stage_plans.filter(version__lt=version).order_by("-version").first()
    return Response({
        **plan_payload(plan),
        "changes": stages.plan_changes(before, plan),
        "batch_count": plan.batches.count(),
        "is_current": plan.pk == product.current_stage_plan().pk,
    })


@api_view(["GET", "PUT"])
def product_stages(request, pk):
    """The QC stages every new batch of this product goes through. A change is a new version."""
    product = get_object_or_404(Product, pk=pk)
    if request.method == "PUT":
        if not has_perm(request.user, "product.manage"):
            return Response({"detail": "You do not have permission to change a product's QC stages."},
                            status=status.HTTP_403_FORBIDDEN)
        try:
            stages.save_stages(product, request.user, request.data.get("stages"), request.data.get("reason", ""))
        except StageError as e:
            return _bad(str(e))
    return _product_stages(request, product)


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([RequiresPermission.of("batch.manage")])
def documents(request, pk):
    batch = _visible(request, pk)
    try:
        services.upload_document(batch, request.user, request.FILES.get("file"), request.data.get("doc_type", ""),
                                 request.data.get("title", ""), request.data.get("replaces_id"),
                                 request.data.get("note", ""))
    except BatchError as e:
        return _bad(str(e))
    return _detail(request, batch)


@api_view(["GET"])
def document_file(request, pk):
    """Documents are served only here, to people who can see the batch — never from a public path."""
    d = get_object_or_404(BatchDocument, pk=pk)
    _visible(request, d.batch_id)
    return private_file_response(d.file, d.extension, d.content_type, d.original_name,
                                 download=request.query_params.get("download") == "1")


@api_view(["POST"])
@permission_classes([RequiresPermission.of("batch.manage")])
def document_withdraw(request, pk):
    d = get_object_or_404(BatchDocument.objects.select_related("batch"), pk=pk)
    batch = _visible(request, d.batch_id)
    try:
        services.withdraw_document(d, request.user, request.data.get("reason", ""))
    except BatchError as e:
        return _bad(str(e))
    return _detail(request, batch)


def _rule_payload(rule: BatchNumberRule) -> dict:
    return {
        "prefix": rule.prefix, "separator": rule.separator, "digits": rule.digits,
        "include_year": rule.include_year, "include_section": rule.include_section,
        "include_product": rule.include_product, "restart_yearly": rule.restart_yearly,
        "example": build_id(rule, "GF", "PCM-500", 2026, 123),
    }


@api_view(["GET", "PUT"])
@permission_classes([CanManageConfig])
def numbering_rule(request):
    rule = BatchNumberRule.get()
    if request.method == "PUT":
        try:
            cleaned = clean_rule(request.data)
        except ValueError as e:
            return _bad(str(e))
        before = _rule_payload(rule)["example"]
        for field, value in cleaned.items():
            setattr(rule, field, value)
        rule.save()
        after = _rule_payload(rule)["example"]
        if before != after:
            record(request.user, "BATCH_RULE_CHANGED", "batch", "numbering rule", before=before, after=after)
    return Response(_rule_payload(rule))
