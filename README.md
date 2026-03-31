# 📬 Telegram Mail Bot

A Telegram bot that lets users fetch the latest email sent to a specific address from a **catch-all IMAP inbox**. Admins can manage registered emails and users via Telegram commands.

---

## Project Structure

```
telegram-mail-bot/
├── bot.py            # Telegram bot — all command handlers
├── db.py             # MongoDB layer (users, emails, admins)
├── mail_client.py    # IMAP fetcher (searches TO: header)
├── requirements.txt
└── .env.example      # Copy to .env and fill in your values
```

---

## Setup

### 1. Clone & install dependencies

```bash
git clone <your-repo>
cd telegram-mail-bot
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Your BotFather token |
| `ADMIN_IDS` | Comma-separated Telegram user IDs for admins |
| `MONGO_URI` | MongoDB Atlas connection string |
| `MONGO_DB_NAME` | Database name (default: `telegram_mail_bot`) |
| `IMAP_HOST` | IMAP server hostname |
| `IMAP_PORT` | IMAP port (default: `993` for SSL) |
| `IMAP_USER` | The catch-all inbox login email |
| `IMAP_PASS` | IMAP password / app password |
| `IMAP_MAILBOX` | Mailbox to search (default: `INBOX`) |

### 3. Run locally

```bash
python bot.py
```

---

## Deploying to Render (free tier)

1. Push your code to a GitHub repo (exclude `.env` — add it to `.gitignore`).
2. Go to [render.com](https://render.com) → **New → Background Worker**.
3. Connect your GitHub repo.
4. Set **Build Command**: `pip install -r requirements.txt`
5. Set **Start Command**: `python bot.py`
6. Add all your `.env` variables under **Environment → Environment Variables**.
7. Deploy.

> ⚠️ Render free tier spins down after inactivity. For a persistent bot, use a **paid instance** or keep it alive with an external pinger.

---

## Bot Commands

### User commands

| Command | Description |
|---|---|
| `/start` | Register and show welcome message |
| `/code <email>` | Fetch the latest email sent TO that address |

### Admin commands

| Command | Description |
|---|---|
| `/addmail <email>` | Register an email address |
| `/removemail <email>` | Remove a registered email |
| `/listmails` | Show all registered emails |
| `/listusers` | Show all users and their status |
| `/blockuser <telegram_id>` | Block a user |
| `/unblockuser <telegram_id>` | Unblock a user |
| `/adminhelp` | List all admin commands |

---

## How it works

1. Admin registers allowed email addresses via `/addmail`.
2. A user sends `/code user@domain.com`.
3. The bot checks MongoDB — if the address isn't registered, it replies with an error.
4. If registered, it connects to the catch-all IMAP inbox and searches for the most recent email where the **To / Cc / Delivered-To** header matches `user@domain.com`.
5. The result (sender, date, subject, body) is sent back to the user.

---

## MongoDB Collections

| Collection | Purpose |
|---|---|
| `users` | All users who have interacted with the bot |
| `registered_emails` | Emails that admins have approved |
| `admins` | Seeded from `ADMIN_IDS` env var on startup |
