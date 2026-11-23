import { useEffect, useState } from "react";
import { fmtSize } from "../util";
import { Message } from "./Feedback";
import ModalBackdrop from "./ModalBackdrop";

const IMAGES = new Set(["png", "jpg", "jpeg", "webp"]);
const TEXTS = new Set(["csv", "txt"]);
const TEXT_LIMIT = 200_000; // characters: enough to recognise a file, not to freeze the tab

export function canPreview(extension: string): boolean {
  const ext = extension.toLowerCase();
  return ext === "pdf" || IMAGES.has(ext) || TEXTS.has(ext);
}

export function downloadFile(url: string) {
  window.location.assign(`${url}?download=1`);
}

/**
 * A stored file, shown here without leaving the screen. The server refuses to
 * let a stored file sit in a frame or run anything (execution/files.py), so a
 * PDF is fetched under the same permission check and shown from memory: nothing
 * about how files are served is loosened for this.
 */
export default function FilePreview({
  file,
  onClose,
}: {
  file: { name: string; url: string; extension: string; size: number; version: number };
  onClose: () => void;
}) {
  const ext = file.extension.toLowerCase();
  const [pdf, setPdf] = useState("");
  const [text, setText] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (IMAGES.has(ext)) return;
    let live = true;
    let objectUrl = "";
    (async () => {
      const response = await fetch(file.url, { credentials: "same-origin" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      if (ext === "pdf") {
        const blob = new Blob([await response.arrayBuffer()], { type: "application/pdf" });
        if (!live) return;
        objectUrl = URL.createObjectURL(blob);
        setPdf(objectUrl);
      } else {
        const content = await response.text();
        if (live) setText(content);
      }
    })().catch(() => {
      if (live) setFailed(true);
    });
    return () => {
      live = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [ext, file.url]);

  return (
    <ModalBackdrop onClick={onClose}>
      <div
        className="modal preview"
        role="dialog"
        aria-modal="true"
        aria-label={`Preview of ${file.name}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="preview-head">
          <div>
            <b title={file.name}>{file.name}</b>
            <span>{ext.toUpperCase()} · {fmtSize(file.size)} · version {file.version}</span>
          </div>
          <button className="ghost small" onClick={() => downloadFile(file.url)}>Download</button>
          <button className="ghost small" onClick={onClose} autoFocus>Close</button>
        </div>
        <div className="preview-body">
          {failed ? (
            <div className="preview-note">
              <Message kind="error">This file could not be shown. Try downloading it instead.</Message>
            </div>
          ) : IMAGES.has(ext) ? (
            <img src={file.url} alt={file.name} onError={() => setFailed(true)} />
          ) : ext === "pdf" ? (
            pdf ? <iframe src={pdf} title={file.name} /> : <div className="preview-note">Opening…</div>
          ) : text === null ? (
            <div className="preview-note">Opening…</div>
          ) : (
            <pre>
              {text.slice(0, TEXT_LIMIT)}
              {text.length > TEXT_LIMIT && "\n\n… Only the start is shown here. Download the file to see all of it."}
            </pre>
          )}
        </div>
      </div>
    </ModalBackdrop>
  );
}
