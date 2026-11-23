"""
Uploaded documents: what the lab accepts, and the checks every file
passes before it is stored.

The extension alone proves nothing, so each type is also checked by its
first bytes. Nothing that a browser would run (HTML, SVG, scripts) is on
the list, and files are always served back with their checked type.
"""
import hashlib
import os
import re

from django.http import FileResponse, Http404

# Outer limit for any single file, whatever a checklist item allows.
MAX_UPLOAD_MB = 20

_ZIP = b"PK\x03\x04"

# extension -> (content type, label, first-bytes check)
ALLOWED: dict[str, tuple[str, str, object]] = {
    "pdf": ("application/pdf", "PDF", lambda h: h.startswith(b"%PDF-")),
    "png": ("image/png", "PNG image", lambda h: h.startswith(b"\x89PNG\r\n\x1a\n")),
    "jpg": ("image/jpeg", "JPEG image", lambda h: h.startswith(b"\xff\xd8\xff")),
    "jpeg": ("image/jpeg", "JPEG image", lambda h: h.startswith(b"\xff\xd8\xff")),
    "webp": ("image/webp", "WebP image", lambda h: h[:4] == b"RIFF" and h[8:12] == b"WEBP"),
    "csv": ("text/csv", "CSV", None),
    "txt": ("text/plain", "Text", None),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "Excel workbook",
             lambda h: h.startswith(_ZIP)),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "Word document",
             lambda h: h.startswith(_ZIP)),
}

# Shown inline in the browser; everything else downloads.
INLINE = {"pdf", "png", "jpg", "jpeg", "webp"}


def private_file_response(stored, extension: str, content_type: str, name: str, download: bool = False):
    """Serve a stored file with its checked type, so nothing in it can run in the browser."""
    try:
        handle = stored.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("The stored file is missing.")
    inline = not download and extension in INLINE
    response = FileResponse(handle, content_type=content_type, as_attachment=not inline, filename=name)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox"
    return response


class FileRejected(ValueError):
    """The upload is not acceptable. The message says why, for the uploader."""


def extension_of(name: str) -> str:
    return os.path.splitext(name or "")[1].lower().lstrip(".")


def safe_display_name(name: str) -> str:
    """The name as shown and offered on download — no path, no control characters."""
    base = os.path.basename((name or "").replace("\\", "/"))
    base = re.sub(r"[\x00-\x1f\x7f\"]", "", base).strip() or "file"
    return base[:200]


def _looks_like_text(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as e:
        # A multi-byte character cut off at the end of the sample is fine.
        return e.start >= len(head) - 3
    return True


def check_upload(uploaded, allowed_types: list[str] | None, max_mb: int) -> tuple[str, str, int, str]:
    """
    Validate an uploaded file. Returns (extension, content type, size,
    sha256). Raises FileRejected with a message for the person uploading.
    """
    if uploaded is None:
        raise FileRejected("Choose a file to upload.")
    ext = extension_of(uploaded.name)
    allowed = [t for t in (allowed_types or ALLOWED.keys()) if t in ALLOWED]
    if ext not in ALLOWED:
        raise FileRejected(
            f"“.{ext or '?'}” files are not accepted. Upload one of: "
            + ", ".join(sorted({ALLOWED[t][1] for t in ALLOWED})) + "."
        )
    if ext not in allowed:
        raise FileRejected(
            "This document must be " + ", ".join(sorted({ALLOWED[t][1] for t in allowed})) + "."
        )
    limit_mb = min(max_mb or MAX_UPLOAD_MB, MAX_UPLOAD_MB)
    if uploaded.size == 0:
        raise FileRejected("That file is empty.")
    if uploaded.size > limit_mb * 1024 * 1024:
        raise FileRejected(f"That file is {uploaded.size / 1048576:.1f} MB — the limit here is {limit_mb} MB.")

    uploaded.seek(0)
    head = uploaded.read(65536)
    content_type, label, check = ALLOWED[ext]
    ok = _looks_like_text(head) if check is None else check(head)
    if not ok:
        raise FileRejected(f"That file is not a genuine {label} — its contents do not match “.{ext}”.")

    digest = hashlib.sha256()
    uploaded.seek(0)
    for chunk in uploaded.chunks():
        digest.update(chunk)
    uploaded.seek(0)
    return ext, content_type, uploaded.size, digest.hexdigest()
