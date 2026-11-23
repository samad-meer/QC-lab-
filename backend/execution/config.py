"""
Step requirements as an administrator configures them on the Workflows
screen: each step's checklist (checks and required documents) and whether
the step must be accepted before anyone works on it — including the front
desk's receipt checks, which must be complete before testing starts.

They belong to a workflow version like the stages do, so they are never
edited: saving a change makes a new version, and samples already
registered keep the requirements they started with.
"""
from decimal import Decimal

from lims.evaluation import ResultValueError, parse_numeric
from .files import ALLOWED, MAX_UPLOAD_MB
from .models import ChecklistItem, ResponseType

MAX_ITEMS = 30
FIELDS = ("label", "help_text", "response_type", "required", "waivable", "expected", "unit",
          "min_value", "max_value", "decimals", "options", "file_types", "max_size_mb")


def _decimal(value, where: str, what: str) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return parse_numeric(value)
    except ResultValueError:
        raise ValueError(f"{where}: the {what} must be a number.")


def clean_checklist(raw, where: str) -> list[dict]:
    """Validate one step's checklist from the editor. Raises ValueError with a readable message."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{where}: the checklist is not valid.")
    if len(raw) > MAX_ITEMS:
        raise ValueError(f"{where}: a step can have at most {MAX_ITEMS} checklist items.")
    out = []
    for n, r in enumerate(raw, start=1):
        if not isinstance(r, dict):
            raise ValueError(f"{where}, item {n} is not valid.")
        label = (r.get("label") or "").strip()
        at = f"{where}, item {n}" + (f" (“{label}”)" if label else "")
        if not label:
            raise ValueError(f"{at}: give it a label, e.g. “Balance calibration checked”.")
        if len(label) > 200:
            raise ValueError(f"{at}: keep the label under 200 characters.")
        help_text = (r.get("help_text") or "").strip()
        if len(help_text) > 300:
            raise ValueError(f"{at}: keep the guidance under 300 characters.")
        kind = r.get("response_type")
        if kind not in ResponseType.values:
            raise ValueError(f"{at}: choose what kind of answer it takes.")
        d = {
            "label": label, "help_text": help_text, "response_type": kind,
            "required": bool(r.get("required", True)), "waivable": bool(r.get("waivable", False)),
            "expected": "", "unit": "", "min_value": None, "max_value": None, "decimals": None,
            "options": [], "file_types": [], "max_size_mb": 10,
        }
        if kind == ResponseType.YES_NO:
            expected = (r.get("expected") or "").strip().upper()
            if expected not in ("", "YES", "NO"):
                raise ValueError(f"{at}: the expected answer must be Yes, No, or either.")
            d["expected"] = expected
        elif kind == ResponseType.NUMBER:
            d["unit"] = (r.get("unit") or "").strip()[:30]
            d["min_value"] = _decimal(r.get("min_value"), at, "minimum")
            d["max_value"] = _decimal(r.get("max_value"), at, "maximum")
            if d["min_value"] is not None and d["max_value"] is not None and d["min_value"] > d["max_value"]:
                raise ValueError(f"{at}: the minimum is above the maximum.")
            decimals = r.get("decimals")
            if decimals not in (None, ""):
                try:
                    decimals = int(decimals)
                except (TypeError, ValueError):
                    raise ValueError(f"{at}: decimal places must be a whole number.")
                if not 0 <= decimals <= 6:
                    raise ValueError(f"{at}: decimal places must be between 0 and 6.")
                d["decimals"] = decimals
        elif kind == ResponseType.CHOICE:
            options = []
            for o in r.get("options") or []:
                o = str(o).strip()
                if o and o not in options:
                    options.append(o[:100])
            if not 2 <= len(options) <= 20:
                raise ValueError(f"{at}: a list needs between 2 and 20 different answers.")
            expected = (r.get("expected") or "").strip()
            if expected and expected not in options:
                raise ValueError(f"{at}: the expected answer must be one of the listed answers.")
            d["options"], d["expected"] = options, expected
        elif kind == ResponseType.FILE:
            types = []
            for t in r.get("file_types") or []:
                t = str(t).strip().lower().lstrip(".")
                if t not in ALLOWED:
                    raise ValueError(f"{at}: “.{t}” is not a file type the lab accepts.")
                if t not in types:
                    types.append(t)
            d["file_types"] = types
            try:
                size = int(r.get("max_size_mb") or 10)
            except (TypeError, ValueError):
                raise ValueError(f"{at}: the size limit must be a whole number of MB.")
            if not 1 <= size <= MAX_UPLOAD_MB:
                raise ValueError(f"{at}: the size limit must be between 1 and {MAX_UPLOAD_MB} MB.")
            d["max_size_mb"] = size
        out.append(d)
    return out


def item_config(item: ChecklistItem) -> dict:
    """An existing item in the same shape the editor sends."""
    return {f: getattr(item, f) for f in FIELDS}


def config_payload(item: ChecklistItem) -> dict:
    d = item_config(item)
    for f in ("min_value", "max_value"):
        d[f] = None if d[f] is None else f"{d[f].normalize():f}"
    return {"id": item.id, "order": item.order, **d}


def signature(cleaned: list[dict]) -> list[tuple]:
    """Comparable form, so saving an unchanged checklist makes no new version."""
    def norm(v):
        return v.normalize() if isinstance(v, Decimal) else v
    return [tuple((f, norm(d[f]) if not isinstance(d[f], list) else tuple(d[f])) for f in FIELDS) for d in cleaned]


def create_items(version, stage, cleaned: list[dict], for_receipt: bool = False):
    for order, d in enumerate(cleaned, start=1):
        ChecklistItem.objects.create(version=version, stage=stage, for_receipt=for_receipt, order=order, **d)


def items_of(version, stage, receipt: bool = False) -> list[ChecklistItem]:
    """One step's items: a review stage's, the testing step's (stage None), or the receipt checks."""
    if version is None:
        return []
    return list(ChecklistItem.objects.filter(version=version, stage=stage, for_receipt=receipt).order_by("order"))
