"""
Turn the hardcoded role enum into configurable Role rows.

Existing users keep exactly the access they had: each old role string maps
to a seeded Role holding the permissions that role's hardcoded checks
allowed. Nothing widens, nothing narrows.
"""
from django.db import migrations, models
import django.db.models.deletion

from accounts.permissions_registry import SYSTEM_ROLES


def seed_roles_and_migrate_users(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Grant = apps.get_model("accounts", "RolePermissionGrant")
    User = apps.get_model("accounts", "User")

    by_code = {}
    for code, name, description, perms in SYSTEM_ROLES:
        role = Role.objects.create(
            code=code, name=name, description=description, is_system=True, is_active=True
        )
        for key in perms:
            Grant.objects.create(role=role, permission=key, reason="Seeded with the system role")
        by_code[code] = role

    for user in User.objects.all():
        role = by_code.get(user.legacy_role)
        if role is not None:
            user.role_id = role.id
            user.save(update_fields=["role"])


def unseed(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Role = apps.get_model("accounts", "Role")
    for user in User.objects.select_related("role"):
        if user.role_id:
            user.legacy_role = user.role.code
            user.save(update_fields=["legacy_role"])
    Role.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Role",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("code", models.SlugField(max_length=40, unique=True)),
                ("name", models.CharField(max_length=80)),
                ("description", models.TextField(blank=True)),
                ("is_system", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="RolePermissionGrant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("permission", models.CharField(max_length=60)),
                ("granted_at", models.DateTimeField(auto_now_add=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("reason", models.CharField(blank=True, max_length=500)),
                ("granted_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT,
                                                 related_name="+", to="accounts.user")),
                ("revoked_by", models.ForeignKey(blank=True, null=True,
                                                 on_delete=django.db.models.deletion.PROTECT,
                                                 related_name="+", to="accounts.user")),
                ("role", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name="grants", to="accounts.role")),
            ],
            options={"ordering": ["-granted_at", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="rolepermissiongrant",
            constraint=models.UniqueConstraint(
                condition=models.Q(("revoked_at__isnull", True)),
                fields=("role", "permission"),
                name="uniq_active_grant",
            ),
        ),
        # Keep the old value under a temporary name so the data migration can read it.
        migrations.RenameField(model_name="user", old_name="role", new_name="legacy_role"),
        migrations.AddField(
            model_name="user",
            name="role",
            field=models.ForeignKey(blank=True, null=True,
                                    on_delete=django.db.models.deletion.PROTECT,
                                    related_name="users", to="accounts.role"),
        ),
        migrations.RunPython(seed_roles_and_migrate_users, unseed),
        migrations.RemoveField(model_name="user", name="legacy_role"),
    ]
