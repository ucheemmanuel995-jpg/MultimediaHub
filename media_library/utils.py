"""Helper utilities: thumbnails, HTTP range streaming, safe redirects."""
import io
import re

from django.utils.http import url_has_allowed_host_and_scheme
from PIL import Image, ImageOps

THUMBNAIL_SIZE = (480, 320)

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def make_image_thumbnail(fieldfile, size=THUMBNAIL_SIZE):
    """Return JPEG bytes for a thumbnail of the given image file, or None."""
    try:
        try:
            fieldfile.seek(0)
        except Exception:  # pragma: no cover - file objects without seek
            pass
        with Image.open(fieldfile) as img:
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
            img.thumbnail(size)
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=82, optimize=True)
        try:
            fieldfile.seek(0)
        except Exception:  # pragma: no cover
            pass
        return buffer.getvalue()
    except Exception:
        return None


def parse_range_header(header, size):
    """
    Parse a single-range HTTP Range header.

    Returns (start, end) inclusive, ``None`` if no usable range was requested,
    or ``False`` if the range is unsatisfiable.
    """
    if not header:
        return None
    match = _RANGE_RE.match(header.strip())
    if not match:
        return None
    start_s, end_s = match.groups()
    if start_s == "" and end_s == "":
        return None
    if start_s == "":
        length = int(end_s)
        if length == 0:
            return False
        start = max(size - length, 0)
        end = size - 1
    else:
        start = int(start_s)
        end = int(end_s) if end_s else size - 1
        end = min(end, size - 1)
    if size == 0 or start >= size or start > end:
        return False
    return start, end


def iter_file_range(path, start, end, chunk_size=64 * 1024):
    """Yield bytes from ``path`` between ``start`` and ``end`` (inclusive)."""
    with open(path, "rb") as handle:
        handle.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            data = handle.read(min(chunk_size, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def safe_next_url(request, default):
    """Return a same-host ``next`` URL from POST/GET, else ``default``."""
    candidate = request.POST.get("next") or request.GET.get("next")
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return default
