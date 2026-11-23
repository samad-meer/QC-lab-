"""
Internal batch IDs: built by the lab's rule, unique forever, never reused.
This never touches the official batch number, which comes from the
manufacturer's own procedure.
"""
import re

from django.db import transaction
from django.utils import timezone

from .models import Batch, BatchCounter, BatchNumberRule

SEPARATORS = ("-", "/", ".", "")
MIN_DIGITS, MAX_DIGITS = 3, 10


def build_id(rule: BatchNumberRule, section_code: str, product_code: str, year: int, number: int) -> str:
    parts = [rule.prefix]
    if rule.include_year:
        parts.append(str(year))
    if rule.include_section:
        parts.append(section_code)
    if rule.include_product:
        parts.append(product_code)
    parts.append(f"{number:0{rule.digits}d}")
    return rule.separator.join(parts)


def _scope(rule: BatchNumberRule, product, year: int) -> str:
    """Each combination the rule tells apart counts on its own."""
    return "|".join([
        rule.prefix,
        str(year) if rule.restart_yearly else "",
        product.section.code if rule.include_section else "",
        product.code if rule.include_product else "",
    ])


def next_internal_id(product) -> str:
    rule = BatchNumberRule.get()
    year = timezone.localdate().year
    with transaction.atomic():
        counter, _ = BatchCounter.objects.select_for_update().get_or_create(scope=_scope(rule, product, year))
        # A changed rule can land on a number already issued under an old one.
        while True:
            counter.last_no += 1
            candidate = build_id(rule, product.section.code, product.code, year, counter.last_no)
            if not Batch.objects.filter(internal_id=candidate).exists():
                break
        counter.save(update_fields=["last_no"])
    return candidate


def clean_rule(data: dict) -> dict:
    """Validate a rule from the Settings screen. Raises ValueError with a readable message."""
    prefix = (data.get("prefix") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9]{1,12}", prefix):
        raise ValueError("The prefix must be 1 to 12 letters or digits.")
    separator = data.get("separator", "-")
    if separator not in SEPARATORS:
        raise ValueError("The separator must be a dash, a slash, a dot, or nothing.")
    try:
        digits = int(data.get("digits", 6))
    except (TypeError, ValueError):
        raise ValueError("The number of digits must be a whole number.")
    if not MIN_DIGITS <= digits <= MAX_DIGITS:
        raise ValueError(f"The number of digits must be between {MIN_DIGITS} and {MAX_DIGITS}.")
    return {
        "prefix": prefix, "separator": separator, "digits": digits,
        "include_year": bool(data.get("include_year")),
        "include_section": bool(data.get("include_section")),
        "include_product": bool(data.get("include_product")),
        "restart_yearly": bool(data.get("restart_yearly")),
    }
