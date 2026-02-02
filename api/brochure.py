from __future__ import annotations

import os
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Iterable

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Emu

PASSWORD_TOKEN = "{{PASSWORD}}"
QR_TOKEN = "{{QR_WIFI}}"

def _iter_shapes_recursive(shapes):
    for sh in shapes:
        yield sh
        if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _iter_shapes_recursive(sh.shapes)

def _replace_text(slide, token: str, value: str) -> bool:
    changed = False
    for sh in _iter_shapes_recursive(slide.shapes):
        if not sh.has_text_frame:
            continue
        text = sh.text_frame.text
        if token in text:
            # Replace entire text (keeps basic formatting; runs may reset)
            sh.text_frame.clear()
            p = sh.text_frame.paragraphs[0]
            run = p.add_run()
            run.text = value
            changed = True
    return changed

def _find_textbox(slide, token: str):
    for sh in _iter_shapes_recursive(slide.shapes):
        if sh.has_text_frame and token in sh.text_frame.text:
            return sh
    return None

def _remove_shape(shape):
    el = shape._element
    el.getparent().remove(el)

def _add_slide_from_template(dst_prs: Presentation, src_slide):
    blank = dst_prs.slide_layouts[6]  # Blank
    new_slide = dst_prs.slides.add_slide(blank)

    # background
    try:
        src_bg = src_slide._element.cSld.bg
        if src_bg is not None:
            new_slide._element.cSld.insert(0, deepcopy(src_bg))
    except Exception:
        pass

    # shapes
    for shape in src_slide.shapes:
        new_el = deepcopy(shape.element)
        new_slide.shapes._spTree.insert_element_before(new_el, 'p:extLst')
    return new_slide

def _insert_qr(slide, qr_png_path: str):
    box = _find_textbox(slide, QR_TOKEN)
    if box:
        left, top, width, height = box.left, box.top, box.width, box.height
        _remove_shape(box)
        slide.shapes.add_picture(qr_png_path, left, top, width=width, height=height)
        return True

    # fallback: place under a "пароль:" / "password:" label if present
    label = None
    for sh in slide.shapes:
        if sh.has_text_frame:
            t = sh.text_frame.text.strip().lower()
            if t.startswith("пароль") or t.startswith("password"):
                label = sh
                break
    if not label:
        return False

    left = label.left
    top = label.top + label.height + Emu(120000)
    size = Emu(1150000)
    slide.shapes.add_picture(qr_png_path, left, top, width=size, height=size)
    return True

def build_pptx(
    template_ru: str,
    template_en: str,
    ru_passwords: list[str],
    en_passwords: list[str],
    qr_png_paths: list[str],
    out_pptx_path: str
):
    """Create a single PPTX that contains RU brochures then EN brochures.

    Each brochure is a full copy of template slides (front+back) with:
    - {{PASSWORD}} replaced by the password
    - {{QR_WIFI}} replaced by a QR with the *raw password string*
    """
    t_ru = Presentation(template_ru)
    t_en = Presentation(template_en)

    # Use RU theme as a base (same visuals for both templates in practice)
    out = Presentation(template_ru)
    # remove all slides from out
    sldIdLst = out.slides._sldIdLst  # noqa
    for i in range(len(sldIdLst)-1, -1, -1):
        rId = sldIdLst[i].rId
        out.part.drop_rel(rId)
        del sldIdLst[i]

    out.slide_width = t_ru.slide_width
    out.slide_height = t_ru.slide_height

    def append_batch(template: Presentation, passwords: list[str], qr_paths_iter: Iterable[str]):
        for pwd, qr_path in zip(passwords, qr_paths_iter):
            new_slides = []
            for src_slide in template.slides:
                new_slides.append(_add_slide_from_template(out, src_slide))
            # apply replacements on slides of this brochure
            for s in new_slides:
                _replace_text(s, PASSWORD_TOKEN, pwd)
                _insert_qr(s, qr_path)

    # qr_png_paths is aligned to ru_passwords+en_passwords order
    ru_qr = qr_png_paths[:len(ru_passwords)]
    en_qr = qr_png_paths[len(ru_passwords):len(ru_passwords)+len(en_passwords)]
    append_batch(t_ru, ru_passwords, ru_qr)
    append_batch(t_en, en_passwords, en_qr)

    out.save(out_pptx_path)

def convert_pptx_to_pdf(soffice_bin: str, pptx_path: str, out_dir: str) -> str:
    pptx_path = str(Path(pptx_path).resolve())
    out_dir = str(Path(out_dir).resolve())

    cmd = [
        soffice_bin,
        "--headless", "--nologo", "--nofirststartwizard", "--norestore",
        "--convert-to", "pdf",
        "--outdir", out_dir,
        pptx_path
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"LibreOffice convert failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
    pdf_path = str(Path(out_dir) / (Path(pptx_path).stem + ".pdf"))
    if not Path(pdf_path).exists():
        raise RuntimeError("PDF file was not produced by LibreOffice.")
    return pdf_path
