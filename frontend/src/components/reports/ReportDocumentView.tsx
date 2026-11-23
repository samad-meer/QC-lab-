import type { ReportDocument, ReportPart } from "../../types";
import { Message } from "../Feedback";
import { TrendChart } from "./LineCharts";
import ReportCell from "./ReportCell";

function Part({ part }: { part: ReportPart }) {
  if (part.kind === "facts") {
    return (
      <div className="kv">
        {part.items.map((f) => (
          <div key={f.label}>
            <div className="k">{f.label}</div>
            <div className="v">{f.value}</div>
          </div>
        ))}
      </div>
    );
  }
  if (part.kind === "note") return <Message kind="info">{part.text}</Message>;
  if (part.kind === "trend") return <TrendChart trend={part} />;
  return (
    <div className="doc-table">
      {part.heading && <h3>{part.heading}</h3>}
      {part.rows.length === 0 ? (
        <p className="hint">{part.empty}</p>
      ) : (
        <div className="table-wrap">
          <table className="grid">
            <thead>
              <tr>{part.columns.map((c) => <th key={c.key}>{c.label}</th>)}</tr>
            </thead>
            <tbody>
              {part.rows.map((row, i) => (
                <tr key={i}>
                  {part.columns.map((c) => <td key={c.key}><ReportCell cell={row[c.key]} /></td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** A report about one thing. The PDF is drawn from exactly these sections. */
export default function ReportDocumentView({ doc }: { doc: ReportDocument }) {
  return (
    <>
      {doc.sections.map((section) => (
        <section className="card" key={section.title} aria-label={section.title}>
          <div className="card-head"><h2>{section.title}</h2></div>
          <div className="card-body doc-parts">
            {section.parts.map((part, i) => <Part key={i} part={part} />)}
          </div>
        </section>
      ))}
    </>
  );
}
