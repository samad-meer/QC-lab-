"""
Enter three weeks of lab work, so the dashboard has something to show.

About twenty samples of Paracetamol, Vitamin C and Ibuprofen, received over the last three weeks and at
every stage a sample can be at: waiting for testing, being tested, waiting for review or approval,
released. Three have a failed result: one investigation is open, one is waiting for its closure to be
approved and one is closed. Their batches have the quality unit's decisions: three released, one
quarantined, one rejected.

    manage.py seed_demo         first: the accounts and products it uses
    manage.py seed_dashboard    the lab's last three weeks
    manage.py seed_production   the production side (batch records), if wanted

Everything goes through the API, as the screens do, so the same rules, password signatures and audit
trail apply, on a clock that runs from three weeks ago to now (see _demo_data). It runs once and refuses
if its batches are already on record. `--dry-run` does everything, then rolls it back.
"""
import datetime as dt
import random
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from batches.models import Batch
from lims.models import Product, Sample, TestResult
from ._demo_data import Api, DryRun, PASSWORD, Timeline, complete_receipt, load_people, require_debug

PREFIX = "DM-"

# (days ago it arrived, product, batch, analyst, where it stands now). Spread over three weeks, with work
# finished in the last one as well, so "this month" has releases and completions late in a month too.
SAMPLES = [
    (22, "PCM-500", "DM-PCM-01", "analyst.gf", "released"),
    (20, "VITC-100", "DM-VIT-01", "analyst.gf2", "released"),
    (19, "IBU-API", "DM-IBU-01", "analyst.api", "released"),
    (18, "PCM-500", "DM-PCM-01", "analyst.gf2", "released"),
    (16, "VITC-100", "DM-VIT-01", "analyst.gf", "released"),
    (14, "PCM-500", "DM-PCM-02", "analyst.gf", "released"),
    (13, "IBU-API", "DM-IBU-01", "analyst.api", "released"),
    (12, "VITC-100", "DM-VIT-02", "analyst.gf", "failure closed"),
    (11, "PCM-500", "DM-PCM-03", "analyst.gf2", "failure awaiting closure"),
    (10, "PCM-500", "DM-PCM-06", "analyst.gf", "awaiting approval"),
    (9, "PCM-500", "DM-PCM-02", "analyst.gf2", "released"),
    (8, "IBU-API", "DM-IBU-02", "analyst.api", "awaiting review"),
    (7, "VITC-100", "DM-VIT-04", "analyst.gf2", "awaiting approval"),
    (6, "PCM-500", "DM-PCM-04", "analyst.gf", "awaiting review"),
    (5, "IBU-API", "DM-IBU-02", "analyst.api", "failure open"),
    (4, "VITC-100", "DM-VIT-03", "analyst.gf2", "being tested"),
    (3, "PCM-500", "DM-PCM-04", "analyst.gf", "being tested"),
    (3, "IBU-API", "DM-IBU-03", "analyst.api", "being tested"),
    (2, "PCM-500", "DM-PCM-05", "analyst.gf2", "received"),
    (1, "VITC-100", "DM-VIT-03", "analyst.gf", "received"),
    (1, "IBU-API", "DM-IBU-03", "analyst.api", "received"),
]

# What the quality unit decided about a batch, and how many days ago.
DECISIONS = [
    ("DM-PCM-01", "RELEASED", 12, "All samples comply and every signature is in."),
    ("DM-VIT-01", "RELEASED", 11, "All samples comply and every signature is in."),
    ("DM-IBU-01", "QUARANTINED", 8, "Held until the supplier's certificate of analysis is on file."),
    ("DM-VIT-02", "REJECTED", 4, "The failed assay was confirmed by the investigation."),
    ("DM-PCM-02", "RELEASED", 3, "All samples comply and every signature is in."),
]

QUANTITY = {"PCM-500": "60 tablets", "VITC-100": "50 tablets", "IBU-API": "25 g"}


def _signer(code: str) -> str:
    """Who signs a review stage, from its code: the checker, QA, or the lab head."""
    if "QA" in code:
        return "qa.officer"
    return "checker" if "CHECK" in code else "labhead"


class Command(BaseCommand):
    help = "Enter a month of demo lab work (samples, results, signatures, investigations, batch decisions)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Do everything, then roll it back.")

    def handle(self, *args, **options):
        require_debug("seed_dashboard")
        if Batch.objects.filter(official_batch_no__startswith=PREFIX).exists():
            raise CommandError("The demo batches (numbered DM-...) are already on record, so this has been entered before.")
        self.products = {}
        for code in {s[1] for s in SAMPLES}:
            product = Product.objects.filter(code=code).first()
            if product is None or product.current_specification() is None:
                raise CommandError(f"{code} has no effective specification. Run seed_demo first.")
            self.products[code] = product
        self.people = load_people(["frontdesk", "analyst.gf", "analyst.gf2", "analyst.api", "checker",
                                   "qa.officer", "labhead"])
        self.api = Api(self.people)
        self.rng = random.Random(2611)
        self.made: dict[int, dict] = {}
        self.timeline = Timeline()
        # A batch has one date of manufacture, three weeks before its first sample arrived.
        first = {}
        for days, _, batch, _, _ in SAMPLES:
            first[batch] = max(first.get(batch, 0), days)
        self.made_on = {b: self.timeline.today - dt.timedelta(days=d + 21) for b, d in first.items()}
        self.plan()
        try:
            with transaction.atomic():
                self.timeline.run()
                if options["dry_run"]:
                    raise DryRun
        except DryRun:
            self.stdout.write(self.style.WARNING("Dry run: everything went through and has been rolled back."))
            return
        self.stdout.write(self.style.SUCCESS(
            f"Entered {len(SAMPLES)} samples over three weeks, in {len({s[2] for s in SAMPLES})} batches. "
            "Open the dashboard."))
        if self.left_waiting:
            self.stdout.write(self.style.WARNING(
                f"Not released, because their product has QC stages that must pass first: "
                f"{', '.join(self.left_waiting)}."))

    # --- the plan ---------------------------------------------------------------------

    def plan(self):
        tl = self.timeline
        for n, (days, code, batch, analyst, fate) in enumerate(SAMPLES):
            tl.add(tl.at(days, "09:20"), lambda n=n, s=(days, code, batch, analyst): self.register(n, *s))
            # The front desk makes the receipt checks the workflow asks for, so testing can start. The
            # newest samples are left waiting for them, so the front desk has something to do.
            if not (fate == "received" and days <= 1):
                tl.add(tl.at(days, "09:45"), lambda n=n: self.complete_receipt(n))
            if fate == "received":
                continue
            tl.add(tl.at(days - 1, "10:05"), lambda n=n, f=fate: self.enter_results(n, f))
            if fate == "being tested":
                continue
            if fate.startswith("failure"):
                tl.add(tl.at(days - 1, "14:10"), lambda n=n: self.open_investigation(n))
                if fate == "failure open":
                    continue
                tl.add(tl.at(days - 2, "11:20"), lambda n=n, f=fate: self.finish_investigation(n, f))
                if fate == "failure closed":
                    tl.add(tl.at(days - 3, "10:30"), lambda n=n: self.close_investigation(n))
                continue
            tl.add(tl.at(days - 1, "15:40"), lambda n=n, f=fate: self.analyst_signs(n, f))
        # A batch of a product that has QC stages is released only when every one has passed. Recording
        # those is the production seeder's work, so here such a batch is left waiting for its decision.
        staged = {code for code, product in self.products.items() if product.current_stage_plan() is not None}
        product_of = {batch: code for _, code, batch, _, _ in SAMPLES}
        self.left_waiting = []
        for batch, decision, days, reason in DECISIONS:
            if decision == "RELEASED" and product_of[batch] in staged:
                self.left_waiting.append(batch)
                continue
            tl.add(tl.at(days, "10:00"), lambda b=batch, d=decision, r=reason: self.decide(b, d, r))

    # --- steps ------------------------------------------------------------------------

    def register(self, n, days, code, batch, analyst):
        product = self.products[code]
        received = timezone.now()
        body = {
            "product_id": product.id, "batch_no": batch, "quantity": QUANTITY[code], "received_from": "Production",
            "received_at": received.isoformat(), "due_date": (timezone.localdate() + dt.timedelta(days=10)).isoformat(),
            "analyst_id": self.people[analyst].id,
            "manufacturing_date": self.made_on[batch].isoformat(),
            "expiry_date": (self.made_on[batch] + dt.timedelta(days=730)).isoformat(),
        }
        plan = product.current_stage_plan()
        if plan is not None:
            stage = plan.stages.filter(kind="TESTED").order_by("order").first()
            if stage is None:
                raise CommandError(f"{code} has QC stages but none is tested in the lab.")
            body["qc_stage_id"] = stage.id
        made = self.api("post", "/api/samples/", "frontdesk", body)
        self.made[n] = {"id": made["id"], "analyst": analyst, "code": code}

    def complete_receipt(self, n):
        complete_receipt(self.api, self.made[n]["id"])

    def _value(self, test, failing: bool):
        """A result inside the limit, or just outside it for the one a failure is made from."""
        low, high = test.min_value, test.max_value
        if test.limit_type == "TEXT_COMPLIES":
            return {"value_text": "Complies"}
        if test.limit_type == "NUMERIC_RANGE":
            span = high - low
            value = low - span * Decimal("0.35") if failing else low + span * Decimal(str(self.rng.uniform(0.3, 0.7)))
        elif test.limit_type == "NUMERIC_MIN":
            value = low * Decimal("0.7") if failing else low + Decimal(str(self.rng.uniform(4, 12)))
        elif test.limit_type == "NUMERIC_MAX":
            value = high * Decimal("1.8") if failing else high * Decimal(str(self.rng.uniform(0.3, 0.7)))
        else:
            value = Decimal(str(self.rng.uniform(40, 80)))
        return {"value_numeric": f"{value:.{test.decimals}f}"}

    def enter_results(self, n, fate):
        sample = Sample.objects.get(pk=self.made[n]["id"])
        tests = list(sample.specification.tests.order_by("order"))
        if fate == "being tested":
            tests = tests[:2]  # started, not finished
        # A failure is made from the first test with a number to be out of.
        failing = next((t.id for t in tests if t.limit_type in ("NUMERIC_RANGE", "NUMERIC_MIN", "NUMERIC_MAX")), None) \
            if fate.startswith("failure") else None
        for t in tests:
            body = {"test_definition_id": t.id, "worksheet_ref": f"WS-{sample.sample_no}",
                    **self._value(t, failing=t.id == failing)}
            self.api("post", f"/api/samples/{sample.id}/results/", self.made[n]["analyst"], body)

    def analyst_signs(self, n, fate):
        cert = self.api("post", f"/api/samples/{self.made[n]['id']}/sign-analyst/", self.made[n]["analyst"],
                        {"password": PASSWORD})
        stages = cert["stages"]
        # How many reviews it has had by now: none, all but the last, or all.
        done = {"awaiting review": 0, "awaiting approval": len(stages) - 1, "released": len(stages)}[fate]
        when = timezone.now()
        for i, stage in enumerate(stages[:done]):
            at = when + dt.timedelta(hours=20 if i == 0 else 20 + 3 * i)
            self.timeline.add(at, lambda c=cert["id"], s=stage: self.review_signs(c, s))

    def review_signs(self, cert_id, stage):
        self.api("post", f"/api/certificates/{cert_id}/sign/", _signer(stage["code"]),
                 {"password": PASSWORD, "stage": stage["order"]})

    def open_investigation(self, n):
        sample_id = self.made[n]["id"]
        failed = TestResult.objects.get(sample_id=sample_id, outcome="FAIL", is_superseded=False)
        made = self.api("post", "/api/investigations/", "checker", {
            "kind": "OOS", "result_id": failed.id, "responsible_id": self.people["checker"].id,
            "description": f"{failed.test_definition.name} is outside its limit.",
            "due_date": (timezone.localdate() + dt.timedelta(days=7)).isoformat(),
        })
        self.made[n]["investigation"] = made["id"]

    def finish_investigation(self, n, fate):
        pk = self.made[n]["investigation"]
        invalidated = fate == "failure awaiting closure"
        self.api("post", f"/api/investigations/{pk}/lab-finding/", "checker", {
            "finding": "ASSIGNABLE" if invalidated else "NONE_FOUND",
            "notes": "Dilution error found on the standard." if invalidated else "No laboratory error was found."})
        self.api("patch", f"/api/investigations/{pk}/", "checker", {
            "classification": "MINOR",
            "root_cause": "Standard diluted to the wrong volume." if invalidated
            else "The raw material lot is below its declared potency.",
            "outcome": "The result is invalidated and the test repeated." if invalidated
            else "The failure is confirmed and the batch is rejected.",
            "conclusion": "INVALIDATED" if invalidated else "CONFIRMED"})
        self.api("post", f"/api/investigations/{pk}/submit/", "checker", {})

    def close_investigation(self, n):
        self.api("post", f"/api/investigations/{self.made[n]['investigation']}/close/", "labhead",
                 {"password": PASSWORD})

    def decide(self, batch_no, decision, reason):
        batch = Batch.objects.get(official_batch_no=batch_no)
        self.api("post", f"/api/batches/{batch.id}/disposition/", "labhead",
                 {"decision": decision, "reason": reason, "password": PASSWORD})
