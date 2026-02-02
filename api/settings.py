from pydantic import BaseModel
import os

class Settings(BaseModel):
    # Google Sheets
    spreadsheet_id: str = os.getenv("SPREADSHEET_ID", "127zHlLiojIdj60UJ42vgIU1SlCftqyB-15C9Ur26YL0")
    sheet_name: str | None = os.getenv("SHEET_NAME")  # if None, use the first sheet
    password_column: str = os.getenv("PASSWORD_COLUMN", "A")  # where passwords live
    # Service account JSON path (mounted as a file)
    google_sa_json_path: str = os.getenv("GOOGLE_SA_JSON_PATH", "/run/secrets/google_sa.json")

    # Templates in repo
    template_ru_path: str = os.getenv("TEMPLATE_RU_PATH", "api/templates/brochure_ru.pptx")
    template_en_path: str = os.getenv("TEMPLATE_EN_PATH", "api/templates/brochure_en.pptx")

    # LibreOffice binary
    soffice_bin: str = os.getenv("SOFFICE_BIN", "soffice")

settings = Settings()
