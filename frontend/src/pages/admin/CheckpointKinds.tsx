import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiPatch } from "../../api";
import { BUILT_IN, KindModal } from "../../components/CheckpointKindForm";
import type { KindDraft } from "../../components/CheckpointKindForm";
import { EmptyState, Message, TableSkeleton } from "../../components/Feedback";
import { useToast } from "../../components/Toast";
import type { CheckpointInUse, CheckpointPreset } from "../../types";

/** What makes a kind of value: what it is based on, its unit, decimals, limits or options. */
type Definition = Pick<CheckpointPreset, "kind" | "unit" | "min_value" | "max_value" | "decimals" | "choices">;

const NUMERIC = ["NUMBER", "PERCENT"];

function details(k: Definition): string {
  if (k.kind === "CHOICE") {
    return k.choices.map((c) => (c.ok ? c.label : `${c.label} (flagged)`)).join(" / ");
  }
  const unit = k.kind === "PERCENT" ? "%" : k.unit;
  const limits = k.min_value !== null && k.max_value !== null ? `${k.min_value} – ${k.max_value}`
    : k.min_value !== null ? `NLT ${k.min_value}` : k.max_value !== null ? `NMT ${k.max_value}` : "";
  return [unit && `in ${unit}`, limits && `limit ${limits}${unit ? ` ${unit}` : ""}`,
    NUMERIC.includes(k.kind) ? `${k.decimals} decimal${k.decimals === 1 ? "" : "s"}` : ""].filter(Boolean).join(" · ") || "—";
}

/** Whether one of the lab's kinds already says what a row of check points says. */
function sameDefinition(a: Definition, b: Definition): boolean {
  if (a.kind !== b.kind) return false;
  if (a.kind === "NUMBER" && a.unit.trim() !== b.unit.trim()) return false;
  if (NUMERIC.includes(a.kind)) return a.min_value === b.min_value && a.max_value === b.max_value && a.decimals === b.decimals;
  const options = (d: Definition) => JSON.stringify(d.choices.map((o) => [o.label.trim().toLowerCase(), o.ok]));
  return a.kind === "CHOICE" && options(a) === options(b);
}

/** A unit says what is measured: kg is a weight, °C a temperature. */
const MEASURES: Record<string, string> = {
  kg: "Weight", g: "Weight", mg: "Weight", mcg: "Weight", "µg": "Weight", L: "Volume", mL: "Volume", ml: "Volume",
  "°C": "Temperature", Pa: "Pressure", kPa: "Pressure", bar: "Pressure", mbar: "Pressure", rpm: "Speed",
  min: "Duration", h: "Duration", s: "Duration", mm: "Length", N: "Hardness", kp: "Hardness",
};
const LINKING = new Set(["after", "before", "of", "in", "at", "for", "the", "and", "on", "to"]);

/** A name to start from: the check point's own when there is one, else what they share. */
function suggestedName(g: CheckpointInUse): string {
  if (g.kind === "CHOICE") return g.choices.map((o) => o.label).join(" / ").slice(0, 60);
  if (g.labels.length === 1 && g.labels[0].length <= 60) return g.labels[0];
  const words = g.labels.map((l) => l.split(" "));
  const shared: string[] = [];
  for (let i = 0; words.every((w) => w[i] !== undefined && w[i].toLowerCase() === words[0][i].toLowerCase()); i += 1) {
    shared.push(words[0][i]);
  }
  while (shared.length && LINKING.has(shared[shared.length - 1].toLowerCase())) shared.pop();
  if (shared.length) return shared.join(" ").slice(0, 60);
  if (g.kind === "NUMBER" && g.unit) return `${MEASURES[g.unit] ?? "Amount"} in ${g.unit}`;
  return g.labels[0].slice(0, 60);
}

function draftOf(g: CheckpointInUse): Partial<KindDraft> {
  return {
    name: suggestedName(g), kind: g.kind, unit: g.unit, decimals: g.decimals,
    min_value: g.min_value ?? "", max_value: g.max_value ?? "",
    choices: g.choices.map((o) => ({ ...o })),
  };
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const SHOWN = 3;

/** The check points of one row: the first few, and the rest on asking. */
function Names({ labels }: { labels: string[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? labels : labels.slice(0, SHOWN);
  return (
    <div className="ck-names">
      {shown.map((l) => <span key={l} title={l}>{l}</span>)}
      {labels.length > SHOWN && (
        <button type="button" className="link-btn" onClick={() => setAll(!all)}>
          {all ? "Show fewer" : `and ${labels.length - SHOWN} more`}
        </button>
      )}
    </div>
  );
}

/** Where a row is used: each product once, with its stages; the first few, and the rest on asking. */
function UsedIn({ places }: { places: CheckpointInUse["used_in"] }) {
  const [all, setAll] = useState(false);
  const byProduct = new Map<number, { name: string; stages: string[] }>();
  for (const p of places) {
    const entry = byProduct.get(p.product_id) ?? { name: p.product, stages: [] };
    entry.stages.push(p.stage);
    byProduct.set(p.product_id, entry);
  }
  const products = [...byProduct.entries()];
  return (
    <div className="ck-used">
      {(all ? products : products.slice(0, SHOWN)).map(([id, p]) => (
        <span key={id}>
          <Link to={`/products/${id}`}>{p.name}</Link>
          <small title={p.stages.join(", ")}>
            {p.stages.slice(0, 2).join(", ")}{p.stages.length > 2 ? ` and ${p.stages.length - 2} more` : ""}
          </small>
        </span>
      ))}
      {products.length > SHOWN && (
        <button type="button" className="link-btn" onClick={() => setAll(!all)}>
          {all ? "Show fewer" : `and ${plural(products.length - SHOWN, "more product")}`}
        </button>
      )}
    </div>
  );
}

/**
 * The kinds of value a stage's check point can be: the built-in ones, the lab's own
 * (Temperature in °C, Mixer speed in rpm, Complies / Does not comply), and those the
 * products' stages already use, any of which can be saved as one of the lab's own.
 */
export default function CheckpointKinds() {
  const toast = useToast();
  const [rows, setRows] = useState<CheckpointPreset[] | null>(null);
  const [inUse, setInUse] = useState<CheckpointInUse[] | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<CheckpointPreset | "new" | null>(null);
  const [start, setStart] = useState<Partial<KindDraft> | undefined>(undefined);

  const load = useCallback(async () => {
    try {
      const [kinds, used] = await Promise.all([
        apiGet<CheckpointPreset[]>("/api/checkpoint-kinds/?all=1"),
        apiGet<CheckpointInUse[]>("/api/checkpoint-kinds/in-use/"),
      ]);
      setRows(kinds);
      setInUse(used);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the kinds.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = async (k: CheckpointPreset) => {
    try {
      await apiPatch(`/api/checkpoint-kinds/${k.id}/`, { is_active: !k.is_active });
      toast("ok", k.is_active ? `“${k.name}” retired` : `“${k.name}” offered again`,
        k.is_active ? "Stages that use it keep their copy." : undefined);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change it.");
    }
  };

  const openNew = (from?: Partial<KindDraft>) => {
    setStart(from);
    setEditing("new");
  };

  const checkpoints = inUse?.reduce((n, g) => n + g.uses, 0) ?? 0;

  return (
    <>
      <div className="page-head">
        <h1>Check point kinds</h1>
        <p className="sub">
          The kinds of value a batch record can ask for. The built-in ones are always offered. The lab's own add a name,
          a unit and limits, or a choice with its acceptable answers, and are offered ready filled in in every stage's
          “Kind of value” list. A stage keeps a copy when it is saved, so changing or retiring a kind here changes no stage
          already in use.
        </p>
      </div>
      {error && <Message kind="error">{error}</Message>}

      <div className="card">
        <div className="card-head">
          <h2>The lab's own kinds</h2>
          <span className="hint">{rows ? `${rows.filter((k) => k.is_active).length} offered` : ""}</span>
          <div className="spacer" />
          <button className="primary small" onClick={() => openNew()}>+ New kind</button>
        </div>
        <div className="card-body flush">
          {!rows ? <TableSkeleton /> : rows.length === 0 ? (
            <EmptyState title="None yet"
              sub="Save one from the kinds your stages already use, below, or add a new one. A check point's “Kind of value” list also has “+ New kind…” at its end." />
          ) : (
            <div className="table-wrap">
              <table className="grid">
                <thead><tr><th>Name</th><th>Based on</th><th>Unit, limits or options</th><th>Status</th><th /></tr></thead>
                <tbody>
                  {rows.map((k) => (
                    <tr key={k.id}>
                      <td className="cell-title">{k.name}</td>
                      <td>{k.kind_label}</td>
                      <td>{details(k)}</td>
                      <td><span className={`badge ${k.is_active ? "pass" : "muted"}`}>{k.is_active ? "Offered" : "Retired"}</span></td>
                      <td>
                        <div className="actions-bar row-icons">
                          <button className="ghost small" onClick={() => setEditing(k)}>Edit</button>
                          <button className="subtle small" onClick={() => void toggle(k)}>{k.is_active ? "Retire" : "Offer again"}</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Already in your stages</h2>
          <span className="hint">
            {inUse ? `${plural(checkpoints, "check point")} in the products' current stages, as ${plural(inUse.length, "kind")} of value` : ""}
          </span>
        </div>
        <div className="card-body flush">
          {!inUse ? <TableSkeleton cols={4} /> : inUse.length === 0 ? (
            <EmptyState title="No check points yet"
              sub="They are added to a product's batch-record stages, on the product's page." />
          ) : (
            <div className="table-wrap">
              <table className="grid ck-table">
                <thead><tr><th>Kind of value</th><th>Check points</th><th>Used in</th><th /></tr></thead>
                <tbody>
                  {inUse.map((g) => {
                    const saved = rows?.find((k) => sameDefinition(k, g));
                    const savable = NUMERIC.includes(g.kind) || g.kind === "CHOICE";
                    return (
                      <tr key={`${g.kind}-${g.unit}-${g.min_value}-${g.max_value}-${g.decimals}-${JSON.stringify(g.choices)}`}>
                        <td>
                          <div className="cell-title">{g.kind_label}</div>
                          <div className="cell-sub">{details(g)}</div>
                          {g.kind_names.length > 0 && <div className="cell-sub">From “{g.kind_names.join("”, “")}”</div>}
                        </td>
                        <td>
                          <div className="ck-count">{plural(g.uses, "check point")}</div>
                          <Names labels={g.labels} />
                        </td>
                        <td><UsedIn places={g.used_in} /></td>
                        <td className="ck-action">
                          {saved ? (
                            <span className={`badge ${saved.is_active ? "pass" : "muted"}`} title={saved.is_active ? "Offered in every stage" : "Retired"}>
                              Saved as “{saved.name}”
                            </span>
                          ) : savable ? (
                            <button className="ghost small" onClick={() => openNew(draftOf(g))}>Save as a kind</button>
                          ) : (
                            <span className="cell-sub" title="Offered in every stage as it is">Built-in</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Built-in kinds</h2>
          <span className="hint">Always offered in every stage; nothing to set up</span>
        </div>
        <div className="card-body">
          <div className="ck-builtins">
            {BUILT_IN.map((k) => (
              <div key={k.value} className="ck-builtin">
                <b>{k.label}</b>
                <span>{k.hint}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {editing && (
        <KindModal
          editing={editing === "new" ? undefined : editing}
          start={editing === "new" ? start : undefined}
          onSaved={(k) => {
            toast("ok", editing === "new" ? `“${k.name}” added` : `“${k.name}” saved`,
              editing === "new" ? "It is offered in every stage's “Kind of value” list." : undefined);
            setEditing(null);
            setStart(undefined);
            void load();
          }}
          onClose={() => {
            setEditing(null);
            setStart(undefined);
          }}
        />
      )}
    </>
  );
}
