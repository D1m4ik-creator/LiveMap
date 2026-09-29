from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select

from livemap.api.errors import APIError, ErrorResponse
from livemap.api.schemas.monitoring import CameraCheckOutput, ReportInput, ReportOutput, ResolveReportInput
from livemap.core.engine import SessionDep
from livemap.db.models import AdminUser, Camera, CameraCheck, CameraReport
from livemap.services.auth import require_admin
from livemap.services.catalog_admin import audit, commit_or_conflict
from livemap.services.rate_limit import report_limiter


public_router = APIRouter(prefix="/cameras", tags=["camera-reports"], responses={404: {"model": ErrorResponse}, 429: {"model": ErrorResponse}})
admin_router = APIRouter(prefix="/admin", tags=["admin-monitoring"], responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})


class OperationsOutput(BaseModel):
    published_cameras: int
    online_cameras: int
    offline_cameras: int
    stale_cameras: int
    open_reports: int
    latest_check_at: datetime | None
    worker_stale: bool


@admin_router.get("/operations", response_model=OperationsOutput)
async def operations(session: SessionDep, _actor: AdminUser = Depends(require_admin)) -> OperationsOutput:
    now = datetime.now(timezone.utc)
    rows = (await session.execute(
        select(Camera.status, func.count(Camera.id))
        .where(Camera.is_published.is_(True)).group_by(Camera.status)
    )).all()
    statuses = {status: count for status, count in rows}
    stale_cameras = (await session.scalar(
        select(func.count(Camera.id)).where(
            Camera.is_published.is_(True),
            (Camera.last_checked_at.is_(None) | (Camera.last_checked_at < now - timedelta(minutes=15))),
        )
    )) or 0
    open_reports = (await session.scalar(
        select(func.count(CameraReport.id)).where(CameraReport.status == "open")
    )) or 0
    latest_check_at = await session.scalar(select(func.max(CameraCheck.checked_at)))
    return OperationsOutput(
        published_cameras=sum(statuses.values()),
        online_cameras=statuses.get("online", 0),
        offline_cameras=statuses.get("offline", 0),
        stale_cameras=stale_cameras,
        open_reports=open_reports,
        latest_check_at=latest_check_at,
        worker_stale=latest_check_at is None or latest_check_at < now - timedelta(minutes=15),
    )


@public_router.post("/{camera_id}/reports", response_model=ReportOutput, status_code=201)
async def report_camera(camera_id: int, body: ReportInput, request: Request, session: SessionDep) -> CameraReport:
    await report_limiter.check(request.client.host if request.client else "unknown")
    camera = await session.get(Camera, camera_id)
    if camera is None:
        raise APIError("camera_not_found", "Camera not found", 404)
    report = CameraReport(camera_id=camera_id, **body.model_dump())
    session.add(report)
    await commit_or_conflict(session)
    await session.refresh(report)
    return report


@admin_router.get("/reports", response_model=list[ReportOutput])
async def list_reports(
    session: SessionDep, _actor: AdminUser = Depends(require_admin),
    status: str = Query(default="open", pattern="^(open|resolved)$"),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[CameraReport]:
    return list((await session.execute(
        select(CameraReport).where(CameraReport.status == status)
        .order_by(CameraReport.created_at.desc()).limit(limit)
    )).scalars())


@admin_router.patch("/reports/{report_id}", response_model=ReportOutput)
async def resolve_report(
    report_id: int, body: ResolveReportInput, session: SessionDep,
    actor: AdminUser = Depends(require_admin),
) -> CameraReport:
    report = await session.get(CameraReport, report_id)
    if report is None:
        raise APIError("report_not_found", "Report not found", 404)
    if report.status == "resolved":
        raise APIError("already_resolved", "Report already resolved", 409)
    if body.unpublish_camera:
        camera = await session.get(Camera, report.camera_id)
        if camera is not None:
            camera.is_published = False
            camera.unpublished_reason = "report"
            audit(session, actor, "unpublish", "camera", camera.id, f"Camera {camera.id} unpublished after report {report.id}")
    report.status = "resolved"
    report.resolution = body.resolution
    report.resolved_at = datetime.now(timezone.utc)
    audit(session, actor, "resolve", "camera_report", report.id, f"Resolved report {report.id}")
    await commit_or_conflict(session)
    await session.refresh(report)
    return report


@admin_router.get("/cameras/{camera_id}/checks", response_model=list[CameraCheckOutput])
async def camera_checks(
    camera_id: int, session: SessionDep, _actor: AdminUser = Depends(require_admin),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[CameraCheck]:
    if await session.get(Camera, camera_id) is None:
        raise APIError("camera_not_found", "Camera not found", 404)
    return list((await session.execute(
        select(CameraCheck).where(CameraCheck.camera_id == camera_id)
        .order_by(CameraCheck.checked_at.desc()).limit(limit)
    )).scalars())
