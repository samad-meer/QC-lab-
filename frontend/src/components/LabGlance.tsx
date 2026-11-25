import { useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { DonutChart, WorkloadBars } from "./Charts";
import type { DonutSlice } from "./Charts";
import { Ageing, DueOutlook, EquipmentHealth, Failures, ResultsByPeriod, TurnaroundSpread } from "./InsightCharts";
import KpiStrip from "./KpiStrip";
import { TimelineChart } from "./reports/LineCharts";
import type { ReportDashboard } from "../types";

/** The stretches of time the dashboard can be asked about. The server knows the same keys. */
export type GlancePeriod = "week" | "lastweek" | "month" | "lastmonth" | "quarter";
export const GLANCE_PERIODS: { key: GlancePeriod; label: string }[] = [
  { key: "week", label: "This week" },
  { key: "lastweek", label: "Last week" },
  { key: "month", label: "This month" },
  { key: "lastmonth", label: "Last month" },
  { key: "quarter", label: "Last 90 days" },
];

/** What each part means keeps its colour on every chart: red is late or failed, amber is near or waiting, green is done. */
const DUE_COLORS: Record<string, string> = { overdue: "var(--fail)", soon: "var(--warn)", later: "var(--chart-1)" };
const CASE_COLORS: Record<string, string> = { OPEN: "var(--warn)", PENDING_CLOSURE: "var(--chart-2)", CLOSED: "var(--pass)" };
const BATCH_COLORS: Record<string, string> = {
  RELEASED: "var(--pass)", QUARANTINED: "var(--warn)", REJECTED: "var(--fail)", WAITING: "var(--chart-6)",
};
/** Parts with no meaning of their own, such as sections, take these in turn. */
const SERIES = ["var(--chart-1)", "var(--chart-3)", "var(--chart-2)", "var(--chart-4)", "var(--chart-5)", "var(--chart-6)"];

const sum = (rows: { value: number }[]) => rows.reduce((n, r) => n + r.value, 0);

type Size = "third" | "half" | "full";

function Card({ title, hint, size = "third", children }: { title: string; hint?: string; size?: Size; children: ReactNode }) {
  return (
    <section className={`glance-card ${size}`} aria-label={title}>
      <div className="glance-head">
        <h3>{title}</h3>
        {hint && <small>{hint}</small>}
      </div>
      {children}
    </section>
  );
}

type TabKey = "overview" | "workload" | "quality" | "equipment";

function readTab(): TabKey {
  try {
    const saved = window.sessionStorage.getItem("qclab-glance-tab");
    if (saved === "workload" || saved === "quality" || saved === "equipment") return saved;
  } catch { /* blocked storage: the first tab is fine */ }
  return "overview";
}

/**
 * The lab in pictures. The headline figures stay on top, each beside the period before and with a trend
 * of its own; below them, what the person is asking about: how the period went, what is waiting, what
 * failed, whether the equipment is in date. Each figure opens the records it counts, and a chart with
 * nothing to show to this person is left out rather than drawn empty.
 */
export default function LabGlance({ data, period, busy = false, onPeriod }: {
  data: ReportDashboard;
  period: GlancePeriod;
  /** The period was just changed and the new figures are on the way: the old ones stay, dimmed. */
  busy?: boolean;
  onPeriod: (next: GlancePeriod) => void;
}) {
  const c = data.charts;
  const ins = data.insights;
  const [chosen, setChosen] = useState<TabKey>(readTab);
  const passed = c.results.passed;
  const failed = c.results.failed;
  const rate = passed + failed > 0 ? Math.round((passed / (passed + failed)) * 100) : null;
  const sections = c.sections.filter((s) => s.value > 0);
  const batches = c.batches ?? [];
  const hasEquipment = Boolean(ins.equipment);

  const due: DonutSlice[] = c.due.map((d) => ({ label: d.label, value: d.value, color: DUE_COLORS[d.key] ?? SERIES[0], to: d.to }));
  const cases: DonutSlice[] = c.investigations.map((d) => ({ label: d.label, value: d.value, color: CASE_COLORS[d.key] ?? SERIES[0], to: d.to }));
  const decisions: DonutSlice[] = batches.map((d) => ({ label: d.label, value: d.value, color: BATCH_COLORS[d.key] ?? SERIES[0] }));
  const bySection: DonutSlice[] = sections.map((s, i) => ({ label: s.label, value: s.value, color: SERIES[i % SERIES.length], to: s.to }));

  // What needs someone's attention, shown on the tab that holds it.
  const equipmentLate = Object.values(ins.equipment ?? {}).reduce(
    (n, g) => n + (g?.rows.find((r) => r.key === "late")?.value ?? 0), 0);
  const openCases = c.investigations.filter((d) => d.key !== "CLOSED").reduce((n, d) => n + d.value, 0);
  const tabs: { key: TabKey; label: string; attention: number; what: string }[] = [
    { key: "overview", label: "Overview", attention: 0, what: "" },
    { key: "workload", label: "Workload", attention: ins.outlook.overdue.value, what: "samples are overdue" },
    { key: "quality", label: "Quality", attention: openCases, what: "investigations are open" },
    ...(hasEquipment ? [{ key: "equipment" as TabKey, label: "Equipment", attention: equipmentLate, what: "are past their date" }] : []),
  ];
  const tab = tabs.some((t) => t.key === chosen) ? chosen : "overview";

  const choose = (next: TabKey) => {
    setChosen(next);
    try { window.sessionStorage.setItem("qclab-glance-tab", next); } catch { /* not remembered, still shown */ }
  };
  const keys = (e: KeyboardEvent) => {
    const at = tabs.findIndex((t) => t.key === tab);
    const to = e.key === "ArrowRight" ? at + 1 : e.key === "ArrowLeft" ? at - 1 : e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : null;
    if (to === null) return;
    e.preventDefault();
    const next = tabs[(to + tabs.length) % tabs.length].key;
    choose(next);
    window.requestAnimationFrame(() => document.getElementById(`glance-tab-${next}`)?.focus());
  };

  return (
    <section className="card" aria-label="Lab at a glance">
      <div className="card-head">
        <h2>Lab at a glance</h2>
        <span className="hint">{data.label} · {data.scope}{ins.compare ? ` · changes are against ${ins.compare}` : ""}</span>
        <div className="spacer" />
        <label className="glance-period">
          <span className="sr-only">Period</span>
          <select value={period} onChange={(e) => onPeriod(e.target.value as GlancePeriod)}>
            {GLANCE_PERIODS.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
          </select>
        </label>
      </div>
      <div className="card-body glance-body">
        <div className={`glance-stack${busy ? " busy" : ""}`} aria-busy={busy}>
          <KpiStrip tiles={ins.tiles} compare={ins.compare} />

          <div className="glance-tabs" role="tablist" aria-label="Views of the lab" onKeyDown={keys}>
            {tabs.map((t) => (
              <button key={t.key} id={`glance-tab-${t.key}`} type="button" role="tab" aria-selected={tab === t.key}
                aria-controls={`glance-panel-${t.key}`} tabIndex={tab === t.key ? 0 : -1} onClick={() => choose(t.key)}>
                {t.label}
                {t.attention > 0 && (
                  <span className="glance-badge">{t.attention}<span className="sr-only"> {t.what}</span></span>
                )}
              </button>
            ))}
          </div>

          <div className="glance" role="tabpanel" id={`glance-panel-${tab}`} aria-labelledby={`glance-tab-${tab}`}>
            {tab === "overview" && (
              <>
                <Card size="half" title="Samples received and completed" hint={`per ${c.flow.unit}`}>
                  <TimelineChart data={c.flow} emptyText="No samples were received or completed in this period." />
                </Card>
                <Card size="half" title="Results entered" hint="passed and failed, per period">
                  <ResultsByPeriod data={c.outcomes} />
                </Card>
                <Card title="Samples still in the lab" hint="by due date, right now">
                  <DonutChart name="Samples still in the lab, by due date" slices={due} centerLabel="in the lab"
                    emptyText="No samples are waiting in the lab." />
                </Card>
                <Card title="Test results" hint={`entered ${data.label.toLowerCase()}`}>
                  <DonutChart
                    name="Test results entered"
                    slices={[
                      { label: "Passed", value: passed, color: "var(--pass)", to: c.results.to_passed },
                      { label: "Failed", value: failed, color: "var(--fail)", to: c.results.to_failed },
                    ]}
                    centerValue={rate === null ? "–" : `${rate}%`}
                    centerLabel="passed"
                    emptyText="No results were entered in this period."
                  />
                </Card>
                {sections.length > 1 && (
                  <Card title="Samples received by section" hint={data.label.toLowerCase()}>
                    <DonutChart name="Samples received, by section" slices={bySection} centerLabel="received" />
                  </Card>
                )}
              </>
            )}

            {tab === "workload" && (
              <>
                <Card size="full" title="Due over the next two weeks" hint="open samples, by the day they are due: click a day to open them">
                  <DueOutlook outlook={ins.outlook} />
                </Card>
                <Card size="half" title="How long samples have waited" hint="open samples, by where they are and for how long">
                  <Ageing data={ins.ageing} />
                </Card>
                <Card size="half" title="Release time" hint={`samples released ${data.label.toLowerCase()}`}>
                  <TurnaroundSpread data={ins.turnaround} />
                </Card>
                {c.analysts && c.analysts.length > 0 && (
                  <Card size="full" title="Open work by analyst" hint="samples each holds, with the part already late: for planning, not for ranking people">
                    <WorkloadBars rows={c.analysts} />
                  </Card>
                )}
              </>
            )}

            {tab === "quality" && (
              <>
                <Card size="half" title="Failures by test" hint={`failed results ${data.label.toLowerCase()}, against all entered`}>
                  <Failures rows={ins.failures.tests} empty="No results failed in this period." />
                </Card>
                <Card size="half" title="Failures by product" hint={`failed results ${data.label.toLowerCase()}, against all entered`}>
                  <Failures rows={ins.failures.products} empty="No results failed in this period." />
                </Card>
                <Card size="half" title="Investigations and deviations" hint="where they stand now">
                  <DonutChart name="Investigations and deviations" slices={cases} centerLabel="cases" emptyText="No investigations or deviations." />
                </Card>
                {sum(decisions) > 0 && (
                  <Card size="half" title="Batches registered" hint={`${data.label.toLowerCase()}, by the quality unit's decision`}>
                    <DonutChart name="Batches registered, by decision" slices={decisions} centerLabel="batches" />
                  </Card>
                )}
              </>
            )}

            {tab === "equipment" && ins.equipment && (
              <>
                {ins.equipment.instruments && (
                  <Card size="half" title="Instruments" hint="by when their calibration runs out, right now">
                    <EquipmentHealth group={ins.equipment.instruments} />
                  </Card>
                )}
                {ins.equipment.materials && (
                  <Card size="half" title="Standards and reagents" hint="by expiry date, right now">
                    <EquipmentHealth group={ins.equipment.materials} />
                  </Card>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
