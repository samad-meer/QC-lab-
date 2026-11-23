"""
Enter batch 26FB017 of Floxcip 500 mg Tablets from its scanned paper record, with
the lab records its testing used: instruments and their calibrations, standards
and reagents, the test method and who is qualified on it.

Everything goes through the API, as the screens do, so the same rules, password
signatures and audit trail apply. Values are as written on the paper. Where the
paper is outside a limit the entry is flagged and its reason says so, and where
the paper gives no reason it says that. Signatures are made by demo accounts
standing in for the people who initialled the paper, and carry today's date.

    manage.py seed_floxcip --dry-run      do everything, then roll it back
    manage.py seed_floxcip --pdf PATH     also attach the scanned record to the batch
"""
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from rest_framework.test import APIClient

from accounts.models import Role, User
from batches.models import Batch, QcStage
from labrecords.models import Method
from labrecords.services import method_digest
from lims.models import Product, Sample, Section, Workflow
from .seed_demo import PASSWORD

CODE = "FLX-500"
BATCH = "26FB017"
METHOD = "QC/CLG/ATM-002"


class _DryRun(Exception):
    pass


def at(day: int, hhmm: str) -> str:
    """A moment in October 2026, as the record writes it: at(2, "16:10")."""
    return f"2026-10-{day:02d}T{hhmm}"


# --- check points --------------------------------------------------------------

def num(label, unit, decimals=3, lo=None, hi=None):
    return {"label": label, "kind": "NUMBER", "unit": unit, "decimals": decimals, "min_value": lo, "max_value": hi}


def pct(label, lo=None, hi=None, decimals=2):
    return {"label": label, "kind": "PERCENT", "unit": "%", "decimals": decimals, "min_value": lo, "max_value": hi}


def span(label):
    return {"label": label, "kind": "TIME_RANGE"}


def moment(label):
    return {"label": label, "kind": "TIME"}


def text(label, required=True):
    return {"label": label, "kind": "TEXT", "required": required}


def yes_no(label):
    return {"label": label, "kind": "YES_NO"}


def check(label):
    return {"label": label, "kind": "CHOICE", "choices": [{"label": "OK", "ok": True}, {"label": "Not OK", "ok": False}]}


CGMP_CHECKS = [
    "Area status board has complete and correct information on the product name and batch number",
    "Area properly cleaned: floor, walls, doors, false ceiling, grills, bins, containers and machines",
    "No material or document of the previous product or batch in the area",
    "All personnel wearing dedicated uniforms as per SOP",
    "Cleaning record of all equipment available and found satisfactory",
    "Logbooks of the area and equipment found updated",
]


def clearance_step(title, last_check):
    return {
        "title": title,
        "instructions": "Check each item before work starts. Area temperature NMT 30 °C, relative humidity "
                        "NMT 60 %, differential pressure 5 – 20 Pa.",
        "checkpoints": [
            *(check(c) for c in CGMP_CHECKS), check(last_check),
            num("Area temperature", "°C", 1, hi="30"), pct("Relative humidity", hi="60", decimals=0),
            num("Differential pressure", "Pa", 0, lo="5", hi="20"),
            text("Previous product and batch in the area"),
            moment("Line clearance intimated"), moment("Clearance given"),
            text("Re-line clearances", required=False),
        ],
    }


BULKING_STEPS = [
    {"title": "Premixing",
     "instructions": "a) Clean the Sigma Mixer thoroughly and dry it.\n"
                     "b) Load the following material into the Sigma Mixer and mix for 20 minutes.",
     "checkpoints": [num("Ciprofloxacin HCl", "kg"), num("Avicel 102", "kg"), num("Primojel", "kg"),
                     span("Premixing time")]},
    {"title": "Preparation of binding solution",
     "instructions": "a) Take purified water and make a slurry with PVP K-30.\n"
                     "b) Add hot purified water to the slurry and stir continuously until the paste is formed.\n"
                     "c) Add this paste to the step 1 material and mix for 10 minutes.\n"
                     "d) Check the wet mass; if required, add more water.",
     "checkpoints": [num("PVP K-30", "kg"), num("Purified water", "L", 1), span("Binding time")]},
    {"title": "Drying",
     "instructions": "a) Shift the wet mass to the FBD trolley and fix the trolley in the FBD.\n"
                     "b) Dry the granules at 50 – 80 °C.\n"
                     "c) Dry the granules till LOD achieves 3.00 – 4.50 %.",
     "checkpoints": [span("Drying time"), pct("LOD after drying", "3.00", "4.50")]},
    {"title": "Dry granulation",
     "instructions": "a) Pass the dried granules from step 3 through SS mesh #16 using the oscillating granulator.\n"
                     "b) Collect the granules in an SS trolley.\n"
                     "c) Check the LOD; if not within limit, repeat step 3.",
     "checkpoints": [span("Granulation time"), pct("LOD after granulation", "3.00", "4.50")]},
]

YIELD_CHECKS = [num("Number of drums", "", 0), num("Total net weight", "kg")]


def stages(roles):
    operator, production, qa = roles["PRODUCTION_OPERATOR"], roles["PRODUCTION_SUPERVISOR"], roles["QA_OFFICER"]
    three = [{"title": "Done by", "holder": "Operator", "role_id": operator},
             {"title": "Checked by", "holder": "Production", "role_id": production},
             {"title": "Checked by", "holder": "QA", "role_id": qa}]
    cleared = [{"title": "Clearance given by", "holder": "Production", "role_id": production},
               {"title": "Clearance given by", "holder": "QA", "role_id": qa}]
    verified = [{"title": "Prepared by", "holder": "Production officer", "role_id": production},
                {"title": "Verified by", "holder": "QA officer", "role_id": qa}]
    return [
        {"name": "Line clearance – manufacturing", "kind": "RECORDED", "required": True,
         "steps": [clearance_step("Pre-manufacturing cGMP checks",
                                  "All raw materials checked and verified against the bill of materials")],
         "signoffs": cleared},
        *({"name": f"Bulking (Lot-{lot})", "kind": "RECORDED", "required": True, "sign_each_step": True,
           "steps": BULKING_STEPS, "signoffs": three} for lot in "ABCD"),
        {"name": "Final mixing", "kind": "RECORDED", "required": True,
         "steps": [
             {"title": "Final mixing and lubrication",
              "instructions": "a) Load the final dried granules of step 4 into the SS cone mixer.\n"
                              "b) Sieve the ingredients below through SS mesh #30.\n"
                              "c) Add them to the granules and mix for 10 minutes.",
              "checkpoints": [num("Primojel", "kg"), num("Magnesium stearate", "kg"), num("Aerosil 200", "kg"),
                              num("Sodium lauryl sulphate", "kg"), num("Talcum", "kg"), num("Avicel 200", "kg"),
                              span("Mixing time")]},
             {"title": "Sampling",
              "instructions": "i. Unload the granules into SS / plastic buckets with proper labels and double "
                              "polythene bags.\nii. Intimate QAD to collect samples of the final granules.",
              "checkpoints": [num("Quantity of sample", "g", 0), text("Taken by"), moment("Sampled at")]},
         ],
         "signoffs": three},
        {"name": "Yield up to lubrication", "kind": "RECORDED", "required": True,
         "steps": [{"title": "Yield calculation",
                    "instructions": "Weigh every drum (gross and tare) and work out the yield. Give the reason "
                                    "if the percentage loss is more than the allowed limit.",
                    "checkpoints": [*YIELD_CHECKS, num("Weight before granulation", "kg"),
                                    num("Weight after mixing", "kg"), num("Loss", "kg"),
                                    pct("Percentage yield", decimals=3),
                                    pct("Percentage loss", hi="1.00", decimals=3)]}],
         "signoffs": verified},
        {"name": "Final grain", "kind": "TESTED", "required": True,
         "description": "QC tests the final granules sampled after lubrication."},
        {"name": "Line clearance – compression", "kind": "RECORDED", "required": True,
         "steps": [clearance_step("Compression cGMP checks",
                                  "All materials checked and verified against the batch number")],
         "signoffs": cleared},
        {"name": "Compression in-process checks", "kind": "RECORDED", "required": True,
         "steps": [{"title": "In-process checks",
                    "instructions": "Check 20 tablets at each interval: individual and average weight, hardness, "
                                    "thickness, friability and disintegration time. Tablet weight 771.50 mg ± 5 % "
                                    "(733 – 810 mg). The full sheets are kept with the batch.",
                    "checkpoints": [moment("Compression started"), moment("Compression ended"),
                                    num("Lowest average weight", "mg", 1, "733", "810"),
                                    num("Highest average weight", "mg", 1, "733", "810"),
                                    yes_no("Every check marked OK on the sheets")]}],
         "signoffs": [{"title": "Checked by", "holder": "Production", "role_id": production},
                      {"title": "Checked by", "holder": "QA", "role_id": qa}]},
        {"name": "Yield up to compression", "kind": "RECORDED", "required": True,
         "steps": [{"title": "Yield calculation",
                    "instructions": "Weigh every drum (gross and tare) and work out the yield. Give the reason "
                                    "if the percentage loss is more than the allowed limit.",
                    "checkpoints": [*YIELD_CHECKS, num("Weight before compression", "kg"),
                                    num("Weight after compression", "kg"), num("Loss", "kg"),
                                    pct("Percentage yield"), pct("Percentage loss", hi="1.00")]}],
         "signoffs": verified},
        {"name": "Core tablets", "kind": "TESTED", "required": True,
         "description": "QC tests the compressed core tablets against the product's specification."},
    ]


# --- what the paper says ----------------------------------------------------------

STRUCK = ("As written on the paper batch record. There the printed limit 3.00 – 4.50 % is struck "
          "through and “NMT 4 %” written by hand beside it.")
UNEXPLAINED = "As written on the paper batch record, which gives no reason."


def n(value, reason=""):
    return {"number": value, **({"reason": reason} if reason else {})}


def between(start_day, start, end_day, end):
    return {"start": at(start_day, start), "end": at(end_day, end)}


def lot(cipro, premix, binding, drying, lod1, granulation, lod2, why1="", why2=""):
    return {
        "Premixing": {"Ciprofloxacin HCl": n(cipro), "Avicel 102": n("28.950"), "Primojel": n("4.000"),
                      "Premixing time": premix},
        "Preparation of binding solution": {"PVP K-30": n("4.500"), "Purified water": n("43.5"),
                                            "Binding time": binding},
        "Drying": {"Drying time": drying, "LOD after drying": n(lod1, why1)},
        "Dry granulation": {"Granulation time": granulation, "LOD after granulation": n(lod2, why2)},
    }


# The paper writes times without AM or PM; they are read in the order the work was done,
# after the line clearance at 03:50 PM on 2 October.
LOTS = {
    "A": lot("175.887", between(2, "16:10", 2, "16:30"), between(2, "16:40", 2, "16:50"),
             between(2, "17:50", 2, "20:30"), "2.10", between(2, "21:10", 2, "22:00"), "2.40", STRUCK, STRUCK),
    "B": lot("175.887", between(2, "17:20", 2, "17:40"), between(2, "17:50", 2, "18:00"),
             between(2, "18:30", 2, "22:00"), "3.30", between(2, "22:40", 2, "23:50"), "2.40", "", STRUCK),
    # Lot-C's Ciprofloxacin HCl reads 17.887 on the paper, where every other lot has 175.887.
    "C": lot("17.887", between(2, "22:10", 2, "22:30"), between(2, "22:40", 2, "22:50"),
             between(2, "23:30", 3, "02:40"), "2.40", between(3, "03:00", 3, "04:10"), "3.10", UNEXPLAINED, ""),
    "D": lot("175.887", between(3, "03:00", 3, "03:20"), between(3, "03:30", 3, "03:40"),
             between(3, "04:10", 3, "06:20"), "2.70", between(3, "07:00", 3, "08:00"), "2.30",
             UNEXPLAINED, UNEXPLAINED),
}

ALL_OK = {c: {"text": "OK"} for c in CGMP_CHECKS}

RECORDS = {
    "Line clearance – manufacturing": {"Pre-manufacturing cGMP checks": {
        **ALL_OK, "All raw materials checked and verified against the bill of materials": {"text": "OK"},
        "Area temperature": n("24"), "Relative humidity": n("42"), "Differential pressure": n("10"),
        "Previous product and batch in the area": {"text": "Floxcip Tab 500 mg, batch 26FB016"},
        "Line clearance intimated": {"start": at(2, "15:35")}, "Clearance given": {"start": at(2, "15:50")},
    }},
    **{f"Bulking (Lot-{k})": v for k, v in LOTS.items()},
    "Final mixing": {
        "Final mixing and lubrication": {
            "Primojel": n("14.400"), "Magnesium stearate": n("12.000"), "Aerosil 200": n("9.600"),
            "Sodium lauryl sulphate": n("6.000"), "Talcum": n("6.000"), "Avicel 200": n("24.851"),
            "Mixing time": {"start": at(3, "08:30"), "end": at(3, "08:40")}},
        "Sampling": {"Quantity of sample": n("150"), "Taken by": {"text": "Zaid-ul-Hassan"},
                     "Sampled at": {"start": at(3, "12:00")}},
    },
    "Yield up to lubrication": {"Yield calculation": {
        "Number of drums": n("26"), "Total net weight": n("923.800"), "Weight before granulation": n("925.800"),
        "Weight after mixing": n("923.800"), "Loss": n("2.000"), "Percentage yield": n("99.784"),
        "Percentage loss": n("0.216"),
    }},
    "Line clearance – compression": {"Compression cGMP checks": {
        **ALL_OK, "All materials checked and verified against the batch number": {"text": "OK"},
        "Area temperature": n("28.7"), "Relative humidity": n("44"), "Differential pressure": n("13"),
        "Previous product and batch in the area": {"text": "Floxcip Tab 500 mg, batch 26FB016"},
        "Line clearance intimated": {"start": at(5, "20:38")}, "Clearance given": {"start": at(5, "20:44")},
        "Re-line clearances": {"text": "06-Oct-2026 09:00 AM: 28.3 °C, RH 54 %. "
                                       "06-Oct-2026 08:39 PM: 28.3 °C, RH 54 %, DP 11 Pa."},
    }},
    "Compression in-process checks": {"In-process checks": {
        "Compression started": {"start": at(5, "21:03")}, "Compression ended": {"start": at(7, "12:30")},
        "Lowest average weight": n("770.8"), "Highest average weight": n("788.1"),
        "Every check marked OK on the sheets": {"yes_no": True},
    }},
    "Yield up to compression": {"Yield calculation": {
        "Number of drums": n("20"), "Total net weight": n("921.600"), "Weight before compression": n("923.800"),
        "Weight after compression": n("921.600"), "Loss": n("2.200"), "Percentage yield": n("99.76"),
        "Percentage loss": n("0.24"),
    }},
}

# --- the lab's tests -----------------------------------------------------------------

COMPLIES = {"limit_type": "TEXT_COMPLIES", "text_expected": "Complies"}


def test(name, limit_text, **limit):
    return {"name": name, "method": METHOD, "limit_text": limit_text, "decimals": 2, **limit}


IDENTIFICATION = test("Identification (UV)", "The UV spectrum of the sample solution corresponds to that of the "
                      "standard solution, as obtained in the assay.", **COMPLIES)
ASSAY = test("Assay by UV (ciprofloxacin)", "Release limit: 98.00 % to 102.00 % of label claim",
             unit="%", limit_type="NUMERIC_RANGE", min_value="98.00", max_value="102.00")

GRAIN_TESTS = [
    test("Description", "White to off-white mixed granular powder, free from foreign particles.", **COMPLIES),
    IDENTIFICATION,
    test("Loss on drying", "3.00 % to 4.50 %", unit="%", limit_type="NUMERIC_RANGE", min_value="3.00", max_value="4.50"),
    ASSAY,
]
CORE_TESTS = [
    test("Description", "White to off-white oblong core tablet, scored on one side and plain on the other.", **COMPLIES),
    IDENTIFICATION,
    test("Disintegration time", "Not more than 15 minutes", unit="min", limit_type="NUMERIC_MAX", max_value="15",
         decimals=0),
    test("Friability", "Less than 1.0 %", unit="%", limit_type="NUMERIC_MAX", max_value="1.0"),
    test("Hardness", "Not less than 30.0 N", unit="N", limit_type="NUMERIC_MIN", min_value="30.0"),
    test("Thickness", "5.50 mm to 6.50 mm", unit="mm", limit_type="NUMERIC_RANGE", min_value="5.50", max_value="6.50"),
    test("Length", "18.00 mm to 18.50 mm", unit="mm", limit_type="NUMERIC_RANGE", min_value="18.00", max_value="18.50"),
    test("Average weight", "771.50 mg ± 3 % (748.36 – 794.65 mg)", unit="mg", limit_type="NUMERIC_RANGE",
         min_value="748.36", max_value="794.65"),
    test("Weight variation", "NMT 2 individual weights deviate from the average weight by more than ± 3 %, "
         "and none by more than ± 6 %.", **COMPLIES),
    test("Uniformity of dosage units", "Acceptance value (L1) not more than 15", limit_type="NUMERIC_MAX",
         max_value="15"),
    ASSAY,
]

# Test name -> (value, instrument code, material codes)
GRAIN_RESULTS = {
    "Description": ("Complies", None, []),
    "Identification (UV)": ("Complies", "UV-01", ["RS-CIP", "RG-HCL"]),
    "Loss on drying": ("1.84", "MA-01", []),
    "Assay by UV (ciprofloxacin)": ("99.29", "UV-01", ["RS-CIP", "RG-HCL"]),
}
CORE_RESULTS = {
    "Description": ("Complies", None, []),
    "Identification (UV)": ("Complies", "UV-01", ["RS-CIP", "RG-HCL"]),
    "Disintegration time": ("3", "DT-01", []),
    "Friability": ("0.05", "FR-01", []),
    "Hardness": ("86.24", "HT-01", []),
    "Thickness": ("5.98", "VC-01", []),
    "Length": ("18.01", "VC-01", []),
    "Average weight": ("770.0", "BAL-01", []),
    "Weight variation": ("Complies", "BAL-01", []),
    "Uniformity of dosage units": ("2.84", "UV-01", ["RS-CIP", "RG-HCL"]),
    "Assay by UV (ciprofloxacin)": ("99.02", "UV-01", ["RS-CIP", "RG-HCL"]),
}

# --- lab records -------------------------------------------------------------------------

# code, name, type, location, (calibrated, next due, reference, comment)
INSTRUMENTS = [
    ("UV-01", "UV-Visible spectrophotometer", "UV-Vis spectrophotometer", "QC laboratory – instrument room",
     ("2026-09-10T10:00", "2027-03-09", "CAL/UV-01/2026-09",
      "Wavelength accuracy, photometric accuracy and stray light within limits")),
    ("BAL-01", "Analytical balance, 0.1 mg", "Analytical balance", "QC laboratory – balance room",
     ("2026-11-02T09:00", "2026-12-01", "CAL/BAL-01/2026-11", "Calibrated with certified weights; within limits")),
    ("MA-01", "Halogen moisture analyser", "Moisture analyser (LOD)", "QC laboratory – physical testing",
     ("2026-08-20T11:00", "2027-02-19", "CAL/MA-01/2026-08", "Temperature and balance checks within limits")),
    ("DT-01", "Disintegration test apparatus", "Disintegration tester", "QC laboratory – physical testing",
     ("2026-07-15T10:30", "2027-01-14", "CAL/DT-01/2026-07", "Stroke rate, distance and bath temperature within limits")),
    ("FR-01", "Friability test apparatus", "Friabilator", "IPQC room – compression area",
     ("2026-07-15T12:00", "2027-01-14", "CAL/FR-01/2026-07", "Drum speed 25 rpm, 100 revolutions verified")),
    ("HT-01", "Tablet hardness tester", "Hardness tester", "IPQC room – compression area",
     ("2026-09-01T10:00", "2027-03-01", "CAL/HT-01/2026-09", "Force readings checked against standard weights")),
    ("VC-01", "Digital vernier caliper", "Vernier caliper", "IPQC room – compression area",
     ("2026-06-05T09:30", "2027-06-04", "CAL/VC-01/2026-06", "Checked with slip gauges; within ± 0.02 mm")),
    # Overdue: kept to show that it is no longer offered when results are entered.
    ("HPLC-01", "HPLC system", "HPLC", "QC laboratory – instrument room",
     ("2026-04-10T10:00", "2026-10-10", "CAL/HPLC-01/2026-04", "Pump flow, detector linearity and injector precision within limits")),
]

MATERIALS = [
    {"kind": "REFERENCE_STANDARD", "code": "RS-CIP", "name": "Ciprofloxacin hydrochloride working standard",
     "lot": "WS/CIP/26/02", "supplier": "Qualified in-house against the USP reference standard", "potency": "99.6",
     "received_on": "2026-06-15", "expiry_date": "2027-06-14", "status": "AVAILABLE"},
    {"kind": "REAGENT", "code": "RG-HCL", "name": "Hydrochloric acid 37 %, AR grade", "lot": "HCL/26/014",
     "supplier": "Approved vendor", "potency": "", "received_on": "2026-05-02", "expiry_date": "2028-04-30",
     "status": "AVAILABLE"},
    {"kind": "CONSUMABLE", "code": "CN-MF045", "name": "Membrane filter 0.45 µm, 47 mm", "lot": "MF/26/031",
     "supplier": "Approved vendor", "potency": "", "received_on": "2026-04-18", "expiry_date": "2028-12-31",
     "status": "AVAILABLE"},
    # Quarantined: kept to show that it is not offered when results are entered.
    {"kind": "REFERENCE_STANDARD", "code": "RS-CIP", "name": "Ciprofloxacin hydrochloride working standard",
     "lot": "WS/CIP/26/03", "supplier": "Qualified in-house against the USP reference standard", "potency": "",
     "received_on": "2026-11-10", "expiry_date": "2027-11-09", "status": "QUARANTINED"},
]


class Command(BaseCommand):
    help = "Enter Floxcip 500 mg batch 26FB017 from its paper record, with the lab records its testing used."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Do everything, then roll it back.")
        parser.add_argument("--pdf", help="The scanned paper record, attached to the batch.")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_floxcip uses the demo accounts' published password, so it never runs in "
                               "production.")
        if Product.objects.filter(code__iexact=CODE).exists():
            raise CommandError(f"{CODE} is already on record, so this batch has been entered before.")
        pdf = Path(options["pdf"]) if options.get("pdf") else None
        if pdf is not None and not pdf.is_file():
            raise CommandError(f"No file at {pdf}.")

        self.client = APIClient(SERVER_NAME="localhost", HTTP_HOST="localhost")
        try:
            with transaction.atomic():
                self.people = self.accounts()
                self.lab_records()
                product = self.product()
                batch = self.batch_record(product)
                self.samples(product, batch)
                self.change_record()
                if pdf is not None and not options["dry_run"]:
                    self.attach(batch, pdf)
                if options["dry_run"]:
                    raise _DryRun
        except _DryRun:
            self.stdout.write(self.style.WARNING("Dry run: everything went through and has been rolled back."))
            return
        self.stdout.write(self.style.SUCCESS(f"Entered {CODE} batch {BATCH} and its lab records."))

    # --- plumbing ------------------------------------------------------------------

    def call(self, method, url, who, body=None, multipart=False):
        self.client.force_authenticate(self.people[who])
        r = getattr(self.client, method)(url, body, **({} if multipart else {"format": "json"}))
        if r.status_code >= 300:
            raise CommandError(f"{method.upper()} {url} as {who} was refused ({r.status_code}): "
                               f"{r.content.decode()[:700]}")
        return r.data

    def accounts(self) -> dict:
        people = {}
        for username in ("frontdesk", "analyst.gf", "analyst.gf2", "checker", "labhead", "qa.officer", "sysadmin"):
            user = User.objects.filter(username=username, is_active=True).first()
            if user is None or not user.check_password(PASSWORD):
                raise CommandError(f"The demo account {username} is missing or its password was changed. "
                                   "Run seed_demo first.")
            people[username] = user
        # The batch record is signed by production as well as QA.
        for username, first, last, role in (("prod.operator", "Kamran", "Ali", "PRODUCTION_OPERATOR"),
                                            ("prod.officer", "Asif", "Mehmood", "PRODUCTION_SUPERVISOR")):
            user, created = User.objects.get_or_create(
                username=username, defaults={"first_name": first, "last_name": last,
                                             "role": Role.objects.get(code=role)})
            if created:
                user.set_password(PASSWORD)
                user.save()
            elif not user.check_password(PASSWORD):
                raise CommandError(f"{username} exists with another password.")
            people[username] = user
        return people

    # --- lab records ----------------------------------------------------------------

    def lab_records(self):
        self.instruments = {}
        for code, name, kind, place, (when, due, ref, comment) in INSTRUMENTS:
            pk = self.call("post", "/api/lab/instruments/", "checker",
                           {"code": code, "name": name, "type": kind, "location": place, "serial_number": ""})["id"]
            self.call("post", f"/api/lab/instruments/{pk}/calibrate/", "checker", {
                "kind": "CALIBRATION", "outcome": "PASS", "performed_at": when, "reference": ref,
                "next_due": due, "comment": comment})
            self.instruments[code] = pk
        self.materials = {}
        for row in MATERIALS:
            pk = self.call("post", "/api/lab/materials/", "checker", row)["id"]
            if row["status"] == "AVAILABLE":
                self.materials[row["code"]] = pk
        pk = self.call("post", "/api/lab/methods/", "checker", {
            "code": METHOD, "title": "Floxcip 500 mg Tablets: final grain and core tablet testing",
            "document_ref": METHOD, "validation_status": "COMPENDIAL"})["id"]
        self.call("post", f"/api/lab/methods/{pk}/approve/", "labhead",
                  {"password": PASSWORD, "digest": method_digest(Method.objects.get(pk=pk))})
        self.method_id = pk
        for analyst in ("analyst.gf", "analyst.gf2"):
            self.call("post", "/api/lab/qualifications/", "labhead", {
                "user_id": self.people[analyst].id, "method": METHOD, "qualified_on": "2026-03-02",
                "expires_on": "2027-03-01", "password": PASSWORD})

    def change_record(self):
        self.call("post", "/api/lab/changes/", "checker", {
            "category": "PROCESS",
            "title": "Floxcip 500 mg bulking: LOD limit changed by hand from 3.00 – 4.50 % to NMT 4 %",
            "description": "On batch 26FB017 the printed drying limit “LOD 3.00 – 4.50 %” of Bulking Lot-A and Lot-B "
                           "is struck through and “NMT 4 %” written beside it. The LODs recorded after drying were "
                           "2.10 – 3.30 %, and QC found 1.84 % on the final grain against 3.00 – 4.50 %.",
            "reason": "The batch record and the final grain specification must state the same limit, and a printed "
                      "limit is changed through change control, not by hand on one batch.",
            "impact_assessment": "Floxcip 500 mg batch record (drying and dry granulation of every bulking lot) and "
                                 "the final grain specification. The finished product specification is not affected.",
        })

    # --- the product and its stages ----------------------------------------------

    def product(self) -> Product:
        section = Section.objects.get(code="GF")
        pid = self.call("post", "/api/product-master/", "sysadmin", {
            "code": CODE, "section_id": section.id, "name": "Floxcip 500 mg Tablets",
            "generic_name": "Ciprofloxacin (as hydrochloride)", "dosage_form": "Tablet", "strength": "500 mg",
            "sample_type": "FINISHED_PRODUCT", "shelf_life_months": 24})["id"]
        # Reviewed by QA as well as QC, and with no receipt checks: the paper record has none.
        review = Workflow.objects.get(name="Extended review")
        self.call("put", f"/api/products/{pid}/workflow/", "sysadmin", {"workflow_id": review.id})
        roles = {r.code: r.id for r in Role.objects.all()}
        self.call("put", f"/api/products/{pid}/qc-stages/", "sysadmin",
                  {"stages": stages(roles), "reason": "Stages and steps from the Floxcip 500 mg batch record"})
        tracks = self.call("get", f"/api/products/{pid}/specifications/", "checker")["tracks"]
        grain = next(t["key"] for t in tracks if t.get("stage") == "Final grain")
        self.specification(pid, "", CORE_TESTS, "Core tablet tests from the QC report of batch 26FB017")
        self.specification(pid, grain, GRAIN_TESTS, "Final grain tests from the QC report of batch 26FB017")
        return Product.objects.get(pk=pid)

    def specification(self, pid, key, tests, reason):
        rows = [{**t, "method_record_id": self.method_id} for t in tests]
        data = self.call("post", f"/api/products/{pid}/specifications/", "checker", {"reason": reason, "stage": key})
        draft = next(s for s in data["specifications"] if s["status"] == "DRAFT")
        data = self.call("put", f"/api/specifications/{draft['id']}/", "checker", {"tests": rows})
        draft = next(s for s in data["specifications"] if s["status"] == "DRAFT")
        self.call("post", f"/api/specifications/{draft['id']}/approve/", "labhead",
                  {"digest": draft["digest"], "password": PASSWORD})

    # --- the batch record ---------------------------------------------------------

    def batch_record(self, product) -> Batch:
        bid = self.call("post", "/api/batches/", "frontdesk", {
            "product_id": product.id, "official_batch_no": BATCH, "manufacturing_date": "2026-10-02",
            "expiry_date": "2028-09-30", "batch_size": "925 kg (12,00,000 tablets)",
            "notes": "Entered from the scanned paper batch record."})["id"]
        batch = Batch.objects.get(pk=bid)
        for stage in QcStage.objects.filter(plan=batch.stage_plan).order_by("order"):
            if stage.name in RECORDS:
                self.fill(batch, stage, RECORDS[stage.name])
        return batch

    def fill(self, batch, stage, written):
        url = f"/api/batches/{batch.id}/qc-stages/{stage.id}"
        columns = list(stage.signoffs.order_by("order"))
        signers = [self.signer(c.role.code) for c in columns]
        # The first column's holder writes the values, as on the shop floor.
        writer = signers[0]
        steps = list(stage.steps.order_by("order"))
        for step in steps:
            values = written[step.title]
            entries = [{"checkpoint_id": cp.id, **values[cp.label]}
                       for cp in step.checkpoints.order_by("order") if cp.label in values]
            self.call("post", f"{url}/entries/", writer, {"entries": entries})
            if stage.sign_each_step:
                self.sign(url, columns, signers, step.id, any(e.get("reason") for e in entries))
        if not stage.sign_each_step:
            flagged = any(v.get("reason") for vs in written.values() for v in vs.values())
            self.sign(url, columns, signers, None, flagged)

    def signer(self, role_code) -> str:
        return {"PRODUCTION_OPERATOR": "prod.operator", "PRODUCTION_SUPERVISOR": "prod.officer",
                "QA_OFFICER": "qa.officer"}[role_code]

    def sign(self, url, columns, signers, step_id, flagged):
        for i, (column, who) in enumerate(zip(columns, signers)):
            body = {"signoff_id": column.id, "password": PASSWORD}
            if step_id is not None:
                body["step_id"] = step_id
            if flagged and i == len(columns) - 1:
                body.update(acknowledge=True, comment="Out-of-limit values acknowledged as written on the "
                                                      "paper record, where QA signed this.")
            self.call("post", f"{url}/sign/", who, body)

    # --- the lab's testing ----------------------------------------------------------

    def samples(self, product, batch):
        plan = {s.name: s.id for s in QcStage.objects.filter(plan=batch.stage_plan)}
        for stage, received, due, quantity, worksheet, conditions, results in (
            ("Final grain", "2026-10-05T09:00:00+05:00", "2026-10-05", "150 g", "CLF/FP-1084/26",
             "23.4 °C / 57.0 % RH", GRAIN_RESULTS),
            ("Core tablets", "2026-10-07T09:00:00+05:00", "2026-10-08", "Not stated on the QC report",
             "CLF/FP-1093/26", "23.7 °C / 56.0 % RH", CORE_RESULTS),
        ):
            sample = self.call("post", "/api/samples/", "frontdesk", {
                "product_id": product.id, "batch_no": BATCH, "qc_stage_id": plan[stage], "quantity": quantity,
                "received_from": "Production", "received_at": received, "due_date": due,
                "analyst_id": self.people["analyst.gf"].id})
            tests = {t.name: t for t in Sample.objects.get(pk=sample["id"]).specification.tests.all()}
            for name, (value, instrument, materials) in results.items():
                t = tests[name]
                body = {"test_definition_id": t.id, "worksheet_ref": worksheet,
                        "notes": f"Environmental condition {conditions}",
                        "material_ids": [self.materials[m] for m in materials]}
                body["value_text" if t.limit_type == "TEXT_COMPLIES" else "value_numeric"] = value
                if instrument:
                    body["instrument_id"] = self.instruments[instrument]
                self.call("post", f"/api/samples/{sample['id']}/results/", "analyst.gf", body)

    def attach(self, batch, pdf: Path):
        upload = SimpleUploadedFile(pdf.name, pdf.read_bytes(), content_type="application/pdf")
        self.call("post", f"/api/batches/{batch.id}/documents/", "frontdesk", {
            "file": upload, "doc_type": "BATCH_RECORD", "title": "Batch manufacturing record, batch 26FB017 (scanned)",
            "note": "The paper record this batch was entered from, with the in-process compression sheets and "
                    "drum weights."}, multipart=True)
