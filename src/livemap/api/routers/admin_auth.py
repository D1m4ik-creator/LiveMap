from fastapi import APIRouter, Depends, Request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from livemap.api.errors import APIError, ErrorResponse
from livemap.api.schemas.admin import AdminUserOutput, CreateUserInput, LoginInput, LoginOutput
from livemap.core.engine import SessionDep
from livemap.db.models import AdminSession, AdminUser, AuditEvent
from livemap.services.auth import (
    create_session,
    current_user,
    hash_password,
    require_admin,
    token_hash,
    verify_password,
    bearer,
)
from livemap.services.rate_limit import login_limiter


router = APIRouter(
    prefix="/admin", tags=["admin-auth"],
    responses={
        400: {"model": ErrorResponse}, 401: {"model": ErrorResponse},
        403: {"model": ErrorResponse}, 409: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
    },
)


@router.post("/login", response_model=LoginOutput, responses={401: {"model": ErrorResponse}})
async def login(body: LoginInput, session: SessionDep, request: Request) -> LoginOutput:
    await login_limiter.check(request.client.host if request.client else "unknown")
    user = (
        await session.execute(select(AdminUser).where(AdminUser.username == body.username))
    ).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise APIError("invalid_credentials", "Invalid credentials", 401)
    token, expires_at = await create_session(session, user)
    return LoginOutput(access_token=token, expires_at=expires_at, role=user.role)


@router.get("/me", response_model=AdminUserOutput)
async def me(user: AdminUser = Depends(current_user)) -> AdminUser:
    return user


@router.post("/logout", status_code=204)
async def logout(session: SessionDep, credentials=Depends(bearer), user: AdminUser = Depends(current_user)) -> None:
    await session.execute(
        delete(AdminSession).where(
            AdminSession.user_id == user.id,
            AdminSession.token_hash == token_hash(credentials.credentials),
        )
    )
    await session.commit()


@router.post("/users", response_model=AdminUserOutput, status_code=201)
async def create_user(
    body: CreateUserInput,
    session: SessionDep,
    actor: AdminUser = Depends(require_admin),
) -> AdminUser:
    user = AdminUser(username=body.username, password_hash=hash_password(body.password), role=body.role)
    session.add(user)
    try:
        await session.flush()
        session.add(AuditEvent(
            actor_id=actor.id, action="create", entity_type="admin_user", entity_id=user.id,
            summary=f"Created {body.role} user {body.username}",
        ))
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise APIError("duplicate_username", "Username already exists", 409) from exc
    await session.refresh(user)
    return user
