"""
Upload validation.

Validation never trusts the client-supplied filename or MIME type. Each file's
leading bytes ("magic numbers") are inspected and images are additionally
decoded with Pillow.
"""
import os

from django.conf import settings
from django.core.exceptions import ValidationError
from PIL import Image

ALLOWED_EXTENSIONS = {
    "image": {".jpg", ".jpeg", ".png", ".gif", ".webp"},
    "video": {".mp4", ".m4v", ".webm", ".ogv"},
    "audio": {".mp3", ".wav", ".ogg", ".oga"},
}

ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}

SIZE_SETTING = {
    "image": "MAX_IMAGE_SIZE_MB",
    "video": "MAX_VIDEO_SIZE_MB",
    "audio": "MAX_AUDIO_SIZE_MB",
}


def get_extension(name):
    return os.path.splitext(name or "")[1].lower()


def max_size_bytes(media_type):
    megabytes = float(getattr(settings, SIZE_SETTING[media_type]))
    return int(megabytes * 1024 * 1024)


def _format_mb(num_bytes):
    return f"{num_bytes / (1024 * 1024):.2f} MB".replace(".00 MB", " MB")


def _read_head(file, length=16):
    try:
        file.seek(0)
    except Exception:
        pass
    head = file.read(length)
    try:
        file.seek(0)
    except Exception:
        pass
    return head or b""


def _validate_size(file, limit, label):
    size = getattr(file, "size", None)
    if size is None:
        return
    if size > limit:
        raise ValidationError(
            f"This {label} is too large ({_format_mb(size)}). "
            f"The maximum allowed size is {_format_mb(limit)}."
        )
    if size == 0:
        raise ValidationError("The uploaded file is empty.")


def validate_image_content(file):
    """Decode the file with Pillow and verify it is a supported raster image."""
    try:
        file.seek(0)
    except Exception:
        pass
    try:
        with Image.open(file) as img:
            image_format = img.format
            img.verify()
    except Exception:
        raise ValidationError("The file is not a valid image or is corrupted.")
    finally:
        try:
            file.seek(0)
        except Exception:
            pass
    if image_format not in ALLOWED_IMAGE_FORMATS:
        raise ValidationError(
            "Unsupported image format. Use JPEG, PNG, GIF or WebP."
        )


def _is_mp4(head):
    return len(head) >= 12 and head[4:8] == b"ftyp"


def _is_webm(head):
    return head[:4] == b"\x1a\x45\xdf\xa3"


def _is_ogg(head):
    return head[:4] == b"OggS"


def _is_mp3(head):
    if head[:3] == b"ID3":
        return True
    return len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0


def _is_wav(head):
    return len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WAVE"


_SIGNATURE_BY_EXTENSION = {
    ".mp4": _is_mp4,
    ".m4v": _is_mp4,
    ".webm": _is_webm,
    ".ogv": _is_ogg,
    ".mp3": _is_mp3,
    ".wav": _is_wav,
    ".ogg": _is_ogg,
    ".oga": _is_ogg,
}


def validate_media_file(file, media_type):
    """
    Validate an uploaded media file for the given media type.

    Checks size, extension, and file signature. This verifies the container
    format but cannot guarantee the streams inside are playable in every
    browser (MP4/H.264 + AAC is the most compatible choice).
    """
    if media_type not in ALLOWED_EXTENSIONS:
        raise ValidationError("Unknown media type.")

    _validate_size(file, max_size_bytes(media_type), media_type)

    extension = get_extension(getattr(file, "name", ""))
    allowed = ALLOWED_EXTENSIONS[media_type]
    if extension not in allowed:
        raise ValidationError(
            f"Unsupported {media_type} file type '{extension or 'none'}'. "
            f"Allowed: {', '.join(sorted(allowed))}."
        )

    if media_type == "image":
        validate_image_content(file)
        return

    head = _read_head(file)
    checker = _SIGNATURE_BY_EXTENSION[extension]
    if not checker(head):
        raise ValidationError(
            f"The file content does not look like a valid {extension} "
            f"{media_type} file. Check that the file is not corrupted or renamed."
        )


def validate_thumbnail(file):
    """Validate an optional thumbnail image."""
    limit = int(float(getattr(settings, "MAX_THUMBNAIL_SIZE_MB", 5)) * 1024 * 1024)
    _validate_size(file, limit, "thumbnail")
    extension = get_extension(getattr(file, "name", ""))
    if extension not in ALLOWED_EXTENSIONS["image"]:
        raise ValidationError(
            "Thumbnails must be JPEG, PNG, GIF or WebP images."
        )
    validate_image_content(file)
