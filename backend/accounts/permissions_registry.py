"""
The permission vocabulary — code, not data.

Roles and their grants are configurable by an administrator at runtime.
The set of permission KEYS is not, because each key corresponds to
enforcement logic that has to exist and be tested. Adding a key here is a
release; granting a key to a role is a Tuesday.

Every key below is actually enforced somewhere. Never list a key that is
not, or the "Roles and permissions" screen becomes a lie.
"""

# (key, label, help text)
MODULES: list[tuple[str, str, list[tuple[str, str, str]]]] = [
    (
        "samples",
        "Sample receipt",
        [
            ("sample.register", "Register samples",
             "Record an arriving sample, issue its number, choose the section and assign the analyst."),
            ("sample.view.all", "See all samples",
             "See every sample in the lab. Without this, a user sees only samples assigned to them."),
            ("sample.assign", "Assign and reassign work",
             "Reassign a sample's testing to another trained analyst, or name the person who reviews a "
             "stage. Where the workflow asks for it, the person must accept before they can work."),
            ("sample.cancel", "Cancel samples",
             "Close a sample with no result: registered by mistake, damaged or not testable. Needs a "
             "reason and your password. A sample with a failed result cannot be cancelled."),
            ("sample.hold", "Put samples on hold",
             "Stop all work on a sample, with a reason, and release it again. Nothing can be entered "
             "or signed while a sample is on hold."),
            ("batch.manage", "Manage batches",
             "Create batches, correct their details with a reason, and keep batch documents. The official "
             "batch number cannot change once a certificate has been signed for the batch."),
            ("batch.disposition", "Decide batch disposition",
             "Release, reject or quarantine a batch, with a reason and your password. Never a batch whose "
             "samples they tested. A certificate of analysis is not this decision."),
            ("batch.stage.record", "Record batch QC stages",
             "Mark a batch's QA-recorded stage, such as a line clearance, passed or failed, with remarks and "
             "your password. A stage tested in the lab passes from its samples instead."),
            ("sample.comment", "Add notes and feedback",
             "Write notes, replies and review feedback on the samples they can see. Everyone who can see "
             "a sample can read them; take this away from read-only roles such as an auditor."),
        ],
    ),
    (
        "production",
        "Production",
        [
            ("batch.view.all", "See every batch",
             "See every batch and its batch record, without seeing the lab's samples. Production staff need "
             "this to fill and sign their stages."),
            ("batch.record.fill", "Fill batch records",
             "Write the values a batch's recorded stages ask for: weights, volumes, times, temperatures, LOD. "
             "A value outside its limits needs a reason, a change needs a reason, and nothing can be written "
             "once the stage's first sign-off column is signed. Who signs each column is set by its role."),
            ("batch.stage.assign", "Assign batch-record stages",
             "Name the person who fills a stage of a batch's record and signs its first column, such as "
             "“Done by”. Only that person can then write its values; the columns after it are signed as "
             "before. Reassigning keeps who had it, and when."),
        ],
    ),
    (
        "results",
        "Testing",
        [
            ("result.enter", "Enter and correct results",
             "Enter results on their own assigned samples, and replace a wrong value with a reason. "
             "Users with this permission are the ones offered as analysts at the front desk."),
            ("result.retest.authorize", "Authorize retests",
             "Allow a failed result to be retested, after reading the analyst's reason. A failed result "
             "is never replaced without this. Never for their own request or a result they entered."),
            ("stage.waive", "Waive a stage requirement",
             "Set aside a checklist item or document that its workflow marks as waivable, with a reason. "
             "Whoever waives a requirement cannot also sign that stage."),
        ],
    ),
    (
        "certificate",
        "Certificate and signatures",
        [
            ("cert.sign.analysed", "Sign as “Analysed by”",
             "Build and sign the certificate for their own sample. Freezes the content and sends it "
             "into its review stages. (Who signs each review stage is set per stage on the "
             "Workflows screen, not here.)"),
            ("cert.withdraw", "Withdraw certificates",
             "Withdraw a released certificate that should no longer be relied on. Needs a reason and "
             "your password. The verification page then says it was withdrawn, and it cannot be printed."),
            ("cert.print", "Print certificates",
             "Print an approved certificate. Copy 1 is the original; later copies are numbered duplicates."),
        ],
    ),
    (
        "quality",
        "Investigations and CAPA",
        [
            ("investigation.manage", "Work on investigations",
             "Open investigations and deviations, record the root cause and outcome, add and complete "
             "corrective and preventive actions, verify an action someone else completed, and send them "
             "for closure."),
            ("investigation.approve", "Approve closures",
             "Close an investigation or deviation, with a password signature, or send it back. Never one "
             "they opened, were responsible for, or whose result they entered. Also verifies actions."),
        ],
    ),
    (
        "labrecords",
        "Lab records",
        [
            ("instrument.view", "See instruments",
             "Open the Instruments register: each instrument, its calibration and its logbook. An analyst "
             "still picks the instrument on a result without this."),
            ("instrument.manage", "Manage instruments",
             "Add instruments, correct them with a reason, keep their logbook of calibration and maintenance, "
             "and take them in and out of service."),
            ("material.view", "See standards and reagents",
             "Open the register of reference standards, reagents, columns and consumables. An analyst still "
             "picks the lot on a result without this."),
            ("material.manage", "Manage standards and reagents",
             "Add lots of reference standards, reagents, columns and consumables, correct them with a reason, "
             "and quarantine or retire them."),
            ("method.view", "See methods",
             "Open the Methods register: every version, its status and its validation. Whoever drafts a "
             "specification still picks its methods without this."),
            ("method.manage", "Draft methods",
             "Draft a method or a new version of one. A draft does nothing until someone else makes it effective."),
            ("method.approve", "Make methods effective",
             "Approve a draft method with a password signature, which retires the version it replaces. "
             "Never a draft they wrote or changed. Also retires a method."),
            ("qualification.view", "See analyst qualifications",
             "Open the register of who is qualified on which method, and until when."),
            ("qualification.manage", "Grant analyst qualifications",
             "Record that an analyst is qualified on a method, until a date, with a password signature, and "
             "revoke it. Never their own. Results on that method are refused without it."),
            ("retained.view", "See retained samples",
             "Open the list of retained samples and when each may be destroyed. It lists only the samples "
             "this person can see. A sample's own custody stays on its page."),
            ("custody.record", "Record sample custody",
             "Add to a sample's chain of custody: received, transferred, stored or retained."),
            ("custody.destroy", "Record sample destruction",
             "Record that a finished sample was destroyed, with a password signature and a witness who "
             "confirms with theirs. Refused until any retain-until date has passed."),
            ("change.view", "See change records",
             "Open the Change control register: every change, its approval and how it was implemented."),
            ("change.manage", "Raise and implement changes",
             "Raise a change record, work on it while it is open, and record that it was implemented."),
            ("change.approve", "Approve and close changes",
             "Approve, reject or close a change record, with a password signature. Never one they raised, "
             "changed or implemented."),
        ],
    ),
    (
        "reports",
        "Reports",
        [
            ("report.view", "Open reports",
             "Open the Reports module. Which reports it holds for this role is chosen one by one below. "
             "Sample-based reports show only the samples this person can see, so give sample.view.all to "
             "anyone who needs the whole lab."),
            ("report.export", "Export reports",
             "Download reports as CSV, Excel or PDF, and lists such as samples, batches and users as "
             "Excel or PDF. Every export is recorded in the activity log."),
            ("report.print.own", "Print their own activity",
             "Print or download their own Person Activity report, for a week, a month or any dates. Without "
             "it they can still read it on screen. Printing anyone else's, and every other report, takes "
             "Export reports. Every print is recorded in the activity log."),
            ("report.performance", "See workload on the overview",
             "Show what each analyst holds on the Reports overview, and choose any person in Person Activity "
             "instead of only yourself. For planning the lab's work, not for ranking people. The workload "
             "reports are chosen below."),
            # One permission per report, from REPORTS below.
        ],
    ),
    (
        "administration",
        "Administration",
        [
            ("user.manage", "Manage users",
             "Create users, set their role and trained sections, deactivate them, reset passwords."),
            ("role.manage", "Manage roles and permissions",
             "Create roles and change which permissions each role holds."),
            ("audit.view", "View the audit trail",
             "Read the record of who did what. The trail can never be edited by anyone."),
            ("config.manage", "Manage lab details",
             "Set the company name, address, licence number and logo, the lab's sections, and the "
             "Received from list the front desk picks from. Does not change what a certificate contains."),
            ("product.manage", "Manage the product master",
             "Add products and change their details, with a reason. Products are never deleted: one no "
             "longer made is deactivated."),
            ("spec.manage", "Draft specifications",
             "Build new specification versions, writing each test in the draft. A draft does "
             "nothing until someone else makes it effective."),
            ("spec.approve", "Make specifications effective",
             "Approve a draft specification, which replaces the current version for samples registered "
             "afterwards. Never a draft they wrote themselves."),
            ("template.manage", "Manage certificate templates",
             "Set a certificate's title, footer and optional details per product. No template can leave "
             "out a test, a limit, a result or a signature."),
            ("notification.manage", "Manage notification rules",
             "Choose which alerts are sent, who receives them, and how early an overdue warning goes out."),
            ("workflow.manage", "Manage review workflows",
             "Create review workflows, set their stages and which role signs each one, and choose "
             "which products use them. Changes apply to samples registered afterwards."),
            ("admin.override", "Act in anyone's place",
             "Do any step of any sample in place of the person or role it belongs to: enter results, "
             "sign any stage (more than once on one certificate), decide retests and waive requirements. "
             "Every use is flagged in the activity log. Take this away to keep duties separated."),
        ],
    ),
]

# Each report is a permission of its own, so a role can open one report and no
# other. (report key, title, what it shows, its group on the Roles screen.) The
# titles are the reports' own; reports/test_report_permissions holds the two
# lists together. A report's history page of one sample, batch or product goes
# with the report it opens from.
REPORTS: list[tuple[str, str, str, str]] = [
    ("sample-register", "Sample Register",
     "Every registered sample: where it is, who holds it and how long it has taken. Also the Reports "
     "overview, whose figures open it, and the full history of one sample.", "Samples"),
    ("turnaround", "Turnaround Time",
     "Released samples: from receipt to release, step by step, against the due date.", "Samples"),
    ("test-results", "Test Results Register",
     "Every recorded result with the method, specification version and limit it was judged against.",
     "Tests and results"),
    ("oos", "OOS Investigations",
     "Every result outside its specification, with what followed it.", "Tests and results"),
    ("oot", "OOT Trends",
     "Numeric results over time, per product and test, with anything unusual against their own history.",
     "Tests and results"),
    ("retests", "Retest History",
     "Each repeat, retest and resample: why, who authorized it, what it found and how it ended.",
     "Tests and results"),
    ("batches", "Batch QC Summary",
     "Each batch of each product: samples, tests, failures and certificates, and the summary of one batch.",
     "Batches and products"),
    ("product-history", "Product Quality History",
     "Each product across its batches: pass rates, trends and recurring investigations.", "Batches and products"),
    ("certificates", "Certificates of Analysis",
     "Every certificate version, issued or superseded.", "Batches and products"),
    ("pending-work", "Pending Work",
     "Everything in the lab that is waiting, the queue it is in, and who it waits on.", "Workflow"),
    ("overdue", "Overdue Work", "Samples, investigations and actions past their due date.", "Workflow"),
    ("analyst-workload", "Analyst Workload",
     "What each analyst holds now, and what they finished in the period. For planning, not for ranking people.",
     "Workflow"),
    ("bottlenecks", "Workflow Bottlenecks",
     "How long work spends at each step, where it piles up, and what sends it back.", "Workflow"),
    ("tasks-by-person", "Tasks by Person",
     "How many tasks each person holds now, of each kind, and how many are late. For planning, not for "
     "ranking people.", "Workflow"),
    ("team-tasks", "Team Tasks",
     "Every open task: who holds it, what and where it is, who gave it to them, when, and when it is due.",
     "Workflow"),
    ("person-activity", "Person Activity",
     "One person's week or month: what was given to them, what they did and signed, and what they still hold. "
     "Everyone can open and print their own; choosing someone else needs “See workload on the overview”.",
     "Workflow"),
    ("audit-trail", "Audit Trail",
     "Who did what, when and from where, including every refused attempt.", "Quality and compliance"),
    ("document-control", "Document Control",
     "Specifications and workflows: what is in force, what is superseded, what used each.",
     "Quality and compliance"),
    ("deviations", "Deviations & CAPA",
     "The register of investigations and deviations, with their corrective and preventive actions.",
     "Quality and compliance"),
]


def report_permission(report_key: str) -> str:
    return f"report.open.{report_key}"


next(perms for key, _, perms in MODULES if key == "reports").extend(
    (report_permission(key), title, help_) for key, title, help_, _ in REPORTS
)

ALL_PERMISSIONS: dict[str, str] = {
    key: label for _, _, perms in MODULES for key, label, _ in perms
}

# Seeing a register comes with working on it: whoever manages instruments sees
# them. The Roles screen shows the see box ticked and fixed while one of these is.
INCLUDED_WITH: dict[str, tuple[str, ...]] = {
    "instrument.view": ("instrument.manage",),
    "material.view": ("material.manage",),
    "method.view": ("method.manage", "method.approve"),
    "qualification.view": ("qualification.manage",),
    "retained.view": ("custody.destroy",),
    "change.view": ("change.manage", "change.approve"),
}
LAB_REGISTER_VIEWS = tuple(INCLUDED_WITH)

# A permission that does nothing without another: a report stays shut without
# "Open reports". The Roles screen says so beside it.
NEEDS: dict[str, str] = {report_permission(key): "report.view" for key, *_ in REPORTS}
# Printing one's own activity needs the report it prints.
NEEDS["report.print.own"] = report_permission("person-activity")

# How the Roles screen groups the long lists: the reports, by what they are about.
GROUPS: dict[str, str] = {report_permission(key): group for key, _, _, group in REPORTS}

# Shown under a module's name on the Roles screen.
MODULE_NOTES: dict[str, str] = {
    "labrecords": "A role that sees none of these registers has no Lab records in its menu.",
    "reports": "A role opens only the reports ticked here, and only with “Open reports”.",
}


def effective(keys) -> set[str]:
    """What a role's grants let its people do: the grants, and what comes with them."""
    held = set(keys)
    return held | {key for key, by in INCLUDED_WITH.items() if held.intersection(by)}


# What the lab can switch off for everyone, administrators too (Settings → Features
# shown), to keep the app small until it is needed. Hiding is not a grant: it takes
# these out of everyone's permissions while they are hidden, and changes no record,
# no role and no rule. (key, name, what it is, the permission that is the whole of
# it or None, its parts as (permission, name, group).) A module with no permission
# of its own is hidden whole by hiding every part.
FEATURES: list[tuple[str, str, str, str | None, list[tuple[str, str, str]]]] = [
    ("reports", "Reports",
     "The Reports module. Hide it whole, or only the reports the lab does not use yet.",
     "report.view",
     [(report_permission(key), title, group) for key, title, _, group in REPORTS]),
    ("labrecords", "Lab records",
     "The registers behind every result. A hidden register keeps its records, and a result can still "
     "name an instrument or a lot that is in it.",
     None,
     [("instrument.view", "Instruments", ""), ("material.view", "Standards and reagents", ""),
      ("method.view", "Methods", ""), ("qualification.view", "Analyst qualifications", ""),
      ("retained.view", "Retained samples", ""), ("change.view", "Change control", "")]),
]
HIDEABLE: dict[str, str] = {
    **{whole: name for _, name, _, whole, _ in FEATURES if whole},
    **{key: label for *_, parts in FEATURES for key, label, _ in parts},
}

# Holding both of a pair on one role is legitimate in a small lab but must
# never be silent — the role screen flags it as a segregation-of-duties
# conflict. Review signatures are no longer permissions, so the conflicts
# that involve them come from the workflow stages a role signs (see
# lims.workflow.stage_conflicts). The runtime rule that every signature on
# one certificate comes from a different person holds for every role that
# does not hold admin.override.
SEGREGATION_CONFLICTS: list[tuple[str, str, str]] = [
    ("result.enter", "result.retest.authorize",
     "Can enter results and also authorize retests. Deciding a retest of their own work is refused "
     "without the administrator override, but these duties are normally kept apart."),
    ("result.enter", "stage.waive",
     "Can enter results and also waive stage requirements. Waiving a requirement of their own "
     "testing is refused without the administrator override, but these duties are normally kept apart."),
    ("admin.override", "role.manage",
     "Can do any lab work in anyone's place, sign every stage of one certificate alone, and also "
     "change who may do what. Every use is flagged in the activity log, but duties are not separated."),
]


def conflicts_in(permissions) -> list[dict]:
    held = set(permissions)
    return [
        {"a": a, "b": b, "message": msg}
        for a, b, msg in SEGREGATION_CONFLICTS
        if a in held and b in held
    ]


# Seeded on first migrate. Roles added later come with their own migration, as
# production's two did (accounts/0024), so a new database and an old one agree.
# The see-a-register and open-one-report permissions come the same way
# (accounts/0025): every role sees every register, and opens what "Open reports"
# opened before. These are ordinary rows — an administrator can
# change their permissions or add new roles beside them. They are marked
# is_system only so they cannot be deleted out from under existing users.
# The Checker and Lab head sign because the default workflow's stages name
# them (lims migration 0005), not because of anything listed here.
SYSTEM_ROLES: list[tuple[str, str, str, list[str]]] = [
    (
        "FRONT_DESK", "Sample custodian",
        "Receives samples, records what arrived, chooses the section and the analyst.",
        ["sample.register", "sample.view.all", "cert.print", "sample.assign", "sample.comment", "report.view",
         "batch.manage", "custody.record"],
    ),
    (
        "ANALYST", "Analyst",
        "Tests the samples assigned to them, enters the results and signs as “Analysed by”.",
        ["result.enter", "cert.sign.analysed", "sample.comment", "report.view", "custody.record"],
    ),
    (
        "CHECKER", "Checker (AM / DM)",
        "Reviews the analyst's work against the limits, then signs or sends it back.",
        ["sample.view.all", "sample.hold", "sample.comment", "report.view", "report.export",
         "report.performance", "investigation.manage", "spec.manage", "custody.record", "instrument.manage",
         "material.manage", "method.manage", "change.manage"],
    ),
    (
        "APPROVER", "Lab head (QCM / HOD)",
        "Verifies and approves the certificate, or rejects it with a reason. Approval releases it.",
        ["sample.view.all", "cert.print", "sample.assign", "sample.hold", "result.retest.authorize",
         "stage.waive", "sample.comment", "report.view", "report.export", "report.performance",
         "investigation.manage", "investigation.approve", "batch.manage", "spec.approve",
         "sample.cancel", "cert.withdraw", "audit.view", "batch.disposition", "batch.stage.record", "instrument.manage",
         "material.manage", "method.manage", "method.approve", "qualification.manage", "custody.record",
         "custody.destroy", "change.manage", "change.approve"],
    ),
    (
        "ADMIN", "System administrator",
        "Manages users, roles, permissions, workflows and the lab's details, and can do every step "
        "of the lab's work. Each time they act in someone's place it is flagged in the activity log.",
        sorted(ALL_PERMISSIONS),
    ),
]
