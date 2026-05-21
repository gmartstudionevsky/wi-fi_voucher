# ARTSTUDIO Wi-Fi vouchers

Единый репозиторий для двух сценариев работы с Wi-Fi ваучерами:

- `/guest` — гостевая страница, где гость запрашивает ваучеры по ФИО, номеру апартамента и количеству устройств.
- `/brochures` и `/` — страница для сотрудников, которая генерирует PDF-брошюры RU/EN с паролями и QR-кодами.

Оба сценария используют одну Google Sheets-таблицу `127zHlLiojIdj60UJ42vgIU1SlCftqyB-15C9Ur26YL0`, но больше не меняют её разными способами. Выдача паролей централизована в Apps Script из `apps-script/Code.gs`.

## Как теперь согласованы запросы

- Пароли лежат в листе `Пароли`, колонка A.
- Выданные пароли записываются в лист `запрошено через QR-код`, колонка D.
- Apps Script берёт `LockService`, читает архив выданных кодов и выбирает первые пароли из `Пароли`, которых ещё нет в архиве.
- Строки из листа `Пароли` не удаляются. Это важно: гостевая страница и генератор брошюр больше не сдвигают друг другу строки.
- PDF-генератор не подключается к Google Sheets напрямую. Он вызывает тот же Apps Script endpoint, что и гостевая страница.

## Apps Script

Код лежит в `apps-script/Code.gs`.

После изменения кода Apps Script нужно обновить существующий web app deployment новой версией. Простого сохранения файла недостаточно: публичный `/exec` endpoint продолжит выполнять старую версию, пока deployment не обновлён.

Проверка endpoint:

```bash
curl https://script.google.com/macros/s/<DEPLOYMENT_ID>/exec
```

Ожидаемый ответ содержит `status: "ok"` и `version: "2026-05-21-unified-reservations"`.

## Переменные окружения

- `VOUCHER_RESERVATION_URL` — URL Apps Script web app. По умолчанию используется текущий URL из прежней гостевой страницы.
- `VOUCHER_REQUEST_TIMEOUT_SECONDS` — таймаут запроса к Apps Script, по умолчанию `30`.
- `TEMPLATE_RU_PATH`, `TEMPLATE_EN_PATH` — пути к PPTX-шаблонам.
- `SOFFICE_BIN` — бинарник LibreOffice, по умолчанию `soffice`.

Переменные `GOOGLE_SA_JSON_PATH`, `SPREADSHEET_ID`, `SHEET_NAME`, `PASSWORD_COLUMN` оставлены для совместимости и локальных экспериментов, но основной поток резервации теперь идёт через Apps Script.

## Шаблоны брошюр

Шаблоны лежат в:

- `api/templates/brochure_ru.pptx`
- `api/templates/brochure_en.pptx`

Можно менять дизайн, но нужно сохранить маркеры:

- `{{PASSWORD}}` — место для пароля.
- `{{QR_WIFI}}` — блок, который будет заменён на QR-код с текстом пароля.

## Локальный запуск

Нужен установленный LibreOffice с `soffice` в PATH.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8080
```

Открыть:

- http://localhost:8080/brochures
- http://localhost:8080/guest

## Docker

```bash
docker build -t artstudio-wifi-vouchers:latest .

docker run --rm -p 8080:8080 \
  -e VOUCHER_RESERVATION_URL=https://script.google.com/macros/s/<DEPLOYMENT_ID>/exec \
  artstudio-wifi-vouchers:latest
```

## GitHub Actions

Workflow `.github/workflows/docker-ghcr.yml` собирает и публикует Docker-образ в GHCR на каждый push в `main`.
