from __future__ import annotations

import tempfile
import asyncio
import secrets
import time
from pathlib import Path
import shutil
from typing import Annotated
from fastapi import BackgroundTasks

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .settings import settings
from .storage import (
    NotEnoughPasswords,
    PasswordConflict,
    PasswordsUnavailable,
    create_password_store,
)
from .qr import make_qr_png
from .brochure import build_merged_pdf

if settings.environment == "production" and not settings.admin_password:
    raise RuntimeError("ADMIN_PASSWORD is required in production")

app = FastAPI(
    title="ARTSTUDIO Wi-Fi voucher module",
    version="1.0.0",
)
app.mount("/assets", StaticFiles(directory="fonts"), name="assets")
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

_lock = asyncio.Lock()
_security = HTTPBasic(auto_error=False)
store = create_password_store(
    database_url=settings.database_url,
    database_path=settings.database_path,
    hotel_id=settings.hotel_id,
    hotel_name=settings.hotel_name,
    reservation_ttl_minutes=settings.reservation_ttl_minutes,
)
store.initialize()

class GenerateRequest(BaseModel):
    ru: int = Field(ge=0, le=500)
    en: int = Field(ge=0, le=500)

class PasswordImportRequest(BaseModel):
    passwords: list[str] = Field(min_length=1, max_length=5000)


class PasswordUpdateRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class PasswordIdsRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=1000)


def render_pdf(passwords: list[str], ru_count: int, work_dir: Path) -> str:
    qr_paths = []
    for index, password in enumerate(passwords, start=1):
        qr_path = work_dir / f"qr_{index:04d}.png"
        make_qr_png(password, str(qr_path))
        qr_paths.append(str(qr_path))

    out_pdf = work_dir / "brochures.pdf"
    build_merged_pdf(
        soffice_bin=settings.soffice_bin,
        template_ru=settings.template_ru_path,
        template_en=settings.template_en_path,
        ru_passwords=passwords[:ru_count],
        en_passwords=passwords[ru_count:],
        qr_png_paths=qr_paths,
        work_dir=str(work_dir),
        out_pdf_path=str(out_pdf),
    )
    return str(out_pdf)


def require_admin(
    credentials: Annotated[HTTPBasicCredentials | None, Depends(_security)],
) -> None:
    if not settings.admin_password:
        return
    username_ok = credentials is not None and secrets.compare_digest(
        credentials.username.encode("utf-8"),
        settings.admin_username.encode("utf-8"),
    )
    password_ok = credentials is not None and secrets.compare_digest(
        credentials.password.encode("utf-8"),
        settings.admin_password.encode("utf-8"),
    )
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация.",
            headers={"WWW-Authenticate": "Basic"},
        )


admin_required = [Depends(require_admin)]


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path == "/" or request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health():
    return {"status": "ok", "module": "wifi-voucher"}


@app.get("/ready")
def ready():
    try:
        healthy = store.health()
    except Exception as error:
        raise HTTPException(status_code=503, detail="Database unavailable") from error
    return {"status": "ready" if healthy else "not-ready"}


@app.get("/api/v1/module-manifest", dependencies=admin_required)
def module_manifest():
    return {
        "id": "wifi-voucher",
        "name": "Wi-Fi пароли",
        "version": "1.0.0",
        "hotel_id": settings.hotel_id,
        "hotel_name": settings.hotel_name,
        "mode": "standalone",
        "capabilities": [
            "passwords.read",
            "passwords.import",
            "passwords.edit",
            "passwords.issue",
            "passwords.delete",
            "vouchers.generate",
        ],
        "api_base": "/api/v1",
    }


@app.get("/", response_class=HTMLResponse, dependencies=admin_required)
def index():
    html_path = Path("web/index.html")
    return html_path.read_text(encoding="utf-8")


@app.get("/api/passwords", dependencies=admin_required, include_in_schema=False)
@app.get("/api/v1/passwords", dependencies=admin_required)
def get_passwords(
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    search: str = Query(default="", max_length=256),
):
    return {
        "hotel_id": settings.hotel_id,
        "items": store.list_available(
            limit=limit,
            offset=offset,
            search=search,
        ),
        "stats": store.stats(),
    }


@app.post(
    "/api/passwords/import",
    dependencies=admin_required,
    include_in_schema=False,
)
@app.post("/api/v1/passwords/import", dependencies=admin_required)
def import_passwords(req: PasswordImportRequest):
    result = store.import_passwords(req.passwords)
    return {
        **result,
        "hotel_id": settings.hotel_id,
        "stats": store.stats(),
    }


@app.post("/api/v1/passwords/import/preview", dependencies=admin_required)
def preview_password_import(req: PasswordImportRequest):
    return {
        "hotel_id": settings.hotel_id,
        **store.preview_import(req.passwords),
    }


@app.patch("/api/v1/passwords/{password_id}", dependencies=admin_required)
def update_password(password_id: int, req: PasswordUpdateRequest):
    try:
        updated = store.update_available(password_id, req.password)
    except PasswordConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not updated:
        raise HTTPException(
            status_code=404,
            detail="Доступный пароль не найден.",
        )
    return {"updated": True, "stats": store.stats()}


@app.post("/api/v1/passwords/issue", dependencies=admin_required)
def issue_passwords(req: PasswordIdsRequest):
    try:
        passwords = store.issue_available(req.ids)
    except PasswordsUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {
        "issued": len(passwords),
        "passwords": passwords,
        "stats": store.stats(),
    }


@app.post("/api/v1/passwords/delete", dependencies=admin_required)
def delete_passwords(req: PasswordIdsRequest):
    deleted = store.delete_available_many(req.ids)
    return {"deleted": deleted, "stats": store.stats()}


@app.delete(
    "/api/passwords/{password_id}",
    dependencies=admin_required,
    include_in_schema=False,
)
@app.delete("/api/v1/passwords/{password_id}", dependencies=admin_required)
def delete_password(password_id: int):
    if not store.delete_available(password_id):
        raise HTTPException(
            status_code=404,
            detail="Доступный пароль не найден.",
        )
    return {"deleted": True, "stats": store.stats()}


@app.get("/api/v1/generations", dependencies=admin_required)
def get_generations(limit: int = Query(default=50, ge=1, le=200)):
    return {
        "hotel_id": settings.hotel_id,
        "items": store.list_generations(limit=limit),
    }


@app.post("/generate", dependencies=admin_required, include_in_schema=False)
@app.post("/api/v1/generations", dependencies=admin_required)
async def generate(req: GenerateRequest, background_tasks: BackgroundTasks):
    total = req.ru + req.en
    if total <= 0:
        raise HTTPException(
            status_code=400,
            detail="Укажите хотя бы одну брошюру.",
        )

    async with _lock:
        try:
            reservation = store.reserve(
                total,
                ru_count=req.ru,
                en_count=req.en,
            )
        except NotEnoughPasswords as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

        passwords = list(reservation.passwords)
        td = Path(tempfile.mkdtemp(prefix="brochures_"))
        render_started = time.perf_counter()
        try:
            pdf_path = await asyncio.to_thread(
                render_pdf,
                passwords,
                req.ru,
                td,
            )
            render_seconds = time.perf_counter() - render_started
            store.commit(reservation.batch_id)
        except Exception as error:
            store.release(reservation.batch_id, str(error)[:1000])
            shutil.rmtree(td, ignore_errors=True)
            raise HTTPException(
                status_code=500,
                detail=f"Render failed: {error}",
            ) from error

    # удаляем папку ПОСЛЕ отдачи файла клиенту
    background_tasks.add_task(shutil.rmtree, td, ignore_errors=True)

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename="brochures.pdf",
        headers={
            "Server-Timing": f"pdf;dur={render_seconds * 1000:.0f}",
            "X-Generation-Seconds": f"{render_seconds:.3f}",
        },
        background=background_tasks,
    )
