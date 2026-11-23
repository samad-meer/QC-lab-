from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from accounts.authz import OVERRIDE, RequiresPermission, has_perm, overrides
from accounts.models import User
from accounts.serializers import UserSerializer
from audit.services import record
from qclab.listing import filter_by_date, filter_by_text, paginated
from .evaluation import ResultValueError, evaluate, parse_numeric, reported_value
from .models import (
    FINISHED,
    Outcome,
    Product,
    Sample,
    SampleStatus,
    Section,
    TestDefinition,
    TestResult,
    WorkflowEvent,
)
from .numbering import next_sample_no
from batches.services import BatchError, find as find_batch, for_registration
from batches.stages import StageError, spec_for, stage_for_registration
from execution.models import TESTING
from execution.rules import ExecutionError, require_can_work, stamp, step_of
from execution.services import (
    authorized_retest_for, mark_retest_used, record_registration, require_second_analyst,
)
from labrecords import rawdata
from labrecords.services import LabRecordError, qualification_problem
from notifications.alerts import failed_result
from reports.list_export import Col, ListExport
from .workflow import is_reviewer, review_queue, samples_visible_to
from .serializers import (
    ProductSerializer,
    SampleDetailSerializer,
    SampleListSerializer,
    SampleRegisterSerializer,
    SectionSerializer,
    TestResultSerializer,
)


# The dates a sample list can be filtered on.
SAMPLE_DATES = {"received": "received_at", "due": "due_date"}
SAMPLE_SEARCH = ["sample_no", "batch_no", "reference", "batch__internal_id", "product__name", "product__code"]


def _status_names(value: str) -> str:
    if value == "ALL":
        return "All"
    names = dict(SampleStatus.choices)
    return ", ".join(names.get(part, part) for part in value.split(","))


# The samples list as a file: the columns of the screen, and the dates behind them.
SAMPLE_EXPORT = ListExport(
    key="samples",
    title="Samples",
    columns=[
        Col("Sample No", lambda s: s.sample_no, 1.1),
        Col("Product", lambda s: s.product.name, 1.8),
        Col("Code", lambda s: s.product.code, 0.8),
        Col("Section", lambda s: s.section.code, 0.7),
        Col("Batch / reference", lambda s: s.batch_label, 1.1),
        Col("Analyst", lambda s: s.assigned_analyst.display_name() if s.assigned_analyst_id else "", 1.2),
        Col("Received", lambda s: s.received_at, 1.2),
        Col("Due", lambda s: s.due_date, 0.9),
        Col("Status", lambda s: s.status_label(), 1.3),
    ],
    filters={"status": ("Status", _status_names), "q": "Search", "mine": ("Assigned", lambda _: "To me")},
    dates={"received": "Received", "due": "Due"},
    scoped=True,
)


@api_view(["GET"])
def sections(request):
    return Response(SectionSerializer(Section.objects.order_by("id"), many=True).data)


@api_view(["GET"])
@permission_classes([RequiresPermission.of("sample.register")])
def products(request):
    qs = Product.objects.filter(is_active=True).select_related("section").order_by("name")
    section = request.query_params.get("section")
    if section:
        qs = qs.filter(section__code=section)
    return Response(ProductSerializer(qs, many=True).data)


@api_view(["GET"])
@permission_classes([RequiresPermission.of("sample.register")])
def analysts(request):
    """
    Who can be assigned a sample: anyone whose role may enter results, and
    who is trained for the chosen section (brief, step 2). Not a fixed role
    name — a lab that invents "Senior Analyst" gets it here for free.
    """
    section = request.query_params.get("section")
    qs = User.objects.filter(is_active=True, role__is_active=True).filter(
        role__grants__permission="result.enter", role__grants__revoked_at__isnull=True
    )
    if section:
        qs = qs.filter(sections__code=section)
    return Response(UserSerializer(qs.distinct().order_by("first_name", "username"), many=True).data)


@api_view(["GET"])
def summary(request):
    """
    Counts for the caller's own view of the pipeline — drives nav badges, and
    the tiles above a sample list, which follow that list's date filter.
    """
    qs = filter_by_date(request, samples_visible_to(request.user), SAMPLE_DATES)
    counts = {row["status"]: row["n"] for row in qs.values("status").annotate(n=Count("id"))}
    mine = 0
    if has_perm(request.user, "result.enter"):
        mine = qs.filter(
            assigned_analyst=request.user,
            status__in=[SampleStatus.RECEIVED, SampleStatus.IN_TESTING],
        ).count()
    if is_reviewer(request.user):
        mine = review_queue(request.user).count()
    overdue = (
        qs.exclude(status__in=FINISHED)
        .filter(due_date__lt=timezone.localdate())
        .count()
    )
    return Response(
        {
            "by_status": {s.value: counts.get(s.value, 0) for s in SampleStatus},
            "total": sum(counts.values()),
            "awaiting_me": mine,
            "overdue": overdue,
        }
    )


@api_view(["GET", "POST"])
def samples(request):
    if request.method == "GET":
        qs = samples_visible_to(request.user)
        if request.query_params.get("mine"):
            qs = qs.filter(assigned_analyst=request.user)
        status_filter = request.query_params.get("status")
        if status_filter:
            if status_filter != "ALL":
                qs = qs.filter(status__in=status_filter.split(","))
        elif is_reviewer(request.user):
            # A reviewer's default view is their queue: samples waiting at a
            # stage their role signs.
            qs = qs.filter(pk__in=review_queue(request.user).values("pk"))
        qs = filter_by_text(request, qs, SAMPLE_SEARCH)
        qs = filter_by_date(request, qs, SAMPLE_DATES).order_by("-created_at", "-id")
        return paginated(
            request, qs,
            lambda rows: SampleListSerializer(rows, many=True, context={"request": request}).data,
            export=SAMPLE_EXPORT,
            overdue=qs.exclude(status__in=FINISHED).filter(due_date__lt=timezone.localdate()).count(),
        )

    # POST — register a new sample
    if not has_perm(request.user, "sample.register"):
        message = "You do not have permission to register samples."
        record(request.user, "ACCESS_REFUSED", "sample", "new sample", reason=message)
        return Response({"detail": message}, status=status.HTTP_403_FORBIDDEN)
    ser = SampleRegisterSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data

    product = get_object_or_404(Product, pk=d["product_id"])
    if not product.is_active:
        return Response({"detail": f"{product.name} is no longer active."}, status=status.HTTP_400_BAD_REQUEST)
    spec = product.current_specification()
    if spec is None:
        return Response(
            {"detail": f"{product.name} has no effective specification. Set one up first."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    workflow = product.review_workflow()
    if workflow is None or workflow.current_version() is None:
        return Response(
            {"detail": f"{product.name} has no review workflow. Ask an administrator to set one up."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    workflow_version = workflow.current_version()
    analyst = get_object_or_404(User, pk=d["analyst_id"], is_active=True)
    if not has_perm(analyst, "result.enter"):
        return Response(
            {"detail": f"{analyst.display_name()} is not permitted to enter results."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not analyst.sections.filter(pk=product.section_id).exists():
        return Response(
            {"detail": f"{analyst.display_name()} is not trained for the {product.section.name} section."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # What a known batch records stands, so its expiry is the one that counts.
    known = find_batch(product, d["batch_no"]) if d["from_batch"] else None
    expiry = (known.expiry_date if known else None) or d.get("expiry_date")
    past_expiry_reason = ""
    if expiry and expiry < timezone.localtime(d["received_at"]).date():
        past_expiry_reason = d.get("past_expiry_reason", "").strip()
        if not past_expiry_reason:
            return Response(
                {"expiry_date": [
                    f"This batch expired on {expiry:%d-%b-%Y}, before it was received. "
                    "Say why it is being tested: the reason prints on the certificate."
                ]},
                status=status.HTTP_400_BAD_REQUEST,
            )

    # Which of the batch's QC stages this sample is for: the stages a known batch
    # has (its version of the product's, and any added to it), or the product's
    # current ones for a batch created now. One that does not apply to the batch,
    # or still waits for an earlier stage, is refused.
    try:
        if d["from_batch"]:
            qc_stage = stage_for_registration(product, known, d.get("qc_stage_id"))
        elif d.get("qc_stage_id"):
            raise StageError("Only a sample from a batch is taken for a QC stage.")
        else:
            qc_stage = None
    except StageError as e:
        return Response({"qc_stage_id": [str(e)]}, status=status.HTTP_400_BAD_REQUEST)
    # A stage with its own tests in force has its samples tested on them.
    spec = spec_for(product, qc_stage)

    with transaction.atomic():
        batch = None
        if d["from_batch"]:
            try:
                batch = for_registration(
                    product, d["batch_no"], request.user, site=d.get("manufacturing_site", "").strip(),
                    manufactured=d.get("manufacturing_date"), expires=d.get("expiry_date"),
                )
            except BatchError as e:
                return Response({"batch_no": [str(e)]}, status=status.HTTP_400_BAD_REQUEST)
            # The product's stages changed while the form was open: a new batch took the new ones.
            if qc_stage is not None and qc_stage.plan_id != batch.stage_plan_id and qc_stage.batch_id != batch.id:
                transaction.set_rollback(True)
                return Response({"qc_stage_id": ["The product's QC stages have just changed. Choose the stage again."]},
                                status=status.HTTP_400_BAD_REQUEST)
        sample = Sample.objects.create(
            sample_no=next_sample_no(product.section),
            product=product,
            specification=spec,
            section=product.section,
            batch=batch,
            # What the batch records stands; these are copied so a signed
            # certificate can freeze them with everything else.
            batch_no=batch.official_batch_no if batch else "",
            reference="" if batch else d["reference"].strip(),
            qc_stage=qc_stage,
            quantity=d["quantity"],
            received_from=d["received_from"],
            received_at=d["received_at"],
            due_date=d["due_date"],
            manufacturing_date=batch.manufacturing_date if batch else d.get("manufacturing_date"),
            expiry_date=batch.expiry_date if batch else d.get("expiry_date"),
            storage_condition=d.get("storage_condition", "") or product.storage_condition,
            past_expiry_reason=past_expiry_reason,
            assigned_analyst=analyst,
            # Bound now, like the specification: a later edit to the
            # workflow never re-routes this sample.
            workflow_version=workflow_version,
            registered_by=request.user,
        )
        WorkflowEvent.objects.create(
            sample=sample,
            actor=request.user,
            from_status=SampleStatus.RECEIVED,
            to_status=SampleStatus.RECEIVED,
            comment=f"Registered and assigned to {analyst.display_name()}",
        )
        record_registration(sample, analyst, request.user)
        record(
            request.user, "SAMPLE_REGISTERED", "sample", sample.sample_no,
            product=product.code, batch=sample.batch_label, analyst=analyst.username,
            spec_version=spec.version, **({"tests_of_stage": spec.stage_name} if spec.stage_key else {}),
            workflow=str(workflow_version),
            **({"past_expiry": past_expiry_reason} if past_expiry_reason else {}),
            **({"qc_stage": qc_stage.name} if qc_stage else {}),
        )
    return Response(
        SampleDetailSerializer(sample, context={"request": request}).data, status=status.HTTP_201_CREATED
    )


@api_view(["GET"])
def sample_detail(request, pk):
    sample = get_object_or_404(Sample, pk=pk)
    if not samples_visible_to(request.user).filter(pk=sample.pk).exists():
        return Response({"detail": "This sample is not assigned to you."}, status=status.HTTP_403_FORBIDDEN)
    return Response(SampleDetailSerializer(sample, context={"request": request}).data)


@api_view(["POST"])
@permission_classes([RequiresPermission.of("result.enter")])
def enter_result(request, pk):
    """
    Enter (or correct) one test result. The system decides pass/fail.
    Correcting an existing result requires a reason; the old value stays,
    marked superseded (Rule Two).

    It can also carry its raw data: worksheet_ref, instrument_id, material_ids,
    readings and notes. With readings and no value, the result reports their mean.
    """
    sample = get_object_or_404(Sample, pk=pk)
    # Not a permission — an invariant. Results only ever go on your own sample,
    # unless an administrator acts in the analyst's place: require_can_work,
    # below, is what notes that on the audit rows.
    if sample.assigned_analyst_id != request.user.id and not has_perm(request.user, OVERRIDE):
        message = "This sample is not assigned to you."
        record(request.user, "ACCESS_REFUSED", "sample", sample.sample_no, reason=message)
        return Response({"detail": message}, status=status.HTTP_403_FORBIDDEN)

    test_id = request.data.get("test_definition_id")
    test = get_object_or_404(TestDefinition, pk=test_id if str(test_id).isdigit() else 0, specification=sample.specification)
    value_numeric = request.data.get("value_numeric", None)
    if value_numeric == "":
        value_numeric = None
    value_text = str(request.data.get("value_text") or "").strip()[:200]

    try:
        # Convert and bound the number once, up front — the same Decimal is
        # both evaluated and stored, so the recorded value is exactly the
        # one the pass/fail decision was made on.
        if value_numeric is not None:
            value_numeric = parse_numeric(value_numeric)
        raw_data = rawdata.parse(request.data)
        value_numeric = rawdata.reported_from(test, value_numeric, value_text, raw_data)
        outcome = evaluate(test, value_numeric, value_text)
    except (ResultValueError, LabRecordError) as e:
        return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        # Lock the sample so result entry cannot race the analyst's signature
        # (which locks the same row), then re-check the status under the lock.
        sample = Sample.objects.select_for_update().get(pk=sample.pk)
        if sample.status not in (SampleStatus.RECEIVED, SampleStatus.IN_TESTING):
            return Response(
                {"detail": f"Results cannot be entered while the sample is {sample.get_status_display()}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            # On hold, or handed over and not yet accepted: nothing is entered.
            require_can_work(sample, step_of(sample, TESTING), request.user)
        except ExecutionError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        if test.method_record_id:
            problem = qualification_problem(request.user, test.method_record.code)
            if problem and not overrides(request.user, "A result is entered by someone qualified on the method."):
                record(request.user, "RESULT_REFUSED_UNQUALIFIED", "sample", sample.sample_no, test=test.name,
                       method=test.method_record.code, reason=problem)
                return Response({"detail": problem}, status=status.HTTP_400_BAD_REQUEST)
        try:
            instrument, materials = rawdata.check_usable(raw_data)
        except LabRecordError as e:
            record(request.user, "RESULT_REFUSED_RAW_DATA", "sample", sample.sample_no, test=test.name, reason=str(e))
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        existing = (
            TestResult.objects.select_for_update()
            .filter(sample=sample, test_definition=test, is_superseded=False)
            .first()
        )
        retest = None
        if existing and existing.outcome == Outcome.FAIL:
            # A failed result is never simply replaced: only an authorized
            # retest may follow it, and the failure stays on record.
            retest = authorized_retest_for(existing)
            if retest is not None:
                try:
                    require_second_analyst(sample, test, request.user)
                except ExecutionError as e:
                    return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
            if retest is None:
                record(request.user, "RESULT_REPLACE_REFUSED_FAILED", "sample", sample.sample_no, test=test.name)
                return Response(
                    {"detail": (
                        f"{test.name} failed its specification. A failed result is never replaced directly — "
                        "request a retest, and once someone else authorizes it, enter the retest result."
                    )},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if existing:
            reason = (request.data.get("supersede_reason") or "").strip()
            if retest is not None:
                reason = (
                    f"Retest authorized by {retest.decided_by.display_name()} on {stamp(retest.decided_at)}: "
                    f"{retest.reason}" + (f" — {reason}" if reason else "")
                )[:500]
            if not reason:
                return Response(
                    {"detail": "A result already exists for this test. Give the reason for replacing it."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            # Mark the old value superseded FIRST so only one result is
            # "current" at any moment (the DB enforces that), then create
            # the replacement and link it.
            existing.is_superseded = True
            existing.superseded_at = timezone.now()
            existing.superseded_by_user = request.user
            existing.supersede_reason = reason
            existing.save()
        new = TestResult.objects.create(
            sample=sample,
            test_definition=test,
            value_numeric=value_numeric,
            value_text=value_text,
            outcome=outcome,
            entered_by=request.user,
        )
        rawdata.save(new, raw_data, instrument, materials, request.user)
        if existing:
            existing.replaced_by = new
            existing.save()
            record(
                request.user, "RESULT_SUPERSEDED", "sample", sample.sample_no,
                test=test.name, old_id=existing.id, new_id=new.id, reason=existing.supersede_reason,
                old_value=reported_value(existing), new_value=reported_value(new),
            )
        if retest is not None:
            mark_retest_used(retest, new, request.user)
        if sample.status == SampleStatus.RECEIVED:
            sample.status = SampleStatus.IN_TESTING
            sample.save(update_fields=["status"])
        record(
            request.user, "RESULT_ENTERED", "sample", sample.sample_no,
            test=test.name, outcome=outcome,
            value=str(value_numeric) if value_numeric is not None else value_text,
        )
        if outcome == Outcome.FAIL:
            failed_result(sample, test, str(value_numeric) if value_numeric is not None else value_text, request.user)
    return Response(TestResultSerializer(new).data, status=status.HTTP_201_CREATED)
