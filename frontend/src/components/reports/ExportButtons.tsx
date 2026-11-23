import { useState } from "react";
import { apiDownload } from "../../api";
import { useToast } from "../Toast";

const LABELS: Record<string, string> = { csv: "CSV", xlsx: "Excel", pdf: "PDF" };

/**
 * Downloads the report or list as it stands, filters and all. A failure, such
 * as a selection over the row limit, is said out loud rather than leaving the
 * person on a blank download.
 */
export default function ExportButtons({
  url,
  formats = ["csv", "xlsx", "pdf"],
  what = "report",
  disabled = false,
}: {
  /** The export address, without the file format. */
  url: string;
  formats?: string[];
  /** What is being exported, for screen readers: "report" or "list". */
  what?: string;
  disabled?: boolean;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState("");

  const download = async (format: string) => {
    setBusy(format);
    try {
      await apiDownload(`${url}${url.includes("?") ? "&" : "?"}file=${format}`);
    } catch (err) {
      toast("error", "Could not export", err instanceof Error ? err.message : "Try again.");
    }
    setBusy("");
  };

  return (
    <div className="actions-bar report-export" role="group" aria-label={`Export this ${what}`}>
      <span className="hint">Export</span>
      {formats.map((format) => (
        <button
          key={format}
          className="ghost small"
          disabled={disabled || busy !== ""}
          title={disabled ? "Nothing to export" : `Download as ${LABELS[format]}`}
          onClick={() => void download(format)}
        >
          {busy === format ? "Preparing…" : LABELS[format]}
        </button>
      ))}
    </div>
  );
}
