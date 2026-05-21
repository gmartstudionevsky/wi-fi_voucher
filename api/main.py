from __future__ import annotations

import tempfile
import asyncio
from pathlib import Path
import shutil
from fastapi import BackgroundTasks

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from .settings import settings
from .reservations import VoucherReservationError, reserve_vouchers
from .qr import make_qr_png
from .brochure import build_merged_pdf

app = FastAPI(title="ARTSTUDIO Wi-Fi vouchers")

_lock = asyncio.Lock()


class GenerateRequest(BaseModel):
    ru: int = Field(ge=0, le=500)
    en: int = Field(ge=0, le=500)


def read_web_file(name: str) -> str:
    return Path("web", name).read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def index():
    return read_web_file("index.html")


@app.get("/brochures", response_class=HTMLResponse)
def brochures():
    return read_web_file("index.html")


@app.get("/guest", response_class=HTMLResponse)
def guest():
    return read_web_file("guest.html")


@app.post("/generate")
async def generate(req: GenerateRequest, background_tasks: BackgroundTasks):
    total = req.ru + req.en
    if total <= 0:
        raise HTTPException(status_code=400, detail="Need at least one brochure (ru+en > 0).")

    async with _lock:
        try:
            passwords = await asyncio.to_thread(
                reserve_vouchers,
                total,
                "brochure-generator",
                {"ru": req.ru, "en": req.en},
            )
        except VoucherReservationError as error:
            message = str(error)
            status_code = 409 if "voucher" in message.lower() or "пар" in message.lower() else 502
            raise HTTPException(status_code=status_code, detail=message) from error

    ru_passwords = passwords[:req.ru]
    en_passwords = passwords[req.ru:req.ru + req.en]

    td = Path(tempfile.mkdtemp(prefix="brochures_"))
    try:
        qr_paths = []
        for i, pwd in enumerate(passwords, start=1):
            qp = td / f"qr_{i:04d}.png"
            make_qr_png(pwd, str(qp))
            qr_paths.append(str(qp))

        out_pdf = td / "brochures.pdf"

        build_merged_pdf(
            soffice_bin=settings.soffice_bin,
            template_ru=settings.template_ru_path,
            template_en=settings.template_en_path,
            ru_passwords=ru_passwords,
            en_passwords=en_passwords,
            qr_png_paths=qr_paths,
            work_dir=str(td),
            out_pdf_path=str(out_pdf),
        )
        pdf_path = str(out_pdf)

    except Exception as error:
        shutil.rmtree(td, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Render failed: {error}") from error

    background_tasks.add_task(shutil.rmtree, td, ignore_errors=True)

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename="brochures.pdf",
        background=background_tasks,
    )
