"""
What stops a certificate. The signing rules read this, so every screen can say
why a sample cannot go forward, and it is checked again as each signature lands.

A passing retest settles nothing by itself: a failure stands in the way until an
investigation of it closes after the failure, and does not confirm it.
"""
from django.db.models import Q

from accounts.models import LabConfig
from lims.models import Outcome, SampleStatus
from .models import Conclusion, Investigation, InvestigationKind, InvestigationStatus


def settling_investigation(sample, test_id, failed_at):
    """The investigation that closed after this failure, if there is one."""
    return Investigation.objects.filter(
        kind=InvestigationKind.OOS, sample=sample, test_definition_id=test_id,
        status=InvestigationStatus.CLOSED, closed_at__gte=failed_at,
    ).order_by("-closed_at").first()


def _unsettled_failures(sample) -> list[str]:
    latest = {}
    for result in sample.results.filter(outcome=Outcome.FAIL).select_related("test_definition"):
        known = latest.get(result.test_definition_id)
        if known is None or result.entered_at > known.entered_at:
            latest[result.test_definition_id] = result
    messages = []
    for test_id, result in latest.items():
        name = f"{result.test_definition.name} on {sample.sample_no}"
        settled = settling_investigation(sample, test_id, result.entered_at)
        if settled is None:
            messages.append(f"{name} failed, and no investigation of it has closed.")
        elif settled.conclusion == Conclusion.CONFIRMED:
            messages.append(f"{settled.reference} confirmed the failure of {name}.")
    return messages


def release_blockers(sample) -> list[str]:
    """Why no certificate can be signed for this sample. Empty when nothing stands in the way."""
    rules = LabConfig.get()
    if not rules.oos_investigation_required:
        return []
    samples = [sample]
    if rules.oos_batch_block and sample.batch_id:
        samples = list(sample.batch.samples.exclude(status=SampleStatus.CANCELLED))
    messages = []
    for each in samples:
        if each.status == SampleStatus.REJECTED:
            messages.append(f"{each.sample_no}, from this batch, was rejected.")
        else:
            messages += _unsettled_failures(each)
    concerning = Q(sample=sample)
    if sample.batch_no:
        concerning |= Q(product=sample.product, batch_no__iexact=sample.batch_no)
    for inv in Investigation.objects.filter(concerning).exclude(status=InvestigationStatus.CLOSED):
        messages.append(f"{inv.reference} is still open on this {'sample' if inv.sample_id == sample.id else 'batch'}.")
    return messages
