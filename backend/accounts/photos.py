"""
Profile photo handling: validate, normalise, store.

A photo is for recognising a colleague on screen. It is deliberately NOT a
signature — the brief is explicit that an electronic signature "is not a
picture of your handwriting" — so it never reaches a certificate.
"""
import uuid
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, UnidentifiedImageError

MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 2 MB
MAX_SOURCE_PIXELS = 2000  # reject anything absurd before we decode it fully
STORED_SIZE = 512  # what we keep: square, plenty for any avatar on screen
LOGO_MAX_WIDTH, LOGO_MAX_HEIGHT = 600, 200  # printed at ~28mm tall on the COA
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


class PhotoError(ValueError):
    """The uploaded file is not an acceptable profile photo."""


def photo_upload_path(instance, filename: str) -> str:
    """
    Never reuse the uploaded filename: it can carry path separators and it
    leaks personal detail. A UUID says everything we need.
    """
    return f"profile_photos/{instance.pk or 'new'}/{uuid.uuid4().hex}.jpg"


def logo_upload_path(instance, filename: str) -> str:
    return f"lab_logo/{uuid.uuid4().hex}.png"


def clean_logo(uploaded) -> ContentFile:
    """
    A company logo, unlike a profile photo, keeps its transparency and its
    aspect ratio — it sits on the letterhead of a document that leaves the
    building, so it must not be cropped square or flattened onto white.
    """
    if uploaded is None:
        raise PhotoError("No file was uploaded.")
    if uploaded.size > MAX_UPLOAD_BYTES:
        raise PhotoError("The logo must be 2 MB or smaller.")

    try:
        image = Image.open(uploaded)
        image.verify()
        uploaded.seek(0)
        image = Image.open(uploaded)
    # A damaged file can fail in any of these ways: a PNG with a bad checksum raises SyntaxError.
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise PhotoError("That file is not an image.")

    if image.format not in ALLOWED_FORMATS:
        raise PhotoError("The logo must be a JPEG, PNG or WebP.")
    if image.width > MAX_SOURCE_PIXELS or image.height > MAX_SOURCE_PIXELS:
        raise PhotoError(f"The logo must be no larger than {MAX_SOURCE_PIXELS}×{MAX_SOURCE_PIXELS} pixels.")

    image = image.convert("RGBA")
    # Fit inside a printable box, keeping the proportions.
    image.thumbnail((LOGO_MAX_WIDTH, LOGO_MAX_HEIGHT), Image.LANCZOS)

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return ContentFile(buffer.getvalue())


def clean_photo(uploaded) -> ContentFile:
    """
    Validate by decoding, not by trusting the extension or content type,
    then re-encode to a square JPEG. Re-encoding also strips EXIF, which on
    a phone photo commonly carries GPS coordinates.
    """
    if uploaded is None:
        raise PhotoError("No file was uploaded.")
    if uploaded.size > MAX_UPLOAD_BYTES:
        raise PhotoError("The image must be 2 MB or smaller.")

    try:
        image = Image.open(uploaded)
        image.verify()  # cheap structural check; consumes the file object
        uploaded.seek(0)
        image = Image.open(uploaded)
    # A damaged file can fail in any of these ways: a PNG with a bad checksum raises SyntaxError.
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise PhotoError("That file is not an image.")

    if image.format not in ALLOWED_FORMATS:
        raise PhotoError("The image must be a JPEG, PNG or WebP.")
    if image.width > MAX_SOURCE_PIXELS or image.height > MAX_SOURCE_PIXELS:
        raise PhotoError(f"The image must be no larger than {MAX_SOURCE_PIXELS}×{MAX_SOURCE_PIXELS} pixels.")

    # Flatten transparency onto white, then centre-crop to a square so every
    # avatar in the interface has the same shape.
    image = image.convert("RGBA") if image.mode in ("RGBA", "LA", "P") else image.convert("RGB")
    if image.mode == "RGBA":
        backdrop = Image.new("RGB", image.size, (255, 255, 255))
        backdrop.paste(image, mask=image.split()[-1])
        image = backdrop

    side = min(image.width, image.height)
    left = (image.width - side) // 2
    top = (image.height - side) // 2
    image = image.crop((left, top, left + side, top + side))
    image = image.resize((STORED_SIZE, STORED_SIZE), Image.LANCZOS)

    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=88, optimize=True)
    return ContentFile(buffer.getvalue())
