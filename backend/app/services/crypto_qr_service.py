from __future__ import annotations

from io import BytesIO

import qrcode
from qrcode.constants import ERROR_CORRECT_M

from app.schemas.crypto import _payment_uri


class CryptoQrService:
    @staticmethod
    def png_bytes(invoice) -> bytes:
        qr = qrcode.QRCode(
            version=None,
            error_correction=ERROR_CORRECT_M,
            box_size=7,
            border=3,
        )
        qr.add_data(_payment_uri(invoice))
        qr.make(fit=True)
        image = qr.make_image(fill_color="#07152f", back_color="#ffffff")
        out = BytesIO()
        image.save(out, format="PNG")
        return out.getvalue()
