import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiGet } from "../../api";
import { Message, TableSkeleton } from "../../components/Feedback";
import DateRangeFilter from "../../components/list/DateRangeFilter";
import ExportButtons from "../../components/reports/ExportButtons";
import ReportDocumentView from "../../components/reports/ReportDocumentView";
import type { ReportDocument } from "../../types";
import { useDateRange } from "../../useList";

const PLACES = {
  sample: { label: "Sample Register", to: "/reports/sample-register" },
  batch: { label: "Batch QC Summary", to: "/reports/batches" },
  product: { label: "Product Quality History", to: "/reports/product-history" },
};

/** A sample's history, a batch's summary or a product's history. */
export default function ReportDocumentPage({ kind }: { kind: keyof typeof PLACES }) {
  const { id = "" } = useParams();
  const range = useDateRange({ defaultPeriod: "all" });
  const [doc, setDoc] = useState<ReportDocument | null>(null);
  const [error, setError] = useState("");

  const url =
    kind === "sample" ? `/api/reports/documents/sample/${id}/`
    : kind === "batch" ? `/api/reports/documents/batch/${id}/`
    : `/api/reports/documents/product/${id}/?${range.search}`;

  useEffect(() => {
    let current = true;
    apiGet<ReportDocument>(url)
      .then((d) => {
        if (!current) return;
        setDoc(d);
        setError("");
      })
      .catch((err) => {
        if (!current) return;
        setDoc(null);
        setError(err instanceof Error ? err.message : "Could not load this report.");
      });
    return () => {
      current = false;
    };
  }, [url]);

  const place = PLACES[kind];
  return (
    <>
      <div className="breadcrumb">
        <Link to="/reports">Reports</Link> / <Link to={place.to}>{place.label}</Link>
        {doc && <> / {doc.reference}</>}
      </div>
      {error && <Message kind="error">{error}</Message>}
      {!doc && !error && <div className="card"><div className="card-body flush"><TableSkeleton rows={6} /></div></div>}
      {doc && (
        <>
          <div className="page-head">
            <h1>{doc.title}: {doc.reference}</h1>
            <p className="sub">{doc.subtitle}</p>
          </div>
          <div className="actions-bar" style={{ marginBottom: 16 }}>
            {doc.links.map((l) => <Link key={l.to} to={l.to} className="btn-link">{l.label} →</Link>)}
            <div className="spacer" />
            {doc.can_export && <ExportButtons url={url} formats={["pdf"]} />}
          </div>
          {kind === "product" && (
            <div className="card">
              <div className="list-filters"><DateRangeFilter range={range} /></div>
            </div>
          )}
          <ReportDocumentView doc={doc} />
          <p className="report-stamp">Generated {doc.generated_at} ({doc.timezone}) for {doc.generated_by}</p>
        </>
      )}
    </>
  );
}
