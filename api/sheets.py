from __future__ import annotations

import time
import re
from dataclasses import dataclass
from typing import List, Tuple

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

PASSWORD_HEADER_RE = re.compile(r"^(password|пароль)\b", re.IGNORECASE)

@dataclass
class SheetInfo:
    spreadsheet_id: str
    sheet_title: str
    sheet_id: int

def _build_service(sa_json_path: str):
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = service_account.Credentials.from_service_account_file(sa_json_path, scopes=scopes)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)

def get_sheet_info(sa_json_path: str, spreadsheet_id: str, sheet_name: str | None) -> SheetInfo:
    service = _build_service(sa_json_path)
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheets = meta.get("sheets", [])
    if not sheets:
        raise RuntimeError("Spreadsheet has no sheets.")
    if sheet_name:
        for s in sheets:
            if s.get("properties", {}).get("title") == sheet_name:
                p = s["properties"]
                return SheetInfo(spreadsheet_id, p["title"], p["sheetId"])
        raise RuntimeError(f"Sheet '{sheet_name}' not found.")
    p = sheets[0]["properties"]
    return SheetInfo(spreadsheet_id, p["title"], p["sheetId"])

def fetch_and_delete_passwords(
    sa_json_path: str,
    spreadsheet_id: str,
    sheet_name: str | None,
    column: str,
    count: int,
    max_retries: int = 3
) -> List[str]:
    """Fetch first `count` passwords from the sheet and delete corresponding rows.

    Assumptions (can be adjusted in README):
    - Passwords are stored in a single column (default A)
    - Rows can include an optional header and/or occasional empty rows
    """
    if count <= 0:
        return []

    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            service = _build_service(sa_json_path)
            info = get_sheet_info(sa_json_path, spreadsheet_id, sheet_name)

            rng = f"{info.sheet_title}!{column}:{column}"
            values_resp = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=rng,
                majorDimension="ROWS"
            ).execute()

            rows = values_resp.get("values", [])
            # rows is like [[cell],[cell],...]
            candidates: List[Tuple[int, str]] = []
            for idx_1based, row in enumerate(rows, start=1):
                cell = (row[0] if row else "").strip()
                if not cell:
                    continue
                # skip obvious header
                if idx_1based == 1 and PASSWORD_HEADER_RE.match(cell):
                    continue
                candidates.append((idx_1based, cell))

            if len(candidates) < count:
                raise RuntimeError(f"Not enough passwords in sheet. Needed {count}, found {len(candidates)}.")

            chosen = candidates[:count]
            passwords = [p for _, p in chosen]

            # delete rows from bottom to top to avoid index shifting
            delete_requests = []
            for row_num, _ in sorted(chosen, key=lambda x: x[0], reverse=True):
                delete_requests.append({
                    "deleteDimension": {
                        "range": {
                            "sheetId": info.sheet_id,
                            "dimension": "ROWS",
                            "startIndex": row_num - 1,  # 0-based inclusive
                            "endIndex": row_num         # exclusive
                        }
                    }
                })

            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": delete_requests}
            ).execute()

            return passwords

        except (HttpError, RuntimeError) as e:
            last_err = e
            # simple backoff
            time.sleep(0.6 * attempt)

    raise RuntimeError(f"Google Sheets operation failed after {max_retries} attempts: {last_err}")
