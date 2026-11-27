/** Permission keys. The backend registry is the source of truth. */
export type Permission =
  | "sample.register"
  | "sample.view.all"
  | "batch.view.all"
  | "batch.record.fill"
  | "batch.stage.assign"
  | "result.enter"
  | "cert.sign.analysed"
  | "cert.print"
  | "user.manage"
  | "role.manage"
  | "audit.view"
  | "config.manage"
  | "workflow.manage"
  | "sample.assign"
  | "sample.hold"
  | "result.retest.authorize"
  | "stage.waive"
  | "sample.comment"
  | "report.view"
  | "report.export"
  | "report.performance"
  | "investigation.manage"
  | "investigation.approve"
  | "admin.override"
  | "batch.manage"
  | "product.manage"
  | "spec.manage"
  | "spec.approve"
  | "template.manage"
  | "notification.manage"
  | "batch.disposition"
  | "instrument.manage"
  | "material.manage"
  | "method.manage"
  | "method.approve"
  | "qualification.manage"
  | "custody.record"
  | "custody.destroy"
  | "change.manage"
  | "change.approve"
  | LabRegisterView
  | `report.open.${ReportKey}`;

/** Seeing one Lab records register. Working on a register comes with seeing it. */
export type LabRegisterView =
  | "instrument.view"
  | "material.view"
  | "method.view"
  | "qualification.view"
  | "retained.view"
  | "change.view";

/** Each report, which is a permission of its own (report.open.<key>). */
export type ReportKey =
  | "sample-register"
  | "turnaround"
  | "test-results"
  | "oos"
  | "oot"
  | "retests"
  | "batches"
  | "product-history"
  | "certificates"
  | "pending-work"
  | "overdue"
  | "analyst-workload"
  | "bottlenecks"
  | "tasks-by-person"
  | "team-tasks"
  | "person-activity"
  | "audit-trail"
  | "document-control"
  | "deviations";

export interface RoleRef {
  id: number;
  code: string;
  name: string;
}

export interface User {
  id: number;
  username: string;
  name: string;
  designation: string;
  role: RoleRef | null;
  sections: string[];
  permissions: Permission[];
  /** Authenticated endpoint with a cache-buster; null when no photo is set. */
  photo_url: string | null;
  is_active: boolean;
  /** The password is temporary or expired, so nothing else works until it is changed. */
  must_change_password: boolean;
  /** Their role signs a review stage. Review signatures are not permissions. */
  is_reviewer: boolean;
}

export interface AdminUser extends User {
  /** An active account holding an active role. A lockout is separate and ends by itself. */
  can_sign_in: boolean;
  first_name: string;
  last_name: string;
  email: string;
  section_ids: number[];
  last_login: string | null;
  employee_id: string | null;
  joining_date: string | null;
  phone: string;
  /** Set only while a lockout after wrong passwords holds. */
  locked_until?: string | null;
}

/** One session in force: a person signed in on one computer. Its key is never sent. */
export interface SignInSession {
  id: string;
  user: { id: number; name: string; username: string; role: string; photo_url: string | null };
  signed_in_at: string | null;
  last_activity: string | null;
  state: "active" | "idle";
  signs_out_at: string | null;
  ip: string;
  device: string;
  /** The session this screen is open in. */
  current: boolean;
}

export interface SignInEvent {
  id: number;
  at: string;
  action: string;
  label: string;
  tone: string;
  person: string;
  by: string;
  ip: string;
}

export interface SignInBoard {
  idle_minutes: number;
  active_minutes: number;
  summary: { online: number; signed_in: number; allowed: number; blocked: number; locked: number };
  sessions: SignInSession[];
  recent: SignInEvent[];
}

/** A user's own record — adds what nobody could previously see about themselves. */
export interface Profile extends AdminUser {
  role_description: string;
  section_names: string[];
  permission_labels: { key: string; label: string }[];
  /** What they may do now, by area, in the order of the Roles screen. */
  permission_groups: {
    key: string;
    name: string;
    permissions: { key: string; label: string; help: string; group?: string }[];
  }[];
  /** The review stages their role signs, workflow by workflow. */
  review_stages: RoleStageRef[];
  date_joined: string;
}

export interface RoleStageRef {
  workflow: string;
  stage: string;
  title: string;
}

export interface Role {
  id: number;
  code: string;
  name: string;
  description: string;
  is_system: boolean;
  is_active: boolean;
  permissions: Permission[];
  conflicts: { a: string; b: string; message: string }[];
  user_count: number;
  review_stages: RoleStageRef[];
  created_at: string;
}

export interface PermissionDef {
  key: Permission;
  label: string;
  help: string;
  /** Held anyway while any of these is: seeing a register comes with working on it. */
  included_with?: Permission[];
  /** Does nothing without this one: a report needs "Open reports". */
  needs?: Permission;
  /** A heading the Roles screen groups a long list under. */
  group?: string;
}

export interface ConflictPair {
  a: string;
  b: string;
  message: string;
}

export interface PermissionModule {
  key: string;
  name: string;
  note?: string;
  permissions: PermissionDef[];
}

/** A part of the app the lab can switch off for everyone (Settings → Features shown). */
export interface FeatureModule {
  key: string;
  name: string;
  help: string;
  /** The permission that is the whole module, or null when it is hidden by hiding every part. */
  whole: Permission | null;
  parts: { key: Permission; label: string; group: string }[];
}

export interface LabFeatures {
  modules: FeatureModule[];
  hidden: Permission[];
}

export interface GrantHistoryRow {
  id: number;
  permission: string;
  label: string;
  granted_at: string;
  granted_by_name: string;
  revoked_at: string | null;
  revoked_by_name: string | null;
  reason: string;
}

/** The lab's letterhead. Presentation only — never certificate content. */
export interface LabDetails {
  lab_name: string;
  /** The line under the system name in the top bar and on sign-in. */
  app_tagline: string;
  company_name: string;
  address: string;
  licence_no: string;
  phone: string;
  email: string;
  website: string;
  footer_note: string;
  /** IANA name, such as Asia/Karachi: where "today" begins, and how every time is written. */
  time_zone: string;
  /** "12h" (02:05 PM) or "24h" (14:05): how a time of day is written. */
  time_format: "12h" | "24h";
  logo_url: string | null;
}

/** One page of any list: every list endpoint answers in this shape. */
export interface Page<T> {
  results: T[];
  count: number;
  page: number;
  page_size: number;
  pages: number;
}

export type PeriodKey = "today" | "week" | "lastweek" | "month" | "lastmonth" | "quarter" | "all";

/** How an event is shown: drives the icon and colour of its marker. */
export type Severity = "signature" | "refused" | "attention" | "admin" | "normal" | "quiet";

export interface AuditRow {
  id: number;
  at: string;
  actor: string;
  actor_name: string;
  action: string;
  entity: string;
  entity_id: string;
  details: Record<string, unknown>;
  ip_address: string;
  /** The event written as a sentence a person can read. */
  sentence: string;
  severity: Severity;
  notable: boolean;
  sample_no: string | null;
}

export interface AnalyticsData {
  period: string;
  label: string;
  from: string | null;
  to: string;
  pipeline: {
    by_status: Record<SampleStatus, number>;
    live: number;
    overdue: number;
  };
  throughput: {
    received: number;
    released: number;
    results_entered: number;
    prints: number;
  };
  quality: {
    failures: number;
    graded_results: number;
    oos_rate: number;
    corrections: number;
    sent_back: number;
  };
  turnaround: {
    samples: number;
    median_days: number | null;
    slowest_days: number | null;
  };
  activity: {
    events: number;
    signatures: number;
    refusals: number;
    daily: { date: string; count: number }[];
  };
  workload: { analyst: string; total: number; done: number }[];
  by_section: { code: string; name: string; count: number }[];
  attention: {
    id: number;
    at: string;
    actor_name: string;
    sentence: string;
    severity: Severity;
    sample_no: string | null;
  }[];
}

export interface LabTitles {
  lab_name: string;
  app_tagline: string;
  /** The lab's logo, beside its name in the top bar and on sign-in. Null shows the default mark. */
  logo_url?: string | null;
}

export interface DemoLogin {
  username: string;
  name: string;
  role: string;
}

export interface LabConfig extends LabTitles {
  time_zone?: string;
  time_format?: string;
  demo_logins?: DemoLogin[];
  demo_password?: string;
}

export interface Summary {
  by_status: Record<SampleStatus, number>;
  total: number;
  awaiting_me: number;
  overdue: number;
}

export interface Section {
  id: number;
  code: string;
  name: string;
}

export interface SectionRow extends Section {
  product_count: number;
  sample_count: number;
  user_count: number;
}

/** A name on the front desk's "Received from" list. */
export interface SampleSource {
  id: number;
  name: string;
  is_active: boolean;
}

export interface Product {
  id: number;
  code: string;
  name: string;
  section: string;
  current_spec_version: number | null;
  /** The review chain a sample registered now would be bound to. */
  workflow: WorkflowRef | null;
  dosage_form: string;
  strength: string;
  storage_condition: string;
  /** The stages a sample of a new batch can be registered for. A known batch has its own. */
  qc_stages: QcStageOption[];
}

/** One review signature after the analyst's. */
export interface WorkflowStage {
  order: number;
  code: string;
  /** The step's label, e.g. "Checked". */
  name: string;
  /** e.g. "Checked by". */
  signature_title: string;
  /** e.g. "AM / DM" — may be blank. */
  holder_title: string;
  /** holder_title, or the role's name when there is none. */
  holder: string;
  role_id: number;
  role_name: string;
  /** Must someone take the stage (or accept it) before signing? */
  requires_acceptance?: boolean;
}

/** A workflow as one version of it — what a sample is bound to. */
export interface WorkflowRef {
  id: number;
  name: string;
  version: number;
  stages: WorkflowStage[];
  /** How many checks the front desk makes on arrival, before testing can start. */
  receipt_checks: number;
}

export interface WorkflowAdmin {
  id: number;
  name: string;
  description: string;
  is_default: boolean;
  version: number | null;
  changed_at: string;
  receipt: ReceiptConfig;
  testing: StepConfig;
  certificate: CertificateConfig;
  stages: WorkflowAdminStage[];
  warnings: string[];
  sample_count: number;
  in_review_count: number;
}

export interface WorkflowProduct {
  id: number;
  code: string;
  name: string;
  section: string;
  workflow_id: number | null;
}

export interface WorkflowRole {
  id: number;
  name: string;
  code: string;
  user_count: number;
}

export interface WorkflowsResponse {
  workflows: WorkflowAdmin[];
  products: WorkflowProduct[];
  roles: WorkflowRole[];
  max_stages: number;
  file_types: string[];
  max_upload_mb: number;
}

export interface WorkflowVersionRow {
  version: number;
  created_at: string;
  created_by_name: string;
  reason: string;
  sample_count: number;
  receipt: ReceiptConfig;
  testing: StepConfig;
  certificate: CertificateConfig;
  stages: WorkflowAdminStage[];
}

export type LimitType =
  | "NUMERIC_RANGE"
  | "NUMERIC_MIN"
  | "NUMERIC_MAX"
  | "TEXT_COMPLIES"
  | "REPORT_ONLY";

export interface TestDefinition {
  id: number;
  order: number;
  name: string;
  method: string;
  /** The method in the method master, where the test names one. */
  method_record: number | null;
  unit: string;
  limit_type: LimitType;
  min_value: string | null;
  max_value: string | null;
  decimals: number;
  text_expected: string;
  limit_text: string;
}

export type Outcome = "PASS" | "FAIL" | "REPORTED";

export interface TestResult {
  id: number;
  test_definition_id: number;
  test_name: string;
  limit_text: string;
  unit: string;
  value_numeric: string | null;
  reported: string;
  value_text: string;
  outcome: Outcome;
  entered_by_name: string;
  entered_at: string;
  is_superseded: boolean;
  superseded_at: string | null;
  superseded_by_name: string | null;
  supersede_reason: string;
  raw_data: RawData | null;
}

export type SampleStatus = "RECEIVED" | "IN_TESTING" | "IN_REVIEW" | "APPROVED" | "REJECTED" | "CANCELLED";

export interface SampleListItem {
  id: number;
  sample_no: string;
  assigned_analyst_id: number;
  product_name: string;
  product_code: string;
  section_code: string;
  batch_id: number | null;
  /** The official number. Blank for a sample that is not from a batch. */
  batch_no: string;
  /** The official number, or what a sample with no batch is. */
  batch_label: string;
  reference: string;
  due_date: string;
  status: SampleStatus;
  /** e.g. "Awaiting AM / DM" — names who the sample is waiting for. */
  status_label: string;
  /** While IN_REVIEW: which review stage (1-based) it waits at. */
  review_stage_order: number | null;
  /** Waiting at a stage the current user's role signs. */
  my_turn: boolean;
  /** my_turn, or an administrator able to step in. */
  can_sign: boolean;
  analyst_name: string;
  received_at: string;
  has_failures: boolean;
  /** How far along: the steps it has and how many are behind it. Null for a rejected or cancelled sample. */
  journey: { done: number; total: number } | null;
}

export interface WorkflowEvent {
  id: number;
  at: string;
  actor_name: string;
  /** As recorded — history keeps statuses from earlier releases too. */
  from_status: string;
  to_status: string;
  comment: string;
}

export interface CertificateRef {
  id: number;
  version: number;
  status: CertStatus;
  created_at: string;
}

export interface SampleDetail extends SampleListItem {
  /** The batch's QC stage it was taken for; empty when none. */
  qc_stage_name: string;
  qc_stage_id: number | null;
  quantity: string;
  received_from: string;
  registered_by_name: string;
  manufacturing_date: string | null;
  expiry_date: string | null;
  past_expiry_reason: string;
  investigations: {
    id: number;
    reference: string;
    kind: string;
    status: string;
    status_label: string;
    test_name: string;
    conclusion: string;
  }[];
  closed_reason: string;
  closed_at: string | null;
  closed_by_name: string | null;
  storage_condition: string;
  batch_internal_id: string;
  manufacturing_site: string;
  specification: {
    id: number;
    version: number;
    status: string;
    effective_date: string;
    /** Set when these are one QC stage's own tests. */
    stage_name: string;
    /** "Specification, version 3", or "Final grain tests, version 1". */
    label: string;
    tests: TestDefinition[];
  };
  results: TestResult[];
  events: WorkflowEvent[];
  certificates: CertificateRef[];
  /** The version bound at registration — never the workflow as edited since. */
  workflow: WorkflowRef;
}

export type CertStatus = "IN_REVIEW" | "APPROVED" | "SUPERSEDED" | "WITHDRAWN";

export interface Signature {
  /** "ANALYSED", or the code of the review stage signed. */
  meaning: string;
  name_snapshot: string;
  signed_at: string;
}

/** One signature the certificate needs, signed or not yet. */
export interface ChainRow {
  code: string;
  title: string;
  holder: string;
  name_snapshot: string | null;
  signed_at: string | null;
}

export interface PrintEvent {
  copy_number: number;
  printed_by_name: string;
  printed_at: string;
  /** The viewer printed it recently and its window closed before it loaded. */
  can_open: boolean;
}

export interface CertContentTest {
  name: string;
  method: string;
  unit: string;
  limit_text: string;
  value: string;
  outcome: Outcome;
  /** The reported value is an authorized retest (only where the workflow prints them). */
  retested?: boolean;
}

export interface CertContentRetest {
  test: string;
  unit: string;
  original_value: string;
  original_entered_at: string;
  reason: string;
  requested_by: string;
  authorized_by: string;
  authorized_at: string;
  retest_value: string;
  retest_outcome: Outcome;
  retest_entered_at: string;
}

export interface CertContent {
  sample_no: string;
  certificate_version: number;
  product_name: string;
  product_code: string;
  section: string;
  batch_no: string;
  quantity: string;
  received_from: string;
  received_at: string;
  due_date: string;
  spec_version: number;
  /** An in-process sample's QC stage, and the stage whose own tests it was tested on. */
  qc_stage?: string;
  spec_of_stage?: string;
  /** Absent on certificates signed before these fields existed. */
  dosage_form?: string;
  strength?: string;
  reference?: string;
  internal_batch_id?: string;
  manufacturing_site?: string;
  manufacturing_date?: string;
  expiry_date?: string;
  storage_condition?: string;
  tests: CertContentTest[];
  /** Present only where the sample's workflow prints retests, and there were some. */
  retests?: CertContentRetest[];
  history_for_review?: CertContentRetest[];
  investigations?: { reference: string; kind: string; conclusion: string; closed_at: string }[];
  past_expiry?: string;
  overall: string;
}

export interface Certificate {
  withdrawn_at: string | null;
  withdrawn_reason: string;
  withdrawn_by_name: string | null;
  can_withdraw: boolean;
  id: number;
  sample_id: number;
  version: number;
  status: CertStatus;
  content: CertContent;
  content_hash: string;
  verification_uuid: string;
  created_at: string;
  superseded_reason: string;
  signatures: Signature[];
  prints: PrintEvent[];
  workflow_name: string;
  stages: WorkflowStage[];
  chain: ChainRow[];
  awaiting_stage: WorkflowStage | null;
  /** The current user may sign or send back the stage it waits at. */
  my_turn: boolean;
  /** my_turn, or an administrator able to step in. */
  can_sign: boolean;
}

/* ============================================================
   Lab execution — what happens inside each step
   ============================================================ */

export type ResponseType =
  | "CHECKBOX"
  | "YES_NO"
  | "PASS_FAIL"
  | "NUMBER"
  | "TEXT"
  | "DATE"
  | "CHOICE"
  | "FILE";

/** One checklist item as the workflow editor sends and receives it. */
export interface ChecklistConfig {
  id?: number;
  order?: number;
  label: string;
  help_text: string;
  response_type: ResponseType;
  required: boolean;
  waivable: boolean;
  /** YES / NO for a yes-no item, one of the options for a list; blank = any. */
  expected: string;
  unit: string;
  min_value: string | null;
  max_value: string | null;
  decimals: number | null;
  options: string[];
  file_types: string[];
  max_size_mb: number;
}

export interface StepConfig {
  requires_acceptance: boolean;
  checklist: ChecklistConfig[];
}

/** The front desk's checks when a sample arrives. */
export interface ReceiptConfig {
  checklist: ChecklistConfig[];
}

/** What the certificate carries besides the results. */
export interface CertificateConfig {
  show_retests: boolean;
}

export type WorkflowAdminStage = WorkflowStage & { checklist: ChecklistConfig[] };

export interface PersonRef {
  id: number;
  name: string;
}

export interface ChecklistItemView extends ChecklistConfig {
  id: number;
  order: number;
  /** What a conforming answer is, in words — "Pass", "15 – 25 °C"… */
  requirement: string;
}

export interface ChecklistAnswer {
  id: number;
  attempt: number;
  value: string;
  display: string;
  attachment_id: number | null;
  conforms: boolean;
  answered_by: PersonRef;
  answered_at: string;
  replaced_at: string | null;
  replaced_by: PersonRef | null;
  change_reason: string;
}

export interface ChecklistRow {
  item: ChecklistItemView;
  response: ChecklistAnswer | null;
  history: ChecklistAnswer[];
  waiver: { reason: string; by: PersonRef; at: string } | null;
}

export interface AttachmentView {
  id: number;
  step: string;
  attempt: number;
  item_id: number | null;
  version: number;
  name: string;
  extension: string;
  content_type: string;
  size: number;
  sha256: string;
  note: string;
  uploaded_by: PersonRef;
  uploaded_at: string;
  is_current: boolean;
  replaces_id: number | null;
  withdrawn_at: string | null;
  withdrawn_by: PersonRef | null;
  withdraw_reason: string;
  url: string;
  inline: boolean;
}

export interface CommentView {
  id: number;
  step: string;
  attempt: number;
  kind: "NOTE" | "FEEDBACK";
  /** The latest wording; earlier versions are in `versions`. */
  body: string;
  author: PersonRef;
  created_at: string;
  latest_id: number;
  amended_at: string | null;
  versions: { id: number; body: string; at: string }[];
  replies: CommentView[];
}

export type AssignmentStatus = "PENDING" | "ACCEPTED" | "REJECTED" | "CANCELLED";

export interface AssignmentView {
  id: number;
  step: string;
  kind: "ASSIGNED" | "HANDOVER" | "CLAIMED";
  kind_label: string;
  status: AssignmentStatus;
  status_label: string;
  from_user: PersonRef | null;
  to_user: PersonRef;
  created_by: PersonRef;
  created_at: string;
  note: string;
  responded_by: PersonRef | null;
  responded_at: string | null;
  response_reason: string;
}

export interface Blocker {
  code: string;
  message: string;
  item_id: number | null;
  waivable: boolean;
}

export type StepStatus =
  | "NOT_STARTED"
  | "WAITING"
  | "COMPLETED"
  | "AWAITING_ACCEPTANCE"
  | "DECLINED"
  | "IN_PROGRESS"
  | "REOPENED"
  | "FAILED"
  | "ON_HOLD"
  | "SUBMITTED"
  | "PASSED"
  | "RETURNED";

export interface StepDecision {
  attempt: number;
  outcome: "SUBMITTED" | "PASSED" | "RETURNED" | "COMPLETED";
  by: PersonRef | null;
  at: string | null;
  reason: string;
}

export interface StepView {
  key: string;
  name: string;
  order: number;
  kind: "receipt" | "testing" | "review";
  role_name: string;
  holder_title: string;
  requires_acceptance: boolean;
  is_current: boolean;
  status: StepStatus;
  status_label: string;
  holder: PersonRef | null;
  pending: AssignmentView | null;
  assignments: AssignmentView[];
  checklist: ChecklistRow[];
  attachments: AttachmentView[];
  comments: CommentView[];
  decisions: StepDecision[];
  /** Why the viewer cannot work on this step right now. */
  work_blockers: Blocker[];
  /** What stops the step being signed, whoever signs it. */
  blockers: Blocker[];
  /** What would stop the viewer here, were they not acting on the administrator override. */
  overridden: string[];
  can: {
    work: boolean;
    accept: boolean;
    cancel: boolean;
    take: boolean;
    hand_over: boolean;
    assign: boolean;
    waive: boolean;
    /** Only receipt checks finish here; other steps end with a signature. */
    complete: boolean;
  };
}

export interface HoldView {
  id: number;
  step: string;
  reason: string;
  placed_by: PersonRef;
  placed_at: string;
  released_by: PersonRef | null;
  released_at: string | null;
  release_comment: string;
}

export type RetestStatus = "PENDING" | "AUTHORIZED" | "DECLINED" | "USED";

/** What each one means is the lab's procedure. The record only keeps them apart. */
export type RetestKind = "RETEST" | "REPEAT" | "RESAMPLE";

export interface RetestView {
  id: number;
  sample_id: number;
  test_definition_id: number;
  test_name: string;
  failed_value: string;
  failed_entered_by: PersonRef;
  failed_entered_at: string;
  kind: RetestKind;
  kind_label: string;
  reason: string;
  requested_by: PersonRef;
  requested_at: string;
  status: RetestStatus;
  status_label: string;
  decided_by: PersonRef | null;
  decided_at: string | null;
  decision_comment: string;
  retest_value: string | null;
  retest_outcome: Outcome | null;
  used_at: string | null;
}

export interface Execution {
  sample_id: number;
  /** The certificate version the current work is for. */
  attempt: number;
  current_step: string | null;
  hold: HoldView | null;
  holds: HoldView[];
  can_hold: boolean;
  can_reject: boolean;
  can_cancel: boolean;
  can_authorize_retests: boolean;
  can_comment: boolean;
  steps: StepView[];
  general_comments: CommentView[];
  retests: RetestView[];
  file_types: string[];
  max_upload_mb: number;
}

export interface Candidate extends PersonRef {
  role: string;
  is_me: boolean;
}

export interface TaskSampleRef {
  id: number;
  sample_no: string;
  product_name: string;
  product_code: string;
  batch_no: string;
  batch_label: string;
  due_date: string;
  status: SampleStatus;
  status_label: string;
  overdue: boolean;
}

export interface TaskRow {
  sample: TaskSampleRef;
  step: string;
  step_name: string;
  assignment?: AssignmentView;
  attempt?: number;
  status?: StepStatus;
  blockers?: string[];
  returned?: { from_step: string; by: PersonRef | null; at: string | null; reason: string } | null;
  needs_taking?: boolean;
  retest?: RetestView;
  hold?: HoldView;
}

export type TaskBucket =
  | "receipts"
  | "to_accept"
  | "returned"
  | "my_testing"
  | "to_review"
  | "retests_to_decide"
  | "needs_reassigning"
  | "upcoming"
  | "sent"
  | "my_retests"
  | "on_hold"
  | "overdue";

export type Tasks = Record<TaskBucket, TaskRow[]> & {
  counts: Record<TaskBucket, number>;
  actionable: number;
  generated_at: string;
  /** Batch-record stages assigned to this person that still need them. */
  batch_stages: BatchStageTask[];
};

/** A recorded stage of a batch assigned to the person looking: to fill, to sign, or waiting. */
export interface BatchStageTask {
  batch: { id: number; official_batch_no: string; internal_id: string; product: string };
  stage: { id: number; order: number; name: string };
  /** "fill": values still to write; "sign": all written, their column to sign; "waiting": earlier stages first. */
  state: "fill" | "sign" | "waiting";
  missing: number;
  waiting_for: string[];
  /** The column they sign, e.g. "Done by". */
  column: string;
  assigned_by: PersonRef | null;
  assigned_at: string;
  note: string;
}

/** Who fills a recorded stage of a batch and signs its first column. */
export interface StageAssignment {
  /** Nobody named: anyone who may fill batch records can. */
  holder: PersonRef | null;
  by: PersonRef | null;
  at: string | null;
  note: string;
  /** Newest first; a row with no holder took the stage away from everyone. */
  history: { holder: PersonRef | null; by: PersonRef; at: string; note: string }[];
  /** The batch works by assignment (one of its stages is assigned): unassigned, this one waits for a name. */
  required: boolean;
  /** The person looking may assign it now. */
  can_assign: boolean;
  /** Who it can go to: those whose role signs its first column. Only for whoever may assign it. */
  people: { id: number; name: string; role: string }[];
}

/* ============================================================
   Notifications
   ============================================================ */

export interface NotificationItem {
  id: number;
  kind: string;
  title: string;
  body: string;
  /** Where in the app it leads, e.g. /samples/12/review. */
  link: string;
  sample_id: number | null;
  actor: PersonRef | null;
  created_at: string;
  read_at: string | null;
}

export interface NotificationsResponse {
  unread: number;
  items: NotificationItem[];
  server_time: string;
}

/* ============================================================
   The product master and batches
   ============================================================ */

export interface ProductMasterRow {
  id: number;
  code: string;
  name: string;
  generic_name: string;
  section_id: number;
  section: string;
  section_name: string;
  sample_type: string;
  sample_type_label: string;
  dosage_form: string;
  strength: string;
  pack_size: string;
  storage_condition: string;
  shelf_life_months: number | null;
  is_active: boolean;
  certificate_template_id: number | null;
  current_spec_version: number | null;
  /** How many QC stages a batch created now goes through; 0 when none are set up. */
  qc_stage_count: number;
  sample_count: number | null;
  batch_count: number | null;
}

export interface BatchRow {
  id: number;
  /** The system's own reference. */
  internal_id: string;
  /** Exactly as the manufacturer assigned it. */
  official_batch_no: string;
  product: { id: number; code: string; name: string; dosage_form: string; strength: string; section: string };
  manufacturing_site: string;
  manufacturing_date: string | null;
  expiry_date: string | null;
  batch_size: string;
  notes: string;
  created_by: string | null;
  created_at: string;
  sample_count: number | null;
  /** Sent by the front desk's lookup: the stages a sample of this batch can be registered for. */
  stage_options?: QcStageOption[];
  /** In the list only: where the batch's required QC stages stand. Null when it has none. */
  qc_progress?: { passed: number; required: number; failed: boolean } | null;
  /**
   * In the list only: the version of its product's QC stages the batch goes through, and the
   * product's newest. Null for a batch created before its product had any.
   */
  stage_plan?: { version: number; latest: number } | null;
}

export interface BatchDocumentView {
  id: number;
  doc_type: string;
  doc_type_label: string;
  title: string;
  version: number;
  name: string;
  extension: string;
  size: number;
  sha256: string;
  note: string;
  uploaded_by: PersonRef;
  uploaded_at: string;
  is_current: boolean;
  replaces_id: number | null;
  withdrawn_at: string | null;
  withdrawn_by: PersonRef | null;
  withdraw_reason: string;
  url: string;
}

export interface BatchDetail extends BatchRow {
  samples: SampleListItem[];
  results: {
    id: number;
    sample_id: number;
    sample_no: string;
    test: string;
    unit: string;
    limit_text: string;
    value: string;
    outcome: Outcome;
    entered_by: string;
    entered_at: string;
  }[];
  certificates: {
    id: number;
    sample_id: number;
    sample_no: string;
    version: number;
    status: CertStatus;
    status_label: string;
    overall: string;
    created_at: string;
  }[];
  documents: BatchDocumentView[];
  document_types: { key: string; label: string }[];
  history: { id: number; at: string; actor_name: string; sentence: string; severity: string }[];
  can_manage: boolean;
  /** Null for a batch created before its product had QC stages. */
  qc_stages: BatchStagesView | null;
  disposition: BatchDispositionView;
}

export type StageKind = "TESTED" | "RECORDED";
export type StageStatus = "NOT_STARTED" | "IN_PROGRESS" | "PASSED" | "FAILED" | "NOT_APPLICABLE";

/** One QC stage as defined on the product. */
export interface QcStageDef {
  id: number;
  order: number;
  name: string;
  description: string;
  kind: StageKind;
  kind_label: string;
  /** A batch is released only when every required stage has passed. */
  required: boolean;
  /** Nothing is done for it until every earlier required stage has passed or does not apply. */
  after_previous: boolean;
}

/** A stage as the product's stages editor shows it. */
export interface QcStagePlanStage extends QcStageDef {
  /** Which tests its samples get; kept when the stage is renamed. */
  key: string;
  /** A lab-tested stage's own tests: the version in force, and whether one is being drafted. */
  own_tests: { version: number | null; draft: boolean } | null;
  /** A recorded stage's steps, and its sign-off columns in the order they are signed. */
  steps: QcStepDef[];
  signoffs: QcSignoffDef[];
  /** Signed under every step, as the paper record has it, rather than once for the stage. */
  sign_each_step: boolean;
  /** A lab-tested stage: the tests its samples get now, its own or the product's. */
  tests: SpecSummary | null;
}

/** A specification in force, as a stage shows it. */
export interface SpecSummary {
  id: number;
  /** "Specification, version 3", or "Final grain tests, version 1". */
  label: string;
  version: number;
  /** A stage's own tests, rather than the product's specification. */
  own: boolean;
  tests: { name: string; method: string; limit_text: string }[];
}

export type CheckpointKind =
  | "NUMBER" | "PERCENT" | "TIME_RANGE" | "TIME" | "DATE" | "TEXT" | "YES_NO" | "CHOICE" | "FILE";

/** One option of a choice, and whether it is an acceptable answer. */
export interface ChoiceOption {
  label: string;
  ok: boolean;
}

/** A kind of value the lab defines once and offers in every stage: Temperature, Equipment ID… */
export interface CheckpointPreset {
  id: number;
  name: string;
  kind: CheckpointKind;
  kind_label: string;
  unit: string;
  min_value: string | null;
  max_value: string | null;
  decimals: number;
  choices: ChoiceOption[];
  is_active: boolean;
}

/**
 * A kind of value the products' current stages already ask for: the check points
 * that share a kind, unit, limits and options, with their names and where they are.
 */
export interface CheckpointInUse {
  kind: CheckpointKind;
  kind_label: string;
  /** The lab's kinds they were made from, if any. */
  kind_names: string[];
  unit: string;
  min_value: string | null;
  max_value: string | null;
  decimals: number;
  choices: ChoiceOption[];
  /** Each distinct check point name, in stage order. */
  labels: string[];
  /** How many check points share this kind of value. */
  uses: number;
  used_in: { product_id: number; product: string; stage: string }[];
}

/** One value a step asks for: a weight in kg, LOD as a percentage between limits, a start and end time. */
export interface QcCheckpointDef {
  id: number;
  order: number;
  label: string;
  kind: CheckpointKind;
  kind_label: string;
  unit: string;
  decimals: number;
  required: boolean;
  /** "3.00 – 4.50 %", "NMT 4.50 %", "Acceptable: Complies", or empty. */
  limit_text: string;
  min_value: string | null;
  max_value: string | null;
  /** A choice's options. */
  choices: ChoiceOption[];
  /** The lab's own name for the kind, such as Temperature; empty for a built-in kind. */
  kind_name: string;
}

/** One step of a recorded stage, as the batch record prints it. */
export interface QcStepDef {
  id: number;
  order: number;
  title: string;
  instructions: string;
  checkpoints: QcCheckpointDef[];
}

/** One sign-off column of a recorded stage: "Done by (Operator)", signed by whoever holds its role. */
export interface QcSignoffDef {
  id: number;
  order: number;
  title: string;
  holder: string;
  role_id: number;
  role: string;
}

/** A value written on a batch's record. The latest counts; the ones before it stay. */
/** A photo or file on a batch record: where to fetch it, and whether it shows as a picture. */
export interface RecordFile {
  url: string;
  name: string;
  type: string;
  size: number;
  image: boolean;
}

export interface RecordEntry {
  id: number;
  number: string | null;
  text: string;
  date: string | null;
  start: string | null;
  end: string | null;
  yes_no: boolean | null;
  /** As the record shows it: "17.887 kg", "17-Nov-2026 10:10 AM – 17-Nov-2026 10:30 AM". */
  shown: string;
  /** The photo or file kept on the record, for a check point of that kind. */
  file: RecordFile | null;
  out_of_limit: boolean;
  reason: string;
  correction: string;
  entered_by: PersonRef;
  entered_at: string;
}

/** A sign-off column on a batch's record, with its signature once signed. */
export type RecordColumn = QcSignoffDef & {
  signature: { by: PersonRef; at: string; comment: string; acknowledged: boolean } | null;
  /** Why the person looking cannot sign it now; empty when they can. */
  blocked: string;
  /** The last column: it acknowledges the values out of limit it covers. */
  acknowledges: boolean;
};

/** A value out of limit, with why. */
export interface RecordFlag { label: string; shown: string; limit: string; reason: string }

/**
 * One recorded stage of one batch: its steps with their values, and its sign-off
 * columns: once for the stage, or under every step when it is signed at every step.
 */
export interface BatchStageRecord {
  /** Signed under every step: each step has its own columns, and the stage's own list is empty. */
  per_step: boolean;
  steps: (Omit<QcStepDef, "checkpoints"> & {
    checkpoints: (QcCheckpointDef & { entry: RecordEntry | null; history: RecordEntry[] })[];
    /** This step's columns, signed at every step; empty otherwise. */
    signoffs: RecordColumn[];
    /** Signed at every step: its first column is signed, so its values are final. */
    locked: boolean;
    missing: string[];
    out_of_limit: RecordFlag[];
  })[];
  signoffs: RecordColumn[];
  /** A column is signed, so the values are final (signed at every step: some step is). */
  locked: boolean;
  can_fill: boolean;
  fill_blocked: string;
  missing: string[];
  out_of_limit: RecordFlag[];
}

export interface QcStagePlanView {
  id: number;
  version: number;
  reason: string;
  created_by: string;
  created_at: string;
  stages: QcStagePlanStage[];
}

/** One version of a product's stages as it was saved, and what it changed from the one before. */
export interface QcStageVersionView extends QcStagePlanView {
  changes: string[];
  batch_count: number;
  is_current: boolean;
}

export interface ProductStagesResponse {
  current: QcStagePlanView | null;
  versions: { version: number; reason: string; created_by: string; created_at: string; stage_count: number; batch_count: number }[];
  kinds: { value: StageKind; label: string }[];
  checkpoint_kinds: { value: CheckpointKind; label: string }[];
  /** The lab's own kinds of value, offered beside the built-in ones. */
  checkpoint_presets: CheckpointPreset[];
  /** Who can sign a sign-off column. */
  roles: { id: number; name: string }[];
  /** The product's own specification, shown with the stages that use it. */
  product_spec: SpecSummary | null;
  /** May draft or approve specifications. */
  can_spec: boolean;
  can_manage: boolean;
}

/** The stages of one batch, bound when it was created, and where each stands. */
export interface BatchStagesView {
  /** The version of the product's stages; null when the batch has only stages added to it. */
  version: number | null;
  /** Required stages that apply to this batch. */
  required: number;
  passed: number;
  /** May record stages, mark them not applicable and add stages (QA), while the batch is open. */
  can_record: boolean;
  /** May register a sample for a stage at the front desk. */
  can_register: boolean;
  kinds: { value: StageKind; label: string }[];
  /** The tests a stage added to this batch can give its samples; "" is the product's specification. */
  tracks: { key: string; name: string }[];
  stages: (QcStageDef & {
    /** The earlier required stages it still waits for, as "1. Line clearance". */
    waiting_for: string[];
    /** Which tests its samples get, e.g. "Final grain tests, version 1". Empty for a QA-recorded stage. */
    tests: string;
    /** Added to this batch alone by QA, with a reason. */
    added_to_batch: boolean;
    added_by: PersonRef | null;
    added_reason: string;
    added_at: string | null;
    /** QA's word that it does not apply to this batch, or applies again; newest first. */
    applicability: { id: number; applies: boolean; reason: string; recorded_by: PersonRef; recorded_at: string }[];
    /** Filled and signed on the batch record; null for a stage tested in the lab or recorded passed / failed. */
    record: BatchStageRecord | null;
    /** A batch-record stage's assignee and who may change it; null for other stages. */
    assignment: StageAssignment | null;
    status: StageStatus;
    status_label: string;
    samples: { id: number; sample_no: string; status_label: string }[];
    /** Samples of this stage the person looking may not see. They still count. */
    hidden_samples: number;
    records: { id: number; decision: "PASSED" | "FAILED"; label: string; remarks: string; recorded_by: PersonRef; recorded_at: string }[];
  })[];
}

/** A stage a sample can be registered for. */
export interface QcStageOption {
  id: number;
  order: number;
  name: string;
  added_to_batch?: boolean;
  /** The earlier stages it still waits for; a sample cannot be registered for it until they pass. */
  waiting_for?: string[];
  /** Which tests its samples get, e.g. "Final grain tests, version 1". */
  tests?: string;
}

/** The latest decision is the batch's status. No decision reads "Not decided". */
export interface BatchDispositionView {
  decision: "" | "RELEASED" | "REJECTED" | "QUARANTINED";
  label: string;
  history: {
    id: number;
    decision: string;
    label: string;
    reason: string;
    decided_by: PersonRef;
    decided_at: string;
    hash: string;
  }[];
  choices: { value: string; label: string }[];
  can_decide: boolean;
  /** Holds the permission, but tested a sample of this batch. */
  tested_it: boolean;
  /** Why it cannot be released, for whoever decides. */
  release_problems: string[];
}

/* ============================================================
   Reports — the server says what each report holds; the screens draw it
   ============================================================ */

/** What the server wrote, dates included. Never reformatted on screen. */
export type ReportCellValue = string | { text: string; to?: string; tone?: string; sub?: string };

export type ReportRow = Record<string, ReportCellValue>;

export interface ReportColumn {
  key: string;
  label: string;
  sortable: boolean;
  numeric: boolean;
  /** Free text: wraps, where every other column keeps to one line. */
  wrap: boolean;
}

export interface ReportFilter {
  key: string;
  label: string;
  kind: "select" | "text" | "toggle";
  options: { value: string; label: string }[];
  /** What choosing nothing means, when it is not "All": a report about one person says "Me". */
  blank?: string;
}

export interface ReportDefinition {
  key: string;
  title: string;
  category: string;
  description: string;
  note: string;
  columns: ReportColumn[];
  filters: ReportFilter[];
  dates: { key: string; label: string }[];
  has_dates: boolean;
  default_period: PeriodKey;
  default_sort: string;
  can_export: boolean;
  action: { label: string; to: string } | null;
}

export interface ReportStamp {
  generated_at: string;
  generated_by: string;
  timezone: string;
  /** Limited to the samples this person can see. */
  partial?: boolean;
}

export interface ReportExtra extends ReportStamp {
  summary: { label: string; value: string | number; sub?: string; alert?: boolean }[];
  period: string;
  /** Whom a report about one person is about. */
  subject?: string;
}

export interface ReportCatalogue {
  categories: {
    key: string;
    title: string;
    question: string;
    reports: { key: string; title: string; description: string; to: string }[];
  }[];
}

export interface ReportTile {
  key: string;
  label: string;
  value: number | string;
  /** Left out when it would lead into a report this person cannot open. */
  to?: string;
  sub?: string;
  alert?: boolean;
}

export interface ReportTimeline {
  unit: "day" | "week" | "month";
  series: string[];
  points: { date: string; values: number[] }[];
}

export interface ReportDashboard extends ReportStamp {
  label: string;
  scope: string;
  now: ReportTile[];
  period: ReportTile[];
  failures: { tests: number; samples: number; batches: number; rejected_batches: number; to?: string };
  charts: {
    flow: ReportTimeline;
    outcomes: ReportTimeline;
    status: { label: string; value: number; to?: string }[];
    sections: { label: string; value: number; to?: string }[];
    analysts?: { label: string; pending: number; overdue: number; to?: string }[];
    /** Passed against failed, over the results entered in the period. */
    results: { passed: number; failed: number; reported?: number; to_passed?: string; to_failed?: string; to_reported?: string };
    /** Samples received in the period, by the kind of material. */
    sample_types?: { key: string; label: string; value: number; to?: string }[];
    /** Investigations and deviations opened in the period, by kind. */
    investigation_kinds?: { key: string; label: string; value: number; to?: string }[];
    /** Samples still in the lab, by how near their due date is. */
    due: { key: string; label: string; value: number; to?: string }[];
    /** Quality events now, and those closed in the period. */
    investigations: { key: string; label: string; value: number; to?: string }[];
    /** Batches registered in the period, by the quality unit's decision. Absent for someone who sees no batches. */
    batches?: { key: string; label: string; value: number }[];
  };
  insights: DashboardInsights;
}

/** How a figure moved against the period before. `good` says which way is better, if either is. */
export interface InsightDelta { change: number; percent: number | null; good: "up" | "down" | null }

export interface InsightTile {
  key: string;
  label: string;
  value: number | null;
  display: string;
  sub: string;
  to: string;
  /** One value per day, week or month of the period. A gap is a stretch with nothing to average. */
  spark: (number | null)[] | null;
  delta: InsightDelta | null;
  alert?: boolean;
}

export interface FailureRow { label: string; failed: number; total: number; rate: number; to: string }
export interface EquipmentGroup { title: string; to: string; rows: { key: string; label: string; value: number }[] }

/** The dashboard's deeper views. Every figure opens the records it counts. */
export interface DashboardInsights {
  compare: string | null;
  tiles: InsightTile[];
  turnaround: { bands: { label: string; value: number }[]; mean: number | null; on_time: number; late: number; to: string };
  outlook: {
    overdue: { value: number; to: string };
    days: { date: string; value: number; to: string }[];
    later: { value: number; to: string };
  };
  ageing: {
    bands: { key: string; label: string }[];
    stages: { key: string; label: string; values: number[]; links: string[] }[];
  };
  failures: { tests: FailureRow[]; products: FailureRow[] };
  equipment?: { instruments?: EquipmentGroup; materials?: EquipmentGroup };
  scorecard: Scorecard;
}

export type ScoreStatus = "good" | "warn" | "bad" | "none";

/** A dial: a share of something, and the levels the screen colours it by. */
export interface ScoreGauge {
  key: string;
  label: string;
  value: number | null;
  /** From this figure it reads as good; from the second, as a warning. */
  reference: [number, number];
  status: ScoreStatus;
  sub: string;
  to: string;
}

export interface ProductScore {
  id: number;
  label: string;
  code: string;
  received: number;
  results: number;
  /** Of those results, how many passed and how many failed. */
  passed: number;
  failed: number;
  completed: number;
  pass_rate: number | null;
  on_time: number | null;
  turnaround: number | null;
  spark: (number | null)[];
  status: ScoreStatus;
  to: string;
  to_received: string;
  to_results: string;
  to_released: string;
}

export interface AnalystScore {
  id: number;
  label: string;
  open: number;
  overdue: number;
  completed: number;
  turnaround: number | null;
  on_time: number | null;
  spark: (number | null)[];
  status: ScoreStatus;
  to: string;
}

export interface SectionRate { label: string; code: string; failed: number; total: number; rate: number; to: string }

/** What the lab has to stay within: the share inside the limit, and the ones outside it a click away. */
export interface LimitRow { key: string; label: string; total: number; outside: number; to: string | null }

export interface Scorecard {
  reference: Record<string, { good: number; warn: number }>;
  gauges: ScoreGauge[];
  products: ProductScore[];
  analysts?: AnalystScore[];
  sections: SectionRate[];
  limits: LimitRow[];
}

export interface ReportTrend {
  kind: "trend";
  heading: string;
  sub: string;
  unit: string;
  low: number | null;
  high: number | null;
  points: {
    date: string;
    label: string;
    y: number;
    text: string;
    batch: string;
    sample: string;
    spec: string;
    outcome: Outcome;
    to?: string;
  }[];
}

export type ReportPart =
  | { kind: "facts"; items: { label: string; value: string }[] }
  | { kind: "note"; text: string }
  | {
      kind: "table";
      heading: string;
      columns: { key: string; label: string }[];
      rows: ReportRow[];
      empty: string;
    }
  | ReportTrend;

export interface ReportDocument extends ReportStamp {
  title: string;
  reference: string;
  subtitle: string;
  links: { label: string; to: string }[];
  sections: { title: string; parts: ReportPart[] }[];
  can_export: boolean;
}

/* ============================================================
   Investigations, deviations and CAPA
   ============================================================ */

export interface CapaActionView {
  id: number;
  kind: "CORRECTIVE" | "PREVENTIVE";
  kind_label: string;
  description: string;
  owner: PersonRef;
  due_date: string;
  created_at: string;
  completed_by: PersonRef | null;
  completed_at: string | null;
  completion_note: string;
  verified_by: PersonRef | null;
  verified_at: string | null;
  verification_note: string;
  can_complete: boolean;
  can_verify: boolean;
}

export interface Investigation {
  id: number;
  reference: string;
  kind: "OOS" | "OOT" | "DEVIATION";
  kind_label: string;
  classification: string;
  classification_label: string;
  status: "OPEN" | "PENDING_CLOSURE" | "CLOSED";
  status_label: string;
  sample: { id: number; sample_no: string } | null;
  test_name: string;
  product_id: number | null;
  product_name: string;
  batch_no: string;
  description: string;
  root_cause: string;
  outcome: string;
  lab_finding: string;
  lab_finding_label: string;
  lab_finding_notes: string;
  lab_finding_by: PersonRef | null;
  lab_finding_at: string | null;
  conclusion: string;
  conclusion_label: string;
  failure: {
    limit: string;
    unit: string;
    results: {
      id: number;
      value: string;
      outcome: Outcome;
      entered_by: PersonRef;
      entered_at: string;
      current: boolean;
      retest_kind: string;
      authorized_by: PersonRef | null;
    }[];
  } | null;
  responsible: PersonRef;
  due_date: string;
  opened_by: PersonRef;
  opened_at: string;
  submitted_by: PersonRef | null;
  submitted_at: string | null;
  closed_by: PersonRef | null;
  closed_at: string | null;
  actions: CapaActionView[];
  events: {
    id: number;
    at: string;
    actor: PersonRef;
    what: string;
    changes: { field: string; old: string; new: string }[];
    comment: string;
  }[];
  can: { edit: boolean; lab_finding: boolean; approve: boolean; approve_blocked: boolean };
}

export interface AuditReviewData {
  latest: { name: string; reviewed_at: string; findings: string; events: number } | null;
  unreviewed: number;
}

export interface QualityRulesData {
  oos_investigation_required: boolean;
  oos_max_retests: number;
  oos_second_analyst: boolean;
  oos_batch_block: boolean;
}

export interface InvestigationOptions {
  kinds: { value: string; label: string }[];
  classifications: { value: string; label: string }[];
  action_kinds: { value: string; label: string }[];
  lab_findings: { value: string; label: string }[];
  conclusions: { value: string; label: string }[];
  products: { id: number; name: string }[];
  people: PersonRef[];
}

/* ============================================================
   Specifications, templates and notification rules
   ============================================================ */

export interface LimitKind {
  key: string;
  label: string;
}

/** One test as the editors hold it, in a specification or a template. */
export interface TestDraft {
  name: string;
  method: string;
  unit: string;
  limit_type: string;
  min_value: string | null;
  max_value: string | null;
  decimals: number;
  text_expected: string;
  limit_text: string;
  /** The template it was copied from, e.g. "ASSAY-HPLC v3". */
  source?: string;
  method_record_id?: number | null;
  method_record_label?: string;
}

/* ============================================================
   Lab records — the server says what each register holds; the screens draw it
   ============================================================ */

export interface LabOption {
  value: string;
  label: string;
}

export interface LabField {
  key: string;
  label: string;
  kind: "text" | "textarea" | "number" | "date" | "datetime" | "select" | "password";
  required: boolean;
  note: string;
  options: LabOption[];
  initial: string | number | null;
}

export interface LabColumn {
  key: string;
  label: string;
  /** "date" and "datetime" are written by the screen, the way every other date is. */
  kind: "" | "date" | "datetime";
}

export type LabValue = string | number | null;
export type LabCell = LabValue | { text: LabValue; to?: string; tone?: string; sub?: string };

export interface LabRegister {
  key: string;
  title: string;
  singular: string;
  description: string;
  note: string;
  /** Where this register reaches the lab's daily work, for the overview. */
  purpose: string;
  /** How many records it holds that this person can see. */
  count: number;
  search_hint: string;
  columns: LabColumn[];
  filters: { key: string; label: string; options: LabOption[] }[];
  can_add: boolean;
  add_label: string;
  add_hint: string;
  add_fields: LabField[];
}

export interface LabRow {
  id: number;
  to: string;
  cells: Record<string, LabCell>;
}

export interface LabAction {
  key: string;
  label: string;
  title: string;
  hint: string;
  tone: "primary" | "danger";
  done: string;
  signed: boolean;
  meaning: string;
  /** The words on the comment box. Empty means it has none. */
  comment: string;
  comment_required: boolean;
  fields: LabField[];
  /** What the person is looking at, so an approval is tied to it. */
  digest: string;
}

export interface LabTable {
  heading: string;
  empty: string;
  columns: LabColumn[];
  rows: Record<string, LabCell>[];
}

export interface LabRecord {
  register: string;
  id: number;
  singular: string;
  register_title: string;
  title: string;
  subtitle: string;
  status: { text: string; tone: string } | null;
  notice: string;
  facts: { label: string; value: LabValue; kind: LabColumn["kind"] }[];
  texts: { label: string; text: string }[];
  tables: LabTable[];
  history: {
    id: number;
    at: string;
    actor: PersonRef;
    what: string;
    changes: { field: string; old: string; new: string }[];
    comment: string;
  }[];
  actions: LabAction[];
}

export interface RawData {
  worksheet_ref: string;
  notes: string;
  instrument: { id: number; code: string; name: string } | null;
  materials: { id: number; code: string; name: string; lot: string; kind: string }[];
  readings: { label: string; value: string }[];
  mean: string;
}

/** What can be named on a result right now. */
export interface ResultOptions {
  instruments: { id: number; code: string; name: string; due: string }[];
  materials: { id: number; code: string; name: string; lot: string; kind: string; expiry_date: string }[];
}

export interface MethodChoice {
  id: number;
  label: string;
  status: string;
  status_label: string;
  validation_status: string;
}

export interface CustodyEntry {
  id: number;
  action: string;
  action_label: string;
  location: string;
  from_person: PersonRef | null;
  to_person: PersonRef | null;
  quantity: string;
  note: string;
  retain_until: string | null;
  witness: PersonRef | null;
  at: string;
  by: PersonRef;
}

export interface CustodyChain {
  entries: CustodyEntry[];
  retain_until: string | null;
  destroyed: boolean;
  can_add: boolean;
  can_destroy: boolean;
  actions: LabOption[];
  people: PersonRef[];
}

export interface TestTemplateRow extends TestDraft {
  id: number;
  code: string;
  version: number;
  is_retired: boolean;
  reason: string;
  created_by: string;
  created_at: string;
}

export interface SpecVersion {
  /** Hash of the tests as shown, so an approval is of what the approver saw. */
  digest: string;
  id: number;
  version: number;
  stage_key: string;
  stage_name: string;
  label: string;
  status: "DRAFT" | "EFFECTIVE" | "SUPERSEDED";
  status_label: string;
  effective_date: string | null;
  review_date: string | null;
  created_at: string;
  created_by: string | null;
  created_by_id: number | null;
  change_reason: string;
  approved_by: string | null;
  approved_at: string | null;
  sample_count: number;
  tests: (TestDraft & { id: number })[];
}

/** One set of tests a product has: its own specification ("" key) or one lab-tested QC stage's. */
export interface SpecTrack {
  key: string;
  name: string;
  /** The stage's name; absent for the product's own specification. */
  stage?: string;
  /** False for a stage the product's current stages no longer have. */
  current: boolean;
  effective_version: number | null;
  draft: boolean;
}

export interface SpecificationsResponse {
  product: { id: number; code: string; name: string };
  /** Which set of tests these versions are: "" for the product's own specification. */
  stage_key: string;
  tracks: SpecTrack[];
  specifications: SpecVersion[];
  limit_types: LimitKind[];
  can_draft: boolean;
  can_approve: boolean;
}

export interface CertificateTemplateRow {
  id: number;
  name: string;
  is_default: boolean;
  title: string;
  header_note: string;
  footer_note: string;
  show_method: boolean;
  show_internal_batch_id: boolean;
  show_manufacturing_site: boolean;
  show_dosage_form: boolean;
  show_analysis_dates: boolean;
  show_storage_condition: boolean;
  /** Products that print with it; for the default, also those that name no template. */
  product_count: number;
}

export interface BatchNumberRuleView {
  prefix: string;
  separator: string;
  digits: number;
  include_year: boolean;
  include_section: boolean;
  include_product: boolean;
  restart_yearly: boolean;
  /** What an ID built by the saved rule looks like. */
  example: string;
}

export interface NotificationRuleRow {
  event: string;
  label: string;
  hint: string;
  enabled: boolean;
  takes_roles: boolean;
  role_ids: number[];
  takes_days_before: boolean;
  days_before: number;
  takes_repeat: boolean;
  repeat_days: number;
  email: boolean;
  updated_at: string;
}

export interface NotificationRulesResponse {
  rules: NotificationRuleRow[];
  roles: { id: number; name: string }[];
  /** A mail server is set up. */
  email_ready: boolean;
}
