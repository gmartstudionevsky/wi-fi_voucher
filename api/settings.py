from pydantic import BaseModel
import os


class Settings(BaseModel):
    voucher_reservation_url: str = os.getenv(
        "VOUCHER_RESERVATION_URL",
        "https://script.google.com/macros/s/AKfycbzaAM4jvFkdfV5FGANK7FTzvJ2C0I1VaU5dInsQhyAB37g71jMyoR7PeESjQc5Jwd7JnA/exec",
    )
    voucher_request_timeout_seconds: int = int(os.getenv("VOUCHER_REQUEST_TIMEOUT_SECONDS", "30"))

    # Google Sheets metadata used by the Apps Script reservation endpoint.
    spreadsheet_id: str = os.getenv("SPREADSHEET_ID", "127zHlLiojIdj60UJ42vgIU1SlCftqyB-15C9Ur26YL0")
    sheet_name: str | None = os.getenv("SHEET_NAME", "Пароли")
    password_column: str = os.getenv("PASSWORD_COLUMN", "A")

    # Service account JSON path is kept only for legacy/local experiments.
    google_sa_json_path: str = os.getenv("GOOGLE_SA_JSON_PATH", "/run/secrets/google_sa.json")

    # Templates in repo
    template_ru_path: str = os.getenv("TEMPLATE_RU_PATH", "api/templates/brochure_ru.pptx")
    template_en_path: str = os.getenv("TEMPLATE_EN_PATH", "api/templates/brochure_en.pptx")

    # LibreOffice binary
    soffice_bin: str = os.getenv("SOFFICE_BIN", "soffice")


settings = Settings()
