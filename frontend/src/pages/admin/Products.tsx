import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiPatch, apiPost } from "../../api";
import { useAuth } from "../../auth";
import { Message } from "../../components/Feedback";
import Field from "../../components/Field";
import ListCard from "../../components/list/ListCard";
import TextFilter from "../../components/list/TextFilter";
import { useToast } from "../../components/Toast";
import type { CertificateTemplateRow, Page, ProductMasterRow, Section } from "../../types";
import { useList, useUrlFilters } from "../../useList";
import ModalBackdrop from "../../components/ModalBackdrop";

const DOSAGE_FORMS = [
  "Tablet", "Capsule", "Syrup", "Suspension", "Injection", "Cream", "Ointment", "Sachet", "Powder", "Raw material",
];
/** The forms offered as one-click suggestions; the box lists the rest as you type. */
const COMMON_FORMS = ["Tablet", "Capsule", "Syrup", "Suspension", "Injection", "Cream"];

const PACK_SIZES = [
  "10 × 10 tablets (blister)", "3 × 10 tablets (Alu-Alu blister)", "1 × 10 capsules (blister)", "30 tablets (bottle)",
  "60 ml bottle", "120 ml bottle", "5 × 1 ml ampoules", "20 g tube", "25 kg drum", "Bulk",
];

const SHELF_LIVES = ["12", "18", "24", "36"];

const STORAGE = [
  { label: "Below 30 °C", value: "Store below 30 °C. Protect from light and moisture." },
  { label: "Below 25 °C", value: "Store below 25 °C. Protect from light." },
  { label: "2–8 °C", value: "Store at 2–8 °C in a refrigerator. Do not freeze." },
  { label: "Cool, dry place", value: "Store in a cool, dry place, in a well-closed container." },
];

/** What each kind of material means, shown under the choice. */
const KINDS: Record<string, string> = {
  RAW_MATERIAL: "An active ingredient or excipient, tested before it is used",
  PACKAGING: "Blisters, bottles, cartons or labels",
  IN_PROCESS: "Granules, blend, cores or bulk, taken during manufacture",
  FINISHED_PRODUCT: "Packed and ready for batch release",
  STABILITY: "Kept and tested at intervals through its shelf life",
};

/** A code made from the name and strength: "Paracetamol 500 mg Tablets" gives PAR-500. Only offered, never filled in. */
function suggestCode(name: string, strength: string): string {
  const letters = (name.trim().split(/\s+/)[0] ?? "").replace(/[^A-Za-z]/g, "").slice(0, 3).toUpperCase();
  if (letters.length < 2) return "";
  const number = (strength.match(/\d+(?:\.\d+)?/) ?? name.match(/\d+(?:\.\d+)?/))?.[0];
  return number ? `${letters}-${number}` : letters;
}

/** Common values for a field, one click each. The one already chosen shows as pressed. */
function Suggestions({ field, options, value, onPick }: {
  field: string;
  options: { label: string; value: string }[];
  value: string;
  onPick: (value: string) => void;
}) {
  return (
    <div className="suggest" role="group" aria-label={`Suggestions for ${field}`}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          className="chip-toggle"
          aria-pressed={value.trim() === o.value}
          title={o.label === o.value ? undefined : o.value}
          onClick={() => onPick(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

interface Extras {
  sample_types: { key: string; label: string }[];
  can_manage: boolean;
}

const BLANK = {
  code: "", name: "", generic_name: "", section_id: "", sample_type: "", dosage_form: "", strength: "",
  pack_size: "", storage_condition: "", shelf_life_months: "",
};

function ProductModal({
  editing,
  sampleTypes,
  onDone,
  onClose,
}: {
  editing: ProductMasterRow | null;
  sampleTypes: Extras["sample_types"];
  onDone: () => void;
  onClose: () => void;
}) {
  const toast = useToast();
  const { can } = useAuth();
  const [templates, setTemplates] = useState<CertificateTemplateRow[]>([]);
  const [templateId, setTemplateId] = useState(editing?.certificate_template_id ? String(editing.certificate_template_id) : "");
  const [f, setF] = useState(
    editing
      ? {
          code: editing.code, name: editing.name, generic_name: editing.generic_name,
          section_id: String(editing.section_id), sample_type: editing.sample_type,
          dosage_form: editing.dosage_form, strength: editing.strength, pack_size: editing.pack_size,
          storage_condition: editing.storage_condition,
          shelf_life_months: editing.shelf_life_months === null ? "" : String(editing.shelf_life_months),
        }
      : BLANK,
  );
  const [active, setActive] = useState(editing?.is_active ?? true);
  const [sections, setSections] = useState<Section[]>([]);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (key: keyof typeof BLANK, value: string) => setF((p) => ({ ...p, [key]: value }));
  const codeIdea = suggestCode(f.name, f.strength);
  const section = sections.find((s) => String(s.id) === f.section_id);
  const sectionHint = editing
    ? "Fixed once created"
    : section
      ? `Its sample numbers will start ${section.code}-${new Date().getFullYear()}-…, and only analysts trained for ${section.name} can test it.`
      : "Which part of the lab tests it. Fixed once created.";

  useEffect(() => {
    apiGet<Section[]>("/api/sections/").then(setSections).catch(() => setSections([]));
    apiGet<Page<CertificateTemplateRow>>("/api/certificate-templates/?page_size=200")
      .then((page) => setTemplates(page.results))
      .catch(() => setTemplates([]));
  }, []);

  const save = async () => {
    setBusy(true);
    setError("");
    const { code, section_id, ...rest } = f;
    const details = can("template.manage") ? { ...rest, certificate_template_id: templateId || null } : rest;
    try {
      if (editing) {
        await apiPatch(`/api/product-master/${editing.id}/`, { ...details, is_active: active, reason });
      } else {
        await apiPost("/api/product-master/", { ...details, code, section_id: Number(section_id) });
      }
      toast("ok", editing ? `${f.name} updated` : `${f.name} added`,
        editing ? undefined : "Next, give it a specification so samples can be registered.");
      onDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the product.");
      setBusy(false);
    }
  };

  return (
    <ModalBackdrop onClick={() => !busy && onClose()}>
      <div className="modal wide product-modal" role="dialog" aria-modal="true" aria-labelledby="product-modal-title"
        onClick={(e) => e.stopPropagation()}>
        <h3 id="product-modal-title">{editing ? `Edit ${editing.name}` : "New product"}</h3>
        {!editing && (
          <p className="modal-sub">
            Only the code, section and name are needed to add it. The rest prints on its certificates or helps
            searches and reports: fill in what you know, and the rest later.
          </p>
        )}

        <section className="modal-part" aria-labelledby="product-part-identity">
          <h4 id="product-part-identity">What it is called</h4>
          <div className="form-row">
            <div className="field-stack">
              <Field
                label="Product code"
                required
                hint={editing ? "Fixed once created" : "Short and unique. Fixed once created."}
                info={<>
                  <p>Your own code for the product, as production and the batch records use it. Letters, numbers
                    and dashes, up to 30 characters.</p>
                  <p>It cannot be changed later, because samples and certificates refer to it.</p>
                  <p>For example <b>PCM-500</b>, <b>AMX-250-SUS</b>, <b>IBU-API</b>.</p>
                </>}
              >
                <input value={f.code} onChange={(e) => set("code", e.target.value)} disabled={!!editing}
                  autoFocus={!editing} maxLength={30} placeholder="e.g. PCM-500" />
              </Field>
              {!editing && !f.code.trim() && codeIdea && (
                <div className="suggest">
                  <span className="suggest-label">From the name:</span>
                  <button type="button" className="chip-toggle" onClick={() => set("code", codeIdea)}>
                    Use {codeIdea}
                  </button>
                </div>
              )}
            </div>
            <Field
              label="Section"
              required
              hint={sectionHint}
              info={<>
                <p>The part of the lab that tests it. The front desk picks the section first and then sees its
                  products, and only analysts trained for that section can be given its samples.</p>
                <p>Sections are set under <b>Admin → Sections</b>.</p>
              </>}
            >
              <select value={f.section_id} onChange={(e) => set("section_id", e.target.value)} disabled={!!editing}>
                <option value="">— choose section —</option>
                {sections.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.code})</option>)}
              </select>
            </Field>
          </div>
          <Field label="Product name" required hint="As it prints on the certificate: name, strength and form">
            <input value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="e.g. Paracetamol 500 mg Tablets" />
          </Field>
        </section>

        <section className="modal-part" aria-labelledby="product-part-material">
          <h4 id="product-part-material">What it is made of</h4>
          <div className="form-row">
            <Field label="Generic name" hint="The active ingredient, so a search finds every brand of it">
              <input value={f.generic_name} onChange={(e) => set("generic_name", e.target.value)} placeholder="e.g. Paracetamol" />
            </Field>
            <Field
              label="Kind of material"
              hint={KINDS[f.sample_type] ?? "Sorts the reports, e.g. finished product or raw material"}
              info={<ul className="info-list">
                {sampleTypes.map((t) => <li key={t.key}><b>{t.label}</b>: {KINDS[t.key] ?? ""}</li>)}
              </ul>}
            >
              <select value={f.sample_type} onChange={(e) => set("sample_type", e.target.value)}>
                <option value="">— not set —</option>
                {sampleTypes.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
              </select>
            </Field>
          </div>
          <div className="form-row">
            <div className="field-stack">
              <Field label="Dosage form" hint="Prints on the certificate">
                <input list="dosage-forms" value={f.dosage_form} onChange={(e) => set("dosage_form", e.target.value)}
                  placeholder="e.g. Tablet" />
                <datalist id="dosage-forms">{DOSAGE_FORMS.map((d) => <option key={d} value={d} />)}</datalist>
              </Field>
              <Suggestions field="Dosage form" value={f.dosage_form} onPick={(v) => set("dosage_form", v)}
                options={COMMON_FORMS.map((d) => ({ label: d, value: d }))} />
            </div>
            <Field label="Strength" hint="Prints on the certificate, beside the dosage form">
              <input value={f.strength} onChange={(e) => set("strength", e.target.value)} placeholder="e.g. 500 mg, or 250 mg/5 ml" />
            </Field>
          </div>
        </section>

        <section className="modal-part" aria-labelledby="product-part-pack">
          <h4 id="product-part-pack">Pack and storage</h4>
          <div className="form-row">
            <Field label="Pack size" hint="How one pack is made up">
              <input list="pack-sizes" value={f.pack_size} onChange={(e) => set("pack_size", e.target.value)}
                placeholder="e.g. 10 × 10 tablets (blister)" />
              <datalist id="pack-sizes">{PACK_SIZES.map((p) => <option key={p} value={p} />)}</datalist>
            </Field>
            <div className="field-stack">
              <Field label="Shelf life (months)" hint="From manufacture to expiry">
                <input type="number" min={1} max={600} value={f.shelf_life_months}
                  onChange={(e) => set("shelf_life_months", e.target.value)} placeholder="e.g. 24" />
              </Field>
              <Suggestions field="Shelf life" value={f.shelf_life_months} onPick={(v) => set("shelf_life_months", v)}
                options={SHELF_LIVES.map((m) => ({ label: `${m} months`, value: m }))} />
            </div>
          </div>
          <div className="field-stack">
            <Field label="Storage condition" hint="Filled in for each sample at the front desk, and printed on its certificate">
              <input value={f.storage_condition} onChange={(e) => set("storage_condition", e.target.value)}
                placeholder="e.g. Store below 30 °C. Protect from light and moisture." />
            </Field>
            <Suggestions field="Storage condition" value={f.storage_condition} options={STORAGE}
              onPick={(v) => set("storage_condition", v)} />
          </div>
        </section>

        {can("template.manage") && (
          <section className="modal-part" aria-labelledby="product-part-certificate">
            <h4 id="product-part-certificate">Certificate</h4>
            <Field label="Certificate template"
              hint="The layout its certificates print with. Keep the default unless this product needs its own title or footer.">
              <select value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
                <option value="">The default</option>
                {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            </Field>
          </section>
        )}
        {editing && (
          <>
            <label className="cl-flag">
              <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
              Active — offered at the front desk
            </label>
            <Field label="Why is it being changed?" required hint="Kept on the record with the old values.">
              <input value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
          </>
        )}
        {error && <Message kind="error">{error}</Message>}
        <div className="actions">
          <button className="subtle" disabled={busy} onClick={onClose}>Cancel</button>
          <button className="primary" disabled={busy || !f.code.trim() || !f.name.trim() || !f.section_id || (!!editing && !reason.trim())}
            onClick={() => void save()}>
            {busy ? "Saving…" : editing ? "Save changes" : "Add product"}
          </button>
        </div>
      </div>
    </ModalBackdrop>
  );
}

/** The product master: one place for what each product is. */
export default function Products() {
  const { params, setFilters } = useUrlFilters();
  const q = params.get("q") ?? "";
  const list = useList<ProductMasterRow, Extras>("/api/product-master/", { query: q ? { q } : {} });
  const [editing, setEditing] = useState<ProductMasterRow | null>(null);
  const [creating, setCreating] = useState(false);
  const canManage = list.data?.can_manage ?? false;

  return (
    <>
      <div className="page-head">
        <h1>Products</h1>
        <p className="sub">
          What each product is, in one place. Products are never deleted, because samples and
          certificates point at them; one no longer made is set inactive.
        </p>
      </div>

      <ListCard
        title="Product master"
        exportable
        list={list}
        failure="Could not load the products"
        emptyTitle="No products match"
        actions={canManage && <button className="primary small" onClick={() => setCreating(true)}>+ New product</button>}
        filters={
          <TextFilter label="Search" value={q} placeholder="Code, name, dosage form or strength"
            onChange={(text) => setFilters({ q: text })} />
        }
      >
        {(rows) => (
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>
                  <th>Code</th><th>Product</th><th>Form · strength</th><th>Section</th>
                  <th>Specification</th><th>QC stages</th><th>Batches</th><th>Samples</th><th />
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.id} style={{ opacity: p.is_active ? 1 : 0.55 }}>
                    <td className="num">{p.code}</td>
                    <td>
                      <div className="cell-title">
                        <Link to={`/products/${p.id}`}>{p.name}</Link>
                        {!p.is_active && <span className="badge muted" style={{ marginLeft: 7 }}>inactive</span>}
                      </div>
                      <div className="cell-sub">{p.sample_type_label || "Kind not set"}</div>
                    </td>
                    <td>{[p.dosage_form, p.strength].filter(Boolean).join(" · ") || "—"}</td>
                    <td>{p.section}</td>
                    <td>
                      {p.current_spec_version ? (
                        <Link to={`/products/${p.id}`}>Version {p.current_spec_version}</Link>
                      ) : (
                        <Link to={`/products/${p.id}`} className="link-btn" title="No specification in force yet">Set up</Link>
                      )}
                    </td>
                    <td>
                      {p.qc_stage_count ? (
                        <Link to={`/products/${p.id}#qc-stages`}>{p.qc_stage_count} stage{p.qc_stage_count === 1 ? "" : "s"}</Link>
                      ) : (
                        <Link to={`/products/${p.id}#qc-stages`} className="link-btn" title="No QC stages yet">Set up</Link>
                      )}
                    </td>
                    <td className="num"><Link to={`/batches?product=${p.id}`}>{p.batch_count}</Link></td>
                    <td className="num">{p.sample_count}</td>
                    <td>
                      {canManage && <button className="subtle small" onClick={() => setEditing(p)}>Edit</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ListCard>

      {(creating || editing) && (
        <ProductModal
          editing={editing}
          sampleTypes={list.data?.sample_types ?? []}
          onDone={() => void list.reload()}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
        />
      )}
    </>
  );
}
