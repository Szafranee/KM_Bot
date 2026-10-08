# Deployment

KM Bot runs on shared hosting (Hostido) the same way as GrafikPlusWeb: a Phusion Passenger Python
application managed with `uv`, updated over SSH/SCP by `deploy.ps1` (PowerShell) or `deploy.sh` (Bash).
Shared hosting does not allow long-running processes, so the bot uses a **Telegram webhook** instead of
long polling, and periodic work runs from **cron**.

```
Telegram ──HTTPS POST /telegram──▶ Passenger ─▶ passenger_wsgi.py ─▶ km_bot.web (python-telegram-bot)
cron ─▶ python -m km_bot refresh-data   (timetable GTFS + KM rolling stock PDFs, daily)
cron ─▶ python -m km_bot check-tracked  (notifications for tracked trains, every 5 min)
```

## 1. One-time server setup (hosting panel)

1. **Subdomain with SSL** – create e.g. `kmbot.xce.pl` and enable a Let's Encrypt certificate.
   Telegram only delivers webhooks over HTTPS with a valid certificate.
2. **Python application** – create a Passenger Python app for the subdomain, exactly like GrafikPlusWeb:
   - Python **3.14** (must match `.python-version`),
   - application root: the directory used as `REMOTE_APP_DIR` (e.g. `/home/<user>/domains/kmbot.xce.pl/KM_Bot`),
   - startup file `passenger_wsgi.py`, entry point `application`.
3. **`.env` on the server** – create `REMOTE_APP_DIR/.env` from `.env.example` (it is never uploaded by the
   deploy scripts):

   ```ini
   TELEGRAM_API_TOKEN=...
   WEBHOOK_URL=https://kmbot.xce.pl/telegram
   WEBHOOK_SECRET=<random string, e.g. python -c "import secrets; print(secrets.token_urlsafe(32))">
   PUBLIC_BASE_URL=https://kmbot.xce.pl
   PLK_API_KEY=            # optional, see below
   GEMINI_API_KEY=         # optional fallback for unknown date notations
   LOG_FILE=data/km_bot.log
   ```

4. **Cron jobs** (panel → Cron jobs). Use the absolute application path:

   ```cron
   */5 * * * *  cd /home/<user>/domains/kmbot.xce.pl/KM_Bot && .venv/bin/python -m km_bot check-tracked >/dev/null 2>&1
   30 4 * * *   cd /home/<user>/domains/kmbot.xce.pl/KM_Bot && .venv/bin/python -m km_bot refresh-data >> data/refresh.log 2>&1
   ```

   KM publishes new rolling stock lists every few weeks and the GTFS feed is rebuilt weekly, so a daily
   refresh is enough (it downloads only what changed). Run it more often if you want new PDFs sooner.

The server needs SSH access with SCP and `uv` on the non-interactive `PATH` (`ssh user@host 'uv --version'`).

## 2. Local deploy configuration

```powershell
Copy-Item deploy.config.ps1.example deploy.config.ps1
```

```bash
cp deploy.config.sh.example deploy.config.sh
```

Fill in the SSH user, host, port, key and `REMOTE_APP_DIR`. Both files are ignored by Git.

## 3. First deployment

```powershell
.\deploy.ps1 -Preset all -RefreshData -SetWebhook
```

```bash
./deploy.sh --preset all --refresh-data --set-webhook
```

This uploads the code, runs `uv sync --locked --no-dev`, checks that `.venv` uses the Python version from
`.python-version`, imports the WSGI app as a preflight, downloads the timetable and rolling stock data,
restarts Passenger and registers the webhook (`WEBHOOK_URL` + `WEBHOOK_SECRET` from the server `.env`) together
with the bot command menu.

Check the result:

```bash
curl https://kmbot.xce.pl/health
ssh user@host 'cd <REMOTE_APP_DIR> && .venv/bin/python -m km_bot webhook-info'
```

## 4. Regular deployments

```powershell
.\deploy.ps1                 # interactive menu, default: only files changed vs the server
.\deploy.ps1 -Preset python  # km_bot/ + passenger_wsgi.py
```

| Purpose | PowerShell | Bash |
| --- | --- | --- |
| Select a preset | `-Preset <name>` | `--preset <name>` |
| Upload explicit paths | `-Files "a.py","b.py"` | `--files "a.py,b.py"` |
| Skip the Passenger restart | `-NoRestart` | `--no-restart` |
| Preview without uploading | `-DryRun` | `--dry-run` |
| Run `refresh-data` on the server | `-RefreshData` | `--refresh-data` |
| Register the webhook | `-SetWebhook` | `--set-webhook` |

| Preset | Contents |
| --- | --- |
| `changed` | Deployable Git files whose MD5 differs from the server copy (default). |
| `all` | Every deployable Git file. |
| `python` | All `.py` files (`km_bot/`, `passenger_wsgi.py`). |
| `assets` | Rolling stock photos in `assets/`. |
| `dependencies` | `pyproject.toml`, `uv.lock`, `.python-version` (followed by `uv sync`). |

Files are discovered with `git ls-files --cached --others --exclude-standard`. Secrets and runtime state
(`.env`, `deploy.config.*`, `data/`, SQLite files, `.venv`, caches, logs) are never uploaded; tests, docs,
Docker files and the deploy scripts are excluded from automatic presets.

## Realtime data: PKP PLK API key (optional)

Delays come from the keyless [mkuran.pl realtime feed](https://mkuran.pl/gtfs/) by default. For data
directly from PKP PLK, register a free key at [pdp-api.plk-sa.pl](https://pdp-api.plk-sa.pl) (tier *Basic*:
100 requests/hour is enough thanks to caching; approval takes a few working days), put it into
`PLK_API_KEY` in the server `.env` and verify it:

```bash
.venv/bin/python -m km_bot plk-check
```

When the PLK API fails the bot automatically falls back to mkuran.pl.

## Local development

```bash
uv sync
cp .env.example .env            # set TELEGRAM_API_TOKEN (preferably of a separate test bot)
uv run python -m km_bot refresh-data
uv run python -m km_bot poll
```

`poll` removes the webhook of the token it uses. If you test with the production token, run
`set-webhook` (or `deploy … -SetWebhook`) afterwards.

## Alternative: Docker / VPS

The `Dockerfile` runs long polling and refreshes the data every 6 hours inside one container:

```bash
docker build -t km-bot .
docker run -d --env-file .env -v km-bot-data:/km_bot/data km-bot
```

Tracked-train notifications are checked by the polling process itself every 2 minutes.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Bot does not answer | `webhook-info` (last error), `curl https://<domain>/health`, `data/km_bot.log` |
| `403` in webhook info | `WEBHOOK_SECRET` in `.env` differs from the registered one – run `set-webhook` again |
| "Rozkład jazdy nie jest jeszcze załadowany" | `refresh-data` has not run yet or failed – run it manually |
| No rolling stock for future days | KM has not published the next "Zestawienie" yet; it is picked up by the daily refresh |
| Startup error after deploy | Passenger stderr log; `.venv` must be created for the Passenger Python version |
