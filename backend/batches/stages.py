"""
QC stages: the stages every batch of a product goes through, such as a line
clearance, the final grain test and the core tablet test.

The stages are set on the product and versioned: a change is a new version, and
a batch keeps the version in force when it was created, so a later change never
alters a batch already under way. Every batch gets its own run of them.

A stage tested in the lab passes when every sample registered for it is approved
with a certificate in force, and fails when one is rejected. Its samples are
tested on the stage's own tests where they are effective (a specification filed
under the stage's key), otherwise on the product's specification. A stage
recorded by QA passes or fails when someone records it with their password; its
latest record counts, and an earlier one stays beside it.

A stage can wait for the stages before it: nothing is done for it until every
earlier required stage has passed or does not apply. QA can say a stage does not
apply to one batch, before anything is done for it, and can add a stage to one
batch alone; both are signed, with a reason, and the product's stages never
change. A batch is released only when every required stage that applies has passed.
"""
from typing import NamedTuple

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.authz import OVERRIDE, has_perm, overrides
from accounts.passwords import confirm_password
from audit.services import record
from certificates.models import CertStatus, Certificate
from lims.models import SampleStatus
from .models import (
    Batch, BatchCheckpointEntry, BatchStageApplicability, BatchStageAssignment, BatchStageResult, BatchStageSignature,
    DispositionDecision, QcCheckpoint, QcStage, QcStagePlan, StageDecision, StageKind,
)
from .records import (  # noqa: F401  StageError is also this module's, as it always was
    StageError, clean_signoffs, clean_steps, create_template, fields_of, is_record, outside, parse_value,
    record_of, shown, template_rows,
)

RECORD = "batch.stage.record"
FILL = "batch.record.fill"
ASSIGN = "batch.stage.assign"
MAX_STAGES = 30
MAX_EXTRA = 10  # stages added to one batch

NOT_STARTED, IN_PROGRESS, PASSED, FAILED, NOT_APPLICABLE = (
    "NOT_STARTED", "IN_PROGRESS", "PASSED", "FAILED", "NOT_APPLICABLE",
)
STATUS_LABELS = {
    NOT_STARTED: "Not started", IN_PROGRESS: "In progress", PASSED: "Passed", FAILED: "Failed",
    NOT_APPLICABLE: "Not applicable",
}
# What a later stage that waits for the stages before it counts as done.
DONE = (PASSED, NOT_APPLICABLE)


# --- keys: which tests a stage's samples get --------------------------------------------

def stage_key(name: str) -> str:
    """The key a stage's tests are filed under, made from a name: “Final  Grain” gives “final grain”."""
    return " ".join(str(name or "").split()).lower()[:80]


def tests_key(stage: QcStage) -> str:
    """The key of the tests this stage's samples get; empty for the product's own specification."""
    return stage.tests_key if stage.tests_key is not None else stage_key(stage.name)


def spec_for(product, stage: QcStage | None):
    """
    The specification a sample for this stage is tested on: the stage's own tests
    when a version of them is effective, otherwise the product's specification.
    """
    if stage is not None:
        key = tests_key(stage)
        if key:
            own = product.current_specification(key)
            if own is not None:
                return own
    return product.current_specification()


def test_tracks(product) -> list[dict]:
    """
    The sets of tests a product's stages can have, besides its own specification:
    one per lab-tested stage of its current version, then any drafted for a stage
    it no longer has, so they stay on view.
    """
    plan = product.current_stage_plan()
    tracks, seen = [], set()
    for s in (plan.stages.order_by("order") if plan else []):
        key = tests_key(s)
        if s.kind != StageKind.TESTED or not key or key in seen:
            continue
        seen.add(key)
        tracks.append({"key": key, "name": s.name, "current": True})
    for key, name in product.specifications.exclude(stage_key="").order_by("-version").values_list(
        "stage_key", "stage_name"
    ):
        if key not in seen:
            seen.add(key)
            tracks.append({"key": key, "name": name, "current": False})
    return tracks


# --- the stages of a product -------------------------------------------------------

def _clean(rows) -> list[dict]:
    if not isinstance(rows, list):
        raise StageError("Send the stages as a list.")
    if len(rows) > MAX_STAGES:
        raise StageError(f"A product can have at most {MAX_STAGES} QC stages.")
    cleaned, seen = [], set()
    for i, row in enumerate(rows, start=1):
        row = row if isinstance(row, dict) else {}
        name = str(row.get("name") or "").strip()
        if not name:
            raise StageError(f"Stage {i} needs a name.")
        if len(name) > 80:
            raise StageError(f"Keep the name of stage {i} to 80 characters.")
        if name.lower() in seen:
            raise StageError(f"Two stages are called “{name}”. Give each its own name.")
        seen.add(name.lower())
        kind = row.get("kind")
        if kind not in StageKind.values:
            raise StageError(f"Choose how stage {i}, {name}, is done: tested in the lab or recorded by QA.")
        key = row.get("key")
        # A recorded stage can have steps with their check points, and sign-off columns;
        # a stage tested in the lab has its samples instead.
        where = f"stage {i}, {name}"
        recorded = kind == StageKind.RECORDED
        steps = clean_steps(where, row.get("steps")) if recorded else []
        signoffs = clean_signoffs(where, row.get("signoffs")) if recorded else []
        if steps and not signoffs:
            raise StageError(f"Give {where} at least one sign-off column, such as Done by, so its steps are signed.")
        cleaned.append({
            "name": name,
            "description": str(row.get("description") or "").strip()[:300],
            "kind": kind,
            "required": bool(row.get("required", True)),
            # The first stage has nothing before it to wait for.
            "after_previous": bool(row.get("after_previous", False)) and i > 1,
            "key": stage_key(key) if isinstance(key, str) else "",
            "steps": steps,
            "signoffs": signoffs,
            # Signed under every step, as on the paper record, or once for the stage.
            "sign_each_step": bool(row.get("sign_each_step", False)) and bool(steps) and bool(signoffs),
        })
    return cleaned


def _assign_keys(product, stages: list[dict]) -> None:
    """
    Each stage's tests key. A stage that already had one keeps it, renamed or not,
    so it keeps its tests; a new stage's is made from its name. No two the same.
    """
    known = {tests_key(s) for s in QcStage.objects.filter(plan__product=product)}
    known |= set(product.specifications.exclude(stage_key="").values_list("stage_key", flat=True))
    taken: set[str] = set()
    for s in stages:
        key = s.pop("key")
        s["tests_key"] = key if key and key in known and key not in taken else None
        if s["tests_key"]:
            taken.add(key)
    for s in stages:
        if s["tests_key"] is None:
            base = key = stage_key(s["name"])
            n = 2
            while key in taken:
                key = f"{base[:76]} {n}"
                n += 1
            s["tests_key"] = key
            taken.add(key)


def _as_rows(plan: QcStagePlan | None) -> list[dict]:
    if plan is None:
        return []
    rows = []
    for s in plan.stages.order_by("order").prefetch_related("steps__checkpoints", "signoffs"):
        steps, signoffs = template_rows(s)
        rows.append({"name": s.name, "description": s.description, "kind": s.kind, "required": s.required,
                     "after_previous": s.after_previous, "tests_key": tests_key(s),
                     "steps": steps, "signoffs": signoffs, "sign_each_step": s.sign_each_step})
    return rows


def save_stages(product, by, rows, reason: str) -> QcStagePlan | None:
    """
    A new version of the product's stages, for batches created from now on. Nothing
    is saved when nothing changed. Batches already created keep theirs.
    """
    stages = _clean(rows)
    reason = (reason or "").strip()[:500]
    with transaction.atomic():
        # One at a time per product, so two administrators cannot both make version 3.
        type(product).objects.select_for_update().get(pk=product.pk)
        _assign_keys(product, stages)
        current = product.current_stage_plan()
        if stages == _as_rows(current):
            return current
        if not reason:
            raise StageError("Say why the stages are changing. The reason stays with the version.")
        plan = QcStagePlan.objects.create(
            product=product, version=(current.version + 1) if current else 1, reason=reason, created_by=by,
        )
        for order, s in enumerate(stages, start=1):
            fields = {k: v for k, v in s.items() if k not in ("steps", "signoffs")}
            stage = QcStage.objects.create(plan=plan, order=order, **fields)
            create_template(stage, s["steps"], s["signoffs"])
        record(by, "QC_STAGES_CHANGED", "product", product.code, version=plan.version, reason=reason,
               changes=plan_changes(current, plan),
               stages=[f"{s['name']} ({'required' if s['required'] else 'optional'}"
                       f"{', waits for the stages before it' if s['after_previous'] else ''}"
                       f"{_shape(s)})" for s in stages])
    return plan


def _shape(s: dict) -> str:
    """“, 3 steps, 9 check points, 3 sign-offs” for the activity log."""
    if not s["steps"] and not s["signoffs"]:
        return ""
    points = sum(len(step["checkpoints"]) for step in s["steps"])
    signed = " signed at every step" if s.get("sign_each_step") else ""
    return f", {len(s['steps'])} steps, {points} check points, {len(s['signoffs'])} sign-offs{signed}"


# --- the stages of a batch ---------------------------------------------------------

TEMPLATE = ("steps__checkpoints", "signoffs__role")


def stages_of(batch: Batch) -> list[QcStage]:
    """Every stage of the batch in order: its version of the product's, then any added to it alone."""
    own = list(batch.stage_plan.stages.prefetch_related(*TEMPLATE)) if batch.stage_plan_id else []
    extra = list(batch.extra_stages.select_related("added_by").prefetch_related(*TEMPLATE))
    return sorted(own + extra, key=lambda s: s.order)


def _tested_status(samples) -> str:
    if not samples:
        return NOT_STARTED
    if any(s.status == SampleStatus.REJECTED for s in samples):
        return FAILED
    in_force = set(
        Certificate.objects.filter(sample__in=samples, status=CertStatus.APPROVED).values_list("sample_id", flat=True)
    )
    if all(s.status == SampleStatus.APPROVED and s.pk in in_force for s in samples):
        return PASSED
    return IN_PROGRESS


def _waiting(rows: list[dict]) -> list[dict]:
    """What each stage still waits for: the earlier required stages not yet passed, if it waits for them."""
    for row in rows:
        stage = row["stage"]
        row["waiting_for"] = [
            r["stage"] for r in rows
            if stage.after_previous and r["stage"].order < stage.order and r["stage"].required
            and r["status"] not in DONE
        ]
    return rows


def batch_stages(batch: Batch) -> list[dict]:
    """
    Each stage of the batch with where it stands, judged from the whole batch: never
    only what the person looking can see.
    """
    stages = stages_of(batch)
    if not stages:
        return []
    samples = list(batch.samples.exclude(status=SampleStatus.CANCELLED).filter(qc_stage__in=stages))
    results = list(batch.stage_results.select_related("recorded_by").order_by("id"))
    marks = list(batch.stage_applicability.select_related("recorded_by").order_by("id"))
    entries = list(batch.checkpoint_entries.select_related("entered_by").order_by("id"))
    signatures = list(batch.stage_signatures.select_related("signed_by").order_by("id"))
    assigned = list(batch.stage_assignments.select_related("assignee", "assigned_by").order_by("id"))
    rows = []
    for stage in stages:
        mine = [s for s in samples if s.qc_stage_id == stage.pk]
        records = [r for r in results if r.stage_id == stage.pk]
        applicability = [m for m in marks if m.stage_id == stage.pk]
        # Who has the stage: the latest assignment, unless it named nobody.
        handed = [a for a in assigned if a.stage_id == stage.pk]
        assignment = handed[-1] if handed and handed[-1].assignee_id else None
        sheet = None
        if is_record(stage):
            points = {cp.pk for step in stage.steps.all() for cp in step.checkpoints.all()}
            columns = {so.pk for so in stage.signoffs.all()}
            sheet = record_of(stage, [e for e in entries if e.checkpoint_id in points],
                              [g for g in signatures if g.signoff_id in columns])
        if applicability and not applicability[-1].applies:
            status = NOT_APPLICABLE
        elif stage.kind == StageKind.TESTED:
            status = _tested_status(mine)
        elif sheet is not None:
            # Filled and signed on the batch record: passed once every column is signed.
            status = PASSED if sheet["signed_all"] else IN_PROGRESS if sheet["touched"] else NOT_STARTED
        else:
            status = {StageDecision.PASSED: PASSED, StageDecision.FAILED: FAILED}[records[-1].decision] \
                if records else NOT_STARTED
        rows.append({"stage": stage, "status": status, "samples": mine, "records": records,
                     "applicability": applicability, "record": sheet,
                     "assignment": assignment, "assignments": handed})
    # Once any stage of the batch is assigned, the batch works by assignment: a stage nobody
    # has been named for waits for someone to be named. With none assigned, anyone who may
    # fill batch records fills any stage, as before.
    by_assignment = any(r["assignment"] is not None for r in rows)
    for r in rows:
        r["by_assignment"] = by_assignment
    return _waiting(rows)


def _fresh_rows(plan: QcStagePlan | None) -> list[dict]:
    """A new batch's stages, before anything has been done for any of them."""
    stages = list(plan.stages.order_by("order")) if plan else []
    return _waiting([{"stage": s, "status": NOT_STARTED, "samples": [], "records": [], "applicability": [],
                      "record": None} for s in stages])


def _names(stages) -> str:
    names = [f"{s.order}. {s.name}" for s in stages]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def waiting_message(stage: QcStage, waiting) -> str:
    return (f"{stage.name} waits for the stages before it, and {_names(waiting)} "
            f"{'has' if len(waiting) == 1 else 'have'} not passed yet.")


def stage_problems(batch: Batch) -> list[str]:
    """
    Why the batch's stages stand in the way of releasing it: a required stage that
    has not passed, and, on any other stage, a value out of limit that its last
    sign-off has not yet acknowledged.
    """
    problems = []
    for row in batch_stages(batch):
        stage = row["stage"]
        if stage.required and row["status"] not in DONE:
            problems.append(f"QC stage {stage.order}, {stage.name}, has not passed "
                            f"({STATUS_LABELS[row['status']].lower()}).")
        elif row["record"] and row["record"]["unacknowledged"] and row["status"] not in DONE:
            count = len(row["record"]["unacknowledged"])
            problems.append(f"QC stage {stage.order}, {stage.name}, has {count} value{'s' if count > 1 else ''} "
                            "out of limit that its last sign-off has not acknowledged.")
    return problems


def progress(batch: Batch) -> dict | None:
    """“2 of 4 required passed”, for a list of batches. None for a batch with no stages."""
    rows = batch_stages(batch)
    if not rows:
        return None
    required = [r for r in rows if r["stage"].required and r["status"] != NOT_APPLICABLE]
    return {
        "passed": sum(1 for r in required if r["status"] == PASSED),
        "required": len(required),
        "failed": any(r["status"] == FAILED for r in required),
    }


def _all_columns(sheet: dict) -> list[dict]:
    """Every sign-off column of a recorded stage: the stage's own, or each step's."""
    return sheet["columns"] + [c for st in sheet["steps"] for c in st["columns"]]


def stage_basis(batch: Batch) -> list[dict]:
    """The stages as a disposition decision sees them, for its record and hash."""
    return [
        {"order": row["stage"].order, "name": row["stage"].name, "required": row["stage"].required,
         "status": row["status"], "samples": [s.sample_no for s in row["samples"]],
         "records": [r.id for r in row["records"]],
         **({"added_to_batch": True} if row["stage"].batch_id else {}),
         **({"applicability": [m.id for m in row["applicability"]]} if row["applicability"] else {}),
         **({"entries": [p["entry"].id for st in row["record"]["steps"] for p in st["points"] if p["entry"]],
             "signatures": [c["signature"].id for c in _all_columns(row["record"]) if c["signature"]]}
            if row["record"] else {})}
        for row in batch_stages(batch)
    ]


def tested_stages(plan: QcStagePlan | None) -> list[QcStage]:
    """The lab-tested stages of a version of the product's stages."""
    if plan is None:
        return []
    return list(plan.stages.filter(kind=StageKind.TESTED).order_by("order"))


def registration_options(product, batch: Batch | None) -> list[dict]:
    """
    The stages a sample can be registered for: a known batch's own, or the product's
    current ones for a batch created now. Each says which tests its samples get, and
    what it still waits for.
    """
    rows = batch_stages(batch) if batch is not None else _fresh_rows(product.current_stage_plan())
    out = []
    for r in rows:
        s = r["stage"]
        if s.kind != StageKind.TESTED or r["status"] == NOT_APPLICABLE:
            continue
        spec = spec_for(product, s)
        out.append({
            "id": s.id, "order": s.order, "name": s.name, "added_to_batch": s.batch_id is not None,
            "waiting_for": [f"{w.order}. {w.name}" for w in r["waiting_for"]],
            "tests": spec.label if spec else "",
        })
    return out


def stage_for_registration(product, batch: Batch | None, chosen) -> QcStage | None:
    """
    The stage a new sample is for, checked: one of the batch's lab-tested stages that
    applies to it and is not waiting for an earlier one. None when it has none.
    Raises StageError with a message for the stage field.
    """
    rows = batch_stages(batch) if batch is not None else _fresh_rows(product.current_stage_plan())
    tested = [r for r in rows if r["stage"].kind == StageKind.TESTED and r["status"] != NOT_APPLICABLE]
    if not tested:
        if chosen:
            raise StageError("This batch has no QC stage that is tested in the lab.")
        return None
    row = next((r for r in tested if r["stage"].pk == chosen), None)
    if row is None:
        raise StageError("Choose which QC stage of the batch this sample is for.")
    if row["waiting_for"]:
        raise StageError(waiting_message(row["stage"], row["waiting_for"]))
    return row["stage"]


def final_decision(batch: Batch) -> str | None:
    """“released” or “rejected” once the batch is decided for good; None while it is still open."""
    latest = batch.latest_disposition()
    if latest is not None and latest.decision in (DispositionDecision.RELEASED, DispositionDecision.REJECTED):
        return latest.get_decision_display().lower()
    return None


def _stage_of(batch: Batch, stage_id) -> QcStage:
    """One of this batch's stages: of its version of the product's, or added to it alone."""
    mine = Q(batch=batch)
    if batch.stage_plan_id:
        mine |= Q(plan_id=batch.stage_plan_id)
    stage = QcStage.objects.filter(mine, pk=stage_id if str(stage_id).isdigit() else 0).first()
    if stage is None:
        raise StageError("That stage is not one of this batch's QC stages.")
    return stage


def _may_change(batch: Batch, by, stage_name: str) -> None:
    if not has_perm(by, RECORD):
        message = "You do not have permission to record batch QC stages."
        record(by, "ACCESS_REFUSED", "batch", batch.internal_id, reason=message)
        raise StageError(message)
    decided = final_decision(batch)
    if decided:
        refusal = f"This batch has been {decided}, so its stages can no longer change."
        record(by, "BATCH_STAGE_REFUSED", "batch", batch.internal_id, stage=stage_name, reason=refusal)
        raise StageError(refusal)


def _signed(batch: Batch, by, password: str, meaning: str) -> None:
    if not confirm_password(by, password):
        record(by, "SIGN_PASSWORD_FAILED", "batch", batch.internal_id, meaning=meaning)
        raise StageError("Password incorrect. Nothing was recorded.")


def _still_open(batch: Batch) -> Batch:
    """The batch, locked for the change, if it has not been decided meanwhile."""
    batch = Batch.objects.select_for_update().get(pk=batch.pk)
    if final_decision(batch):
        raise StageError(f"This batch has been {final_decision(batch)}, so its stages can no longer change.")
    return batch


def record_stage(batch: Batch, stage_id, by, decision: str, remarks: str, password: str) -> BatchStageResult:
    """A QA-recorded stage passed or failed, signed with a password. Doing it again adds a record."""
    if not has_perm(by, RECORD):
        message = "You do not have permission to record batch QC stages."
        record(by, "ACCESS_REFUSED", "batch", batch.internal_id, reason=message)
        raise StageError(message)
    stage = _stage_of(batch, stage_id)
    if stage.kind != StageKind.RECORDED:
        raise StageError(f"{stage.name} is tested in the lab: it passes when its samples are approved.")
    if stage.signoffs.exists():
        raise StageError(f"{stage.name} is filled and signed on the batch record, not recorded passed or failed.")
    if decision not in StageDecision.values:
        raise StageError("Choose passed or failed.")
    remarks = (remarks or "").strip()
    if len(remarks) > 1000:
        raise StageError("Keep the remarks to 1000 characters.")
    if decision == StageDecision.FAILED and not remarks:
        raise StageError("Say why the stage failed. The remarks stay on the batch's record.")
    _may_change(batch, by, stage.name)
    row = next(r for r in batch_stages(batch) if r["stage"].pk == stage.pk)
    refusal = ""
    if row["status"] == NOT_APPLICABLE:
        refusal = f"{stage.name} does not apply to this batch, so there is nothing to record."
    elif row["waiting_for"]:
        refusal = waiting_message(stage, row["waiting_for"])
    if refusal:
        record(by, "BATCH_STAGE_REFUSED", "batch", batch.internal_id, stage=stage.name, reason=refusal)
        raise StageError(refusal)
    _signed(batch, by, password, f"QC stage {stage.name}")
    with transaction.atomic():
        batch = _still_open(batch)
        result = BatchStageResult.objects.create(
            batch=batch, stage=stage, decision=decision, remarks=remarks, recorded_by=by,
        )
        record(by, "BATCH_STAGE_RECORDED", "batch", batch.internal_id, stage=stage.name,
               decision=result.get_decision_display().lower(), remarks=remarks or "—")
    return result


def set_applicability(batch: Batch, stage_id, by, applies: bool, reason: str, password: str):
    """
    QA says a stage does not apply to this batch, or applies again; signed, with a
    reason. Only a stage nothing has been done for can be set aside, so a failure
    or work under way is never hidden by it.
    """
    stage = _stage_of(batch, stage_id)
    _may_change(batch, by, stage.name)
    reason = (reason or "").strip()
    if not reason:
        raise StageError("Say why. The reason stays on the batch's record.")
    if len(reason) > 500:
        raise StageError("Keep the reason to 500 characters.")
    row = next(r for r in batch_stages(batch) if r["stage"].pk == stage.pk)
    if applies and row["status"] != NOT_APPLICABLE:
        raise StageError(f"{stage.name} already applies to this batch.")
    if not applies:
        if row["status"] == NOT_APPLICABLE:
            raise StageError(f"{stage.name} is already marked not applicable to this batch.")
        if row["status"] != NOT_STARTED:
            refusal = (f"Work on {stage.name} has already been done ({STATUS_LABELS[row['status']].lower()}). "
                       "Only a stage nothing has been done for yet can be marked not applicable.")
            record(by, "BATCH_STAGE_REFUSED", "batch", batch.internal_id, stage=stage.name, reason=refusal)
            raise StageError(refusal)
    _signed(batch, by, password, f"QC stage {stage.name} {'applies' if applies else 'not applicable'}")
    with transaction.atomic():
        batch = _still_open(batch)
        mark = BatchStageApplicability.objects.create(
            batch=batch, stage=stage, applies=applies, reason=reason, recorded_by=by,
        )
        record(by, "BATCH_STAGE_APPLIES_AGAIN" if applies else "BATCH_STAGE_NOT_APPLICABLE", "batch",
               batch.internal_id, stage=stage.name, reason=reason)
    return mark


def add_stage(batch: Batch, by, data: dict, password: str) -> QcStage:
    """A stage for this batch alone, signed, with a reason. It goes after the batch's other stages."""
    name = str(data.get("name") or "").strip()
    _may_change(batch, by, name or "a new stage")
    if not name:
        raise StageError("Give the stage a name.")
    if len(name) > 80:
        raise StageError("Keep the name to 80 characters.")
    current = stages_of(batch)
    if any(s.name.lower() == name.lower() for s in current):
        raise StageError(f"This batch already has a stage called “{name}”.")
    if sum(1 for s in current if s.batch_id) >= MAX_EXTRA:
        raise StageError(f"A batch can have at most {MAX_EXTRA} stages added to it.")
    kind = data.get("kind")
    if kind not in StageKind.values:
        raise StageError("Choose how it is done: tested in the lab or recorded by QA.")
    tests = ""
    if kind == StageKind.TESTED:
        tests = str(data.get("tests") or "")
        if tests and tests not in {t["key"] for t in test_tracks(batch.product)}:
            raise StageError("Choose which tests its samples get from the list.")
    reason = str(data.get("reason") or "").strip()
    if not reason:
        raise StageError("Say why this batch needs the stage. The reason stays on its record.")
    if len(reason) > 500:
        raise StageError("Keep the reason to 500 characters.")
    _signed(batch, by, password, f"QC stage {name} added")
    with transaction.atomic():
        batch = _still_open(batch)
        last = max([s.order for s in stages_of(batch)], default=0)
        stage = QcStage.objects.create(
            batch=batch, order=last + 1, name=name, description=str(data.get("description") or "").strip()[:300],
            kind=kind, required=bool(data.get("required", True)), tests_key=tests, after_previous=False,
            added_by=by, added_reason=reason[:500], added_at=timezone.now(),
        )
        record(by, "BATCH_STAGE_ADDED", "batch", batch.internal_id, stage=name, kind=stage.get_kind_display(),
               required="required" if stage.required else "optional", reason=reason)
    return stage


# --- the batch record: values and signatures ------------------------------------------------

def _row(batch: Batch, stage: QcStage) -> dict:
    return next(r for r in batch_stages(batch) if r["stage"].pk == stage.pk)


def _record_stage_of(batch: Batch, stage_id) -> QcStage:
    stage = _stage_of(batch, stage_id)
    if not is_record(stage):
        raise StageError(f"{stage.name} is not filled on the batch record.")
    return stage


def _open_for_work(batch: Batch, row: dict) -> str:
    """Why nothing can be written or signed on this stage now; empty when it can."""
    decided = final_decision(batch)
    if decided:
        return f"This batch has been {decided}, so its stages can no longer change."
    if row["status"] == NOT_APPLICABLE:
        return f"{row['stage'].name} does not apply to this batch."
    if row["waiting_for"]:
        return waiting_message(row["stage"], row["waiting_for"])
    return ""


def holder_name(user) -> str:
    return user.display_name()


def _not_theirs(row: dict, user, act: bool, then: str) -> str:
    """
    Why this person may not fill a stage or sign its first column because of who it is
    assigned to: someone else, or nobody yet on a batch that works by assignment. Empty
    when it is theirs, when the batch assigns nothing, or when an administrator passes
    the rule (noted for the activity log when act). `then` ends the first case's sentence.
    """
    assignment = row.get("assignment")
    name = row["stage"].name
    if assignment is not None:
        if assignment.assignee_id == user.pk:
            return ""
        rule = f"{name} is assigned to {holder_name(assignment.assignee)}."
        said = f"{rule} {then}"
    elif row.get("by_assignment"):
        rule = f"{name} is not assigned to anyone yet."
        said = f"{rule} Stages of this batch are assigned: the production supervisor names who does it."
    else:
        return ""
    allowed = overrides if act else (lambda u, _rule: has_perm(u, OVERRIDE))
    return "" if allowed(user, rule) else said


def fill_blocker(batch: Batch, row: dict, user, act: bool = False) -> str:
    """Why this person cannot write values on this stage now; empty when they can."""
    if not has_perm(user, FILL):
        return "You do not have permission to fill batch records."
    why = _open_for_work(batch, row)
    if why:
        return why
    theirs = _not_theirs(row, user, act, "Only they write its values.")
    if theirs:
        return theirs
    sheet = row["record"]
    if sheet["per_step"]:
        if sheet["steps"] and all(st["locked"] for st in sheet["steps"]):
            return "Every step of this stage has been signed, so its values are final."
    elif sheet["locked"]:
        return f"“{sheet['columns'][0]['signoff'].title}” has been signed, so the values of this stage are final."
    return ""


def step_name(step) -> str:
    """“Step 2, Granulation”, as the record and the activity log write it."""
    return f"Step {step.order}{f', {step.title}' if step.title else ''}"


def step_locked(step_row: dict) -> str:
    """Why the values of this step are final; empty while they can still be written."""
    if not step_row["locked"]:
        return ""
    step = step_row["step"]
    return f"{step_name(step)}{',' if step.title else ''} has been signed, so its values are final."


def sign_blocker(batch: Batch, row: dict, signoff, user, act: bool = False, step_row: dict | None = None) -> str:
    """
    Why this person cannot sign this column now; empty when they can. A stage signed
    at every step is signed one step at a time: step_row is that step. With act, a
    rule an administrator passes is noted for the activity log, as overrides() does.
    """
    sheet = row["record"]
    part = step_row if step_row is not None else sheet
    where = "step" if step_row is not None else "stage"
    columns = part["columns"]
    here = next(c for c in columns if c["signoff"].pk == signoff.pk)
    if here["signature"] is not None:
        return f"“{signoff.title}” is signed."
    why = _open_for_work(batch, row)
    if why:
        return why
    before = [c for c in columns if c["signoff"].order < signoff.order and c["signature"] is None]
    if before:
        return f"“{before[0]['signoff'].title}” is signed first."
    allowed = overrides if act else (lambda u, rule: has_perm(u, OVERRIDE))
    if user.role_id != signoff.role_id and not allowed(user, f"“{signoff.title}” is signed by {signoff.role.name}."):
        return f"“{signoff.title}” is signed by {signoff.role.name}."
    # The first column is the assignee's: whoever filled the stage signs for doing it.
    if signoff.pk == columns[0]["signoff"].pk:
        theirs = _not_theirs(row, user, act, f"They sign “{signoff.title}”.")
        if theirs:
            return theirs
    mine = [c["signoff"].title for c in columns if c["signature"] and c["signature"].signed_by_id == user.pk]
    if mine and not allowed(user, f"One person signs only one column of a {where}."):
        return f"You signed “{mine[0]}” on this {where}; someone else signs “{signoff.title}”."
    if part["missing"]:
        names = ", ".join(cp.label for cp in part["missing"][:5]) + ("…" if len(part["missing"]) > 5 else "")
        return f"Fill every required value{' of this step' if step_row is not None else ''} first: {names}."
    return ""


class _Write(NamedTuple):
    """One value about to be written: the check point, the value, whether it is out of limit, and why."""

    cp: object
    full: dict
    flagged: bool
    reason: str
    correction: str
    upload: dict | None  # the photo or file that goes with it, if the check point takes one


def save_entries(batch: Batch, stage_id, by, items) -> list[BatchCheckpointEntry]:
    """
    Values written on a stage of the batch record. Each one is a new entry: a value
    changed needs a reason, and a number outside its limits needs one too. All are
    saved or none.
    """
    stage = _record_stage_of(batch, stage_id)
    row = _row(batch, stage)
    why = fill_blocker(batch, row, by, act=True)
    if why:
        record(by, "BATCH_RECORD_REFUSED", "batch", batch.internal_id, stage=stage.name, reason=why)
        raise StageError(why)
    if not isinstance(items, list) or not items:
        raise StageError("Nothing to save.")
    points = {p["checkpoint"].pk: (p, step) for step in row["record"]["steps"] for p in step["points"]}
    writes = []
    for item in items:
        item = item if isinstance(item, dict) else {}
        point, step_row = points.get(item.get("checkpoint_id"), (None, None))
        if point is None:
            raise StageError("That value is not one this stage asks for.")
        cp, latest = point["checkpoint"], point["entry"]
        final = step_locked(step_row)
        if final:
            raise StageError(final)
        value = parse_value(cp, item)
        if value is None:
            continue
        upload = value.pop("file", None)  # a photo or file travels beside the typed values
        full = {**dict.fromkeys(("number", "date", "start", "end", "yes_no")), "text": "", **value}
        # The same file again is no change, whatever it is called now.
        if latest is not None and (latest.sha256 == upload["sha256"] if upload is not None
                                   else fields_of(latest) == full):
            continue
        flagged = outside(cp, full)
        reason = str(item.get("reason") or "").strip()[:500]
        if flagged and not reason:
            what = (f"not an acceptable answer ({cp.limit_text()})" if cp.kind == "CHOICE"
                    else f"outside its limit of {cp.limit_text()}")
            raise StageError(f"“{cp.label}” is {shown(cp, full)}, {what}. "
                             "Say why. It stays on the record and QA acknowledges it.")
        correction = str(item.get("correction") or "").strip()[:500]
        if latest is not None and not correction:
            raise StageError(f"“{cp.label}” already reads {shown(cp, fields_of(latest))}. Say why it is being changed.")
        writes.append(_Write(cp, full, flagged, reason if flagged else "", correction if latest is not None else "",
                             upload))
    if not writes:
        return []
    with transaction.atomic():
        batch = _still_open(batch)
        made = [
            BatchCheckpointEntry.objects.create(
                batch=batch, checkpoint=w.cp, out_of_limit=w.flagged, reason=w.reason, correction=w.correction,
                entered_by=by, **{k: v for k, v in w.full.items() if k != "text"}, text=w.full["text"],
                **({"file": w.upload["upload"], "extension": w.upload["extension"],
                    "content_type": w.upload["content_type"], "size": w.upload["size"], "sha256": w.upload["sha256"]}
                   if w.upload is not None else {}),
            )
            for w in writes
        ]
        record(by, "BATCH_RECORD_WRITTEN", "batch", batch.internal_id, stage=stage.name,
               values=[f"{w.cp.label}: {shown(w.cp, w.full)}" for w in writes],
               summary="; ".join(f"{w.cp.label} {shown(w.cp, w.full)}" for w in writes),
               **({"out_of_limit": [f"{w.cp.label}: {w.reason}" for w in writes if w.flagged]}
                  if any(w.flagged for w in writes) else {}),
               **({"corrections": [f"{w.cp.label}: {w.correction}" for w in writes if w.correction]}
                  if any(w.correction for w in writes) else {}),
               **({"files": [f"{w.cp.label}: {w.full['text']} ({w.upload['size']} bytes, sha256 {w.upload['sha256']})"
                             for w in writes if w.upload is not None]}
                  if any(w.upload is not None for w in writes) else {}))
    return made


def sign_stage(batch: Batch, stage_id, signoff_id, by, password: str, comment: str = "",
               acknowledge: bool = False, step_id=None) -> BatchStageSignature:
    """
    One sign-off column of a recorded stage, signed with a password, in order, by
    whoever holds its role. The last column acknowledges every value out of limit.
    A stage signed at every step is signed one step at a time, step_id naming it:
    the last column of a step acknowledges the values of that step.
    """
    stage = _record_stage_of(batch, stage_id)
    row = _row(batch, stage)
    sheet = row["record"]
    step_row = None
    if sheet["per_step"]:
        step_row = next((st for st in sheet["steps"] if str(st["step"].pk) == str(step_id)), None)
        if step_row is None:
            raise StageError(f"{stage.name} is signed at every step. Say which step is being signed.")
    elif step_id not in (None, ""):
        raise StageError(f"{stage.name} is signed once for the whole stage, not step by step.")
    part = step_row if step_row is not None else sheet
    column = next((c for c in part["columns"] if str(c["signoff"].pk) == str(signoff_id)), None)
    if column is None:
        raise StageError("That is not one of this stage's sign-off columns.")
    signoff = column["signoff"]
    where = f"{stage.name}, {step_name(step_row['step'])}" if step_row is not None else stage.name
    why = sign_blocker(batch, row, signoff, by, act=True, step_row=step_row)
    if why:
        record(by, "BATCH_RECORD_REFUSED", "batch", batch.internal_id, stage=where, reason=why)
        raise StageError(why)
    comment = (comment or "").strip()
    if len(comment) > 500:
        raise StageError("Keep the comment to 500 characters.")
    last = signoff.pk == part["columns"][-1]["signoff"].pk
    flagged = part["out_of_limit"]
    if last and flagged and not (acknowledge and comment):
        listed = "; ".join(f"{cp.label} {shown(cp, fields_of(e))}" for cp, e in flagged)
        raise StageError(f"{len(flagged)} value{'s are' if len(flagged) > 1 else ' is'} out of limit ({listed}). "
                         "Acknowledge that you have reviewed it, with a comment, to sign.")
    _signed(batch, by, password, f"QC stage {where}, {signoff.title}")
    with transaction.atomic():
        batch = _still_open(batch)
        signature = BatchStageSignature.objects.create(
            batch=batch, signoff=signoff, step=step_row["step"] if step_row is not None else None,
            signed_by=by, comment=comment, acknowledged=bool(last and flagged),
        )
        record(by, "BATCH_STAGE_SIGNED", "batch", batch.internal_id, stage=where,
               column=f"{signoff.title}{f' ({signoff.holder})' if signoff.holder else ''}",
               **({"acknowledged": [f"{cp.label} {shown(cp, fields_of(e))}" for cp, e in flagged]}
                  if last and flagged else {}),
               **({"comment": comment} if comment else {}))
    return signature


# --- who fills a stage of a batch ------------------------------------------------------------

def assignable(stage: QcStage) -> list:
    """
    Who a recorded stage can be assigned to: active people who may fill batch records and
    whose role signs its first column, so the person named can both fill it and sign it.
    """
    from accounts.models import User

    first = stage.signoffs.order_by("order").first()
    people = User.objects.filter(is_active=True, role__is_active=True).select_related("role")
    if first is not None:
        people = people.filter(role_id=first.role_id)
    return [u for u in people.order_by("first_name", "last_name", "username") if has_perm(u, FILL)]


def _first_column_parts(row: dict) -> list[dict]:
    """The parts of a recorded stage that have a first column to sign: each step, or the stage."""
    sheet = row["record"]
    return [p for p in (sheet["steps"] if sheet["per_step"] else [sheet]) if p["columns"]]


def assign_blocker(batch: Batch, row: dict, user) -> str:
    """Why this person cannot assign this stage now; empty when they can."""
    if not has_perm(user, ASSIGN):
        return "You do not have permission to assign batch-record stages."
    decided = final_decision(batch)
    if decided:
        return f"This batch has been {decided}, so its stages can no longer change."
    if row["status"] == NOT_APPLICABLE:
        return f"{row['stage'].name} does not apply to this batch."
    parts = _first_column_parts(row)
    if parts and all(p["columns"][0]["signature"] is not None for p in parts):
        title = parts[0]["columns"][0]["signoff"].title
        every = " at every step" if row["record"]["per_step"] else ""
        return f"“{title}” is signed{every} on {row['stage'].name}: the work it is assigned for is done."
    return ""


def assign_stage(batch: Batch, stage_id, by, assignee_id, note: str = "") -> BatchStageAssignment:
    """
    Name the person who fills a recorded stage of this batch and signs its first column,
    or name nobody to leave it open to anyone who may fill batch records again.
    """
    stage = _record_stage_of(batch, stage_id)
    rows = batch_stages(batch)
    row = next(r for r in rows if r["stage"].pk == stage.pk)
    why = assign_blocker(batch, row, by)
    if why:
        record(by, "BATCH_RECORD_REFUSED", "batch", batch.internal_id, stage=stage.name, reason=why)
        raise StageError(why)
    note = " ".join(str(note or "").split())
    if len(note) > 500:
        raise StageError("Keep the note to 500 characters.")
    person = None
    if assignee_id not in (None, ""):
        person = next((u for u in assignable(stage) if str(u.pk) == str(assignee_id)), None)
        if person is None:
            first = stage.signoffs.order_by("order").first()
            who = (f"someone who signs “{first.title}” ({first.role.name}) and may fill batch records"
                   if first else "someone who may fill batch records")
            raise StageError(f"{stage.name} can only be assigned to {who}.")
    was = row["assignment"].assignee if row["assignment"] else None
    if (was.pk if was else None) == (person.pk if person else None):
        raise StageError(f"{stage.name} is already assigned to {holder_name(person)}." if person
                         else f"{stage.name} is not assigned to anyone.")
    with transaction.atomic():
        batch = _still_open(batch)
        made = BatchStageAssignment.objects.create(batch=batch, stage=stage, assignee=person, note=note,
                                                   assigned_by=by)
        extra = {**({"was": holder_name(was)} if was else {}), **({"note": note} if note else {})}
        if person is not None:
            record(by, "BATCH_STAGE_ASSIGNED", "batch", batch.internal_id, stage=stage.name, to=holder_name(person),
                   was_note=(f" (it was {holder_name(was)}’s)" if was else "") + (f" — “{note}”" if note else ""),
                   **extra)
        else:
            # Still working by assignment while another stage is assigned: then it waits for a name.
            others = any(r["assignment"] is not None for r in rows if r["stage"].pk != stage.pk)
            record(by, "BATCH_STAGE_UNASSIGNED", "batch", batch.internal_id, stage=stage.name,
                   after=(": it waits to be assigned again, as other stages of the batch are assigned" if others
                          else ", leaving it open to anyone who fills batch records"),
                   **extra)
    return made


def assigned_work(user) -> list[dict]:
    """
    The recorded stages assigned to this person that still need them, for their task
    list: values to write, or their column to sign. Gone once they have signed it
    everywhere, or the stage is reassigned, or the batch is decided.
    """
    return open_stage_work(only=user)


def open_stage_work(only=None, batches=None) -> list[dict]:
    """
    The same, for the team: every recorded stage someone has been named to fill and sign
    that still needs them. `only` keeps one person's, and `batches` (a queryset) keeps the
    stages of those batches, so a screen shows no more than its viewer may see.
    """
    named = BatchStageAssignment.objects.all()
    if only is not None:
        named = named.filter(assignee=only)
    if batches is not None:
        named = named.filter(batch__in=batches)
    # order_by() clears the model's default order, which would add the row's id to what is
    # compared and list a stage once for every time it was assigned.
    pairs = named.order_by().values_list("batch_id", "stage_id").distinct()
    work, rows_of = [], {}
    for batch_id, stage_id in pairs:
        latest = (BatchStageAssignment.objects.filter(batch_id=batch_id, stage_id=stage_id)
                  .select_related("assignee", "assigned_by").order_by("-id").first())
        if latest is None or latest.assignee_id is None or (only is not None and latest.assignee_id != only.pk):
            continue
        batch = Batch.objects.select_related("product").get(pk=batch_id)
        if final_decision(batch):
            continue
        if batch_id not in rows_of:
            rows_of[batch_id] = batch_stages(batch)
        row = next((r for r in rows_of[batch_id] if r["stage"].pk == stage_id), None)
        if row is None or row["record"] is None or row["status"] in DONE:
            continue
        open_parts = [p for p in _first_column_parts(row) if p["columns"][0]["signature"] is None]
        if not open_parts:
            continue  # signed by them everywhere: the columns after theirs are the checkers'
        missing = sum(len(p["missing"]) for p in open_parts)
        work.append({
            "batch": batch, "stage": row["stage"], "assignment": latest, "missing": missing,
            "state": "waiting" if row["waiting_for"] else "fill" if missing else "sign",
            "waiting_for": [f"{w.order}. {w.name}" for w in row["waiting_for"]],
            "column": open_parts[0]["columns"][0]["signoff"].title,
        })
    return sorted(work, key=lambda w: w["assignment"].assigned_at)


# --- what changed between two versions of a product's stages ------------------------------

def _mode(row: dict) -> str:
    if row["kind"] == StageKind.TESTED:
        return "tested in the lab"
    return "a batch record" if row["signoffs"] else "recorded passed or failed by QA"


def _limit(cp: dict) -> str:
    # An unsaved check point, only to write its limits the way the record does.
    return QcCheckpoint(**{k: cp[k] for k in ("kind", "unit", "min_value", "max_value", "decimals", "choices")}).limit_text()


def _point_changes(where: str, old: dict, new: dict) -> list[str]:
    out = []
    if (old["kind"], old["kind_name"]) != (new["kind"], new["kind_name"]):
        out.append(f"{where}: now a {(new['kind_name'] or new['kind']).replace('_', ' ').lower()} value.")
    if _limit(old) != _limit(new):
        out.append(f"{where}: limit {_limit(old) or 'none'} → {_limit(new) or 'none'}.")
    elif old["unit"] != new["unit"]:
        out.append(f"{where}: unit {old['unit'] or 'none'} → {new['unit'] or 'none'}.")
    if old["decimals"] != new["decimals"] and new["kind"] in ("NUMBER", "PERCENT"):
        out.append(f"{where}: {old['decimals']} → {new['decimals']} decimals.")
    if old["required"] != new["required"]:
        out.append(f"{where}: now {'required' if new['required'] else 'optional'}.")
    return out


def _step_changes(stage: str, old: list[dict], new: list[dict]) -> list[str]:
    out = []
    before = {s["title"].lower(): s for s in old}
    after = {s["title"].lower(): s for s in new}
    for s in new:
        o = before.get(s["title"].lower())
        if o is None:
            out.append(f"{stage}: added step “{s['title']}”.")
            continue
        here = f"{stage} › {s['title']}"
        if o["instructions"] != s["instructions"]:
            out.append(f"{here}: instructions changed.")
        points_before = {c["label"].lower(): c for c in o["checkpoints"]}
        points_after = {c["label"].lower(): c for c in s["checkpoints"]}
        for c in s["checkpoints"]:
            p = points_before.get(c["label"].lower())
            if p is None:
                out.append(f"{here}: added check point “{c['label']}”"
                           f"{f' ({_limit(c)})' if _limit(c) else ''}.")
            else:
                out += _point_changes(f"{here} › {c['label']}", p, c)
        out += [f"{here}: removed check point “{c['label']}”." for k, c in points_before.items() if k not in points_after]
    out += [f"{stage}: removed step “{s['title']}”." for k, s in before.items() if k not in after]
    if [s["title"].lower() for s in new if s["title"].lower() in before] != \
            [s["title"].lower() for s in old if s["title"].lower() in after]:
        out.append(f"{stage}: steps in a new order.")
    return out


def plan_changes(before: QcStagePlan | None, after: QcStagePlan) -> list[str]:
    """
    What a version of a product's stages changed from the one before, in plain words.
    Stages are matched by their key, so a renamed stage reads as renamed.
    """
    from accounts.models import Role

    old, new = _as_rows(before), _as_rows(after)
    if not old:
        return [f"First version: {len(new)} stage{'s' if len(new) != 1 else ''}."]
    roles = dict(Role.objects.values_list("id", "name"))

    def columns(row):
        return " → ".join(f"{s['title']}{' (' + s['holder'] + ')' if s['holder'] else ''} by {roles.get(s['role_id'], '?')}"
                          for s in row["signoffs"])

    by_key = {r["tests_key"]: r for r in old}
    kept = {r["tests_key"] for r in new}
    out = []
    for r in new:
        o = by_key.get(r["tests_key"])
        name = r["name"]
        if o is None:
            out.append(f"Added stage “{name}”, {_mode(r)}.")
            continue
        if o["name"] != name:
            out.append(f"Renamed stage “{o['name']}” to “{name}”.")
        if _mode(o) != _mode(r):
            out.append(f"“{name}” is now {_mode(r)}.")
        if o["required"] != r["required"]:
            out.append(f"“{name}” is now {'required for release' if r['required'] else 'optional'}.")
        if o["after_previous"] != r["after_previous"]:
            out.append(f"“{name}” {'now waits' if r['after_previous'] else 'no longer waits'} for the stages before it.")
        if o["description"] != r["description"]:
            out.append(f"“{name}”: description changed.")
        out += _step_changes(f"“{name}”", o["steps"], r["steps"])
        if o["signoffs"] != r["signoffs"] and r["signoffs"]:
            out.append(f"“{name}”: signed by {columns(r)}.")
        if o["sign_each_step"] != r["sign_each_step"] and r["signoffs"]:
            out.append(f"“{name}” is now signed {'at every step' if r['sign_each_step'] else 'once for the whole stage'}.")
    out += [f"Removed stage “{o['name']}”." for o in old if o["tests_key"] not in kept]
    if [r["tests_key"] for r in new if r["tests_key"] in by_key] != [o["tests_key"] for o in old if o["tests_key"] in kept]:
        out.append("Stages in a new order: " + ", ".join(r["name"] for r in new) + ".")
    return out or ["No change to the stages themselves."]
