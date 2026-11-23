import django.db.models.functions.text
from django.db import migrations, models


def seed_from_samples(apps, schema_editor):
    """
    Start the list with the names already received under, so the front desk is
    never left with nothing to choose. Spellings that differ only in case or
    spacing become one entry, under the spelling used most.
    """
    Sample = apps.get_model("lims", "Sample")
    SampleSource = apps.get_model("lims", "SampleSource")
    counts: dict[str, dict[str, int]] = {}
    for raw in Sample.objects.values_list("received_from", flat=True):
        name = " ".join((raw or "").split())[:200]
        if name:
            spellings = counts.setdefault(name.lower(), {})
            spellings[name] = spellings.get(name, 0) + 1
    for spellings in counts.values():
        name = max(spellings, key=lambda s: (spellings[s], s))
        SampleSource.objects.create(name=name)


class Migration(migrations.Migration):

    dependencies = [
        ('lims', '0017_testdefinition_method_record'),
    ]

    operations = [
        migrations.CreateModel(
            name='SampleSource',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'constraints': [
                    models.UniqueConstraint(
                        django.db.models.functions.text.Lower('name'), name='lims_samplesource_name_ci_unique'
                    ),
                ],
            },
        ),
        migrations.RunPython(seed_from_samples, migrations.RunPython.noop),
    ]
