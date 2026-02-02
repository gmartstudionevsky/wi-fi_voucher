from __future__ import annotations

from pathlib import Path
import qrcode

def make_qr_png(password: str, out_path: str):
    # Small payload: simple text like ABCD-1234
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(password)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
