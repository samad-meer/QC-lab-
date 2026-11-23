import { useEffect, useState } from "react";
import type { ProductStagesResponse, QcStagePlanStage, SpecSummary } from "../types";
import { EmptyState } from "./Feedback";
import SpecManager from "./SpecManager";

const KIND_TEXT: Record<string, string> = {
  NUMBER: "Number", PERCENT: "Percentage", TIME_RANGE: "Start and end time", TIME: "Time", DATE: "Date",
  TEXT: "Text", YES_NO: "Yes / No", CHOICE: "Choice",
};

function modeLabel(s: QcStagePlanStage): string {
  if (s.kind === "TESTED") return "Tested in the lab";
  return s.signoffs.length ? "Batch record" : "QA record";
}

/** A set of tests and their limits, as a stage shows them: like the check points of a batch record. */
function TestList({ spec }: { spec: SpecSummary }) {
  return (
    <div className="sb-points" role="table" aria-label={spec.label}>
      {spec.tests.map((t) => (
        <div className="sb-point" role="row" key={t.name}>
          <span className="sb-point-name" role="cell">{t.name}</span>
          <span className="cell-sub" role="cell">{t.method || "—"}</span>
          <span className="sb-point-limit" role="cell">{t.limit_text}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * The product's QC stages as its batch record reads, each with what it asks for
 * inside it: a batch-record stage its steps and check points, a stage tested in the
 * lab its tests and limits. The product's own specification closes the list: the
 * stages without tests of their own use it, and so does a sample with no stage.
 */
export default function StagesView({ data, productId, focus, onChanged, onEdit, readOnly = false }: {
  data: ProductStagesResponse;
  productId: number;
  /** Open one set of tests to begin with: a stage's key, or "" for the product's specification. */
  focus?: string | null;
  onChanged: () => void;
  /** Change the stages, beginning at this one. */
  onEdit?: (stageId: number) => void;
  /** An earlier version, shown as it was: nothing to change, no specification beneath. */
  readOnly?: boolean;
}) {
  const stages = data.current?.stages ?? [];
  // Which set of tests is open for drafting: a stage's key, "" for the product's specification.
  const [open, setOpen] = useState<string | null>(focus ?? null);
  const toggle = (key: string) => setOpen((now) => (now === key ? null : key));
  const usesProduct = stages.some((s) => s.kind === "TESTED" && !s.tests?.own);

  useEffect(() => {
    if (focus === null || focus === undefined) return;
    setOpen(focus);
    const target = focus === "" ? document.getElementById("product-spec")
      : document.querySelector(`[data-tests-key="${CSS.escape(focus)}"]`);
    target?.scrollIntoView({ block: "start" });
  }, [focus]);

  const openProductSpec = () => {
    setOpen("");
    window.setTimeout(() => document.getElementById("product-spec")?.scrollIntoView({ block: "start", behavior: "smooth" }), 50);
  };

  return (
    <div className="sb-all">
      {stages.length === 0 ? (
        <EmptyState
          title="No QC stages"
          sub={data.can_manage
            ? "Add the stages each batch goes through, as its batch record has them: Bulking, Drying, Compression…"
            : "No stages are set up for this product. Batches are released on their samples alone."}
        />
      ) : (
        <ol className="sb-list">
          {stages.map((s) => (
            <li className="sb" key={s.id} data-tests-key={s.key}>
              <div className="sb-head">
                <span className="qcs-num" aria-hidden="true">{s.order}</span>
                <div className="sb-title">
                  <b>{s.name}</b>
                  <span className="badge muted">{modeLabel(s)}</span>
                  <span className={`badge ${s.required ? "info" : "muted"}`}>{s.required ? "Required for release" : "Optional"}</span>
                  {s.after_previous && <span className="cell-sub">⏸ Waits for the stages before it</span>}
                </div>
                {onEdit && !readOnly && (
                  <>
                    <div className="spacer" />
                    <button type="button" className="ghost small" onClick={() => onEdit(s.id)}
                      title="Change this stage. Saving makes a new version; batches already created keep theirs.">
                      Change
                    </button>
                  </>
                )}
              </div>
              {s.description && <div className="cell-sub sb-desc">{s.description}</div>}

              {s.kind === "RECORDED" && s.signoffs.length > 0 && (
                <div className="sb-body">
                  {s.steps.map((st) => (
                    <div className="rec-step" key={st.id}>
                      <div className="rec-step-head">
                        <span className="rec-step-num">{st.order}</span>
                        <b>{st.title}</b>
                      </div>
                      {st.instructions && <div className="rec-instructions">{st.instructions}</div>}
                      {st.checkpoints.length > 0 && (
                        <div className="sb-points sb-indent" role="table" aria-label={`${st.title} check points`}>
                          {st.checkpoints.map((cp) => (
                            <div className="sb-point" role="row" key={cp.id}>
                              <span className="sb-point-name" role="cell">
                                {cp.label}{!cp.required && <span className="note"> (optional)</span>}
                              </span>
                              <span className="cell-sub" role="cell">
                                {cp.kind_name || KIND_TEXT[cp.kind] || cp.kind_label}{cp.unit && cp.kind === "NUMBER" ? `, ${cp.unit}` : ""}
                                {cp.kind === "CHOICE" && `: ${cp.choices.map((c) => c.label).join(" / ")}`}
                              </span>
                              <span className="sb-point-limit" role="cell">{cp.limit_text || "—"}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                  <div className="sb-signoffs" aria-label="Sign-off columns">
                    <span className="sb-where">{s.sign_each_step ? "Signed under every step:" : "Signed once for the stage:"}</span>
                    {s.signoffs.map((so, i) => (
                      <span className="sb-signoff" key={so.id}>
                        {i > 0 && <span className="sb-arrow" aria-hidden="true">→</span>}
                        <b>{so.title}{so.holder ? ` (${so.holder})` : ""}</b>
                        <span className="cell-sub">{so.role}</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {s.kind === "TESTED" && (
                <div className="sb-body">
                  <div className="sb-tests-head">
                    <b>
                      {s.tests
                        ? s.tests.own ? `Its own tests, version ${s.tests.version}` : `The product's specification, version ${s.tests.version}`
                        : "No specification in force yet"}
                    </b>
                    <div className="spacer" />
                    {data.can_spec && !readOnly && (
                      <>
                        {!s.tests?.own && (
                          <button type="button" className="ghost small" onClick={openProductSpec}>Change the product's specification</button>
                        )}
                        <button type="button" className="ghost small" onClick={() => toggle(s.key)}>
                          {open === s.key ? "Close" : s.tests?.own || s.own_tests?.draft ? "Change its tests" : "Give it its own tests"}
                        </button>
                      </>
                    )}
                  </div>
                  {s.tests && <TestList spec={s.tests} />}
                  {!s.tests?.own && (
                    <div className="cell-sub">
                      Until it has tests of its own in force, its samples are tested on the product's specification
                      {s.own_tests?.draft ? " (its own are being drafted)" : ""}.
                    </div>
                  )}
                  {open === s.key && (
                    <div className="sb-manager">
                      <SpecManager productId={productId} stageKey={s.key} stageName={s.name} onChanged={onChanged} />
                    </div>
                  )}
                </div>
              )}

              {s.kind === "RECORDED" && s.signoffs.length === 0 && (
                <div className="sb-body cell-sub">QA records it passed or failed on each batch, with remarks and a password.</div>
              )}
            </li>
          ))}
        </ol>
      )}

      {!readOnly && (
      <section className="sb sb-product" id="product-spec" aria-label="Product specification">
        <div className="sb-head">
          <span className="qcs-num sb-spec-mark" aria-hidden="true">✓</span>
          <div className="sb-title">
            <b>Product specification</b>
            <span className="badge muted">Certificate of Analysis</span>
          </div>
          <div className="spacer" />
          {data.can_spec && (
            <button type="button" className="ghost small" onClick={() => toggle("")}>
              {open === "" ? "Close" : data.product_spec ? "Change the specification" : "Set up the specification"}
            </button>
          )}
        </div>
        <div className="cell-sub sb-desc">
          {usesProduct
            ? "The stages above without tests of their own are tested on these, and so is a sample registered without a stage."
            : stages.length
              ? "A sample registered without a stage is tested on these, and its Certificate of Analysis prints them."
              : "Every sample of this product is tested on these, and its Certificate of Analysis prints them."}
        </div>
        <div className="sb-body">
          {data.product_spec ? (
            <>
              <b className="sb-spec-label">{data.product_spec.label}</b>
              <TestList spec={data.product_spec} />
            </>
          ) : (
            <div className="cell-sub">No specification is in force yet: samples of this product cannot be registered until one is.</div>
          )}
          {open === "" && (
            <div className="sb-manager">
              <SpecManager productId={productId} stageKey="" onChanged={onChanged} />
            </div>
          )}
        </div>
      </section>
      )}
    </div>
  );
}
