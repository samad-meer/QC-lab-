import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, apiGet, apiPost } from "../api";
import type { FieldErrors } from "../api";
import StepPanel from "../components/execution/StepPanel";
import { useExecution } from "../components/execution/useExecution";
import Field from "../components/Field";
import { Message } from "../components/Feedback";
import ListCard from "../components/list/ListCard";
import SampleFilters, { useSampleFilters } from "../components/SampleFilters";
import SampleTable from "../components/SampleTable";
import { useToast } from "../components/Toast";
import type {
  BatchRow, Execution, Product, SampleDetail, SampleListItem, SampleSource, Section, User,
} from "../types";
import { useList } from "../useList";
import { nowLocalInput, todayInput } from "../util";

const BLANK = {
  productId: "",
  analystId: "",
  batchNo: "",
  reference: "",
  manufacturingSite: "",
  quantity: "",
  receivedFrom: "",
  dueDate: "",
  // Optional batch details that appear on the certificate.
  manufacturingDate: "",
  pastExpiryReason: "",
  expiryDate: "",
  storageCondition: "",
  qcStageId: "",
};

/** Maps a backend field name onto the form control it belongs to. */
const FIELD_MAP: Record<string, string> = {
  product_id: "productId",
  analyst_id: "analystId",
  batch_no: "batchNo",
  reference: "reference",
  manufacturing_site: "manufacturingSite",
  quantity: "quantity",
  received_from: "receivedFrom",
  received_at: "receivedAt",
  due_date: "dueDate",
  manufacturing_date: "manufacturingDate",
  expiry_date: "expiryDate",
  past_expiry_reason: "pastExpiryReason",
  storage_condition: "storageCondition",
  qc_stage_id: "qcStageId",
};

function mapErrors(fields: FieldErrors): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, message] of Object.entries(fields)) {
    out[FIELD_MAP[key] ?? key] = message;
  }
  return out;
}

/** The checks a just-registered sample needs, right where it was registered. */
function ReceiptChecks({
  sample,
  onChange,
  onClose,
}: {
  sample: { id: number; sample_no: string };
  onChange: () => void;
  onClose: () => void;
}) {
  const { exec, setExec, error } = useExecution(sample.id);
  const step = exec?.steps.find((s) => s.kind === "receipt");
  const done = step?.status === "COMPLETED";

  const changed = (e: Execution) => {
    setExec(e);
    onChange();
  };

  return (
    <section className="card" aria-label={`Receipt checks for ${sample.sample_no}`}>
      <div className="card-head">
        <h2>Receipt checks — <Link to={`/samples/${sample.id}`}>{sample.sample_no}</Link></h2>
        <span className="hint">{done ? "Complete — the analyst can start" : "Testing cannot start until these are complete"}</span>
        <div className="spacer" />
        <button type="button" className="ghost small" onClick={onClose}>{done ? "Done" : "Finish later"}</button>
      </div>
      <div className="card-body">
        {error && <Message kind="error">{error}</Message>}
        {exec && step && <StepPanel sampleId={sample.id} exec={exec} step={step} onChange={changed} />}
      </div>
    </section>
  );
}

export default function FrontDesk() {
  const toast = useToast();
  const [sections, setSections] = useState<Section[]>([]);
  // Who samples come from, kept by an administrator so a name is never typed three ways.
  const [sources, setSources] = useState<SampleSource[] | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [analysts, setAnalysts] = useState<User[]>([]);
  const [lookupsLoading, setLookupsLoading] = useState(false);
  const listFilters = useSampleFilters();
  const samples = useList<SampleListItem>("/api/samples/", { query: { ...listFilters.query, status: "ALL" } });

  const [sectionCode, setSectionCode] = useState("");
  // Opened from a QC stage on a batch page: the section, product, batch and stage
  // arrive filled in, each once the list it belongs to has loaded.
  const [params] = useSearchParams();
  const prefill = useRef(params.get("product") ? {
    section: params.get("section") ?? "", product: params.get("product") ?? "",
    batch: params.get("batch") ?? "", stage: params.get("stage") ?? "",
  } : null);
  useEffect(() => {
    if (prefill.current?.section) setSectionCode(prefill.current.section);
  }, []);
  const [f, setF] = useState({ ...BLANK });
  // Both dates start on today so the common case needs no typing.
  const [receivedAt, setReceivedAt] = useState(nowLocalInput());
  // "Now" stays now, however long the page sits open, until someone sets a time themselves.
  const [timeChosen, setTimeChosen] = useState(false);
  useEffect(() => {
    if (timeChosen) return undefined;
    const timer = window.setInterval(() => setReceivedAt(nowLocalInput()), 30_000);
    return () => window.clearInterval(timer);
  }, [timeChosen]);
  const [dueDate, setDueDate] = useState(todayInput());
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState("");
  const [lookupError, setLookupError] = useState("");
  const [busy, setBusy] = useState(false);
  // Most samples come from a batch; water, swabs and complaints do not.
  const [fromBatch, setFromBatch] = useState(true);
  // The batch on record for the number typed, if there is one.
  const [known, setKnown] = useState<BatchRow | null>(null);
  const expiryOnFile = known?.expiry_date ?? f.expiryDate;
  const pastExpiry = Boolean(expiryOnFile) && expiryOnFile < receivedAt.slice(0, 10);
  // A sample just registered whose workflow asks for receipt checks.
  const [receiptFor, setReceiptFor] = useState<{ id: number; sample_no: string } | null>(null);

  const set = (k: keyof typeof BLANK, v: string) => {
    setF((prev) => ({ ...prev, [k]: v }));
    // Clear a field's error the moment the user starts fixing it.
    setErrors((prev) => (prev[k] ? { ...prev, [k]: "" } : prev));
  };

  // Which signatures this product's certificate will need — products differ.
  const workflow = products.find((p) => String(p.id) === f.productId)?.workflow;
  const product = products.find((p) => String(p.id) === f.productId);
  const receiptChecks = workflow?.receipt_checks ?? 0;
  // A known batch keeps the stages it was created with; a new one takes the product's current ones.
  const stageOptions = fromBatch ? (known ? known.stage_options ?? [] : product?.qc_stages ?? []) : [];
  const stageChosen = stageOptions.some((s) => String(s.id) === f.qcStageId);
  const chosenStage = stageOptions.find((s) => String(s.id) === f.qcStageId);
  const reviewHint = workflow
    ? `Review: ${workflow.stages.map((s) => s.name).join(" → ")} (${workflow.name})`
      + (receiptChecks ? ` · ${receiptChecks} receipt check${receiptChecks === 1 ? "" : "s"} after registering` : "")
    : undefined;

  // Is this number already a batch of this product? Asked once typing pauses.
  useEffect(() => {
    setKnown(null);
    const number = f.batchNo.trim();
    if (!fromBatch || !f.productId || !number) return;
    let stale = false;
    const timer = window.setTimeout(() => {
      apiGet<{ batch: BatchRow | null }>(
        `/api/batches/lookup/?product=${f.productId}&official_no=${encodeURIComponent(number)}`,
      )
        .then((r) => {
          if (!stale) setKnown(r.batch);
        })
        .catch(() => undefined);
    }, 350);
    return () => {
      stale = true;
      window.clearTimeout(timer);
    };
  }, [fromBatch, f.productId, f.batchNo]);

  // The stage comes last: it is one of the known batch's, so it waits for the lookup.
  useEffect(() => {
    const want = prefill.current?.stage;
    if (want && known?.stage_options?.some((s) => String(s.id) === want && !s.waiting_for?.length)) {
      setF((prev) => ({ ...prev, qcStageId: want }));
      prefill.current = null;
    }
  }, [known]);

  useEffect(() => {
    apiGet<Section[]>("/api/sections/")
      .then(setSections)
      .catch((err) =>
        setLookupError(err instanceof Error ? err.message : "Could not load sections."),
      );
    apiGet<SampleSource[]>("/api/sample-sources/")
      .then(setSources)
      .catch((err) =>
        setLookupError(
          err instanceof Error
            ? `Could not load the Received from list — ${err.message}`
            : "Could not load the Received from list.",
        ),
      );
  }, []);

  // The section choice drives which products and which analysts are offered:
  // only analysts trained for that section appear (brief, step 2).
  useEffect(() => {
    setF((prev) => ({ ...prev, productId: "", analystId: "" }));
    setLookupError("");
    if (!sectionCode) {
      setProducts([]);
      setAnalysts([]);
      return;
    }
    setLookupsLoading(true);
    Promise.all([
      apiGet<Product[]>(`/api/products/?section=${sectionCode}`),
      apiGet<User[]>(`/api/analysts/?section=${sectionCode}`),
    ])
      .then(([p, a]) => {
        setProducts(p);
        setAnalysts(a);
        const want = prefill.current;
        if (want && p.some((x) => String(x.id) === want.product)) {
          setFromBatch(true);
          setF((prev) => ({ ...prev, productId: want.product, batchNo: want.batch }));
          if (!want.stage) prefill.current = null;
        }
      })
      .catch((err) =>
        setLookupError(
          err instanceof Error
            ? `Could not load the products and analysts for this section — ${err.message}`
            : "Could not load this section.",
        ),
      )
      .finally(() => setLookupsLoading(false));
  }, [sectionCode]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setFormError("");
    setErrors({});
    try {
      const created = await apiPost<SampleDetail>("/api/samples/", {
        product_id: Number(f.productId),
        analyst_id: Number(f.analystId),
        from_batch: fromBatch,
        batch_no: fromBatch ? f.batchNo : "",
        reference: fromBatch ? "" : f.reference,
        manufacturing_site: fromBatch ? f.manufacturingSite : "",
        quantity: f.quantity,
        received_from: f.receivedFrom,
        // As picked, in the lab's time zone: the server reads it that way.
        received_at: receivedAt,
        due_date: dueDate,
        manufacturing_date: known?.manufacturing_date ?? (f.manufacturingDate || null),
        expiry_date: known?.expiry_date ?? (f.expiryDate || null),
        storage_condition: f.storageCondition,
        past_expiry_reason: f.pastExpiryReason,
        qc_stage_id: stageChosen ? Number(f.qcStageId) : null,
      });
      const checks = created.workflow?.receipt_checks ?? 0;
      toast("ok", `Registered ${created.sample_no}`, checks
        ? "Complete the receipt checks below so testing can start."
        : `Now on ${created.analyst_name}'s worklist.`);
      setReceiptFor(checks ? { id: created.id, sample_no: created.sample_no } : null);
      setF({ ...BLANK });
      setReceivedAt(nowLocalInput());
      setTimeChosen(false);
      setDueDate(todayInput());
      await samples.reload();
    } catch (err) {
      if (err instanceof ApiError && err.hasFieldErrors) {
        setErrors(mapErrors(err.fields));
        setFormError(
          err.hasFieldErrors && Object.keys(err.fields).length > 1
            ? "Some entries need correcting — see the highlighted fields."
            : "",
        );
      } else {
        setFormError(err instanceof Error ? err.message : "Registration failed.");
      }
      toast("error", "Sample not registered", err instanceof Error ? err.message : undefined);
    } finally {
      setBusy(false);
    }
  };

  const selectedAnalyst = analysts.find((a) => String(a.id) === f.analystId);

  const analystPlaceholder = !sectionCode
    ? "Choose a section first"
    : lookupsLoading
      ? "Loading…"
      : analysts.length === 0
        ? "No trained analysts in this section"
        : "— choose analyst —";

  return (
    <>
      <div className="page-head">
        <h1>Receive a sample</h1>
        <p className="sub">
          Record what arrived, choose the section, and assign the analyst. The system issues the
          sample number — it can never be repeated or reused.
        </p>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>New sample</h2>
          <span className="hint">The number is issued on save</span>
        </div>
        <div className="card-body">
          {lookupError && (
            <div style={{ marginBottom: 16 }}>
              <Message kind="error">{lookupError}</Message>
            </div>
          )}
          <form className="stack" onSubmit={submit} noValidate>
            <div className="form-seg">
              What is this sample?
              <div className="seg" role="group" aria-label="What is this sample?">
                <button type="button" className={fromBatch ? "on" : ""} aria-pressed={fromBatch} onClick={() => setFromBatch(true)}>
                  From a batch
                </button>
                <button type="button" className={fromBatch ? "" : "on"} aria-pressed={!fromBatch} onClick={() => setFromBatch(false)}>
                  Not from a batch
                </button>
              </div>
            </div>

            <div className="form-row">
              <Field
                label="Section"
                required
                error={errors.section}
                info={<>
                  <p>The part of the lab that will test this sample. It decides which products and which analysts are
                    offered, and its code starts the sample number, e.g. GF-2026-0016.</p>
                  <p>Sections are added by an administrator under <b>Admin → Sections</b>.</p>
                </>}
              >
                <select value={sectionCode} onChange={(e) => setSectionCode(e.target.value)}>
                  <option value="">— choose section —</option>
                  {sections.map((s) => (
                    <option key={s.id} value={s.code}>{s.name}</option>
                  ))}
                </select>
              </Field>
              <Field
                label="Product"
                required
                error={errors.productId}
                hint={reviewHint}
                info={<>
                  <p>Only the <b>active</b> products of the chosen section are listed.</p>
                  <p>Products are added under <b>Admin → Products</b> by whoever manages the product master (by
                    default an administrator). A product also needs an effective specification and a review workflow
                    before its samples can be registered.</p>
                </>}
              >
                <select
                  value={f.productId}
                  onChange={(e) => {
                    set("productId", e.target.value);
                    const chosen = products.find((p) => String(p.id) === e.target.value);
                    if (chosen?.storage_condition && !f.storageCondition) set("storageCondition", chosen.storage_condition);
                  }}
                  disabled={!sectionCode || lookupsLoading}
                >
                  <option value="">
                    {!sectionCode ? "Choose a section first" : lookupsLoading ? "Loading…" : "— choose product —"}
                  </option>
                  {products.map((p) => (
                    <option key={p.id} value={p.id}>{p.name} ({p.code})</option>
                  ))}
                </select>
              </Field>
            </div>

            <div className="form-row">
              {fromBatch ? (
                <Field
                  label="Official batch / lot number"
                  required
                  error={errors.batchNo}
                  hint={
                    known
                      ? `On record: ${known.internal_id}, ${known.sample_count} sample${known.sample_count === 1 ? "" : "s"} so far`
                      : f.batchNo.trim() && product
                        ? "New batch — an internal ID is issued when you register"
                        : "Exactly as the manufacturer assigned it"
                  }
                >
                  <input value={f.batchNo} onChange={(e) => set("batchNo", e.target.value)} />
                </Field>
              ) : (
                <Field label="What is this sample?" required error={errors.reference}
                  hint="Nothing from a batch to trace, so say what it is">
                  <input value={f.reference} onChange={(e) => set("reference", e.target.value)}
                    placeholder="e.g. Purified water, point WP-3" />
                </Field>
              )}
              <Field
                label="Quantity received"
                required
                error={errors.quantity}
                hint="Whatever units the lab uses"
              >
                <input
                  value={f.quantity}
                  onChange={(e) => set("quantity", e.target.value)}
                  placeholder="e.g. 60 tablets, 2 × 100 g"
                />
              </Field>
            </div>

            {stageOptions.length > 0 && (
              <Field
                label="QC stage"
                required
                error={errors.qcStageId}
                hint={chosenStage?.tests
                  ? `Tested on: ${chosenStage.tests}`
                  : known ? `The stages batch ${known.official_batch_no} has` : "The product's QC stages"}
                info={<>
                  <p>The stage of the batch this sample was taken for, such as the final grain or the core tablets.
                    Its samples are tested on the stage's own tests when it has them, otherwise on the product's
                    specification.</p>
                  <p>A stage greyed out waits for an earlier one: it cannot be chosen until that has passed.</p>
                </>}
              >
                <select value={stageChosen ? f.qcStageId : ""} onChange={(e) => set("qcStageId", e.target.value)}>
                  <option value="">— which stage is this sample for? —</option>
                  {stageOptions.map((s) => (
                    <option key={s.id} value={s.id} disabled={Boolean(s.waiting_for?.length)}>
                      {s.order}. {s.name}{s.added_to_batch ? " (added to this batch)" : ""}
                      {s.waiting_for?.length ? ` — waits for ${s.waiting_for.join(", ")}` : ""}
                    </option>
                  ))}
                </select>
              </Field>
            )}

            <div className="form-row">
              <Field
                label="Received from"
                required
                error={errors.receivedFrom}
                hint={sources?.length === 0 ? "The list is empty — ask an administrator to add names" : undefined}
                info={<>
                  <p>Who handed the sample over: a department, a supplier or a person. Choosing from the list means
                    one name is never typed several ways.</p>
                  <p>Not on the list? An administrator adds it under <b>Admin → Received from</b>. Names are never
                    deleted, and a sample keeps the name it was received under.</p>
                </>}
              >
                <select
                  value={f.receivedFrom}
                  onChange={(e) => set("receivedFrom", e.target.value)}
                  disabled={!sources?.length}
                >
                  <option value="">
                    {sources === null ? "Loading…" : sources.length === 0 ? "No names on the list" : "— choose who sent it —"}
                  </option>
                  {sources?.map((s) => (
                    <option key={s.id} value={s.name}>{s.name}</option>
                  ))}
                </select>
              </Field>
              <Field
                label="Date and time received"
                required
                error={errors.receivedAt}
                hint="Filled in with now — change it only if the sample arrived earlier"
              >
                <input
                  type="datetime-local"
                  value={receivedAt}
                  onChange={(e) => {
                    setReceivedAt(e.target.value);
                    setTimeChosen(true);
                    setErrors((p) => (p.receivedAt ? { ...p, receivedAt: "" } : p));
                  }}
                />
              </Field>
            </div>

            <div className="form-row">
              <Field
                label="Assign to analyst"
                required
                error={errors.analystId}
                hint="Only analysts trained for this section are offered"
                info={<>
                  <p>Only people who may enter results <b>and</b> are trained for the chosen section are listed. The
                    sample goes to their worklist.</p>
                  <p>Someone missing? An administrator ticks this section for them under <b>Admin → Users</b>.</p>
                </>}
              >
                <select
                  value={f.analystId}
                  onChange={(e) => set("analystId", e.target.value)}
                  disabled={!sectionCode || lookupsLoading}
                >
                  <option value="">{analystPlaceholder}</option>
                  {analysts.map((a) => (
                    <option key={a.id} value={a.id}>{a.name}</option>
                  ))}
                </select>
              </Field>
              <Field
                label="Due date"
                required
                error={errors.dueDate}
                hint="Filled in with today — change it if the result is due later"
              >
                <input
                  type="date"
                  value={dueDate}
                  onChange={(e) => {
                    setDueDate(e.target.value);
                    setErrors((p) => (p.dueDate ? { ...p, dueDate: "" } : p));
                  }}
                />
              </Field>
            </div>

            <details className="more-fields">
              <summary>{fromBatch ? "Batch details for the certificate (optional)" : "Details for the certificate (optional)"}</summary>
              {fromBatch && (
                <div style={{ marginTop: 14 }}>
                  <Field label="Manufacturing site" error={errors.manufacturingSite} hint="If applicable">
                    <input value={known?.manufacturing_site || f.manufacturingSite}
                      disabled={Boolean(known?.manufacturing_site)}
                      onChange={(e) => set("manufacturingSite", e.target.value)} />
                  </Field>
                </div>
              )}
              <div className="form-row" style={{ marginTop: 14 }}>
                <Field
                  label="Date of manufacture"
                  error={errors.manufacturingDate}
                  hint="Leave blank if the container does not state one"
                >
                  <input
                    type="date"
                    value={known?.manufacturing_date ?? f.manufacturingDate}
                    disabled={Boolean(known?.manufacturing_date)}
                    onChange={(e) => set("manufacturingDate", e.target.value)}
                  />
                </Field>
                <Field
                  label="Expiry / retest date"
                  error={errors.expiryDate}
                  hint="Printed on the certificate when given"
                >
                  <input
                    type="date"
                    value={known?.expiry_date ?? f.expiryDate}
                    disabled={Boolean(known?.expiry_date)}
                    onChange={(e) => set("expiryDate", e.target.value)}
                  />
                </Field>
              </div>
              {pastExpiry && (
                <div style={{ marginTop: 14 }}>
                  <Field
                    label="Why is this expired batch being tested?"
                    required
                    error={errors.pastExpiryReason}
                    hint="This batch is past its expiry date. The reason prints on the certificate."
                  >
                    <input
                      value={f.pastExpiryReason}
                      maxLength={300}
                      onChange={(e) => set("pastExpiryReason", e.target.value)}
                    />
                  </Field>
                </div>
              )}
              <div style={{ marginTop: 14 }}>
                <Field label="Storage condition" error={errors.storageCondition}>
                  <input
                    value={f.storageCondition}
                    onChange={(e) => set("storageCondition", e.target.value)}
                    placeholder="e.g. Store below 25 °C, protected from light"
                  />
                </Field>
              </div>
            </details>

            {formError && <Message kind="error">{formError}</Message>}

            <div className="actions-bar">
              {selectedAnalyst && (
                <span style={{ fontSize: 13, color: "var(--ink-3)" }}>
                  {receiptChecks
                    ? `Goes to ${selectedAnalyst.name} once the receipt checks are complete.`
                    : `Goes straight to ${selectedAnalyst.name}'s worklist.`}
                </span>
              )}
              <div className="spacer" />
              <button className="primary" disabled={busy}>
                {busy ? "Registering…" : "Register sample"}
              </button>
            </div>
          </form>
        </div>
      </div>

      {receiptFor && (
        <ReceiptChecks key={receiptFor.id} sample={receiptFor} onChange={() => void samples.reload()}
          onClose={() => setReceiptFor(null)} />
      )}

      <ListCard
        title="All samples"
        hint={samples.loaded && !samples.error ? `${samples.count} in the lab` : undefined}
        list={samples}
        failure="Could not load samples"
        emptyTitle="No samples yet"
        emptySub="Register the first one above, or widen the date range."
        filters={<SampleFilters filters={listFilters} />}
      >
        {(rows) => <SampleTable samples={rows} />}
      </ListCard>
    </>
  );
}
