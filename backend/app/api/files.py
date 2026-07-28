from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import AppError
from app.models.result import GenerationResult, ResultType
from app.services.file_storage import FileStorageService

router = APIRouter(prefix="/files")


@router.get("/download/{result_id}", response_class=FileResponse)
def download_result(
    result_id: int,
    inline: bool = False,
    session: Session = Depends(get_db),
) -> FileResponse:
    result = session.get(GenerationResult, result_id)
    if result is None:
        raise AppError("生成结果不存在", "RESULT_NOT_FOUND", 404)
    path = FileStorageService().resolve_relative(result.file_path)
    if not path.is_file():
        raise AppError("生成文件不存在", "RESULT_FILE_NOT_FOUND", 404)
    return FileResponse(
        path,
        media_type=(
            "video/mp4" if result.result_type == ResultType.VIDEO else "image/png"
        ),
        filename=result.file_name,
        content_disposition_type="inline" if inline else "attachment",
    )
