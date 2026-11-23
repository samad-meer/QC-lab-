import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { apiGet } from "../api";
import { modeOfStage, modeShown } from "../stageKinds";
import type { ProductStagesResponse, QcStagePlanStage } from "../types";
import { Message } from "./Feedback";
import ModalBackdrop from "./ModalBackdrop";

interface SourceProduct {
  id: number;
  code: string;
  name: string;
  qc_stage_count: number;
}

export interface CopiedStages {
  product: { code: string; name: string };
  version: number;
  stages: QcStagePlanStage[];
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** A stage of a kind the lab offers now (stageKinds.ts): only those can be copied. */
const offered = (s: QcStagePlanStage) => modeShown(modeOfStage(s.kind, s.signoffs.length));

/** How a stage is done, as the stages editor names it. */
function kindOf(s: QcStagePlanStage): { label: string; tone: string } {
  if (s.kind === "TESTED") return { label: "Tested in the lab", tone: "info" };
  if (!s.signoffs.length) return { label: "QA pass / fail", tone: "warn" };
  return { label: "Batch record", tone: "muted" };
}

/** What comes across with the stage. */
function contents(s: QcStagePlanStage): string {
  if (s.kind === "TESTED") {
    // Every lab-tested stage carries own_tests; a version only when it has tests of its own in force.
    return s.own_tests?.version != null
      ? "Its own tests stay with that product; here it uses this product's specification"
      : "Uses this product's specification";
  }
  if (!s.signoffs.length) return "QA records it passed or failed on each batch";
  const points = s.steps.reduce((n, st) => n + st.checkpoints.length, 0);
  return `${plural(s.steps.length, "step")} · ${plural(points, "check point")} · `
    + `${plural(s.signoffs.length, "sign-off")} ${s.sign_each_step ? "at every step" : "once"}`;
}

/** Everything in a stage, as it would come across: read before ticking it. */
function Preview({ s, from, id }: { s: QcStagePlanStage; from: string; id: string }) {
  const desc = s.description && <p className="cs-desc">{s.description}</p>;
  if (s.kind === "TESTED") {
    return (
      <div className="cs-preview" id={id}>
        {desc}
        {s.tests ? (
          <>
            <div className="cs-pv-head">
              {s.tests.label} on {from}{" "}
              <span className="cs-pv-note">
                — not copied: {s.tests.own ? `these stay with ${from}; ` : ""}here it uses this product's specification
              </span>
            </div>
            <div className="cs-table-wrap">
              <table className="cs-table cs-tests">
                <thead><tr><th>Test</th><th>Method</th><th>Limit</th></tr></thead>
                <tbody>
                  {s.tests.tests.map((t, i) => (
                    <tr key={i}><td>{t.name}</td><td>{t.method || "—"}</td><td>{t.limit_text || "—"}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <p className="cs-desc">No tests are set up for it on {from}.</p>
        )}
      </div>
    );
  }
  if (!s.signoffs.length) {
    return (
      <div className="cs-preview" id={id}>
        {desc}
        <p className="cs-desc">QA records it passed or failed on each batch, with remarks and their password. No steps to fill.</p>
      </div>
    );
  }
  return (
    <div className="cs-preview" id={id}>
      {desc}
      {s.steps.map((st) => (
        <div className="cs-step" key={st.id}>
          <div className="cs-pv-head">Step {st.order}{st.title ? ` · ${st.title}` : ""}</div>
          {st.instructions && <p className="cs-desc">{st.instructions}</p>}
          {st.checkpoints.length ? (
            <div className="cs-table-wrap">
              <table className="cs-table cs-points">
                <thead><tr><th>Check point</th><th>Value</th><th>Limit</th></tr></thead>
                <tbody>
                  {st.checkpoints.map((cp) => (
                    <tr key={cp.id}>
                      <td>{cp.label}{!cp.required && <span className="cs-pv-note"> (optional)</span>}</td>
                      <td>{cp.kind_name || cp.kind_label}{cp.unit ? `, ${cp.unit}` : ""}</td>
                      <td>{cp.limit_text || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="cs-desc">No check points.</p>
          )}
        </div>
      ))}
      <div className="cs-pv-head">
        Signed {s.sign_each_step ? "under every step" : "once for the stage"}, in this order
      </div>
      <ol className="cs-signoffs">
        {s.signoffs.map((so) => (
          <li key={so.id}><b>{so.title}</b>{so.holder ? ` (${so.holder})` : ""} <span className="cs-pv-note">· {so.role}</span></li>
        ))}
      </ol>
    </div>
  );
}

/**
 * Copy QC stages from a product already set up into this product's draft: every step,
 * check point, limit and sign-off column comes across, and nothing is saved until the
 * draft is. A copy, not a link: a later change to either product leaves the other alone,
 * as each product's stages are versioned and approved on their own.
 *
 * The title and the product stay at the top and the button at the bottom; only the
 * stages scroll between them, two to a row, so a long batch record fits a zoomed screen.
 */
export default function CopyStagesModal({ productId, taken, onCopy, onClose }: {
  productId: number;
  /** Names already in the draft, lower-cased: two stages may not share one. */
  taken: Set<string>;
  onCopy: (copied: CopiedStages) => void;
  onClose: () => void;
}) {
  // The draft cannot change while this is open: taken once, so a re-render never reloads the stages.
  const [names] = useState(taken);
  const [products, setProducts] = useState<SourceProduct[] | null>(null);
  const [sourceId, setSourceId] = useState("");
  const [source, setSource] = useState<ProductStagesResponse | null>(null);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  // Stages opened to read what is in them.
  const [viewing, setViewing] = useState<Set<number>>(new Set());
  const [error, setError] = useState("");

  useEffect(() => {
    apiGet<{ results: SourceProduct[] }>("/api/product-master/?active=1&page_size=200")
      .then((r) => {
        const offered = r.results.filter((p) => p.id !== productId && p.qc_stage_count > 0);
        setProducts(offered);
        // Only one to copy from: choose it.
        if (offered.length === 1) setSourceId(String(offered[0].id));
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load the products."));
  }, [productId]);

  useEffect(() => {
    setSource(null);
    setViewing(new Set());
    if (!sourceId) return;
    let live = true;
    apiGet<ProductStagesResponse>(`/api/products/${sourceId}/qc-stages/`)
      .then((r) => {
        if (!live) return;
        setSource(r);
        // Everything offered ticked, except a stage whose name this product already has.
        setPicked(new Set((r.current?.stages ?? []).filter(offered)
          .filter((s) => !names.has(s.name.trim().toLowerCase())).map((s) => s.id)));
      })
      .catch((err) => live && setError(err instanceof Error ? err.message : "Could not load that product's stages."));
    return () => {
      live = false;
    };
  }, [sourceId, names]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const all = source?.current?.stages ?? [];
  const stages = all.filter(offered);
  // Lab-tested and QA pass / fail stages, while those kinds are not offered.
  const left = all.length - stages.length;
  const chosen = stages.filter((s) => picked.has(s.id));
  const clashing = chosen.filter((s) => names.has(s.name.trim().toLowerCase())).length;
  const product = products?.find((p) => String(p.id) === sourceId);
  const flip = (set: Set<number>, id: number) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  };
  const toggle = (id: number) => setPicked((p) => flip(p, id));
  const view = (id: number) => {
    const opening = !viewing.has(id);
    setViewing((v) => flip(v, id));
    // An opened stage takes the full width: keep it in view.
    if (opening) requestAnimationFrame(() => document.getElementById(`cs-card-${id}`)?.scrollIntoView({ block: "nearest" }));
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!product || !source?.current || chosen.length === 0) return;
    onCopy({ product: { code: product.code, name: product.name }, version: source.current.version, stages: chosen });
  };

  return (
    <ModalBackdrop onClick={onClose}>
      <div className="modal copy-stages" role="dialog" aria-modal="true" aria-labelledby="copy-stages-title"
        onClick={(e) => e.stopPropagation()}>
        <div className="cs-head">
          <h3 id="copy-stages-title">Copy stages from another product</h3>
          <p className="modal-sub">
            Steps, check points, limits and sign-off columns all come across, after this product's stages. It is a
            copy: change what differs here, and later changes to either product leave the other alone.
          </p>
          <label className="field cs-source">
            Copy from
            <select value={sourceId} onChange={(e) => setSourceId(e.target.value)} autoFocus disabled={!products}>
              <option value="">{products ? "— choose a product —" : "Loading…"}</option>
              {products?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.code} · {p.name} ({plural(p.qc_stage_count, "stage")})
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="cs-body">
          {error && <Message kind="error">{error}</Message>}
          {products && products.length === 0 && (
            <p className="cs-empty">No other product has QC stages yet: set them up on one product first, then copy them.</p>
          )}
          {products && products.length > 0 && !sourceId && (
            <p className="cs-empty">Choose the product to copy from: its stages appear here, ready to tick.</p>
          )}
          {sourceId && !source && !error && <p className="cs-empty">Loading its stages…</p>}
          {source && (
            <>
              <div className="cs-tools">
                <span>
                  <b>{product?.code}</b>, version {source.current?.version} · click a stage to tick or untick it;{" "}
                  <b>View</b> shows what is in it
                </span>
                <div className="spacer" />
                <button type="button" className="link-btn" onClick={() => setPicked(new Set(stages.map((s) => s.id)))}>
                  Tick all
                </button>
                <button type="button" className="link-btn" onClick={() => setPicked(new Set())}>Tick none</button>
              </div>
              {left > 0 && (
                <p className="cs-desc">
                  {left === all.length ? "None of its stages can be copied: they are" : `${plural(left, "stage")} not shown:`}{" "}
                  lab-tested or QA pass / fail, kinds the stages editor does not offer for now. Only batch records are copied.
                </p>
              )}
              <div className="cs-list" role="group" aria-label="Stages to copy">
                {stages.map((s) => {
                  const on = picked.has(s.id);
                  const clash = names.has(s.name.trim().toLowerCase());
                  const kind = kindOf(s);
                  const steps = s.steps.map((st) => st.title).filter(Boolean).join(" · ");
                  const open = viewing.has(s.id);
                  return (
                    <div key={s.id} id={`cs-card-${s.id}`} className={`cs-item${on ? " on" : ""}${open ? " open" : ""}`}>
                      <label className="cs-pick">
                        <input type="checkbox" checked={on} onChange={() => toggle(s.id)} />
                        <span className="cs-text">
                          <span className="cs-title">
                            <span className="cs-no" aria-hidden="true">{s.order}</span>
                            <b>{s.name}</b>
                          </span>
                          <span className="cs-tags">
                            <span className={`badge ${kind.tone}`}>{kind.label}</span>
                            {!s.required && <span className="badge muted">Optional</span>}
                            {clash && <span className="badge hot">Name already here</span>}
                          </span>
                          <span className="cs-meta">{contents(s)}</span>
                          {steps && !open && <span className="cs-steps" title={steps}>Steps: {steps}</span>}
                        </span>
                      </label>
                      <button type="button" className="ghost small cs-view" aria-expanded={open}
                        aria-controls={`cs-pv-${s.id}`} onClick={() => view(s.id)}>
                        {open ? "Hide" : "View"}
                      </button>
                      {open && <Preview s={s} from={product?.code ?? "that product"} id={`cs-pv-${s.id}`} />}
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>

        <form className="cs-foot" onSubmit={submit}>
          <span className="cs-count">
            {source ? (
              <>
                <b>{chosen.length}</b> of {plural(stages.length, "stage")} ticked
                {clashing > 0 && (
                  <span className="cs-warn"> · {clashing} share{clashing === 1 ? "s" : ""} a name with a stage here: rename before saving</span>
                )}
              </>
            ) : null}
          </span>
          <div className="spacer" />
          <button type="button" className="ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="primary" disabled={chosen.length === 0}>
            {chosen.length ? `Add ${plural(chosen.length, "stage")}` : "Add stages"}
          </button>
        </form>
      </div>
    </ModalBackdrop>
  );
}
