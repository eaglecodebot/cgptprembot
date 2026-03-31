import os
import re
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from dotenv import load_dotenv
from db import Database
from mail_client import fetch_latest_email_for_address

load_dotenv()

logging.basicConfig(

    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in the environment / .env file")

try:
    db = Database()
    logger.info("Database connection established.")
except Exception as e:
    logger.critical("Failed to connect to the database: %s", e)
    raise


# ─────────────────────────────────────────────
# Translations
# ─────────────────────────────────────────────

STRINGS = {
    "en": {
        "blocked":                  "🚫 You are blocked and cannot use this bot.",
        "admin_only":               "⛔ This command is for admins only.",
        "welcome_admin":            "👋 Welcome, Admin!\n\nUse /help to see user commands.\nUse /adminhelp to see all admin commands.",
        "welcome_user":             "👋 Welcome! Great to have you here.\n\nUse /help to see all available commands and how to use them.",
        "choose_language":          "🌐 Please choose your language:",
        "language_set":             "✅ Language set to English!",
        "code_usage":               "Usage: /code <email address>",
        "code_not_registered":      "❌ No account registered for *{email}*.",
        "code_searching":           "🔍 Searching for the latest code for *{email}*…",
        "code_not_found":           "⚠️ No code found. Please try resending the verification email.",
        "code_found":               "✅ *Code:* `{code}`",
        "code_hint":                "🔄 If the code doesn't work, try resending the email and run the command again.",
        "code_error":               "⚠️ An error occurred while fetching the email. Please try again later.",
        "addmail_usage":            "Usage: /addmail `<email>`\n\nExample: `/addmail user@outlook.com`",
        "addmail_exists":           "ℹ️ {email} is already registered.",
        "addmail_done":             "✅ *{email}* has been registered.",
        "removemail_usage":         "Usage: /removemail <email>",
        "removemail_not_found":     "❌ {email} is not registered.",
        "removemail_done":          "🗑️ *{email}* has been removed.",
        "listmails_empty":          "📭 No email addresses registered yet.",
        "listmails_header":         "📋 *Registered Emails*\n📊 Total: *{total}* emails\n\nPage {page}/{total_pages}:\n\n",
        "listusers_empty":          "No users yet.",
        "listusers_header":         "👥 *All Users*\n📊 Total: *{total}* users\n🟢 Active last 30 days: *{active}*\n\nPage {page}/{total_pages}:\n\n",
        "user_blocked_status":      "🚫 blocked",
        "user_active_status":       "✅ active",
        "blockuser_usage":          "Usage: /blockuser <telegram_id>",
        "blockuser_invalid_id":     "❌ Invalid Telegram ID.",
        "blockuser_done":           "🚫 User `{uid}` has been blocked.",
        "unblockuser_usage":        "Usage: /unblockuser <telegram_id>",
        "unblockuser_invalid_id":   "❌ Invalid Telegram ID.",
        "unblockuser_done":         "✅ User `{uid}` has been unblocked.",
        "requestlogs_usage":        "Usage: /requestlogs `<telegram_id>`\n\nExample: `/requestlogs 123456789`",
        "requestlogs_invalid_id":   "❌ Invalid Telegram ID.",
        "requestlogs_empty":        "📭 User `{uid}` has made no requests.",
        "requestlogs_header":       "📋 *Requests by user* `{uid}`\n📊 Total requests: *{total}*\n\n",
        "requestlogs_row":          "{i}. `{email}`\n   🔁 {count} requests — last: {last}",
        "rankings_empty":           "📭 No request data yet.",
        "rankings_top":             "🏆 *User Rankings*\n\n👑 *Most active:* `{tid}` @{username} with *{total}* requests\n\n",
        "rankings_row":             "{medal} `{tid}` @{username} — *{total}* requests",
        "adminhelp_text":           (
            "🛠️ *Admin Commands*\n\n"
            "/addmail `<email>` — Register a new email address\n"
            "/removemail `<email>` — Remove a registered email\n"
            "/listmails — View all registered emails\n"
            "/listusers — View all bot users\n"
            "/blockuser `<id>` — Block a user by Telegram ID\n"
            "/unblockuser `<id>` — Unblock a user\n"
            "/requestlogs `<id>` — View emails requested by a user\n"
            "/rankings — View user rankings by requests\n"
            "/adminhelp — Show this message"
        ),
        "help_text":                (
            "📖 *Available Commands*\n\n"
            "/start — Register and start using the bot\n"
            "/code `<email>` — Get the latest code sent to that email\n\n"
            "_Example:_ `/code you@domain.com`\n\n"
            "If the email hasn't been registered by an admin, you'll get an error."
        ),
        "unknown_command":          "❓ Unknown command. Use /help for more information.",
        "btn_prev":                 "⬅️ Previous",
        "btn_next":                 "Next ➡️",
    },
    "es": {
        "blocked":                  "🚫 Estás bloqueado y no puedes usar este bot.",
        "admin_only":               "⛔ Este comando es solo para administradores.",
        "welcome_admin":            "👋 ¡Bienvenido, Admin!\n\nUsa /help para ver los comandos de usuario.\nUsa /adminhelp para ver todos los comandos de administrador.",
        "welcome_user":             "👋 ¡Bienvenido! Nos alegra tenerte aquí.\n\nUsa /help para ver todos los comandos disponibles y cómo usarlos.",
        "choose_language":          "🌐 Por favor elige tu idioma:",
        "language_set":             "✅ ¡Idioma configurado en Español!",
        "code_usage":               "Uso: /code <dirección de correo>",
        "code_not_registered":      "❌ No hay ninguna cuenta registrada para *{email}*.",
        "code_searching":           "🔍 Buscando el último código para *{email}*…",
        "code_not_found":           "⚠️ No se encontró ningún código. Por favor, intenta reenviar el correo de verificación.",
        "code_found":               "✅ *Código:* `{code}`",
        "code_hint":                "🔄 Si el código no funciona, intenta reenviar el correo y ejecuta el comando de nuevo.",
        "code_error":               "⚠️ Ocurrió un error al obtener el correo. Por favor, inténtalo más tarde.",
        "addmail_usage":            "Uso: /addmail `<correo>`\n\nEjemplo: `/addmail user@outlook.com`",
        "addmail_exists":           "ℹ️ {email} ya está registrado.",
        "addmail_done":             "✅ *{email}* ha sido registrado.",
        "removemail_usage":         "Uso: /removemail <correo>",
        "removemail_not_found":     "❌ {email} no está registrado.",
        "removemail_done":          "🗑️ *{email}* ha sido eliminado.",
        "listmails_empty":          "📭 Aún no hay direcciones de correo registradas.",
        "listmails_header":         "📋 *Correos registrados*\n📊 Total: *{total}* correos\n\nPágina {page}/{total_pages}:\n\n",
        "listusers_empty":          "Aún no hay usuarios.",
        "listusers_header":         "👥 *Todos los usuarios*\n📊 Total: *{total}* usuarios\n🟢 Activos últimos 30 días: *{active}*\n\nPágina {page}/{total_pages}:\n\n",
        "user_blocked_status":      "🚫 bloqueado",
        "user_active_status":       "✅ activo",
        "blockuser_usage":          "Uso: /blockuser <telegram_id>",
        "blockuser_invalid_id":     "❌ ID de Telegram no válido.",
        "blockuser_done":           "🚫 El usuario `{uid}` ha sido bloqueado.",
        "unblockuser_usage":        "Uso: /unblockuser <telegram_id>",
        "unblockuser_invalid_id":   "❌ ID de Telegram no válido.",
        "unblockuser_done":         "✅ El usuario `{uid}` ha sido desbloqueado.",
        "requestlogs_usage":        "Uso: /requestlogs `<telegram_id>`\n\nEjemplo: `/requestlogs 123456789`",
        "requestlogs_invalid_id":   "❌ ID de Telegram no válido.",
        "requestlogs_empty":        "📭 El usuario `{uid}` no ha realizado ninguna solicitud.",
        "requestlogs_header":       "📋 *Solicitudes del usuario* `{uid}`\n📊 Total de solicitudes: *{total}*\n\n",
        "requestlogs_row":          "{i}. `{email}`\n   🔁 {count} solicitudes — último: {last}",
        "rankings_empty":           "📭 No hay datos de solicitudes todavía.",
        "rankings_top":             "🏆 *Ranking de usuarios*\n\n👑 *Más activo:* `{tid}` @{username} con *{total}* solicitudes\n\n",
        "rankings_row":             "{medal} `{tid}` @{username} — *{total}* solicitudes",
        "adminhelp_text":           (
            "🛠️ *Comandos de Administrador*\n\n"
            "/addmail `<correo>` — Registrar una nueva dirección de correo\n"
            "/removemail `<correo>` — Eliminar un correo registrado\n"
            "/listmails — Ver todos los correos registrados\n"
            "/listusers — Ver todos los usuarios del bot\n"
            "/blockuser `<id>` — Bloquear un usuario por su ID de Telegram\n"
            "/unblockuser `<id>` — Desbloquear un usuario\n"
            "/requestlogs `<id>` — Ver correos solicitados por un usuario\n"
            "/rankings — Ver ranking de usuarios por solicitudes\n"
            "/adminhelp — Mostrar este mensaje"
        ),
        "help_text":                (
            "📖 *Comandos Disponibles*\n\n"
            "/start — Regístrate y empieza a usar el bot\n"
            "/code `<correo>` — Obtén el último código de enviado a ese correo\n\n"
            "_Ejemplo:_ `/code tu@dominio.com`\n\n"
            "Si el correo no ha sido registrado por un administrador, recibirás un error."
        ),
        "unknown_command":          "❓ Comando desconocido. Usa /help para obtener más información.",
        "btn_prev":                 "⬅️ Anterior",
        "btn_next":                 "Siguiente ➡️",
    },
}


def t(uid: int, key: str, **kwargs) -> str:
    """Return translated string for user's language."""
    lang = db.get_user_language(uid)
    text = STRINGS.get(lang, STRINGS["es"]).get(key, key)
    return text.format(**kwargs) if kwargs else text


def extract_code(body: str):
    """Extract a 6-digit code from the email body."""
    match = re.search(r'\b(\d{6})\b', body)
    return match.group(1) if match else None


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return db.is_admin(user_id)


def is_blocked(user_id: int) -> bool:
    return db.is_user_blocked(user_id)


async def guard(update: Update) -> bool:
    if not update.effective_user or not update.message:
        return True
    uid = update.effective_user.id
    if is_blocked(uid):
        await update.message.reply_text(t(uid, "blocked"))
        return True
    return False


# ─────────────────────────────────────────────
# User commands
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
    uid = update.effective_user.id
    if db.is_user_blocked(uid):
        lang = db.get_user_language(uid)
        await update.message.reply_text(STRINGS[lang]["blocked"])
        return
    db.register_user(uid, update.effective_user.username or "")
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
        InlineKeyboardButton("🇪🇸 Español", callback_data="lang_es"),
    ]])
    await update.message.reply_text("🌐 Please choose your language / Por favor elige tu idioma:", reply_markup=keyboard)


async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    lang = query.data.split("_")[1]  # "en" or "es"
    db.set_user_language(uid, lang)

    await query.edit_message_text(STRINGS[lang]["language_set"])

    if is_admin(uid):
        await context.bot.send_message(uid, STRINGS[lang]["welcome_admin"])
    else:
        await context.bot.send_message(uid, STRINGS[lang]["welcome_user"])


async def code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update):
        return

    uid = update.effective_user.id
    db.register_user(uid, update.effective_user.username or "")

    if not context.args:
        await update.message.reply_text(t(uid, "code_usage"))
        return

    target_email = context.args[0].strip().lower()

    if not db.is_email_registered(target_email):
        await update.message.reply_text(t(uid, "code_not_registered", email=target_email), parse_mode="Markdown")
        return

    await update.message.reply_text(t(uid, "code_searching", email=target_email), parse_mode="Markdown")
    await asyncio.sleep(5)

    try:
        db.log_code_request(uid, update.effective_user.username or "?", target_email)
        result = fetch_latest_email_for_address(target_email)
        if result is None:
            await update.message.reply_text(t(uid, "code_not_found"), parse_mode="Markdown")
            return

        code_found = extract_code(result["body"])

        if code_found:
            await update.message.reply_text(t(uid, "code_found", code=code_found), parse_mode="Markdown")
            await update.message.reply_text(t(uid, "code_hint"), parse_mode="Markdown")
        else:
            await update.message.reply_text(t(uid, "code_not_found"), parse_mode="Markdown")

    except Exception as e:
        logger.error("Error fetching email: %s", e)
        await update.message.reply_text(t(uid, "code_error"))


# ─────────────────────────────────────────────
# Admin commands
# ─────────────────────────────────────────────

async def admin_only(update: Update) -> bool:
    if not update.effective_user or not update.message:
        return True
    if await guard(update):
        return True
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text(t(uid, "admin_only"))
        return True
    return False


async def addmail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text(t(uid, "addmail_usage"), parse_mode="Markdown")
        return
    email_addr = context.args[0].strip().lower()
    if db.is_email_registered(email_addr):
        await update.message.reply_text(t(uid, "addmail_exists", email=email_addr))
        return
    db.add_email(email_addr, added_by=uid)
    await update.message.reply_text(t(uid, "addmail_done", email=email_addr), parse_mode="Markdown")


async def removemail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text(t(uid, "removemail_usage"))
        return
    email_addr = context.args[0].strip().lower()
    if not db.is_email_registered(email_addr):
        await update.message.reply_text(t(uid, "removemail_not_found", email=email_addr))
        return
    db.remove_email(email_addr)
    await update.message.reply_text(t(uid, "removemail_done", email=email_addr), parse_mode="Markdown")


async def listmails(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return
    await send_mails_page(update.message, page=0, uid=update.effective_user.id)


async def send_mails_page(message, page: int, uid: int):
    PAGE_SIZE = 10
    emails = db.list_emails_paginated(page, PAGE_SIZE)
    total = db.count_emails()

    if total == 0:
        await message.reply_text(t(uid, "listmails_empty"))
        return

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    lines = [f"{i + 1 + page * PAGE_SIZE}. `{e['email']}`" for i, e in enumerate(emails)]
    text = t(uid, "listmails_header", total=total, page=page+1, total_pages=total_pages) + "\n".join(lines)

    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton(t(uid, "btn_prev"), callback_data=f"mails_page_{page - 1}"))
    if (page + 1) < total_pages:
        buttons.append(InlineKeyboardButton(t(uid, "btn_next"), callback_data=f"mails_page_{page + 1}"))

    keyboard = InlineKeyboardMarkup([buttons]) if buttons else None
    await message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def listusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return
    await send_users_page(update.message, page=0, uid=update.effective_user.id)


async def send_users_page(message, page: int, uid: int):
    PAGE_SIZE = 10
    users = db.list_users_paginated(page, PAGE_SIZE)
    total = db.count_users()

    if total == 0:
        await message.reply_text(t(uid, "listusers_empty"))
        return

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    active = db.count_active_users()
    lines = []
    for i, u in enumerate(users):
        status = t(uid, "user_blocked_status") if u.get("blocked") else t(uid, "user_active_status")
        lines.append(f"{i + 1 + page * PAGE_SIZE}. `{u['telegram_id']}` @{u.get('username', '?')} — {status}")

    text = t(uid, "listusers_header", total=total, active=active, page=page+1, total_pages=total_pages) + "\n".join(lines)

    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton(t(uid, "btn_prev"), callback_data=f"users_page_{page - 1}"))
    if (page + 1) < total_pages:
        buttons.append(InlineKeyboardButton(t(uid, "btn_next"), callback_data=f"users_page_{page + 1}"))

    keyboard = InlineKeyboardMarkup([buttons]) if buttons else None
    await message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def blockuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text(t(uid, "blockuser_usage"))
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(t(uid, "blockuser_invalid_id"))
        return
    db.set_user_blocked(target_id, blocked=True)
    await update.message.reply_text(t(uid, "blockuser_done", uid=target_id), parse_mode="Markdown")


async def unblockuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text(t(uid, "unblockuser_usage"))
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(t(uid, "unblockuser_invalid_id"))
        return
    db.set_user_blocked(target_id, blocked=False)
    await update.message.reply_text(t(uid, "unblockuser_done", uid=target_id), parse_mode="Markdown")


async def requestlogs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text(t(uid, "requestlogs_usage"), parse_mode="Markdown")
        return
    try:
        target_id = int(context.args[0].strip())
    except ValueError:
        await update.message.reply_text(t(uid, "requestlogs_invalid_id"))
        return

    requests = db.get_user_email_requests(target_id)
    total = db.count_user_requests(target_id)

    if total == 0:
        await update.message.reply_text(t(uid, "requestlogs_empty", uid=target_id), parse_mode="Markdown")
        return

    lines = []
    for i, r in enumerate(requests):
        last = r["last_requested"].strftime("%d/%m/%Y %H:%M")
        lines.append(t(uid, "requestlogs_row", i=i+1, email=r["_id"], count=r["count"], last=last))

    text = t(uid, "requestlogs_header", uid=target_id, total=total) + "\n".join(lines)
    await update.message.reply_text(text, parse_mode="Markdown")


async def rankings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return

    uid = update.effective_user.id
    data = db.get_user_rankings()

    if not data:
        await update.message.reply_text(t(uid, "rankings_empty"))
        return

    lines = []
    for i, entry in enumerate(data):
        tid = entry["_id"]["telegram_id"]
        username = entry["_id"].get("username") or "?"
        total = entry["total"]
        medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i + 1}."
        lines.append(t(uid, "rankings_row", medal=medal, tid=tid, username=username, total=total))

    top = data[0]
    text = t(uid, "rankings_top",
             tid=top["_id"]["telegram_id"],
             username=top["_id"].get("username") or "?",
             total=top["total"]) + "\n".join(lines)
    await update.message.reply_text(text, parse_mode="Markdown")


async def adminhelp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return
    uid = update.effective_user.id
    await update.message.reply_text(t(uid, "adminhelp_text"), parse_mode="Markdown")


# ─────────────────────────────────────────────
# Pagination callback
# ─────────────────────────────────────────────

async def pagination_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    data = query.data

    # Language selection
    if data.startswith("lang_"):
        await language_callback(update, context)
        return

    await query.answer()

    if not is_admin(uid):
        await query.answer(STRINGS["en"]["admin_only"], show_alert=True)
        return

    if data.startswith("mails_page_"):
        page = int(data.split("_")[-1])
        PAGE_SIZE = 10
        emails = db.list_emails_paginated(page, PAGE_SIZE)
        total = db.count_emails()
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        lines = [f"{i + 1 + page * PAGE_SIZE}. `{e['email']}`" for i, e in enumerate(emails)]
        text = t(uid, "listmails_header", total=total, page=page+1, total_pages=total_pages) + "\n".join(lines)
        buttons = []
        if page > 0:
            buttons.append(InlineKeyboardButton(t(uid, "btn_prev"), callback_data=f"mails_page_{page - 1}"))
        if (page + 1) < total_pages:
            buttons.append(InlineKeyboardButton(t(uid, "btn_next"), callback_data=f"mails_page_{page + 1}"))
        keyboard = InlineKeyboardMarkup([buttons]) if buttons else None
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)

    elif data.startswith("users_page_"):
        page = int(data.split("_")[-1])
        PAGE_SIZE = 10
        users = db.list_users_paginated(page, PAGE_SIZE)
        total = db.count_users()
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        active = db.count_active_users()
        lines = []
        for i, u in enumerate(users):
            status = t(uid, "user_blocked_status") if u.get("blocked") else t(uid, "user_active_status")
            lines.append(f"{i + 1 + page * PAGE_SIZE}. `{u['telegram_id']}` @{u.get('username', '?')} — {status}")
        text = t(uid, "listusers_header", total=total, active=active, page=page+1, total_pages=total_pages) + "\n".join(lines)
        buttons = []
        if page > 0:
            buttons.append(InlineKeyboardButton(t(uid, "btn_prev"), callback_data=f"users_page_{page - 1}"))
        if (page + 1) < total_pages:
            buttons.append(InlineKeyboardButton(t(uid, "btn_next"), callback_data=f"users_page_{page + 1}"))
        keyboard = InlineKeyboardMarkup([buttons]) if buttons else None
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


# ─────────────────────────────────────────────
# Help & fallback
# ─────────────────────────────────────────────

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update):
        return
    uid = update.effective_user.id
    await update.message.reply_text(t(uid, "help_text"), parse_mode="Markdown")


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return
    uid = update.effective_user.id
    await update.message.reply_text(t(uid, "unknown_command"))


# ─────────────────────────────────────────────
# App bootstrap
# ─────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN is missing. Exiting.")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # User
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("code", code))

    # Admin
    app.add_handler(CommandHandler("addmail", addmail))
    app.add_handler(CommandHandler("removemail", removemail))
    app.add_handler(CommandHandler("listmails", listmails))
    app.add_handler(CommandHandler("listusers", listusers))
    app.add_handler(CommandHandler("blockuser", blockuser))
    app.add_handler(CommandHandler("unblockuser", unblockuser))
    app.add_handler(CommandHandler("requestlogs", requestlogs))
    app.add_handler(CommandHandler("rankings", rankings))
    app.add_handler(CommandHandler("adminhelp", adminhelp))

    # Pagination + Language selection (single CallbackQueryHandler routes both)
    app.add_handler(CallbackQueryHandler(pagination_callback))

    # Fallback
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    logger.info("Bot is running…")
    try:
        app.run_polling()
    except Exception as e:
        logger.critical("Bot crashed: %s", e)
        raise


if __name__ == "__main__":
    main()
