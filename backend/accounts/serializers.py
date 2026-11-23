from rest_framework import serializers

from .models import Role, RolePermissionGrant, User
from .passwords import needs_new_password
from .permissions_registry import ALL_PERMISSIONS


def review_stages_of(role) -> list[dict]:
    """The review stages this role signs in each workflow's current version."""
    from lims.workflow import current_stages

    if role is None:
        return []
    return [
        {"workflow": s.version.workflow.name, "stage": s.name, "title": s.full_title}
        for s in current_stages()
        if s.role_id == role.id
    ]


def photo_url_for(user) -> str | None:
    """
    Authenticated endpoint, not a MEDIA_URL path. The cache-buster is the
    stored filename, which is a fresh UUID on every upload — so a changed
    photo is never served from cache.
    """
    if not user.photo:
        return None
    stamp = user.photo.name.rsplit("/", 1)[-1].split(".")[0]
    return f"/api/auth/users/{user.pk}/photo/?v={stamp}"


class UserSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    sections = serializers.SlugRelatedField(slug_field="code", many=True, read_only=True)
    role = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    photo_url = serializers.SerializerMethodField()
    is_reviewer = serializers.SerializerMethodField()
    must_change_password = serializers.SerializerMethodField()

    class Meta:
        model = User
        # Fetched on every page load — keep it lean.
        fields = [
            "id", "username", "name", "designation", "role", "sections",
            "permissions", "photo_url", "is_active", "is_reviewer", "must_change_password",
        ]

    def get_must_change_password(self, obj) -> bool:
        return needs_new_password(obj)

    def get_name(self, obj) -> str:
        return obj.display_name()

    def get_role(self, obj):
        if obj.role_id is None:
            return None
        return {"id": obj.role.id, "code": obj.role.code, "name": obj.role.name}

    def get_permissions(self, obj):
        return sorted(obj.permissions())

    def get_photo_url(self, obj):
        return photo_url_for(obj)

    def get_is_reviewer(self, obj) -> bool:
        """Signs a review stage — review signatures come from workflows, not permissions."""
        from lims.workflow import is_reviewer

        return is_reviewer(obj)


class UserAdminSerializer(UserSerializer):
    """Adds the fields only an administrator needs to see."""

    section_ids = serializers.SerializerMethodField()
    can_sign_in = serializers.SerializerMethodField()
    locked_until = serializers.SerializerMethodField()

    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + [
            "first_name", "last_name", "email", "section_ids", "last_login",
            "employee_id", "joining_date", "phone", "can_sign_in", "locked_until",
        ]

    def get_locked_until(self, obj):
        """Only while it holds: a lockout ends by itself."""
        from .passwords import is_locked
        return obj.locked_until if is_locked(obj) else None

    def get_section_ids(self, obj):
        return list(obj.sections.values_list("id", flat=True))

    def get_can_sign_in(self, obj) -> bool:
        return obj.may_sign_in()


class ProfileSerializer(UserAdminSerializer):
    """
    A user's own record. Adds the things nobody could previously see about
    themselves: which sections they are qualified for, what they are
    permitted to do, and when they last signed in.
    """

    role_description = serializers.SerializerMethodField()
    section_names = serializers.SerializerMethodField()
    permission_labels = serializers.SerializerMethodField()
    permission_groups = serializers.SerializerMethodField()
    review_stages = serializers.SerializerMethodField()

    class Meta(UserAdminSerializer.Meta):
        fields = UserAdminSerializer.Meta.fields + [
            "role_description", "section_names", "permission_labels", "permission_groups", "review_stages",
            "date_joined",
        ]

    def get_permission_groups(self, obj):
        """What they may do now, by area, in the order of the Roles screen. A report keeps its group."""
        from .permissions_registry import GROUPS, MODULES

        held = obj.permissions()
        groups = []
        for mod_key, name, perms in MODULES:
            mine = [
                {"key": k, "label": label, "help": help_, **({"group": GROUPS[k]} if k in GROUPS else {})}
                for k, label, help_ in perms if k in held
            ]
            if mine:
                groups.append({"key": mod_key, "name": name, "permissions": mine})
        return groups

    def get_role_description(self, obj):
        return obj.role.description if obj.role_id else ""

    def get_section_names(self, obj):
        return list(obj.sections.values_list("name", flat=True))

    def get_permission_labels(self, obj):
        return [
            {"key": key, "label": ALL_PERMISSIONS[key]}
            for key in sorted(obj.permissions())
            if key in ALL_PERMISSIONS
        ]

    def get_review_stages(self, obj):
        return review_stages_of(obj.role) if obj.is_active else []


class RoleSerializer(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()
    conflicts = serializers.SerializerMethodField()
    user_count = serializers.SerializerMethodField()
    review_stages = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = [
            "id", "code", "name", "description", "is_system", "is_active",
            "permissions", "conflicts", "user_count", "review_stages", "created_at",
        ]

    def get_permissions(self, obj):
        return sorted(obj.permissions())

    def get_conflicts(self, obj):
        return obj.conflicts()

    def get_review_stages(self, obj):
        return review_stages_of(obj)

    def get_user_count(self, obj):
        return obj.users.filter(is_active=True).count()


class GrantHistorySerializer(serializers.ModelSerializer):
    label = serializers.CharField(read_only=True)
    granted_by_name = serializers.SerializerMethodField()
    revoked_by_name = serializers.SerializerMethodField()

    class Meta:
        model = RolePermissionGrant
        fields = [
            "id", "permission", "label", "granted_at", "granted_by_name",
            "revoked_at", "revoked_by_name", "reason",
        ]

    def get_granted_by_name(self, obj):
        return obj.granted_by.display_name() if obj.granted_by else "System"

    def get_revoked_by_name(self, obj):
        return obj.revoked_by.display_name() if obj.revoked_by else None


def permission_catalogue():
    """The vocabulary, grouped for the admin screen, with what each permission needs or comes with."""
    from .permissions_registry import GROUPS, INCLUDED_WITH, MODULE_NOTES, MODULES, NEEDS

    def entry(key, label, help_):
        out = {"key": key, "label": label, "help": help_}
        if key in INCLUDED_WITH:
            out["included_with"] = list(INCLUDED_WITH[key])
        if key in NEEDS:
            out["needs"] = NEEDS[key]
        if key in GROUPS:
            out["group"] = GROUPS[key]
        return out

    return [
        {
            "key": mod_key,
            "name": mod_name,
            "note": MODULE_NOTES.get(mod_key, ""),
            "permissions": [entry(k, lbl, help_) for k, lbl, help_ in perms],
        }
        for mod_key, mod_name, perms in MODULES
    ]


def known_permission(key: str) -> bool:
    return key in ALL_PERMISSIONS
