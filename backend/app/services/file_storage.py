import logging
from pathlib import Path, PurePosixPath
from uuid import uuid4

from app.core.config import get_settings

logger = logging.getLogger(__name__)


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
        try:
            target.write_bytes(content)
        except Exception:
            # 写入失败时文件可能已被创建；清理失败只记录类型，不能覆盖原始写入异常。
            try:
                target.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                logger.warning(
                    "清理未完成的文件失败 exception_type=%s",
                    type(cleanup_exc).__name__,
                )
            raise
        return relative.as_posix(), len(content)

    def delete(self, relative_path: str) -> None:
        target = self.resolve_relative(relative_path)
        if target.is_file():
            target.unlink()

    def try_delete(self, relative_path: str, *, context: str) -> None:
        """补偿性删除不得覆盖触发补偿的原始业务异常。"""
        try:
            self.delete(relative_path)
        except Exception as exc:
            logger.warning(
                "文件补偿清理失败 context=%s exception_type=%s",
                context,
                type(exc).__name__,
            )
