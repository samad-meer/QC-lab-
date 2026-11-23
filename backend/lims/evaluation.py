"""
Pass/fail evaluation — the system decides on its own (brief, step 4).

Rounding policy, decided once and applied uniformly: the entered value is
rounded to the test's configured number of decimal places using
ROUND_HALF_UP *before* comparison with the limit. So with decimals=1,
an entered 98.45 rounds to 98.5 and PASSES a "not less than 98.5" limit.
If your lab's SOP says otherwise, change it here and only here.

A result is never rounded more coarsely than its limit is written (USP General
Notices 7.20), whatever the test's setting says: 0.40 must not become 0 and pass
"not more than 0.10". New tests cannot be set up that way; this covers the ones
already approved.

On a "not more than" limit a result can be reported below what the method can
measure: "<0.05", or "ND" for not detected.
"""
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .models import LimitType, Outcome, TestDefinition

# DecimalField(max_digits=14, decimal_places=6) leaves 8 integer digits.
MAX_ABS_VALUE = Decimal("1E8")
MAX_PLACES = 6
NOT_DETECTED = {"nd", "n.d.", "not detected"}


class ResultValueError(ValueError):
    """The entered value does not fit the test's limit type."""


def rounded(value: Decimal, decimals: int) -> Decimal:
    q = Decimal(1).scaleb(-decimals)  # e.g. 0.1 for decimals=1
    return value.quantize(q, rounding=ROUND_HALF_UP)


def decimals_of(value) -> int:
    """The decimal places a number needs: 0.10 needs 1, and 95.000000 from the column needs 0."""
    if value is None:
        return 0
    return max(-Decimal(value).normalize().as_tuple().exponent, 0)


def reporting_decimals(test) -> int:
    return max(test.decimals, decimals_of(test.min_value), decimals_of(test.max_value))


def reported_value(result) -> str:
    """
    A result as it is judged and printed. Every screen and document shows this,
    so none can contradict the outcome beside it.
    """
    if result.value_numeric is None:
        return result.value_text
    return str(rounded(Decimal(result.value_numeric), reporting_decimals(result.test_definition)))


def parse_numeric(raw) -> Decimal:
    """
    Convert an entered value to Decimal and bound it to what the column can
    hold. Goes through str() so a JSON number (which arrives as a float)
    keeps its decimal literal — Decimal(2.675) would be 2.67499999… and
    would silently break the ROUND_HALF_UP policy at half-way values.
    """
    text = str(raw).strip()
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError, TypeError, ArithmeticError):
        raise ResultValueError(
            f"“{text}” is not a number. Enter digits only, using a full stop "
            "for the decimal point — for example 99.8"
        )
    if not value.is_finite():
        raise ResultValueError("The value must be an ordinary number.")
    if abs(value) >= MAX_ABS_VALUE:
        raise ResultValueError(
            "That number is too large to record — the maximum is 8 digits before the decimal point."
        )
    # Stored to 6 places. Any more and the stored number would differ from the
    # one judged, and could round to a different value when printed.
    if decimals_of(value) > MAX_PLACES:
        raise ResultValueError(f"That number has too many decimal places — the maximum is {MAX_PLACES}.")
    return value


def _judged_below_limit(test: TestDefinition, text: str) -> str:
    """A result on a "not more than" limit reported as "<0.05" or "ND"."""
    if test.max_value is None:
        raise ResultValueError(f"'{test.name}' is misconfigured: maximum missing.")
    if text.casefold() in NOT_DETECTED:
        return Outcome.PASS
    below = re.fullmatch(r"<\s*(.+)", text)
    if below is None:
        raise ResultValueError(
            f"“{text}” is not a result. Enter the value you measured, or < with the method's limit "
            "(for example <0.05), or ND for not detected."
        )
    if parse_numeric(below.group(1)) > test.max_value:
        raise ResultValueError(
            f"“{text}” does not show that the sample meets {test.limit_text}. "
            "Enter the value you measured."
        )
    return Outcome.PASS


def evaluate(test: TestDefinition, value_numeric, value_text: str) -> str:
    if test.limit_type in (LimitType.NUMERIC_RANGE, LimitType.NUMERIC_MIN, LimitType.NUMERIC_MAX):
        if value_numeric is None:
            if test.limit_type == LimitType.NUMERIC_MAX and value_text.strip():
                return _judged_below_limit(test, value_text.strip())
            raise ResultValueError(
                f"“{test.name}” is measured as a number ({test.limit_text}). Enter the value you measured."
            )
        v = rounded(parse_numeric(value_numeric), reporting_decimals(test))
        if test.limit_type == LimitType.NUMERIC_RANGE:
            if test.min_value is None or test.max_value is None:
                raise ResultValueError(f"'{test.name}' is misconfigured: range limits missing.")
            ok = test.min_value <= v <= test.max_value
        elif test.limit_type == LimitType.NUMERIC_MIN:
            if test.min_value is None:
                raise ResultValueError(f"'{test.name}' is misconfigured: minimum missing.")
            ok = v >= test.min_value
        else:  # NUMERIC_MAX
            if test.max_value is None:
                raise ResultValueError(f"'{test.name}' is misconfigured: maximum missing.")
            ok = v <= test.max_value
        return Outcome.PASS if ok else Outcome.FAIL

    if test.limit_type == LimitType.TEXT_COMPLIES:
        if not value_text.strip():
            raise ResultValueError(
                f"“{test.name}” is an observation, not a measurement. "
                f"Choose whether it complies with: {test.limit_text}"
            )
        ok = value_text.strip().casefold() == test.text_expected.strip().casefold()
        return Outcome.PASS if ok else Outcome.FAIL

    if test.limit_type == LimitType.REPORT_ONLY:
        if value_numeric is None and not value_text.strip():
            raise ResultValueError(f"“{test.name}” has no limit — enter the value to report.")
        return Outcome.REPORTED

    raise ResultValueError(f"Unknown limit type: {test.limit_type}")
