from pathlib import Path, PurePosixPath
from uuid import uuid4

from app.core.config import get_settings


class FileStorageService:
    directories = (
        "uploads/image",
        "uploads/video",
        "outputs/image",
        "outputs/video",
        "temp",
    )

    def __init__(self, root: Path | None = None):
        self.root = (root or get_settings().storage_root).resolve()

    def ensure_directories(self) -> None:
        for relative in self.directories:
            (self.root / relative).mkdir(parents=True, exist_ok=True)

    def resolve_relative(self, relative_path: str) -> Path:
        normalized = PurePosixPath(relative_path)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError("存储路径必须是安全的相对路径")
        return self.root.joinpath(*normalized.parts)

    def save_bytes(
        self,
        directory: str,
        content: bytes,
        extension: str,
        prefix: str = "",
    ) -> tuple[str, int]:
        safe_extension = extension.lower().lstrip(".")
        if not safe_extension.isalnum():
            raise ValueError("文件扩展名不合法")
        filename = f"{prefix}{uuid4().hex}.{safe_extension}"
        relative = PurePosixPath(directory) / filename
        target = self.resolve_relative(relative.as_posix())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return relative.as_posix(), len(content)

    def delete(self, relative_path: str) -> None:
        target = self.resolve_relative(relative_path)
        if target.is_file():
            target.unlink()
