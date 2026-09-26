from fastapi import APIRouter, Depends

from livemap.api.errors import ErrorResponse
from livemap.api.schemas.imports import ImportInput, ImportPreview, ImportResult
from livemap.core.engine import SessionDep
from livemap.db.models import AdminUser
from livemap.services.auth import current_user, require_admin
from livemap.services.catalog_import import apply_import, prepare_import


router = APIRouter(
    prefix="/admin/import", tags=["admin-import"],
    responses={
        400: {"model": ErrorResponse}, 401: {"model": ErrorResponse},
        403: {"model": ErrorResponse}, 409: {"model": ErrorResponse},
    },
)


@router.post("/preview", response_model=ImportPreview)
async def preview(body: ImportInput, session: SessionDep, _actor: AdminUser = Depends(current_user)) -> ImportPreview:
    result, _ = await prepare_import(session, body)
    return result


@router.post("/apply", response_model=ImportResult)
async def apply(body: ImportInput, session: SessionDep, actor: AdminUser = Depends(require_admin)) -> ImportResult:
    return await apply_import(session, body, actor)
