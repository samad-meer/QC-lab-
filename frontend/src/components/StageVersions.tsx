import { useState } from "react";
import { apiGet } from "../api";
import type { ProductStagesResponse, QcStageVersionView } from "../types";
import { fmtDateTime } from "../util";
import { Message, TableSkeleton } from "./Feedback";
import StagesView from "./StagesView";

/**
 * Every version of a product's QC stages, newest first. Each opens as it was saved,
 * with what it changed from the one before; batches keep the version they began on.
 */
export default function StageVersions({ data, productId }: { data: ProductStagesResponse; productId: number }) {
  const [open, setOpen] = useState<number | null>(null);
  const [loaded, setLoaded] = useState<Record<number, QcStageVersionView>>({});
  const [error, setError] = useState("");

  const toggle = async (version: number) => {
    if (open === version) {
      setOpen(null);
      return;
    }
    setOpen(version);
    setError("");
    if (!loaded[version]) {
      try {
        const v = await apiGet<QcStageVersionView>(`/api/products/${productId}/qc-stages/versions/${version}/`);
        setLoaded((all) => ({ ...all, [version]: v }));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not open that version.");
      }
    }
  };

  return (
    <details className="qcs-versions" open={data.versions.length > 1 || undefined}>
      <summary>Versions ({data.versions.length})</summary>
      <p className="cell-sub" style={{ margin: "6px 0 10px" }}>
        Each change is saved as a new version. A batch keeps the version in force when it was created, so changing the
        stages never alters a batch already under way; new batches get the newest.
      </p>
      <ol className="ver-list">
        {data.versions.map((v) => {
          const view = loaded[v.version];
          const current = v.version === data.current?.version;
          return (
            <li key={v.version} className={`ver${open === v.version ? " open" : ""}`}>
              <div className="ver-head">
                <b>Version {v.version}</b>
                {current && <span className="badge pass">In use for new batches</span>}
                <span className="cell-sub">
                  {fmtDateTime(v.created_at)} · {v.created_by} · {v.stage_count} stage{v.stage_count === 1 ? "" : "s"} ·{" "}
                  {v.batch_count} batch{v.batch_count === 1 ? "" : "es"} on it
                </span>
                <div className="spacer" />
                <button type="button" className="ghost small" onClick={() => void toggle(v.version)}
                  aria-expanded={open === v.version}>
                  {open === v.version ? "Close" : "View"}
                </button>
              </div>
              <div className="ver-reason">“{v.reason}”</div>
              {open === v.version && (
                <div className="ver-body">
                  {error && <Message kind="error">{error}</Message>}
                  {!view ? !error && <TableSkeleton /> : (
                    <>
                      <div className="ver-changes">
                        <b>{v.version === 1 ? "What it set up" : `What changed from version ${v.version - 1}`}</b>
                        <ul>{view.changes.map((c) => <li key={c}>{c}</li>)}</ul>
                      </div>
                      <StagesView data={{ ...data, current: view, can_spec: false }} productId={productId}
                        onChanged={() => undefined} readOnly />
                    </>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </details>
  );
}
