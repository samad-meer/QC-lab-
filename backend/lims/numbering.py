"""
Sample numbering: unique forever, never repeated or reused (brief, step 1).
Format: <SECTION>-<YEAR>-<SEQ>, e.g. GF-2026-0007.
"""
from django.db import transaction
from django.utils import timezone

from .models import SampleCounter, Section


def next_sample_no(section: Section) -> str:
    year = timezone.localdate().year
    with transaction.atomic():
        counter, _ = SampleCounter.objects.select_for_update().get_or_create(
            year=year, section=section
        )
        counter.last_no += 1
        counter.save(update_fields=["last_no"])
        return f"{section.code}-{year}-{counter.last_no:04d}"
