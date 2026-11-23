"""
Certificates move through workflow stages instead of two fixed statuses.

SIGNED_ANALYST and SIGNED_CHECKED both become IN_REVIEW: how far a
certificate has got is now read from the signatures it carries, matched to
the stages of its sample's workflow. Signatures themselves are untouched —
their meanings (CHECKED, APPROVED) are the default workflow's stage codes.
The meaning column only widens to fit longer stage codes.

(On PostgreSQL the certificate trigger from 0002 permits status changes.)
"""
from django.db import migrations, models


def forward(apps, schema_editor):
    Certificate = apps.get_model("certificates", "Certificate")
    Certificate.objects.filter(status__in=["SIGNED_ANALYST", "SIGNED_CHECKED"]).update(status="IN_REVIEW")


def reverse(apps, schema_editor):
    Certificate = apps.get_model("certificates", "Certificate")
    for cert in Certificate.objects.filter(status="IN_REVIEW"):
        checked = cert.signatures.filter(meaning="CHECKED").exists()
        Certificate.objects.filter(pk=cert.pk).update(status="SIGNED_CHECKED" if checked else "SIGNED_ANALYST")


class Migration(migrations.Migration):

    dependencies = [
        ("certificates", "0002_pg_lockdown"),
    ]

    operations = [
        migrations.AlterField(
            model_name="certificate",
            name="status",
            field=models.CharField(
                choices=[
                    ("IN_REVIEW", "Signed by analyst — in review"),
                    ("APPROVED", "Approved — releasable"),
                    ("SUPERSEDED", "Superseded (sent back / corrected)"),
                ],
                default="IN_REVIEW",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="signature",
            name="meaning",
            field=models.CharField(max_length=30),
        ),
        migrations.RunPython(forward, reverse),
    ]
