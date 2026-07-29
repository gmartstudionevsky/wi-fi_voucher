import os
from pathlib import Path

from pydantic import BaseModel


def _default_soffice_bin() -> str:
    configured = os.getenv("SOFFICE_BIN")
    if configured:
        return configured

    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.getenv(variable)
        if not root:
            continue
        candidate = Path(root) / "LibreOffice" / "program" / "soffice.com"
        if candidate.exists():
            return str(candidate)

    return "soffice"


class Settings(BaseModel):
    environment: str = os.getenv("ENVIRONMENT", "development")

    # Local standalone storage. DATABASE_URL takes precedence when configured.
    database_path: str = os.getenv("DATABASE_PATH", "data/vouchers.db")
    database_url: str = os.getenv("DATABASE_URL", "")

    # Tenant boundary. Standalone mode is scoped to exactly one hotel.
    hotel_id: str = os.getenv("HOTEL_ID", "standalone")
    hotel_name: str = os.getenv("HOTEL_NAME", "Standalone hotel")
    reservation_ttl_minutes: int = int(
        os.getenv("RESERVATION_TTL_MINUTES", "15")
    )

    # Templates in repo
    template_ru_path: str = os.getenv("TEMPLATE_RU_PATH", "api/templates/brochure_ru.pptx")
    template_en_path: str = os.getenv("TEMPLATE_EN_PATH", "api/templates/brochure_en.pptx")

    # LibreOffice binary
    soffice_bin: str = _default_soffice_bin()

    # Optional HTTP Basic protection for the password management interface.
    admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "")

    # Same-origin by default. Set a comma-separated allowlist when a separate
    # dashboard frontend starts calling this module directly.
    cors_origins: list[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]


settings = Settings()
