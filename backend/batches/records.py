"""
Batch records: what a recorded stage asks for, and what a batch writes on it.

A recorded stage holds steps (Premixing, Preparation of binding solution, Drying),
each with its instructions and check points: a number with its unit, a percentage,
a start and end time, a time, a date, text or yes / no. A number or percentage can
have limits, such as LOD 3.00 – 4.50 %. The stage also has its sign-off columns,
each signed by whoever holds its role, in order: Done by (Operator), Checked by
(Production), Checked by (QA).

These are the pieces that do not depend on the rest of the stage rules: reading and
checking a template, building a batch's record from its entries and signatures,
and reading a typed value. The actions that write live in stages.py.
"""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from accounts.lab_zone import clock
from accounts.models import Role
from execution.files import FileRejected, check_upload, safe_display_name
from .models import CheckpointKind, QcCheckpoint, QcSignoff, QcStep, StageKind

MAX_STEPS = 40
MAX_CHECKPOINTS = 40  # in one step
MAX_SIGNOFFS = 10
NUMERIC = (CheckpointKind.NUMBER, CheckpointKind.PERCENT)
# A time a few minutes ahead of the server is a slow clock; more is a mistake.
FUTURE_SLACK = timedelta(minutes=10)
# What a Photo or file check point takes: pictures from a phone or a scanner, and PDFs.
FILE_TYPES = ["jpg", "jpeg", "png", "webp", "pdf"]
FILE_MAX_MB = 10


class StageError(Exception):
    """A refused stage action. The message is written for the person who tried."""


# --- the template ----------------------------------------------------------------------

def _decimal(raw, what: str) -> Decimal | None:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation:
        raise StageError(f"{what} must be a number.") from None
    if not value.is_finite() or abs(value) >= Decimal(10) ** 12:
        raise StageError(f"{what} must be a number.")
    return value


def _text(raw, limit: int, what: str) -> str:
    value = str(raw or "").strip()
    if len(value) > limit:
        raise StageError(f"Keep {what} to {limit} characters.")
    return value


MAX_CHOICES = 20


def _clean_choices(raw, what: str) -> list[dict]:
    """A choice's options, each with whether it is acceptable. Plain strings are all acceptable."""
    if not isinstance(raw, list):
        raise StageError(f"Give {what} its options, such as Complies and Does not comply.")
    out, seen = [], set()
    for item in raw:
        label = str(item.get("label") if isinstance(item, dict) else item or "").strip()
        if not label:
            continue
        if len(label) > 100:
            raise StageError(f"Keep each option of {what} to 100 characters.")
        if label.lower() in seen:
            raise StageError(f"{what} has the option “{label}” twice.")
        seen.add(label.lower())
        out.append({"label": label, "ok": bool(item.get("ok", True)) if isinstance(item, dict) else True})
    if len(out) < 2:
        raise StageError(f"Give {what} at least two options to choose from.")
    if len(out) > MAX_CHOICES:
        raise StageError(f"{what} can have at most {MAX_CHOICES} options.")
    if not any(c["ok"] for c in out):
        raise StageError(f"Mark at least one option of {what} as acceptable.")
    return out


def clean_kind(data: dict, what: str) -> dict:
    """
    What kind of value something is, and its unit, decimals, limits or options,
    checked: for a check point, and for one of the lab's own kinds alike.
    """
    kind = data.get("kind")
    if kind not in CheckpointKind.values:
        raise StageError(f"Choose what kind of value {what} is.")
    numeric = kind in NUMERIC
    low = _decimal(data.get("min_value"), f"The lower limit of {what}") if numeric else None
    high = _decimal(data.get("max_value"), f"The upper limit of {what}") if numeric else None
    if low is not None and high is not None and low > high:
        raise StageError(f"The lower limit of {what} is above its upper limit.")
    try:
        decimals = int(data.get("decimals", 2))
    except (TypeError, ValueError):
        decimals = 2
    return {
        "kind": kind,
        "unit": "%" if kind == CheckpointKind.PERCENT
        else _text(data.get("unit"), 30, f"the unit of {what}") if kind == CheckpointKind.NUMBER else "",
        "min_value": low, "max_value": high,
        "decimals": min(max(decimals, 0), 6) if numeric else 0,
        "choices": _clean_choices(data.get("choices"), what) if kind == CheckpointKind.CHOICE else [],
    }


def clean_steps(where: str, rows) -> list[dict]:
    """A recorded stage's steps and their check points, checked. `where` names the stage in messages."""
    if rows in (None, ""):
        return []
    if not isinstance(rows, list):
        raise StageError(f"Send the steps of {where} as a list.")
    if len(rows) > MAX_STEPS:
        raise StageError(f"{where} can have at most {MAX_STEPS} steps.")
    out = []
    for i, row in enumerate(rows, start=1):
        row = row if isinstance(row, dict) else {}
        at = f"{where}, step {i}"
        title = _text(row.get("title"), 200, f"the title of {at}")
        if not title:
            raise StageError(f"{at} needs a title, such as Premixing.")
        points_in = row.get("checkpoints") or []
        if not isinstance(points_in, list):
            raise StageError(f"Send the check points of {at} as a list.")
        if len(points_in) > MAX_CHECKPOINTS:
            raise StageError(f"{at} can have at most {MAX_CHECKPOINTS} check points.")
        points, seen = [], set()
        for j, cp in enumerate(points_in, start=1):
            cp = cp if isinstance(cp, dict) else {}
            label = _text(cp.get("label"), 200, f"the name of check point {j} of {at}")
            if not label:
                raise StageError(f"Check point {j} of {at} needs a name, such as Ciprofloxacin HCl.")
            if label.lower() in seen:
                raise StageError(f"{at} has two check points called “{label}”.")
            seen.add(label.lower())
            points.append({
                "label": label, **clean_kind(cp, f"“{label}”"),
                "kind_name": _text(cp.get("kind_name"), 60, f"the kind of “{label}”"),
                "required": bool(cp.get("required", True)),
            })
        out.append({"title": title, "instructions": _text(row.get("instructions"), 4000, f"the instructions of {at}"),
                    "checkpoints": points})
    return out


def clean_signoffs(where: str, rows) -> list[dict]:
    """A recorded stage's sign-off columns, in the order they are signed."""
    if rows in (None, ""):
        return []
    if not isinstance(rows, list):
        raise StageError(f"Send the sign-off columns of {where} as a list.")
    if len(rows) > MAX_SIGNOFFS:
        raise StageError(f"{where} can have at most {MAX_SIGNOFFS} sign-off columns.")
    out = []
    for i, row in enumerate(rows, start=1):
        row = row if isinstance(row, dict) else {}
        title = _text(row.get("title"), 60, f"the title of sign-off column {i} of {where}")
        if not title:
            raise StageError(f"Sign-off column {i} of {where} needs a title, such as Done by.")
        role_id = row.get("role_id")
        role = Role.objects.filter(pk=role_id if str(role_id).isdigit() else 0, is_active=True).first()
        if role is None:
            raise StageError(f"Choose the role that signs “{title}” on {where}.")
        out.append({"title": title, "holder": _text(row.get("holder"), 60, f"who holds “{title}”"),
                    "role_id": role.id})
    return out


def template_rows(stage) -> tuple[list[dict], list[dict]]:
    """A stage's steps and sign-off columns as clean_steps and clean_signoffs write them, to compare."""
    steps = [
        {"title": s.title, "instructions": s.instructions, "checkpoints": [
            {"label": c.label, "kind": c.kind, "unit": c.unit, "min_value": c.min_value, "max_value": c.max_value,
             "decimals": c.decimals, "choices": c.choices, "kind_name": c.kind_name, "required": c.required}
            for c in s.checkpoints.all()
        ]}
        for s in stage.steps.all()
    ]
    signoffs = [{"title": s.title, "holder": s.holder, "role_id": s.role_id} for s in stage.signoffs.all()]
    return steps, signoffs


def create_template(stage, steps: list[dict], signoffs: list[dict]) -> None:
    for order, s in enumerate(steps, start=1):
        step = QcStep.objects.create(stage=stage, order=order, title=s["title"], instructions=s["instructions"])
        for n, c in enumerate(s["checkpoints"], start=1):
            QcCheckpoint.objects.create(step=step, order=n, **c)
    for order, s in enumerate(signoffs, start=1):
        QcSignoff.objects.create(stage=stage, order=order, **s)


# --- a batch's record ---------------------------------------------------------------------

def is_record(stage) -> bool:
    """Is this stage filled and signed on the batch record, rather than recorded passed or failed by QA?"""
    return stage.kind == StageKind.RECORDED and len(stage.signoffs.all()) > 0


def record_of(stage, entries, signatures) -> dict:
    """
    One recorded stage of one batch: each check point with its latest value and the
    ones before it, its sign-off columns with their signatures, and what is missing
    or out of limit. Signed at every step, each step has its own columns, and its
    values are final once its first column is signed; otherwise the stage has one
    set, and every value is final once its first column is signed.
    """
    by_point: dict[int, list] = {}
    for e in entries:
        by_point.setdefault(e.checkpoint_id, []).append(e)
    signoffs = list(stage.signoffs.all())
    per_step = bool(stage.sign_each_step) and bool(signoffs)

    def columns_for(step_id):
        signed = {g.signoff_id: g for g in signatures if g.step_id == step_id}
        return [{"signoff": so, "signature": signed.get(so.pk)} for so in signoffs]

    steps, missing, outside_limits, touched = [], [], [], False
    for step in stage.steps.all():
        points, step_missing, step_outside = [], [], []
        for cp in step.checkpoints.all():
            history = by_point.get(cp.pk, [])
            latest = history[-1] if history else None
            touched = touched or latest is not None
            if latest is None and cp.required:
                step_missing.append(cp)
            if latest is not None and latest.out_of_limit:
                step_outside.append((cp, latest))
            points.append({"checkpoint": cp, "entry": latest, "history": history[:-1]})
        columns = columns_for(step.pk) if per_step else []
        steps.append({
            "step": step, "points": points, "missing": step_missing, "out_of_limit": step_outside,
            "columns": columns,
            "locked": any(c["signature"] for c in columns),
            "signed_all": bool(columns) and all(c["signature"] for c in columns),
        })
        missing += step_missing
        outside_limits += step_outside
    if per_step:
        columns = []
        locked = any(s["locked"] for s in steps)
        signed_all = bool(steps) and all(s["signed_all"] for s in steps)
        # Acknowledged by the last column of their own step.
        unacknowledged = [pair for s in steps if not s["signed_all"] for pair in s["out_of_limit"]]
    else:
        columns = columns_for(None)
        locked = any(c["signature"] for c in columns)
        signed_all = all(c["signature"] for c in columns)
        unacknowledged = [] if signed_all else list(outside_limits)
    return {
        "per_step": per_step, "steps": steps, "columns": columns, "missing": missing,
        "out_of_limit": outside_limits, "unacknowledged": unacknowledged,
        "touched": touched or locked, "locked": locked, "signed_all": signed_all,
    }


def _moment(raw, what: str):
    if raw is None or str(raw).strip() == "":
        return None
    value = parse_datetime(str(raw).strip())
    if value is None:
        raise StageError(f"{what}: that is not a date and time.")
    if timezone.is_naive(value):
        # Typed on the screen, so read in the lab's time zone.
        value = timezone.make_aware(value)
    if value > timezone.now() + FUTURE_SLACK:
        raise StageError(f"{what} cannot be in the future.")
    return value


def parse_value(cp, item: dict) -> dict | None:
    """The value typed for a check point, checked; None when nothing was typed."""
    kind, label = cp.kind, cp.label
    if kind in NUMERIC:
        number = _decimal(item.get("number"), f"“{label}”")
        return None if number is None else {"number": number}
    if kind == CheckpointKind.TIME_RANGE:
        start = _moment(item.get("start"), f"“{label}”, start")
        end = _moment(item.get("end"), f"“{label}”, end")
        if start is None and end is None:
            return None
        if start is None or end is None:
            raise StageError(f"“{label}”: give both the start and the end time.")
        if end < start:
            raise StageError(f"“{label}”: the end time is before the start time.")
        return {"start": start, "end": end}
    if kind == CheckpointKind.TIME:
        start = _moment(item.get("start"), f"“{label}”")
        return None if start is None else {"start": start}
    if kind == CheckpointKind.DATE:
        raw = str(item.get("date") or "").strip()
        if not raw:
            return None
        try:
            day = parse_date(raw)
        except ValueError:
            day = None
        if day is None:
            raise StageError(f"“{label}”: that is not a date.")
        if day > timezone.localdate():
            raise StageError(f"“{label}” cannot be in the future.")
        return {"date": day}
    if kind == CheckpointKind.TEXT:
        text = _text(item.get("text"), 1000, f"“{label}”")
        return {"text": text} if text else None
    if kind == CheckpointKind.CHOICE:
        picked = str(item.get("text") or "").strip()
        if not picked:
            return None
        match = next((c["label"] for c in cp.choices if c["label"].lower() == picked.lower()), None)
        if match is None:
            raise StageError(f"“{label}”: choose one of its options.")
        return {"text": match}
    if kind == CheckpointKind.YES_NO:
        answer = item.get("yes_no")
        if answer is None or answer == "":
            return None
        if not isinstance(answer, bool):
            raise StageError(f"“{label}”: answer yes or no.")
        return {"yes_no": answer}
    if kind == CheckpointKind.FILE:
        upload = item.get("file")
        if upload is None:
            return None
        if not hasattr(upload, "chunks"):
            raise StageError(f"“{label}”: choose a photo or file to attach.")
        try:
            extension, content_type, size, sha256 = check_upload(upload, FILE_TYPES, FILE_MAX_MB)
        except FileRejected as e:
            raise StageError(f"“{label}”: {e}") from None
        # The name is what the record shows; the file itself goes with it, apart from the typed value.
        return {"text": safe_display_name(upload.name), "file": {
            "upload": upload, "extension": extension, "content_type": content_type, "size": size, "sha256": sha256,
        }}
    return None


def outside(cp, value: dict) -> bool:
    """Is this number outside the check point's limits, or this choice not an acceptable one?"""
    if cp.kind == CheckpointKind.CHOICE:
        return any(c["label"] == value.get("text") and not c.get("ok") for c in cp.choices)
    number = value.get("number")
    if number is None:
        return False
    return (cp.min_value is not None and number < cp.min_value) or (cp.max_value is not None and number > cp.max_value)


EMPTY = {"number": None, "text": "", "date": None, "start": None, "end": None, "yes_no": None}


def fields_of(entry) -> dict:
    return {k: getattr(entry, k) for k in EMPTY}


def shown(cp, value: dict) -> str:
    """A value as the record writes it: 17.887 kg, 02:10 PM – 02:30 PM, Yes."""
    def at(moment):
        return timezone.localtime(moment).strftime(f"%d-%b-%Y {clock(seconds=False)}")

    if value.get("number") is not None:
        return f"{value['number']:.{cp.decimals}f}{' ' + cp.unit if cp.unit else ''}"
    if value.get("start") is not None and value.get("end") is not None:
        return f"{at(value['start'])} – {at(value['end'])}"
    if value.get("start") is not None:
        return at(value["start"])
    if value.get("date") is not None:
        return value["date"].strftime("%d-%b-%Y")
    if value.get("yes_no") is not None:
        return "Yes" if value["yes_no"] else "No"
    return value.get("text") or ""
