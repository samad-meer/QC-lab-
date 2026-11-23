"""
The raw data behind a result: the worksheet, what was used, and each reading.

Entering a result calls this in three steps, so a caller who sends none of it
gets exactly what they got before: nothing is read, checked or written.

1. parse() reads what was sent, or returns None when nothing was.
2. reported_from() settles the number the result reports. With readings and no
   value it is their mean; with both, they must agree once rounded.
3. check_usable() and save() run under the sample's lock, beside the result.

The mean is rounded once, straight to the places the test reports. Storing it
at six places first and rounding that again would round twice, and a mean of
5.00499… would print as 5.01 against a limit of 5.00.
"""
from dataclasses import dataclass
from decimal import Decimal, localcontext

from audit.services import record
from lims.evaluation import ResultValueError, parse_numeric, reporting_decimals, rounded
from lims.models import LimitType
from .models import Instrument, Material, ResultReading, ResultRecord
from .services import LabRecordError, instrument_problem, material_label, material_problem

MAX_READINGS = 100
MAX_MATERIALS = 50


@dataclass
class RawData:
    worksheet_ref: str
    notes: str
    instrument_id: int | None
    material_ids: list[int]
    readings: list[tuple[str, Decimal]]


def _text(data: dict, key: str, limit: int, name: str) -> str:
    text = str(data.get(key) or "").strip()
    if len(text) > limit:
        raise LabRecordError(f"Keep the {name} to {limit} characters.")
    return text


def _is_id(value) -> bool:
    """Digits a primary key could be. Anything longer is not a mistake worth a query."""
    return str(value).isdigit() and len(str(value)) <= 18


def _instrument_id(raw) -> int | None:
    if raw in (None, ""):
        return None
    if not _is_id(raw):
        raise LabRecordError("That instrument is not on the register.")
    return int(raw)


def _material_ids(raw) -> list[int]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list) or not all(_is_id(m) for m in raw):
        raise LabRecordError("The materials used are not valid.")
    if len(raw) > MAX_MATERIALS:
        raise LabRecordError(f"A result can name at most {MAX_MATERIALS} materials.")
    return sorted({int(m) for m in raw})


def _readings(raw) -> list[tuple[str, Decimal]]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise LabRecordError("The readings are not valid.")
    if len(raw) > MAX_READINGS:
        raise LabRecordError(f"A result can hold at most {MAX_READINGS} readings.")
    readings = []
    for number, row in enumerate(raw, start=1):
        if not isinstance(row, dict):
            raise LabRecordError(f"Reading {number} is not valid.")
        label = str(row.get("label") or "").strip() or f"Reading {number}"
        if len(label) > 60:
            raise LabRecordError(f"Keep the name of reading {number} to 60 characters.")
        if row.get("value") in (None, ""):
            raise LabRecordError(f"Enter the value of {label}.")
        try:
            readings.append((label, parse_numeric(row["value"])))
        except ResultValueError as e:
            raise LabRecordError(f"{label}: {e}")
    return readings


def parse(data: dict) -> RawData | None:
    """What was sent with the result. None when it was nothing at all."""
    raw = RawData(
        worksheet_ref=_text(data, "worksheet_ref", 100, "worksheet reference"),
        notes=_text(data, "notes", 1000, "notes"),
        instrument_id=_instrument_id(data.get("instrument_id")),
        material_ids=_material_ids(data.get("material_ids")),
        readings=_readings(data.get("readings")),
    )
    if not (raw.worksheet_ref or raw.notes or raw.instrument_id or raw.material_ids or raw.readings):
        return None
    return raw


def mean_of(values: list[Decimal]) -> Decimal:
    """Exact to far more places than anything reports. Decimal, so nothing drifts on the way."""
    with localcontext() as context:
        context.prec = 60
        return sum(values, Decimal(0)) / len(values)


def reported_from(test, value_numeric: Decimal | None, value_text: str, raw: RawData | None) -> Decimal | None:
    """The number this result reports, given its readings. Without readings, what was entered."""
    if raw is None or not raw.readings:
        return value_numeric
    if test.limit_type == LimitType.TEXT_COMPLIES:
        raise LabRecordError(f"{test.name} is an observation, so it takes no readings.")
    if value_text:
        raise LabRecordError(f"Enter readings or a written result for {test.name}, not both.")
    places = reporting_decimals(test)
    mean = rounded(mean_of([value for _, value in raw.readings]), places)
    if value_numeric is None:
        return mean
    if rounded(value_numeric, places) != mean:
        raise LabRecordError(
            f"The readings average {mean}, but the value entered rounds to {rounded(value_numeric, places)}. "
            "Correct one of them, or leave the value empty and the system will report the mean."
        )
    return value_numeric


def check_usable(raw: RawData | None) -> tuple[Instrument | None, list[Material]]:
    """
    The instrument and materials, if each can be used right now. Their rows stay
    locked until the result is saved, so a failed calibration cannot land between
    the check and the record.
    """
    if raw is None:
        return None, []
    instrument = None
    if raw.instrument_id is not None:
        instrument = Instrument.objects.select_for_update().filter(pk=raw.instrument_id).first()
        if instrument is None:
            raise LabRecordError("That instrument is not on the register.")
        problem = instrument_problem(instrument)
        if problem:
            raise LabRecordError(f"{problem} It cannot be used for this result.")
    materials = list(Material.objects.select_for_update().filter(pk__in=raw.material_ids).order_by("pk"))
    if len(materials) != len(raw.material_ids):
        raise LabRecordError("One of those materials is not on the register.")
    for material in materials:
        problem = material_problem(material)
        if problem:
            raise LabRecordError(f"{problem} It cannot be used for this result.")
    return instrument, materials


def save(result, raw: RawData | None, instrument, materials, by) -> ResultRecord | None:
    if raw is None:
        return None
    entry = ResultRecord.objects.create(
        result=result, worksheet_ref=raw.worksheet_ref, notes=raw.notes, instrument=instrument,
    )
    if materials:
        entry.materials.add(*materials)
    for order, (label, value) in enumerate(raw.readings):
        ResultReading.objects.create(record=entry, order=order, label=label, value=value)
    record(by, "RESULT_RAW_DATA_RECORDED", "sample", result.sample.sample_no, test=result.test_definition.name,
           worksheet=raw.worksheet_ref, instrument=instrument.code if instrument else "",
           materials=[material_label(m) for m in materials],
           readings=[{"label": label, "value": str(value)} for label, value in raw.readings])
    return entry


def payload(result) -> dict | None:
    """The raw data of a result as every screen shows it. None when it has none."""
    entry = getattr(result, "raw_data", None)
    if entry is None:
        return None
    readings = list(entry.readings.all())
    return {
        "worksheet_ref": entry.worksheet_ref,
        "notes": entry.notes,
        "instrument": {"id": entry.instrument_id, "code": entry.instrument.code, "name": entry.instrument.name}
        if entry.instrument_id else None,
        "materials": [
            {"id": m.id, "code": m.code, "name": m.name, "lot": m.lot, "kind": m.get_kind_display()}
            for m in entry.materials.all()
        ],
        "readings": [{"label": r.label, "value": format(r.value.normalize(), "f")} for r in readings],
        "mean": str(rounded(mean_of([r.value for r in readings]), reporting_decimals(result.test_definition)))
        if readings else "",
    }
