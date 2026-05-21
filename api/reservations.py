from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .settings import settings


class VoucherReservationError(RuntimeError):
    pass


def reserve_vouchers(count: int, source: str, metadata: dict[str, Any] | None = None) -> list[str]:
    if count <= 0:
        return []
    if not settings.voucher_reservation_url:
        raise VoucherReservationError("VOUCHER_RESERVATION_URL is not configured.")

    payload: dict[str, Any] = {
        "mode": "reserve",
        "voucher_count": count,
        "source": source,
    }
    if metadata:
        payload.update(metadata)

    body = json.dumps(payload).encode("utf-8")
    request = Request(
        settings.voucher_reservation_url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "text/plain;charset=utf-8",
        },
    )

    try:
        with urlopen(request, timeout=settings.voucher_request_timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise VoucherReservationError(f"Reservation endpoint returned HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise VoucherReservationError(f"Reservation endpoint is unavailable: {error.reason}") from error
    except TimeoutError as error:
        raise VoucherReservationError("Reservation endpoint timed out.") from error

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise VoucherReservationError("Reservation endpoint returned invalid JSON.") from error

    if data.get("error"):
        raise VoucherReservationError(str(data["error"]))

    vouchers = data.get("vouchers")
    if not isinstance(vouchers, list) or len(vouchers) != count:
        raise VoucherReservationError("Reservation endpoint returned an unexpected voucher count.")

    normalized = [str(voucher).strip() for voucher in vouchers]
    if any(not voucher for voucher in normalized):
        raise VoucherReservationError("Reservation endpoint returned an empty voucher.")

    return normalized
