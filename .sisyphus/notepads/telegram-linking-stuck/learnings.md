# Learnings

## Telegram Linking Bug
- Root cause: `_link_chat_id()` clears `linking_code = None` after successful bot link, but frontend keeps polling by that cleared code
- Fix direction: separate short-lived `linking_code` from stable browser `client_token`
- Token must be sent via `X-Telegram-Client-Token` header, never in query strings

## Project Conventions
- Branch: `Produzione` for all production work
- Backend: FastAPI + SQLAlchemy + Alembic
- Frontend: Vanilla JS, localStorage for browser state
- Cache bump required in `public/service-worker.js` when frontend JS changes
- Render auto-deploy unreliable; must verify manually

## Database
- SQLite in dev, PostgreSQL in prod
- Alembic migrations in `meteo-backend/db_migrations/versions/`
- Baseline migration: `20260404_0001_baseline_schema.py`
- `TelegramSubscription` model in `meteo-backend/database.py:186-203`

## Test Infrastructure
- pytest available via `pytest-cov` and `pytest-asyncio`
- Existing test: `meteo-backend/tests/test_telegram_notify.py`
- No frontend Playwright specs currently exist

## 2026-05-14 — Stable Telegram Client Token Schema
- Alembic head before the change was `20260512_0007`; the new revision chained from that head as `20260514_0001`.
- The new Telegram schema fields are nullable to preserve existing production rows: `client_token_hash` and `linking_code_expires_at`.
- Client token generation uses `secrets.token_urlsafe(32)` and hashing uses SHA-256 hex; the router helper retries up to 5 times to avoid hash collisions.
- The migration follows the inspector-based idempotent pattern: create the table when missing, otherwise add only missing columns/indexes.

## 2026-05-14 — Header-Based Telegram Linking Contract
- `POST /api/telegram/link-code` now returns both the short-lived `linking_code` and the raw `client_token`; only the SHA-256 hash is persisted server-side.
- The browser-facing Telegram lifecycle now keys off `X-Telegram-Client-Token`: pending rows stay addressable after `/start CODE`, while the OTP is still cleared immediately on successful linking.
- `_link_chat_id()` must clear any older active row for the same `chat_id` before assigning the new one, otherwise the unique DB constraint blocks relinking; preference copying should only fill default/empty values on the new row.
- SQLite can surface naive datetimes even for timezone columns, so status expiry checks need timestamp normalization before comparing against `datetime.now(timezone.utc)`.

## 2026-05-14 — Frontend Telegram Client Token Flow
- Replaced linking_code-based polling with client_token-based auth via X-Telegram-Client-Token header
- localStorage keys: le_previsioni_telegram_client_token_v1 (stable token), le_previsioni_telegram_pending_code_v1 (display-only code)
- Legacy le_previsioni_telegram_code_v1 cleaned up on init; users with only legacy code see disconnected with message
- Terminal states handled: pending (keep polling), expired (stop + retry button), not_found/unlinked (stop + clear + disconnected), error (stop + retry)
- Bounded failure threshold: 5 consecutive fetch failures then stop polling + show connection error with retry
- showTelegramDisconnected() now accepts optional message param for contextual error messages
- showTelegramPending() now takes (code, clientToken) — code for display, token for polling
- savePreferences() and unlinkTelegram() read token from localStorage instead of taking a parameter
- client_token never appears in UI or URL query strings

## 2026-05-14 — Telegram Linking Regression Test Setup
- `meteo-backend/tests/test_telegram_linking.py` imports `main.app` only after setting `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_WEBHOOK_URL`, plus `ENABLE_SCHEDULER=false` and `AUTO_LOAD_CITIES=false` to keep the app bootstrap isolated.
- The isolated SQLite DB is created under `C:/Users/Andrea/AppData/Local/Temp/opencode` because the default `pytest-of-Andrea` temp root can fail with `PermissionError` in this environment.
- The regression suite verifies the full browser-token flow end-to-end: link-code generation, `_link_chat_id()` success/failure paths, header-based status, preferences update, unlink cleanup, expired codes, relink on the same `chat_id`, and duplicate `/start CODE` reuse.

## 2026-05-14 — Production Deploy Notes
- Bumped `public/service-worker.js` cache name to `le-previsioni-static-v16-telegram-fix` so the live frontend can drop stale Telegram JS after deploy.
- `git branch --show-current` confirmed the repo is on `Produzione`, which matches the production workflow rule.
- `public/service-worker.js` passed a direct Node syntax check after the LSP server was unavailable in this environment.
