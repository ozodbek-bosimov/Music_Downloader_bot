# Deploying on alwaysdata (Free plan)

The free plan gives **256 MB RAM, 0.25 CPU, 1 GB disk** — enough for this bot.
This guide assumes you have an alwaysdata account.

## What to expect

- Text searches, Spotify track links, and cached tracks are fast and reliable.
- First-time YouTube downloads of new tracks may occasionally fail with
  "YouTube is temporarily blocking..." (datacenter-IP rate limiting). Caching
  and cookies (below) reduce this a lot.
- If RAM is exceeded, alwaysdata kills the process — so keep auto-restart on.

## 1. Create the database

In the admin panel → **Databases → PostgreSQL**, create a database and user.
Note the host, database name, user, and password.

## 2. Get the code

Use **SSH** (admin panel → Remote access → SSH) and clone the repo into your
account, e.g. under `~/`:

```bash
git clone <your-repo-url> ~/music-bot
cd ~/music-bot
python3 -m venv env
```

## 3. Install and configure

```bash
source install.sh
```

`install.sh` installs dependencies, asks for your bot token and the PostgreSQL
details from step 1, writes `.env`, and runs the database migrations.

(If you prefer manual setup: create `.env` with the variables from the README,
then run `poetry install` and `alembic upgrade head`.)

## 4. Run it as a Process

In the admin panel → **Processes**, add a new process:

- **Command:**
  ```
  /home/<account>/music-bot/env/bin/python /home/<account>/music-bot/main.py
  ```
  (use the real absolute paths to your `env` and `main.py`)
- **Working directory:** the project folder (`/home/<account>/music-bot`)
- **Enable automatic restart** so it comes back if it crashes or the server
  recycles it.

Start the process. Check its log — you should see `Run polling for bot ...`.

> Only run **one** instance. Telegram allows a single poller per bot; a second
> one causes `TelegramConflictError`.

## 5. Cookies (recommended for reliable YouTube)

To avoid "Sign in to confirm you're not a bot":

1. In a browser, log into YouTube with a **throwaway** account (not your main).
2. Export cookies with a "Get cookies.txt" browser extension → save as
   `cookies.txt`.
3. Upload it to the server (e.g. `~/music-bot/cookies.txt`) — keep it private,
   never commit it.
4. Add to `.env`:
   ```
   YTDLP_COOKIEFILE=/home/<account>/music-bot/cookies.txt
   ```
5. Restart the process.

Cookies last weeks to months; re-export when downloads start failing again.

## 6. Maintenance

- **Update yt-dlp** every so often (YouTube changes often):
  ```bash
  source env/bin/activate
  poetry update yt-dlp
  ```
  then restart the process.
- Logs go to the console by default (visible in the alwaysdata process log).
  Set `LOG_TO_FILE=1` only if you want files in `logs/`.

## Tuning for the free plan

The defaults are already tuned for it. If needed, adjust in `.env`:

```
MAX_PARALLEL_DOWNLOADS=1     # keep at 1 on 0.25 CPU
CACHE_MAX_ENTRIES=5000       # ~1 MB in the DB
MAX_TRACK_STORAGE_SIZE=209715200
```
