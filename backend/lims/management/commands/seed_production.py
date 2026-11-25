"""
Enter the production side: a batch record, and batches at different points in it.

Metformin 500 mg Tablets has a three-stage batch record (dispensing, granulation and drying,
compression) with the values production writes and the columns it signs: done by the operator, checked
by the production supervisor, and for the last two stages checked by QA. Four batches stand at
different points, so each production screen has something to show:

  MET-26-001  all three stages written and signed
  MET-26-002  dispensing done; granulation signed by production and waiting for QA
  MET-26-003  dispensing assigned to the operator, written and signed by them, waiting for the supervisor
  MET-26-004  dispensing assigned to the operator, nothing written yet (their "Your batch records")

    manage.py seed_demo         first: the accounts it uses
    manage.py seed_production   the batch record and the four batches

Everything goes through the API, as the screens do, on a clock that runs from three weeks ago to now
(see _demo_data). It runs once and refuses if Metformin is already on record. `--dry-run` does everything,
then rolls it back.
"""
import datetime as dt
import random

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Role
from batches.models import Batch, QcStage
from lims.models import Product, Section
from ._demo_data import Api, DryRun, PASSWORD, Timeline, load_people, require_debug
from .seed_floxcip import check, moment, n, num, pct, span

CODE = "MET-500"
SIGNER = {"PRODUCTION_OPERATOR": "prod.operator", "PRODUCTION_SUPERVISOR": "prod.officer", "QA_OFFICER": "qa.officer"}

# (batch number, days ago it was started, whether its first stage is assigned to the operator, how far it got)
BATCHES = [
    ("MET-26-001", 21, False, "complete"),
    ("MET-26-002", 14, False, "waiting for QA"),
    ("MET-26-003", 7, True, "waiting for the supervisor"),
    ("MET-26-004", 2, True, "assigned"),
]


def stages(roles: dict) -> list[dict]:
    operator, production, qa = roles["PRODUCTION_OPERATOR"], roles["PRODUCTION_SUPERVISOR"], roles["QA_OFFICER"]
    two = [{"title": "Done by", "holder": "Operator", "role_id": operator},
           {"title": "Checked by", "holder": "Production", "role_id": production}]
    three = [*two, {"title": "Checked by", "holder": "QA", "role_id": qa}]
    return [
        {"name": "Dispensing", "kind": "RECORDED", "required": True, "signoffs": two,
         "steps": [{"title": "Weighing of raw materials",
                    "instructions": "Weigh each material on the calibrated balance and write its weight.",
                    "checkpoints": [num("Metformin hydrochloride", "kg"), num("Povidone K-30", "kg"),
                                    num("Maize starch", "kg"), num("Purified water", "L", 1),
                                    check("Weights verified against the bill of materials")]}]},
        {"name": "Granulation and drying", "kind": "RECORDED", "required": True, "signoffs": three,
         "steps": [{"title": "Granulation",
                    "instructions": "Mix the dry powders for 10 minutes, add the binder solution and granulate.",
                    "checkpoints": [num("Binder solution added", "L", 1), span("Granulation time")]},
                   {"title": "Drying",
                    "instructions": "Dry the wet granules in the fluid bed dryer until the loss on drying is 2.00 – 3.50 %.",
                    "checkpoints": [num("Inlet air temperature", "°C", 0, "50", "70"),
                                    pct("LOD after drying", "2.00", "3.50")]}]},
        {"name": "Compression", "kind": "RECORDED", "required": True, "signoffs": three,
         "steps": [{"title": "Compression",
                    "instructions": "Check the tablet weight and hardness every 30 minutes.",
                    "checkpoints": [moment("Compression started"), num("Average tablet weight", "mg", 1, "570", "630"),
                                    num("Hardness", "N", 0, lo="80"), moment("Compression ended")]}]},
    ]


class Command(BaseCommand):
    help = "Enter a demo batch record (Metformin 500 mg) and four production batches at different points in it."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Do everything, then roll it back.")

    def handle(self, *args, **options):
        require_debug("seed_production")
        if Product.objects.filter(code__iexact=CODE).exists():
            raise CommandError(f"{CODE} is already on record, so this has been entered before.")
        self.people = load_people(["prod.operator", "prod.officer", "qa.officer", "sysadmin"])
        self.api = Api(self.people)
        self.rng = random.Random(2611)
        self.made: dict[str, dict] = {}
        self.timeline = Timeline()
        self.plan()
        try:
            with transaction.atomic():
                self.timeline.run()
                if options["dry_run"]:
                    raise DryRun
        except DryRun:
            self.stdout.write(self.style.WARNING("Dry run: everything went through and has been rolled back."))
            return
        self.stdout.write(self.style.SUCCESS(f"Entered {CODE} with its batch record and {len(BATCHES)} batches."))

    # --- the product -----------------------------------------------------------------

    def product(self):
        """The first step: the product and its batch record exist before any batch of it is started."""
        section = Section.objects.get(code="GF")
        pid = self.api("post", "/api/product-master/", "sysadmin", {
            "code": CODE, "section_id": section.id, "name": "Metformin 500 mg Tablets",
            "generic_name": "Metformin hydrochloride", "dosage_form": "Tablet", "strength": "500 mg",
            "sample_type": "FINISHED_PRODUCT", "shelf_life_months": 24})["id"]
        roles = {r.code: r.id for r in Role.objects.all()}
        self.api("put", f"/api/products/{pid}/qc-stages/", "sysadmin",
                 {"stages": stages(roles), "reason": "The batch record for Metformin 500 mg Tablets"})
        self.product_id = pid

    # --- the plan ---------------------------------------------------------------------

    def plan(self):
        tl = self.timeline
        tl.add(tl.at(max(d for _, d, _, _ in BATCHES) + 2, "08:00"), self.product)
        for batch_no, days, assigned, progress in BATCHES:
            tl.add(tl.at(days, "08:10"), lambda b=batch_no, d=days: self.start(b, d))
            if assigned:
                tl.add(tl.at(days, "08:25"), lambda b=batch_no: self.assign(b, 1))
            if progress == "assigned":
                continue
            tl.add(tl.at(days, "09:30"), lambda b=batch_no: self.write(b, 1))
            sign = tl.at(days, "11:00")
            tl.add(sign, lambda b=batch_no: self.sign(b, 1, 1))
            if progress == "waiting for the supervisor":
                continue
            tl.add(tl.at(days, "13:30"), lambda b=batch_no: self.sign(b, 1, 2))
            if progress == "complete" or progress == "waiting for QA":
                tl.add(tl.at(days - 1, "09:00"), lambda b=batch_no: self.write(b, 2))
                tl.add(tl.at(days - 1, "12:00"), lambda b=batch_no: self.sign(b, 2, 1))
                tl.add(tl.at(days - 1, "14:00"), lambda b=batch_no: self.sign(b, 2, 2))
            if progress == "complete":
                tl.add(tl.at(days - 1, "16:00"), lambda b=batch_no: self.sign(b, 2, 3))
                tl.add(tl.at(days - 2, "09:15"), lambda b=batch_no: self.write(b, 3))
                tl.add(tl.at(days - 2, "11:30"), lambda b=batch_no: self.sign(b, 3, 1))
                tl.add(tl.at(days - 2, "13:30"), lambda b=batch_no: self.sign(b, 3, 2))
                tl.add(tl.at(days - 2, "15:30"), lambda b=batch_no: self.sign(b, 3, 3))

    # --- steps ------------------------------------------------------------------------

    def start(self, batch_no, days):
        made = timezone.localdate()
        batch = self.api("post", "/api/batches/", "prod.officer", {
            "product_id": self.product_id, "official_batch_no": batch_no, "manufacturing_date": made.isoformat(),
            "expiry_date": (made + dt.timedelta(days=730)).isoformat(), "batch_size": "120 kg (240,000 tablets)",
            "notes": "Demo batch entered by seed_production."})
        self.made[batch_no] = {"id": batch["id"]}

    def _stage(self, batch_no, order) -> QcStage:
        batch = Batch.objects.get(pk=self.made[batch_no]["id"])
        return QcStage.objects.get(plan=batch.stage_plan, order=order)

    def assign(self, batch_no, order):
        stage = self._stage(batch_no, order)
        self.api("post", f"/api/batches/{self.made[batch_no]['id']}/qc-stages/{stage.id}/assign/", "prod.officer",
                 {"assignee_id": self.people["prod.operator"].id, "note": "To be written on the next shift."})

    def _jitter(self, base, spread, places):
        return f"{base + self.rng.uniform(-spread, spread):.{places}f}"

    def _values(self, order) -> dict:
        now = timezone.localtime()
        at = lambda minutes: (now + dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M")  # noqa: E731
        if order == 1:
            return {"Weighing of raw materials": {
                "Metformin hydrochloride": n(self._jitter(60.0, 0.05, 3)), "Povidone K-30": n(self._jitter(3.6, 0.01, 3)),
                "Maize starch": n(self._jitter(12.0, 0.02, 3)), "Purified water": n(self._jitter(18.0, 0.2, 1)),
                "Weights verified against the bill of materials": {"text": "OK"}}}
        if order == 2:
            return {
                "Granulation": {"Binder solution added": n(self._jitter(18.0, 0.2, 1)),
                                "Granulation time": {"start": at(-150), "end": at(-125)}},
                "Drying": {"Inlet air temperature": n(self._jitter(60, 4, 0)),
                           "LOD after drying": n(self._jitter(2.7, 0.3, 2))}}
        return {"Compression": {
            "Compression started": {"start": at(-240)}, "Average tablet weight": n(self._jitter(600.0, 9.0, 1)),
            "Hardness": n(self._jitter(110, 12, 0)), "Compression ended": {"start": at(-10)}}}

    def write(self, batch_no, order):
        stage = self._stage(batch_no, order)
        url = f"/api/batches/{self.made[batch_no]['id']}/qc-stages/{stage.id}"
        written = self._values(order)
        for step in stage.steps.order_by("order"):
            values = written[step.title]
            entries = [{"checkpoint_id": cp.id, **values[cp.label]} for cp in step.checkpoints.order_by("order")]
            self.api("post", f"{url}/entries/", "prod.operator", {"entries": entries})

    def sign(self, batch_no, order, column):
        stage = self._stage(batch_no, order)
        col = list(stage.signoffs.order_by("order"))[column - 1]
        self.api("post", f"/api/batches/{self.made[batch_no]['id']}/qc-stages/{stage.id}/sign/",
                 SIGNER[col.role.code], {"signoff_id": col.id, "password": PASSWORD})
