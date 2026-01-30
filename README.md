# Guest brochure generator (RU/EN) — passwords + QR

Сервис генерирует один PDF для двусторонней печати:
- пользователь вводит количество брошюр RU и EN
- сервис берёт нужное количество паролей из Google Sheets (колонка A по умолчанию),
  **удаляет использованные строки**
- в PPTX-шаблонах подставляет пароль и заменяет маркер `{{QR_WIFI}}` на QR-код, содержащий **только текст пароля**
- собирает итоговую презентацию (RU блок → EN блок) и конвертирует в PDF через LibreOffice (headless)

## Важно про редактирование дизайна

Шаблоны лежат в:
- `api/templates/brochure_ru.pptx`
- `api/templates/brochure_en.pptx`

Можно менять всё, **кроме маркеров**:
- `{{PASSWORD}}` — место, куда будет вставлен пароль
- `{{QR_WIFI}}` — квадрат/блок, который будет заменён на QR-код

Если вы переместите `{{QR_WIFI}}` — QR будет вставлен в новое место автоматически.

## Настройка Google Sheets

По умолчанию сервис использует spreadsheet id из задачи:
`127zHlLiojIdj60UJ42vgIU1SlCftqyB-15C9Ur26YL0`

Требования к таблице:
- пароли лежат в одной колонке (по умолчанию A)
- может быть заголовок `password` / `пароль` (будет пропущен)
- пустые строки допускаются

### Секрет service account

**Не коммитьте JSON ключ в репозиторий.**

1) Создайте локально папку `.secrets/` (она в `.gitignore`)  
2) Положите файл ключа как: `.secrets/google_sa.json`  
3) Запускайте контейнер, примонтировав файл в `/run/secrets/google_sa.json`

## Переменные окружения

- `GOOGLE_SA_JSON_PATH` — путь к service-account json в контейнере (по умолчанию `/run/secrets/google_sa.json`)
- `SPREADSHEET_ID` — id таблицы (по умолчанию уже задан)
- `SHEET_NAME` — имя листа (опционально, по умолчанию берётся первый лист)
- `PASSWORD_COLUMN` — буква колонки (по умолчанию `A`)
- `TEMPLATE_RU_PATH`, `TEMPLATE_EN_PATH` — пути к PPTX шаблонам (если переименуете)
- `SOFFICE_BIN` — бинарник LibreOffice (по умолчанию `soffice`)

## Локальный запуск (без Docker)

> Нужен установленный LibreOffice с `soffice` в PATH.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export GOOGLE_SA_JSON_PATH=/absolute/path/to/google_sa.json
uvicorn api.main:app --reload --port 8080
```

Откройте: http://localhost:8080

## Запуск в Docker

```bash
docker build -t brochure-gen:latest .

docker run --rm -p 8080:8080 \
  -e GOOGLE_SA_JSON_PATH=/run/secrets/google_sa.json \
  -e SPREADSHEET_ID=127zHlLiojIdj60UJ42vgIU1SlCftqyB-15C9Ur26YL0 \
  -v "$PWD/.secrets/google_sa.json:/run/secrets/google_sa.json:ro" \
  brochure-gen:latest
```

## GitHub Actions

В репозитории есть workflow `.github/workflows/docker-ghcr.yml`, который собирает и пушит Docker-образ в GHCR на каждый push в `main`.
Дальше образ можно запускать на любом сервере/платформе, где есть Docker.
