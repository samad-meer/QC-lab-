"""
Turns an audit row into a sentence a person can read.

"SIGNED_CHECKED · certificate · 41" tells an inspector almost nothing.
"Bilal Ahmed signed GF-2026-0004 as Checked by" tells them everything. The
raw action and details are still returned alongside — this is a reading aid,
never a replacement for the record.
"""

# action -> (severity, template). {who} and {what} are always available;
# anything else comes from the event's details.
TEMPLATES: dict[str, tuple[str, str]] = {
    # --- the journey ---------------------------------------------------
    "SAMPLE_REGISTERED": ("normal", "registered sample {what} ({product}, {batch}) and assigned it to {analyst}"),
    "NOTIFICATION_RULE_CHANGED": ("admin", "changed the notification rule “{label}”"),
    # --- specifications and templates ----------------------------------------
    "SPEC_DRAFTED": ("admin", "drafted specification {what} — “{reason}”"),
    "SPEC_EDITED": ("quiet", "edited draft specification {what} ({tests} tests)"),
    "SPEC_DISCARDED": ("admin", "discarded draft specification {what}"),
    "SPEC_APPROVED": ("signature", "made specification {what} effective, replacing {replaces}"),
    "SPEC_APPROVAL_REFUSED": ("refused", "was refused making {what} effective — they drafted it themselves"),
    "SPEC_REVIEW_DATE_CHANGED": ("admin", "changed the review date of {what} from {before} to {after} — “{reason}”"),
    "TEST_TEMPLATE_CREATED": ("admin", "added test template {what} ({name})"),
    "TEST_TEMPLATE_CHANGED": ("admin", "saved version {version} of test template {what} — “{reason}”"),
    "CERT_TEMPLATE_CREATED": ("admin", "added certificate template “{what}”"),
    "CERT_TEMPLATE_CHANGED": ("admin", "changed certificate template “{what}”"),
    "CERT_TEMPLATE_DELETED": ("admin", "deleted certificate template “{what}”"),
    "LABEL_PRINTED": ("quiet", "printed a label for {what}"),
    "RECORD_PRINTED": ("normal", "printed the {kind} record of {what}"),
    # --- the product master and batches -----------------------------------
    "PRODUCT_CREATED": ("admin", "added product {what} ({name}) to the master"),
    "PRODUCT_UPDATED": ("admin", "changed product {what} — “{reason}”"),
    "BATCH_CREATED": ("normal", "recorded batch {what} (official number {official}, product {product})"),
    "BATCH_DETAILS_ADDED": ("normal", "filled in missing details on batch {what}"),
    "BATCH_UPDATED": ("attention", "corrected batch {what} — “{reason}”"),
    "BATCH_RULE_CHANGED": ("admin", "changed how internal batch IDs are built: {before} is now {after}"),
    "BATCH_DOCUMENT_ADDED": ("normal", "added “{title}” (version {version}) to batch {what}"),
    "BATCH_DOCUMENT_WITHDRAWN": ("attention", "withdrew “{title}” (version {version}) from batch {what} — “{reason}”"),
    "QC_STAGES_CHANGED": ("admin", "saved version {version} of the QC stages of product {what} — “{reason}”"),
    "BATCH_STAGE_RECORDED": ("signature", "recorded QC stage “{stage}” of batch {what} as {decision}"),
    "BATCH_STAGE_REFUSED": ("refused", "was refused recording QC stage “{stage}” of batch {what} — {reason}"),
    "BATCH_STAGE_NOT_APPLICABLE": ("signature", "marked QC stage “{stage}” not applicable to batch {what} — “{reason}”"),
    "BATCH_STAGE_APPLIES_AGAIN": ("signature", "said QC stage “{stage}” applies to batch {what} after all — “{reason}”"),
    "CHECKPOINT_KIND_CREATED": ("admin", "added the check point kind “{what}”, based on {based_on}"),
    "CHECKPOINT_KIND_CHANGED": ("admin", "changed the check point kind “{what}”"),
    "BATCH_RECORD_WRITTEN": ("normal", "wrote on stage “{stage}” of batch {what}: {summary}"),
    "BATCH_RECORD_REFUSED": ("refused", "was refused writing or signing stage “{stage}” of batch {what} — {reason}"),
    "BATCH_STAGE_SIGNED": ("signature", "signed “{column}” on stage “{stage}” of batch {what}"),
    "BATCH_STAGE_ASSIGNED": ("normal", "assigned stage “{stage}” of batch {what} to {to}{was_note}"),
    "BATCH_STAGE_UNASSIGNED": ("normal", "took stage “{stage}” of batch {what} away from {was}{after}"),
    "BATCH_STAGE_ADDED": ("signature", "added QC stage “{stage}” ({kind}, {required}) to batch {what} — “{reason}”"),
    "RECEIPT_COMPLETED": ("normal", "completed the receipt checks on {what} — testing can start"),
    "RESULT_ENTERED": ("normal", "entered {test} = {value} on {what} — {outcome}"),
    "RESULT_SUPERSEDED": ("attention", "replaced the earlier {test} result on {what} — reason: “{reason}”"),
    "SIGNED_ANALYSED": ("signature", "signed certificate v{version} for {sample} as “Analysed by”"),
    "SIGNED_STAGE": ("signature", "signed the certificate for {sample} as “{title}” (review {step} of {of})"),
    "SIGNED_FINAL": ("signature", "signed the certificate for {sample} as “{title}” and released it"),
    "RETURNED_TO_ANALYST": ("attention", "sent {sample} back to the analyst at “{stage}” — “{comment}”"),
    "PRINTED": ("normal", "printed copy {copy_number} of the certificate for {sample}"),
    # --- inside each step: checklists, documents, notes --------------------
    "CHECKLIST_ANSWERED": ("normal", "answered “{item}” on {what} at {step}: {answer}"),
    "CHECKLIST_CHANGED": ("attention", "changed “{item}” on {what} at {step} from {previous} to {answer}"),
    "CHECKLIST_CLEARED": ("attention", "cleared the answer to “{item}” on {what} at {step} — “{reason}”"),
    "ATTACHMENT_UPLOADED": ("normal", "attached {name} (version {version}) to {what} at {step}"),
    "ATTACHMENT_WITHDRAWN": ("attention", "withdrew {name} (version {version}) from {what} — “{reason}”"),
    "COMMENT_ADDED": ("quiet", "added a note on {what} at {step}"),
    "FEEDBACK_ADDED": ("normal", "gave review feedback on {what} at {step}"),
    "COMMENT_REPLIED": ("quiet", "replied to a comment on {what} at {step}"),
    "COMMENT_AMENDED": ("attention", "amended their own comment on {what} at {step} (the original is kept)"),
    # --- who holds the work ----------------------------------------------
    "ASSIGNED": ("normal", "assigned {step} of {what} to {to} (previously {previous})"),
    "HANDOVER_OFFERED": ("normal", "handed {step} of {what} over to {to} — “{note}”"),
    "HANDOVER_ACCEPTED": ("normal", "accepted {step} of {what} from {sender}"),
    "HANDOVER_REJECTED": ("attention", "declined {step} of {what} from {sender} — “{reason}”"),
    "HANDOVER_CANCELLED": ("normal", "cancelled the handover of {step} of {what} to {to}"),
    "STEP_CLAIMED": ("normal", "took {step} of {what}"),
    "SAMPLE_HELD": ("attention", "put {what} on hold — “{reason}”"),
    "SAMPLE_RELEASED": ("normal", "released {what} from hold — “{comment}”"),
    # --- failures, retests and waivers ----------------------------------
    "RETEST_REQUESTED": ("attention", "asked to retest {test} on {what} (failed value {failed_value}) — “{reason}”"),
    "RETEST_AUTHORIZED": ("attention", "authorized the retest of {test} on {what} requested by {analyst}"),
    "RETEST_DECLINED": ("attention", "declined the retest of {test} on {what} — “{comment}”"),
    "RETEST_ENTERED": ("normal", "entered the authorized retest of {test} on {what}: {value} — {outcome}"),
    "REQUIREMENT_WAIVED": ("attention", "waived “{item}” on {what} at {step} — “{reason}”"),
    # --- investigations, deviations and CAPA ------------------------------
    "INVESTIGATION_OPENED": ("attention", "opened {what} ({kind})"),
    "INVESTIGATION_CHANGED": ("normal", "changed {fields} on {what}"),
    "CAPA_ADDED": ("normal", "added a {kind} action to {what}: “{description}”"),
    "CAPA_COMPLETED": ("normal", "completed a {kind} action on {what}: “{note}”"),
    "INVESTIGATION_SUBMITTED": ("normal", "sent {what} for closure approval"),
    "INVESTIGATION_RETURNED": ("attention", "sent {what} back for more work — “{comment}”"),
    "INVESTIGATION_CLOSED": ("signature", "approved the closure of {what}"),
    "INVESTIGATION_LAB_FINDING": ("normal", "recorded the laboratory finding on {what}"),
    "SAMPLE_REJECTED": ("signature", "rejected sample {what}"),
    "SAMPLE_CANCELLED": ("signature", "cancelled sample {what}"),
    "CERT_WITHDRAWN": ("signature", "withdrew the certificate for {what}"),
    "CERT_INTEGRITY_FAILED": ("refused", "found that the certificate for {what} no longer matches what was signed"),
    "CERT_COPY_OPENED": ("normal", "opened a numbered copy of a certificate to print it"),
    "AUDIT_REVIEWED": ("signature", "reviewed the activity log ({events} events)"),
    "INTEGRITY_CHECK": ("quiet", "checked records and files against their hashes"),
    "QUALITY_RULES_CHANGED": ("normal", "changed the quality rules"),
    "RETEST_REFUSED_SAME_ANALYST": ("refused", "was refused a retest of their own failure on {what}"),
    "INVESTIGATION_CLOSE_REFUSED": ("refused", "was refused the closure of {what} — they were involved in the work"),
    "CAPA_VERIFIED": ("signature", "verified a {kind} action on {what}: “{note}”"),
    "CAPA_VERIFY_REFUSED": ("refused", "was refused verifying a {kind} action on {what} — they owned or completed it"),
    # --- instruments, materials, methods and qualifications ---------------
    "INSTRUMENT_ADDED": ("admin", "added instrument {what} ({name})"),
    "INSTRUMENT_CORRECTED": ("attention", "corrected instrument {what} — “{reason}”"),
    "INSTRUMENT_STATUS_CHANGED": ("attention", "changed instrument {what} from {before} to {after} — “{reason}”"),
    "INSTRUMENT_OUT_OF_SERVICE": ("attention", "took instrument {what} out of service after a failure ({reference})"),
    "CALIBRATION_RECORDED": ("normal", "recorded a {kind} of {what}: {outcome} ({reference})"),
    "MATERIAL_ADDED": ("admin", "added {kind} {what} ({name}), status {status}"),
    "MATERIAL_CORRECTED": ("attention", "corrected {what} — “{reason}”"),
    "MATERIAL_STATUS_CHANGED": ("attention", "changed {what} from {before} to {after} — “{reason}”"),
    "METHOD_DRAFTED": ("admin", "drafted method {what} ({title})"),
    "METHOD_EDITED": ("quiet", "edited draft method {what}"),
    "METHOD_APPROVED": ("signature", "made method {what} effective, replacing {replaces}"),
    "METHOD_APPROVAL_REFUSED": ("refused", "was refused making {what} effective — they drafted or changed it"),
    "METHOD_RETIRED": ("attention", "retired method {what} — “{reason}”"),
    "SPEC_APPROVAL_REFUSED_METHOD": ("refused", "was refused making {what} effective — {reason}"),
    "QUALIFICATION_GRANTED": ("signature", "qualified {person} on {method} until {expires}"),
    "QUALIFICATION_REVOKED": ("signature", "revoked {what} — “{reason}”"),
    "QUALIFICATION_REFUSED": ("refused", "was refused qualifying themselves: {what}"),
    "RESULT_REFUSED_UNQUALIFIED": ("refused", "was refused a result for {test} on {what} — {reason}"),
    "RESULT_REFUSED_RAW_DATA": ("refused", "was refused a result for {test} on {what} — {reason}"),
    "RESULT_RAW_DATA_RECORDED": ("normal", "recorded the raw data of {test} on {what}"),
    # --- chain of custody ---------------------------------------------------
    "CUSTODY_RECORDED": ("normal", "recorded {what} as {movement}"),
    "SAMPLE_DESTROYED": ("signature", "destroyed sample {what}, witnessed by {witness}"),
    "SAMPLE_DESTRUCTION_REFUSED": ("refused", "was refused destroying {what} — {reason}"),
    # --- change control ---------------------------------------------------
    "CHANGE_RAISED": ("attention", "raised change {what}: “{title}”"),
    "CHANGE_EDITED": ("normal", "changed {fields} on {what} — “{reason}”"),
    "CHANGE_APPROVED": ("signature", "approved change {what}"),
    "CHANGE_REJECTED": ("signature", "rejected change {what} — “{reason}”"),
    "CHANGE_IMPLEMENTED": ("normal", "implemented change {what}: “{note}”"),
    "CHANGE_CLOSED": ("signature", "closed change {what}"),
    "CHANGE_APPROVAL_REFUSED": ("refused", "was refused deciding {what} — they raised or changed it"),
    "CHANGE_CLOSE_REFUSED": ("refused", "was refused closing {what} — they raised or implemented it"),
    # --- batch disposition ------------------------------------------------
    "BATCH_DISPOSITION": ("signature", "decided batch {what}: {decision} — “{reason}”"),
    "BATCH_DISPOSITION_REFUSED": ("refused", "was refused a decision on batch {what} — {reason}"),
    # --- reports ---------------------------------------------------------
    "REPORT_EXPORTED": ("normal", "exported the {title} report as {format} ({rows} rows)"),
    "DOCUMENT_EXPORTED": ("normal", "exported the {title} for {what} as {format}"),
    "LIST_EXPORTED": ("normal", "exported the {title} list as {format} ({rows} rows)"),
    # --- recorded before review workflows; kept so old history still reads -
    "SIGNED_CHECKED": ("signature", "signed the certificate for {sample} as “Checked by”"),
    "SIGNED_APPROVED": ("signature", "approved and released the certificate for {sample}"),
    "SENT_BACK_BY_CHECKER": ("attention", "sent {sample} back to the analyst — “{comment}”"),
    "REJECTED_BY_APPROVER": ("attention", "rejected the certificate for {sample} — “{reason}”"),
    # --- refusals: the ones an inspector looks for ----------------------
    "SIGN_REFUSED_SAME_PERSON": ("refused", "was refused a second signature on {sample} — every signature must come from a different person"),
    "SIGN_PASSWORD_FAILED": ("refused", "failed the password check when signing {what}"),
    "PRINT_REFUSED_UNAPPROVED": ("refused", "tried to print the certificate for {sample} before it was approved"),
    "PRINT_REFUSED_NO_PERMISSION": ("refused", "tried to print the certificate for {sample} without permission"),
    "PASSWORD_CHANGE_FAILED": ("refused", "gave the wrong current password when changing their own"),
    "LOGIN_FAILED": ("refused", "failed to sign in as “{username}”"),
    "SIGN_REFUSED_BLOCKED": ("refused", "was stopped from signing {what} at {step} — requirements outstanding"),
    "RECEIPT_REFUSED_BLOCKED": ("refused", "was stopped from completing the receipt checks on {what} — requirements outstanding"),
    "SIGN_REFUSED_WAIVER": ("refused", "was refused the signature at {step} on {what} — they waived one of its requirements"),
    "RESULT_REPLACE_REFUSED_FAILED": ("refused", "tried to replace the failed {test} result on {what} without an authorized retest"),
    "RETEST_REFUSED_NOT_INDEPENDENT": ("refused", "tried to decide the retest of {test} on {what} for their own work"),
    "ATTACHMENT_REFUSED": ("refused", "had the file {name} refused on {what} — {reason}"),
    "ACCESS_REFUSED": ("refused", "was refused on {what} — “{reason}”"),
    # --- access and administration --------------------------------------
    "LOGIN": ("quiet", "signed in"),
    "LOGOUT": ("quiet", "signed out"),
    "USER_CREATED": ("admin", "created the user {what} ({name}) in the {role} role"),
    "USER_UPDATED": ("admin", "changed the user {what}"),
    "PASSWORD_RESET": ("attention", "reset the password for {what}"),
    "PASSWORD_CHANGED": ("quiet", "changed their password"),
    "ACCOUNT_LOCKED": ("refused", "was locked out of {what} after repeated wrong passwords"),
    "SESSION_TIMED_OUT": ("quiet", "was signed out after a period of inactivity"),
    "SESSION_ENDED": ("admin", "signed {what} out on {device}, from {where}"),
    "ACCOUNT_UNLOCKED": ("admin", "lifted the lockout on {what}"),
    "ROLE_CREATED": ("admin", "created the role {name}"),
    "ROLE_UPDATED": ("admin", "changed the role {what}"),
    "SECTION_CREATED": ("admin", "added the section {what} ({name})"),
    "SECTION_RENAMED": ("admin", "renamed section {what} from “{was}” to “{name}”"),
    "SECTION_DELETED": ("admin", "deleted the unused section {what}"),
    "SAMPLE_SOURCE_ADDED": ("admin", "added “{name}” to the Received from list"),
    "SAMPLE_SOURCE_RENAMED": ("admin", "renamed “{was}” to “{name}” on the Received from list"),
    "SAMPLE_SOURCE_DEACTIVATED": ("admin", "stopped offering “{name}” under Received from"),
    "SAMPLE_SOURCE_REACTIVATED": ("admin", "offered “{name}” under Received from again"),
    "EMAIL_TEST_SENT": ("admin", "sent a test email to {to}"),
    "EMAIL_FAILED": ("attention", "could not email “{title}” to {to} — {error}"),
    "ROLE_PERMISSIONS_CHANGED": ("admin", "changed what the {what} role may do"),
    "ROLE_DELETED": ("admin", "deleted the role {what}"),
    "WORKFLOW_CREATED": ("admin", "created the review workflow “{name}”: {stages}"),
    "WORKFLOW_CHANGED": ("admin", "changed the stages of “{name}” (now version {version}): {stages}"),
    "WORKFLOW_UPDATED": ("admin", "renamed or re-described the workflow “{name}”"),
    "WORKFLOW_DEFAULT_CHANGED": ("admin", "made “{name}” the default review workflow"),
    "WORKFLOW_DELETED": ("admin", "deleted the unused workflow “{name}”"),
    "PRODUCT_WORKFLOW_CHANGED": ("admin", "set product {what} to use {workflow}"),
    "LAB_CONFIG_UPDATED": ("admin", "changed the lab details"),
    "FEATURES_CHANGED": ("admin", "changed what the lab shows: hid {hidden}; showed {shown}"),
    "LAB_LOGO_CHANGED": ("admin", "replaced the lab logo"),
    "LAB_LOGO_REMOVED": ("admin", "removed the lab logo"),
    # The break-glass site works outside the app's rules, so it always stands out.
    "ADMIN_SITE_ADDED": ("attention", "added {model} “{name}” through the Django admin site"),
    "ADMIN_SITE_CHANGED": ("attention", "changed {model} “{name}” through the Django admin site — {change}"),
    "ADMIN_SITE_DELETED": ("attention", "deleted {model} “{name}” through the Django admin site"),
    "PROFILE_UPDATED": ("quiet", "updated their own contact details"),
    "PROFILE_PHOTO_CHANGED": ("quiet", "changed their profile photo"),
    "PROFILE_PHOTO_REMOVED": ("quiet", "removed their profile photo"),
    "PASSWORD_CHANGED": ("normal", "changed their own password"),
}

# Which of these are worth surfacing on the dashboard as "needs attention".
NOTABLE = {"refused", "attention"}

# Work returned to the analyst — today's action and the two it replaced.
RETURN_ACTIONS = ["RETURNED_TO_ANALYST", "SENT_BACK_BY_CHECKER", "REJECTED_BY_APPROVER"]


class _Blank(dict):
    """A missing detail renders as an em dash rather than blowing up."""

    def __missing__(self, key):
        return "—"


def describe(event) -> dict:
    severity, template = TEMPLATES.get(event.action, ("normal", "performed {action} on {what}"))
    fields = _Blank(event.details or {})
    fields["who"] = event.actor_username or "system"
    fields["what"] = event.entity_id
    fields["action"] = event.action.replace("_", " ").lower()
    # Certificate events carry the sample number in details; sample events are
    # keyed by it. Make {sample} work for both.
    if "sample" not in fields and event.entity == "sample":
        fields["sample"] = event.entity_id

    try:
        sentence = template.format_map(fields)
    except (KeyError, IndexError, ValueError):
        sentence = f"performed {fields['action']} on {fields['what']}"

    # Done in someone's place: the rule it passed is part of what happened.
    overridden = (event.details or {}).get("override")
    if overridden:
        sentence = f"{sentence} — administrator override: {' '.join(overridden)}"
        if severity != "refused":
            severity = "attention"

    return {
        "severity": severity,
        "sentence": sentence,
        "notable": severity in NOTABLE,
    }


def sample_reference(event) -> str | None:
    """The sample number this event concerns, if any — lets the UI link to it."""
    details = event.details or {}
    if event.entity == "sample":
        return event.entity_id
    return details.get("sample")
