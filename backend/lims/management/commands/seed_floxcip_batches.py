"""
Three more batches of Floxcip 500 mg Tablets, made after 26FB017, so QA has Floxcip work to sign.

seed_floxcip enters batch 26FB017 as it is on paper, and its two samples are still being tested. This
adds the batches made after it. Each has a Final grain and a Core tablets sample, tested by the lab
and reviewed as far as it would have got by now:

    26FB019   both samples approved by QC, QA and the lab head
    26FB020   both checked by QC and waiting for QA's review
    26FB021   Final grain waiting for QA's review, Core tablets still being tested

    manage.py seed_floxcip                      first: the product, its stages and its lab records
    manage.py seed_floxcip_batches              these three batches
    manage.py seed_floxcip_batches --dry-run    do everything, then roll it back

Everything goes through the API, as in the other seeders, on a clock that runs from a week ago to now
(see _demo_data). The results use the instruments, standards and reagents seed_floxcip entered. The
production stages of the batch record are left for production to fill.
"""
import datetime as dt

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from batches.models import Batch
from labrecords.models import Instrument, Material, MaterialStatus
from lims.models import Product, Sample
from ._demo_data import Api, DryRun, PASSWORD, Timeline, complete_receipt, load_people, require_debug
from .seed_floxcip import CODE, CORE_RESULTS, GRAIN_RESULTS

GRAIN, CORE = "Final grain", "Core tablets"
APPROVED, WAITING_FOR_QA, BEING_TESTED = "approved", "waiting for QA", "being tested"

# batch -> days ago it was made
BATCHES = {"26FB019": 12, "26FB020": 9, "26FB021": 7}

# (days ago it arrived, batch, stage, analyst, where it stands now)
SAMPLES = [
    (7, "26FB019", GRAIN, "analyst.gf", APPROVED),
    (6, "26FB019", CORE, "analyst.gf2", APPROVED),
    (4, "26FB020", GRAIN, "analyst.gf", WAITING_FOR_QA),
    (3, "26FB020", CORE, "analyst.gf2", WAITING_FOR_QA),
    (2, "26FB021", GRAIN, "analyst.gf", WAITING_FOR_QA),
    (1, "26FB021", CORE, "analyst.gf2", BEING_TESTED),
]

# What each batch measured. A test not listed is one judged by eye: “Complies”.
MEASURED = {
    ("26FB019", GRAIN): {"Loss on drying": "3.46", "Assay by UV (ciprofloxacin)": "99.84"},
    ("26FB019", CORE): {"Disintegration time": "4", "Friability": "0.07", "Hardness": "84.10", "Thickness": "6.02",
                        "Length": "18.10", "Average weight": "772.60", "Uniformity of dosage units": "3.05",
                        "Assay by UV (ciprofloxacin)": "100.12"},
    ("26FB020", GRAIN): {"Loss on drying": "3.71", "Assay by UV (ciprofloxacin)": "100.36"},
    ("26FB020", CORE): {"Disintegration time": "3", "Friability": "0.05", "Hardness": "88.40", "Thickness": "5.97",
                        "Length": "18.06", "Average weight": "769.90", "Uniformity of dosage units": "2.71",
                        "Assay by UV (ciprofloxacin)": "99.47"},
    ("26FB021", GRAIN): {"Loss on drying": "3.28", "Assay by UV (ciprofloxacin)": "99.18"},
    ("26FB021", CORE): {"Disintegration time": "5", "Friability": "0.09", "Hardness": "80.70"},
}
INSTRUMENTS_AND_LOTS = {GRAIN: GRAIN_RESULTS, CORE: CORE_RESULTS}
QUANTITY = {GRAIN: "150 g", CORE: "60 tablets"}
# Days QC has for each, from receipt to the last signature: testing and every review.
TURNAROUND = {GRAIN: 5, CORE: 6}
STARTED = 5  # results entered so far on the sample still being tested

# When each review signs, after the analyst: (days later, time).
REVIEW_TIMES = [(1, "10:30"), (1, "14:45"), (2, "11:15")]


def _signer(code: str) -> str:
    """Who signs a review stage, from its code: the checker, QA, or the lab head."""
    if "QA" in code:
        return "qa.officer"
    return "checker" if "CHECK" in code else "labhead"


def _expiry(made: dt.date) -> dt.date:
    """Two years' shelf life, to the end of the month before, as on 26FB017 (made 02-Oct, expires 30-Sep)."""
    return dt.date(made.year + 2, made.month, 1) - dt.timedelta(days=1)


class Command(BaseCommand):
    help = "Add three Floxcip 500 mg batches after 26FB017: one approved, the others waiting for QA's review."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Do everything, then roll it back.")

    def handle(self, *args, **options):
        require_debug("seed_floxcip_batches")
        self.product = Product.objects.filter(code__iexact=CODE).first()
        if self.product is None:
            raise CommandError(f"{CODE} is not on record. Run seed_floxcip first.")
        taken = sorted(Batch.objects.filter(product=self.product, official_batch_no__in=BATCHES)
                       .values_list("official_batch_no", flat=True))
        if taken:
            raise CommandError(f"Batch {', '.join(taken)} of {CODE} is already on record, so these batches have "
                               "been entered before.")
        plan = self.product.current_stage_plan()
        self.stages = {s.name: s.id for s in plan.stages.all()} if plan else {}
        missing = [name for name in (GRAIN, CORE) if name not in self.stages]
        if missing:
            raise CommandError(f"{CODE} has no stage {' or '.join(missing)}. Its stages are not seed_floxcip's.")
        self.instruments = {}
        self.lots = {}
        for results in INSTRUMENTS_AND_LOTS.values():
            for _, instrument, lots in results.values():
                if instrument and instrument not in self.instruments:
                    found = Instrument.objects.filter(code=instrument).first()
                    if found is None:
                        raise CommandError(f"Instrument {instrument} is not on record. Run seed_floxcip first.")
                    self.instruments[instrument] = found.id
                for code in lots:
                    if code not in self.lots:
                        found = (Material.objects.filter(code=code, status=MaterialStatus.AVAILABLE)
                                 .order_by("-id").first())
                        if found is None:
                            raise CommandError(f"No lot of {code} is available. Run seed_floxcip first.")
                        self.lots[code] = found.id

        self.people = load_people(["frontdesk", "analyst.gf", "analyst.gf2", "checker", "qa.officer", "labhead"])
        self.api = Api(self.people)
        self.timeline = Timeline()
        self.made: dict[int, dict] = {}
        self.plan()
        try:
            with transaction.atomic():
                self.timeline.run()
                if options["dry_run"]:
                    raise DryRun
        except DryRun:
            self.stdout.write(self.style.WARNING("Dry run: everything went through and has been rolled back."))
            return
        waiting = sum(1 for s in SAMPLES if s[4] == WAITING_FOR_QA)
        self.stdout.write(self.style.SUCCESS(
            f"Entered {CODE} batches {', '.join(BATCHES)} with {len(SAMPLES)} samples; {waiting} wait for QA's "
            "review."))

    # --- the plan ---------------------------------------------------------------------

    def plan(self):
        tl = self.timeline
        opened = set()
        for n, (days, batch, stage, analyst, fate) in enumerate(SAMPLES):
            if batch not in opened:
                opened.add(batch)
                tl.add(tl.at(days, "09:05"), lambda b=batch: self.open_batch(b))
            tl.add(tl.at(days, "09:20"), lambda n=n, s=(batch, stage, analyst): self.register(n, *s))
            tl.add(tl.at(days, "09:45"), lambda n=n: complete_receipt(self.api, self.made[n]["id"]))
            tl.add(tl.at(days, "11:10"), lambda n=n, f=fate: self.enter_results(n, f))
            if fate != BEING_TESTED:
                tl.add(tl.at(days, "16:20"), lambda n=n, d=days, f=fate: self.analyst_signs(n, d, f))

    # --- steps ------------------------------------------------------------------------

    def open_batch(self, batch_no):
        made = self.timeline.today - dt.timedelta(days=BATCHES[batch_no])
        self.api("post", "/api/batches/", "frontdesk", {
            "product_id": self.product.id, "official_batch_no": batch_no, "manufacturing_date": made.isoformat(),
            "expiry_date": _expiry(made).isoformat(), "batch_size": "925 kg (12,00,000 tablets)",
            "notes": "Batch record kept by production."})

    def register(self, n, batch, stage, analyst):
        received = timezone.now()
        due = timezone.localdate() + dt.timedelta(days=TURNAROUND[stage])
        sample = self.api("post", "/api/samples/", "frontdesk", {
            "product_id": self.product.id, "batch_no": batch, "qc_stage_id": self.stages[stage],
            "quantity": QUANTITY[stage], "received_from": "Production", "received_at": received.isoformat(),
            "due_date": due.isoformat(), "analyst_id": self.people[analyst].id})
        self.made[n] = {"id": sample["id"], "batch": batch, "stage": stage, "analyst": analyst}

    def enter_results(self, n, fate):
        made = self.made[n]
        sample = Sample.objects.get(pk=made["id"])
        tests = list(sample.specification.tests.order_by("order"))
        if fate == BEING_TESTED:
            tests = tests[:STARTED]
        measured = MEASURED[(made["batch"], made["stage"])]
        used = INSTRUMENTS_AND_LOTS[made["stage"]]
        for t in tests:
            _, instrument, lots = used[t.name]
            body = {"test_definition_id": t.id, "worksheet_ref": f"CLF/FP-{1100 + n * 7}/26",
                    "notes": "Environmental condition 23.6 °C / 55.0 % RH",
                    "material_ids": [self.lots[code] for code in lots]}
            if t.limit_type == "TEXT_COMPLIES":
                body["value_text"] = "Complies"
            else:
                body["value_numeric"] = measured[t.name]
            if instrument:
                body["instrument_id"] = self.instruments[instrument]
            self.api("post", f"/api/samples/{sample.id}/results/", made["analyst"], body)

    def analyst_signs(self, n, days, fate):
        cert = self.api("post", f"/api/samples/{self.made[n]['id']}/sign-analyst/", self.made[n]["analyst"],
                        {"password": PASSWORD})
        stages = cert["stages"]
        if fate == APPROVED:
            done = len(stages)
        else:
            # Every review before QA's: the sample then waits in QA's queue.
            done = next((i for i, s in enumerate(stages) if "QA" in s["code"]), None)
            if done is None:
                raise CommandError(f"{CODE}'s review has no QA stage, so nothing would wait for QA.")
        if done > len(REVIEW_TIMES):
            raise CommandError(f"{CODE}'s review has more stages than this seeder signs.")
        for stage, (later, hhmm) in zip(stages[:done], REVIEW_TIMES):
            self.timeline.add(self.timeline.at(days - later, hhmm),
                              lambda c=cert["id"], s=stage: self.review_signs(c, s))

    def review_signs(self, cert_id, stage):
        self.api("post", f"/api/certificates/{cert_id}/sign/", _signer(stage["code"]),
                 {"password": PASSWORD, "stage": stage["order"]})
