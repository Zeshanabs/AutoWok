"""Content-based media validation, metadata extraction, and thumbnails.

The upload pipeline never trusts the browser-supplied filename or MIME type.
The file type is detected from magic bytes, images are decoded with Pillow,
and MP4/QuickTime videos are parsed structurally to read duration and size.
"""

from __future__ import annotations

import io
import re
import struct
import unicodedata
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import get_settings

IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif"}
VIDEO_TYPES = {"video/mp4": "mp4", "video/quicktime": "mov"}
ALLOWED_TYPES = {**IMAGE_TYPES, **VIDEO_TYPES}
EXTENSION_ALIASES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "mp4": "video/mp4",
    "m4v": "video/mp4",
    "mov": "video/quicktime",
}
_MP4_BRANDS = {
    b"isom", b"iso2", b"iso3", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42",
    b"avc1", b"M4V ", b"M4VH", b"M4VP", b"dash", b"mmp4", b"MSNV", b"3gp4", b"3gp5",
}
_MAX_IMAGE_PIXELS = 40_000_000
THUMBNAIL_SIZE = (480, 480)


class MediaValidationError(ValueError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class ProcessedMedia:
    mime_type: str
    extension: str
    data: bytes
    width: int | None
    height: int | None
    duration_seconds: float | None
    thumbnail: bytes | None
    metadata_stripped: bool


def sanitize_filename(filename: str | None) -> str:
    """Return a display-safe filename. It is never used as a storage path."""
    name = unicodedata.normalize("NFKC", (filename or "").replace("\\", "/").split("/")[-1])
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().strip(".")
    name = re.sub(r"[^\w.\- ()]", "_", name)
    return (name or "upload")[:200]


def sniff_mime_type(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:6] in {b"GIF87a", b"GIF89a"}:
        return "image/gif"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        major = data[8:12]
        if major == b"qt  ":
            return "video/quicktime"
        if major in _MP4_BRANDS:
            return "video/mp4"
    return None


def _iter_boxes(data: bytes, start: int, end: int):
    offset = start
    while offset + 8 <= end:
        size, box_type = struct.unpack(">I4s", data[offset : offset + 8])
        header = 8
        if size == 1:
            if offset + 16 > end:
                return
            size = struct.unpack(">Q", data[offset + 8 : offset + 16])[0]
            header = 16
        elif size == 0:
            size = end - offset
        if size < header or offset + size > end:
            return
        yield box_type, offset + header, offset + size
        offset += size


def parse_iso_bmff(data: bytes) -> tuple[float | None, int | None, int | None]:
    """Return (duration_seconds, width, height) from an MP4/MOV file."""
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    found_moov = False
    for box_type, body_start, body_end in _iter_boxes(data, 0, len(data)):
        if box_type != b"moov":
            continue
        found_moov = True
        for child, c_start, c_end in _iter_boxes(data, body_start, body_end):
            if child == b"mvhd" and c_end - c_start >= 20:
                version = data[c_start]
                if version == 1 and c_end - c_start >= 32:
                    timescale, length = struct.unpack(">IQ", data[c_start + 20 : c_start + 32])
                else:
                    timescale, length = struct.unpack(">II", data[c_start + 12 : c_start + 20])
                if timescale:
                    duration = round(length / timescale, 3)
            elif child == b"trak":
                for t_child, t_start, t_end in _iter_boxes(data, c_start, c_end):
                    if t_child != b"tkhd":
                        continue
                    version = data[t_start]
                    dims_offset = t_start + (88 if version == 1 else 76)
                    if dims_offset + 8 <= t_end:
                        w, h = struct.unpack(">II", data[dims_offset : dims_offset + 8])
                        if w >> 16 and h >> 16 and width is None:
                            width, height = w >> 16, h >> 16
    if not found_moov:
        raise MediaValidationError(
            "The video is missing its metadata (moov) section or is not a valid MP4/QuickTime file."
        )
    return duration, width, height


def _process_image(data: bytes, mime_type: str) -> ProcessedMedia:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            probe = Image.open(io.BytesIO(data))
            probe.verify()
            image = Image.open(io.BytesIO(data))
            if image.width * image.height > _MAX_IMAGE_PIXELS:
                raise MediaValidationError("The image dimensions are too large.", 413)
            image.load()
    except MediaValidationError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise MediaValidationError("The image file is corrupt or not a valid image.") from exc

    expected = {"image/jpeg": "JPEG", "image/png": "PNG", "image/gif": "GIF"}[mime_type]
    if image.format != expected:
        raise MediaValidationError("The image content does not match a supported image format.")

    output = data
    stripped = False
    if mime_type in {"image/jpeg", "image/png"}:
        # Re-encode to drop EXIF/GPS and other embedded metadata.
        cleaned = ImageOps.exif_transpose(image)
        buffer = io.BytesIO()
        if mime_type == "image/jpeg":
            cleaned.convert("RGB").save(buffer, format="JPEG", quality=95, optimize=True)
        else:
            cleaned.save(buffer, format="PNG", optimize=True)
        output = buffer.getvalue()
        stripped = True
        image = cleaned

    thumb = image.copy()
    thumb.thumbnail(THUMBNAIL_SIZE)
    thumb_buffer = io.BytesIO()
    thumb.convert("RGB").save(thumb_buffer, format="JPEG", quality=85)
    return ProcessedMedia(
        mime_type=mime_type,
        extension=IMAGE_TYPES[mime_type],
        data=output,
        width=image.width,
        height=image.height,
        duration_seconds=None,
        thumbnail=thumb_buffer.getvalue(),
        metadata_stripped=stripped,
    )


def process_upload(data: bytes, filename: str | None) -> ProcessedMedia:
    if not data:
        raise MediaValidationError("The uploaded file is empty.")
    settings = get_settings()
    extension = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    if extension not in EXTENSION_ALIASES:
        raise MediaValidationError(
            "Unsupported file extension. Allowed: JPG, PNG, GIF, MP4, and MOV.", 415
        )
    mime_type = sniff_mime_type(data)
    if mime_type is None:
        raise MediaValidationError(
            "The file contents are not a supported image or video format.", 415
        )
    claimed = EXTENSION_ALIASES[extension]
    if claimed.split("/")[0] != mime_type.split("/")[0]:
        raise MediaValidationError("The file extension does not match the file contents.", 415)

    if mime_type in IMAGE_TYPES:
        if len(data) > settings.media_max_image_bytes:
            raise MediaValidationError(
                f"Images must be {settings.media_max_image_bytes // (1024 * 1024)} MB or smaller.", 413
            )
        return _process_image(data, mime_type)

    if len(data) > settings.media_max_video_bytes:
        raise MediaValidationError(
            f"Videos must be {settings.media_max_video_bytes // (1024 * 1024)} MB or smaller.", 413
        )
    duration, width, height = parse_iso_bmff(data)
    return ProcessedMedia(
        mime_type=mime_type,
        extension=VIDEO_TYPES[mime_type],
        data=data,
        width=width,
        height=height,
        duration_seconds=duration,
        thumbnail=None,
        metadata_stripped=False,
    )


def max_upload_bytes() -> int:
    settings = get_settings()
    return max(settings.media_max_image_bytes, settings.media_max_video_bytes)
