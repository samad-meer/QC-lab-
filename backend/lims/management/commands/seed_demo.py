"""
Seed demo data: three sections, demo users for every role, three
products with effective specifications, and two review workflows beside
the default so the products show different numbers of signatures:

  Paracetamol  — Standard review: Checked → Approved (3 signatures)
  Vitamin C    — Short release:   Approved           (2 signatures)
  Ibuprofen    — Extended review: Checked → QA review → Approved (4)

Idempotent — safe to run twice, and never overrides a workflow an
administrator has already chosen for a product.

Demo logins (all password: qclab1234):
  frontdesk / analyst.gf / analyst.gf2 / analyst.api / checker / qa.officer / labhead /
  prod.operator (Kamran Ali) / prod.officer (Asif Mehmood) / sysadmin

Floxcip 500 mg, batch 26FB017, is entered by `manage.py seed_floxcip`, which needs these
accounts, so run this first.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import LabConfig, Role, RolePermissionGrant, User
from accounts.permissions_registry import LAB_REGISTER_VIEWS, REPORTS, report_permission
from lims.models import (
    LimitType, Product, SampleSource, SampleType, Section, SpecStatus, Specification, TestDefinition,
    Workflow, WorkflowStage, WorkflowVersion,
)
from lims.workflow import stage_code


PASSWORD = "qclab1234"


class Command(BaseCommand):
    help = "Seed demo sections, users, products and specifications."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "seed_demo creates accounts with a published password, so it never runs in production. "
                "Use create_administrator."
            )
        LabConfig.get()

        gf, _ = Section.objects.get_or_create(code="GF", defaults={"name": "General Formulation"})
        nutra, _ = Section.objects.get_or_create(code="NUTRA", defaults={"name": "Nutraceutical"})
        api, _ = Section.objects.get_or_create(code="API", defaults={"name": "Active Pharmaceutical Ingredient"})
        # What the front desk picks under "Received from".
        for name in ("Production", "Store", "Supplier"):
            if not SampleSource.objects.filter(name__iexact=name).exists():
                SampleSource.objects.create(name=name)

        # Roles are seeded by migration accounts/0003; look them up by code.
        # The QA officer is a demo role of our own, for the extended workflow.
        qa_role, created = Role.objects.get_or_create(
            code="QA_OFFICER",
            defaults={"name": "QA officer",
                      "description": "Reviews certificates whose workflow includes a QA review stage."},
        )
        for permission in ("sample.view.all", "report.view", "report.export", "report.performance",
                           "audit.view", "investigation.manage", "investigation.approve", "batch.stage.record",
                           *LAB_REGISTER_VIEWS, *(report_permission(key) for key, *_ in REPORTS)):
            if not qa_role.grants.filter(permission=permission, revoked_at__isnull=True).exists():
                RolePermissionGrant.objects.create(role=qa_role, permission=permission, reason="Seeded demo role")
        roles = {r.code: r for r in Role.objects.all()}

        def user(username, first, last, role_code, sections=()):
            u, created = User.objects.get_or_create(
                username=username,
                defaults={"first_name": first, "last_name": last, "role": roles[role_code]},
            )
            if created:
                u.set_password(PASSWORD)
                u.save()
            u.sections.set(sections)
            return u

        user("frontdesk", "Farah", "Iqbal", "FRONT_DESK")
        user("analyst.gf", "Ahmed", "Raza", "ANALYST", [gf, nutra])
        user("analyst.gf2", "Hina", "Malik", "ANALYST", [gf, nutra])  # a second analyst, for retests
        user("analyst.api", "Sana", "Khan", "ANALYST", [api])
        user("checker", "Bilal", "Ahmed", "CHECKER", [gf, nutra, api])
        user("qa.officer", "Usman", "Tariq", "QA_OFFICER", [gf, nutra, api])
        user("labhead", "Dr. Nadia", "Hussain", "APPROVER", [gf, nutra, api])
        # Production, who fill batch records and sign their stages (roles from accounts/0024).
        # The same two seed_floxcip uses, so running either never makes a second pair.
        user("prod.operator", "Kamran", "Ali", "PRODUCTION_OPERATOR")
        user("prod.officer", "Asif", "Mehmood", "PRODUCTION_SUPERVISOR")
        admin, created = User.objects.get_or_create(
            username="sysadmin",
            defaults={"first_name": "System", "last_name": "Admin", "role": roles["ADMIN"],
                      "is_staff": True, "is_superuser": True},
        )
        if created:
            admin.set_password(PASSWORD)
            admin.save()

        def product(code, name, section, sample_type, tests):
            p, _ = Product.objects.get_or_create(
                code=code, defaults={"name": name, "section": section, "sample_type": sample_type},
            )
            if not p.specifications.exists():
                spec = Specification.objects.create(
                    product=p, version=1, status=SpecStatus.EFFECTIVE, effective_date="2026-01-01"
                )
                for i, t in enumerate(tests):
                    TestDefinition.objects.create(specification=spec, order=i, **t)
            return p

        product("PCM-500", "Paracetamol 500 mg Tablets", gf, SampleType.FINISHED_PRODUCT, [
            dict(name="Description", method="Visual", limit_type=LimitType.TEXT_COMPLIES,
                 text_expected="Complies", limit_text="White, capsule-shaped tablets"),
            dict(name="Identification (HPLC)", method="USP monograph", limit_type=LimitType.TEXT_COMPLIES,
                 text_expected="Complies", limit_text="Retention time matches standard"),
            dict(name="Average weight", method="In-house WT-01", unit="mg", limit_type=LimitType.NUMERIC_RANGE,
                 min_value="617.5", max_value="682.5", decimals=1, limit_text="617.5 – 682.5 mg"),
            dict(name="Assay (Paracetamol)", method="USP, HPLC", unit="%", limit_type=LimitType.NUMERIC_RANGE,
                 min_value="95.0", max_value="105.0", decimals=1, limit_text="95.0 – 105.0 %"),
            dict(name="Dissolution (Q)", method="USP <711>", unit="%", limit_type=LimitType.NUMERIC_MIN,
                 min_value="80", decimals=0, limit_text="NLT 80 %"),
        ])
        vitc = product("VITC-100", "Vitamin C 100 mg Chewable Tablets", nutra, SampleType.FINISHED_PRODUCT, [
            dict(name="Description", method="Visual", limit_type=LimitType.TEXT_COMPLIES,
                 text_expected="Complies", limit_text="Orange, round, flat tablets"),
            dict(name="Assay (Ascorbic acid)", method="Titrimetric", unit="%", limit_type=LimitType.NUMERIC_RANGE,
                 min_value="90.0", max_value="120.0", decimals=1, limit_text="90.0 – 120.0 %"),
            dict(name="Disintegration", method="USP <701>", unit="min", limit_type=LimitType.NUMERIC_MAX,
                 max_value="30", decimals=0, limit_text="NMT 30 min"),
        ])
        ibu = product("IBU-API", "Ibuprofen (API)", api, SampleType.RAW_MATERIAL, [
            dict(name="Description", method="Visual", limit_type=LimitType.TEXT_COMPLIES,
                 text_expected="Complies", limit_text="White crystalline powder"),
            dict(name="Assay", method="Ph. Eur., titration", unit="%", limit_type=LimitType.NUMERIC_RANGE,
                 min_value="98.5", max_value="101.0", decimals=1, limit_text="98.5 – 101.0 %"),
            dict(name="Loss on drying", method="Ph. Eur. 2.2.32", unit="%", limit_type=LimitType.NUMERIC_MAX,
                 max_value="0.5", decimals=2, limit_text="NMT 0.50 %"),
            dict(name="Sulphated ash", method="Ph. Eur. 2.4.14", unit="%", limit_type=LimitType.NUMERIC_MAX,
                 max_value="0.1", decimals=2, limit_text="NMT 0.10 %"),
            dict(name="Melting range", method="Ph. Eur. 2.2.14", unit="°C", limit_type=LimitType.REPORT_ONLY,
                 limit_text="Report result"),
        ])

        def workflow(name, description, stages, products):
            wf = Workflow.objects.filter(name=name).first()
            if wf is None:
                wf = Workflow.objects.create(name=name, description=description)
                version = WorkflowVersion.objects.create(workflow=wf, version=1, reason="Seeded demo workflow")
                taken = set()
                for order, (stage_name, title, holder, role_code) in enumerate(stages, start=1):
                    code = stage_code(stage_name, taken)
                    taken.add(code)
                    WorkflowStage.objects.create(
                        version=version, order=order, code=code, name=stage_name,
                        signature_title=title, holder_title=holder, role=roles[role_code],
                    )
            for p in products:
                if p.workflow_id is None:
                    p.workflow = wf
                    p.save(update_fields=["workflow"])

        # PCM-500 keeps the default (Standard review), created by lims/0005.
        workflow("Short release", "A single approval after the analyst — low-risk nutraceuticals.", [
            ("Approved", "Approved by", "QCM / HOD", "APPROVER"),
        ], [vitc])
        workflow("Extended review", "Adds a QA review between the check and the approval.", [
            ("Checked", "Checked by", "AM / DM", "CHECKER"),
            ("QA review", "Reviewed by", "QA", "QA_OFFICER"),
            ("Approved", "Approved by", "QCM / HOD", "APPROVER"),
        ], [ibu])

        self.stdout.write(self.style.SUCCESS(
            "Seeded. Logins (password: %s): frontdesk, analyst.gf, analyst.gf2, analyst.api, checker, "
            "qa.officer, labhead, prod.operator, prod.officer, sysadmin. "
            "For Floxcip 500 mg batch 26FB017 run seed_floxcip next." % PASSWORD
        ))
