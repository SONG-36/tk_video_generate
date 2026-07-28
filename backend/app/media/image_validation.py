from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from app.core.exceptions import AppError

MAX_IMAGE_SIZE = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png"}
FORMAT_TO_MIME = {"JPEG": "image/jpeg", "PNG": "image/png"}
FORMAT_TO_EXTENSIONS = {"JPEG": {".jpg", ".jpeg"}, "PNG": {".png"}}


@dataclass(frozen=True)
class ValidatedImage:
    original_name: str
    content: bytes
    size: int
    mime_type: str
    extension: str


async def validate_upload(file: UploadFile) -> ValidatedImage:
    filename = Path(file.filename or "upload").name
    extension = Path(filename).suffix.lower()
    declared_mime = (file.content_type or "").lower()
    content = await file.read(MAX_IMAGE_SIZE + 1)
    await file.seek(0)

    if len(content) > MAX_IMAGE_SIZE:
        raise AppError(f"{filename} 超过 10MB", "IMAGE_TOO_LARGE", 422)
    if not content:
        raise AppError(f"{filename} 是空文件", "EMPTY_IMAGE", 422)
    if extension not in ALLOWED_EXTENSIONS or declared_mime not in ALLOWED_MIME_TYPES:
        raise AppError(
            f"{filename} 仅支持 JPG、JPEG、PNG",
            "UNSUPPORTED_IMAGE_TYPE",
            422,
        )

    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
            actual_format = (image.format or "").upper()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise AppError(f"{filename} 不是有效图片", "INVALID_IMAGE_CONTENT", 422) from exc

    actual_mime = FORMAT_TO_MIME.get(actual_format)
    if (
        actual_mime is None
        or actual_mime != declared_mime
        or extension not in FORMAT_TO_EXTENSIONS[actual_format]
    ):
        raise AppError(
            f"{filename} 的扩展名、MIME 类型与实际内容不一致",
            "IMAGE_TYPE_MISMATCH",
            422,
        )

    return ValidatedImage(
        original_name=filename,
        content=content,
        size=len(content),
        mime_type=actual_mime,
        extension=extension,
    )

