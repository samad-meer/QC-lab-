"""The certificate as it has always printed, as the default template."""
from django.db import migrations


def seed(apps, schema_editor):
    apps.get_model("standards", "CertificateTemplate").objects.get_or_create(
        name="Standard certificate", defaults={"is_default": True}
    )


def unseed(apps, schema_editor):
    apps.get_model("standards", "CertificateTemplate").objects.filter(name="Standard certificate").delete()


class Migration(migrations.Migration):
    dependencies = [("standards", "0001_standards")]

    operations = [migrations.RunPython(seed, unseed)]
