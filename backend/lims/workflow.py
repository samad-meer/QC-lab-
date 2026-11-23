"""
Review workflows: who may act on a sample in review, and what each user's
queue is.

Review signatures are not permissions. Each workflow stage names the one
role that signs it, so "may this user sign?" is answered here, from the
stage the sample is waiting at — never from a fixed role name.
"""
import re

from django.db.models import Exists, OuterRef, Q

from accounts.authz import has_perm
from .models import Sample, SampleStatus, Workflow, WorkflowStage

MAX_STAGES = 10

# Reserved for the analyst's signature (certificates.models.ANALYSED), the
# analyst's step (execution.models.TESTING) and the front desk's receipt
# checks (execution.models.RECEIPT).
RESERVED_CODES = {"ANALYSED", "TESTING", "RECEIPT"}


def may_sign_stage(user, stage) -> bool:
    return bool(
        stage is not None
        and getattr(user, "is_authenticated", False)
        and user.is_active
        and user.role_id is not None
        and user.role_id == stage.role_id
        and user.role.is_active
    )


def is_reviewer(user) -> bool:
    """Does this user's role sign any review stage, in any workflow version?"""
    if not getattr(user, "is_authenticated", False) or user.role_id is None or not user.role.is_active:
        return False
    return WorkflowStage.objects.filter(role_id=user.role_id).exists()


def review_queue(user):
    """Samples waiting at a stage this user's role signs, that they have not already signed."""
    from certificates.models import CertStatus, Signature

    if not is_reviewer(user):
        return Sample.objects.none()
    already_signed = Signature.objects.filter(
        certificate__sample=OuterRef("pk"), certificate__status=CertStatus.IN_REVIEW, user=user
    )
    return Sample.objects.filter(
        status=SampleStatus.IN_REVIEW, review_stage__role_id=user.role_id
    ).filter(~Exists(already_signed))


def samples_visible_to(user):
    """
    With sample.view.all, everything. Otherwise: samples assigned to you,
    samples you registered, samples waiting at a stage your role signs,
    samples you have signed, and samples with a step handed or assigned to you.
    """
    from certificates.models import Signature
    from execution.models import Assignment, AssignmentStatus

    qs = Sample.objects.select_related("product", "section", "assigned_analyst", "review_stage__role")
    if has_perm(user, "sample.view.all"):
        return qs
    visible = (
        Q(assigned_analyst=user)
        | Q(registered_by=user)  # whoever received it makes its receipt checks
        | Exists(Signature.objects.filter(certificate__sample=OuterRef("pk"), user=user))
        | Exists(Assignment.objects.filter(
            sample=OuterRef("pk"), to_user=user,
            status__in=[AssignmentStatus.PENDING, AssignmentStatus.ACCEPTED],
        ))
    )
    if user.role_id is not None:
        visible |= Q(status=SampleStatus.IN_REVIEW, review_stage__role_id=user.role_id)
    return qs.filter(visible)


def stage_code(name: str, taken: set[str]) -> str:
    """A signature meaning derived from the stage name, unique within its version."""
    base = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")[:26] or "STAGE"
    code, n = base, 2
    while code in taken or code in RESERVED_CODES:
        code = f"{base}_{n}"
        n += 1
    return code


def current_stages():
    """The stages of every workflow's newest version — what new samples will use."""
    stages = []
    for workflow in Workflow.objects.all():
        version = workflow.current_version()
        if version is not None:
            stages += list(version.stages.select_related("role", "version__workflow"))
    return stages


def stage_conflicts(role) -> list[dict]:
    """
    Segregation-of-duties conflicts that come from the stages a role signs.
    Reported, never blocked — a small lab may need them. Same shape as
    accounts.permissions_registry.conflicts_in.
    """
    held = role.permissions()
    mine = [s for s in current_stages() if s.role_id == role.id]
    found = []
    for stage in mine:
        where = f"“{stage.full_title}” in {stage.version.workflow.name}"
        if "cert.sign.analysed" in held:
            found.append({
                "a": "cert.sign.analysed", "b": f"stage:{stage.code}",
                "message": f"Can sign as the analyst and also sign {where}.",
            })
        admin_keys = held & {"role.manage", "workflow.manage", "user.manage"}
        if admin_keys:
            found.append({
                "a": sorted(admin_keys)[0], "b": f"stage:{stage.code}",
                "message": f"An administrator role also signs {where} — it could change the rules it signs under.",
            })
    by_workflow: dict[str, list] = {}
    for stage in mine:
        by_workflow.setdefault(stage.version.workflow.name, []).append(stage)
    for name, stages in by_workflow.items():
        if len(stages) > 1:
            found.append({
                "a": f"stage:{stages[0].code}", "b": f"stage:{stages[1].code}",
                "message": (
                    f"Signs {len(stages)} stages of {name} — each certificate needs "
                    f"{len(stages)} different people holding this role."
                ),
            })
    return found


def stage_warnings(stages) -> list[str]:
    """Things an administrator should know before samples start waiting at these stages."""
    warnings = []
    seen: dict[int, list] = {}
    for stage in stages:
        seen.setdefault(stage.role_id, []).append(stage)
    for stages_of_role in seen.values():
        role = stages_of_role[0].role
        if not role.users.filter(is_active=True).exists():
            warnings.append(
                f"Nobody holds the {role.name} role yet — samples would wait at "
                f"“{stages_of_role[0].name}” with no one able to sign."
            )
        if len(stages_of_role) > 1:
            warnings.append(
                f"The {role.name} role signs {len(stages_of_role)} stages, so each certificate "
                f"needs {len(stages_of_role)} different people holding it."
            )
        if "cert.sign.analysed" in role.permissions():
            warnings.append(
                f"The {role.name} role can also sign as the analyst. Nobody can sign the same "
                "certificate twice, but these duties are normally kept apart."
            )
    return warnings
