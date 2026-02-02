from __future__ import annotations

import os
import tempfile
import asyncio
from pathlib import Path
import shutil
from fastapi import BackgroundTasks

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from .settings import settings
from .sheets import fetch_and_delete_passwords
from .qr import make_qr_png
from .brochure import build_pptx, convert_pptx_to_pdf

app = FastAPI(title="Guest brochure generator")

_lock = asyncio.Lock()

class GenerateRequest(BaseModel):
    ru: int = Field(ge=0, le=500)
    en: int = Field(ge=0, le=500)

@app.get("/", response_class=HTMLResponse)
def index():
    html_path = Path("web/index.html")
    return html_path.read_text(encoding="utf-8")

@app.post("/generate")
async def generate(req: GenerateRequest, background_tasks: BackgroundTasks):
    total = req.ru + req.en
    if total <= 0:
        raise HTTPException(status_code=400, detail="Need at least one brochure (ru+en > 0).")

    async with _lock:
        try:
            passwords = fetch_and_delete_passwords(
                sa_json_path=settings.google_sa_json_path,
                spreadsheet_id=settings.spreadsheet_id,
                sheet_name=settings.sheet_name,
                column=settings.password_column,
                count=total,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    ru_passwords = passwords[:req.ru]
    en_passwords = passwords[req.ru:req.ru + req.en]

    td = Path(tempfile.mkdtemp(prefix="brochures_"))
    try:
        qr_paths = []
        for i, pwd in enumerate(passwords, start=1):
            qp = td / f"qr_{i:04d}.png"
            make_qr_png(pwd, str(qp))
            qr_paths.append(str(qp))

        out_pptx = td / "brochures_out.pptx"
        out_pdf_dir = td / "pdf"
        out_pdf_dir.mkdir(parents=True, exist_ok=True)

        build_pptx(
            template_ru=settings.template_ru_path,
            template_en=settings.template_en_path,
            ru_passwords=ru_passwords,
            en_passwords=en_passwords,
            qr_png_paths=qr_paths,
            out_pptx_path=str(out_pptx),
        )
        pdf_path = convert_pptx_to_pdf(settings.soffice_bin, str(out_pptx), str(out_pdf_dir))

    except Exception as e:
        shutil.rmtree(td, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Render failed: {e}")

    # удаляем папку ПОСЛЕ отдачи файла клиенту
    background_tasks.add_task(shutil.rmtree, td, ignore_errors=True)

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename="brochures.pdf",
        background=background_tasks,
    )
