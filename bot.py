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
        await update.message.reply_text("🚫 Estás bloqueado y no puedes usar este bot.")
        return True
    return False


# ─────────────────────────────────────────────
# User commands
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update):
        return
    uid = update.effective_user.id
    db.register_user(uid, update.effective_user.username or "")
    if is_admin(uid):
        await update.message.reply_text(
            "👋 ¡Bienvenido, Admin!\n\n"
            "Usa /help para ver los comandos de usuario.\n"
            "Usa /adminhelp para ver todos los comandos de administrador."
        )
    else:
        await update.message.reply_text(
            "👋 ¡Bienvenido! Nos alegra tenerte aquí.\n\n"
            "Usa /help para ver todos los comandos disponibles y cómo usarlos."
        )


async def code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update):
        return

    uid = update.effective_user.id
    db.register_user(uid, update.effective_user.username or "")

    if not context.args:
        await update.message.reply_text("Uso: /code <dirección de correo>")
        return

    target_email = context.args[0].strip().lower()

    if not db.is_email_registered(target_email):
        await update.message.reply_text(
            f"❌ No hay ninguna cuenta registrada para *{target_email}*.",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(f"🔍 Buscando el último código para *{target_email}*…", parse_mode="Markdown")

    await asyncio.sleep(5)

    try:
        db.log_code_request(uid, update.effective_user.username or "?", target_email)
        result = fetch_latest_email_for_address(target_email)
        if result is None:
            await update.message.reply_text("⚠️ No se encontró ningún código. Por favor, intenta reenviar el código.", parse_mode="Markdown")
            return

        code_found = extract_code(result["body"])

        if code_found:
    msg = (
        f"✅ *Código:* `{code_found}`\n\n"
        f"🔄 Si el código no funciona, reenvía el correo e intenta el comando de nuevo."
    )
else:
    msg = "⚠️ No se encontró ningún código. Por favor, intenta reenviar el código."

        await update.message.reply_text(msg, parse_mode="Markdown")

    except Exception as e:
        logger.error("Error fetching email: %s", e)
        await update.message.reply_text("⚠️ Ocurrió un error al obtener el correo. Por favor, inténtalo más tarde.")


# ─────────────────────────────────────────────
# Admin commands
# ─────────────────────────────────────────────

async def admin_only(update: Update) -> bool:
    if not update.effective_user or not update.message:
        return True
    if await guard(update):
        return True
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Este comando es solo para administradores.")
        return True
    return False


async def addmail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return
    if not context.args:
        await update.message.reply_text(
            "Uso: /addmail `<correo>`\n\n"
            "Ejemplo: `/addmail user@outlook.com`",
            parse_mode="Markdown"
        )
        return
    email_addr = context.args[0].strip().lower()
    if db.is_email_registered(email_addr):
        await update.message.reply_text(f"ℹ️ {email_addr} ya está registrado.")
        return
    db.add_email(email_addr, added_by=update.effective_user.id)
    await update.message.reply_text(f"✅ *{email_addr}* ha sido registrado.", parse_mode="Markdown")


async def removemail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: /removemail <correo>")
        return
    email_addr = context.args[0].strip().lower()
    if not db.is_email_registered(email_addr):
        await update.message.reply_text(f"❌ {email_addr} no está registrado.")
        return
    db.remove_email(email_addr)
    await update.message.reply_text(f"🗑️ *{email_addr}* ha sido eliminado.", parse_mode="Markdown")


async def listmails(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return
    await send_mails_page(update.message, page=0)


async def send_mails_page(message, page: int):
    PAGE_SIZE = 10
    emails = db.list_emails_paginated(page, PAGE_SIZE)
    total = db.count_emails()

    if total == 0:
        await message.reply_text("📭 Aún no hay direcciones de correo registradas.")
        return

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    lines = [f"{i + 1 + page * PAGE_SIZE}. `{e['email']}`" for i, e in enumerate(emails)]
    text = (
        f"📋 *Correos registrados*\n"
        f"📊 Total: *{total}* correos\n\n"
        f"Página {page + 1}/{total_pages}:\n\n"
        + "\n".join(lines)
    )

    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"mails_page_{page - 1}"))
    if (page + 1) < total_pages:
        buttons.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"mails_page_{page + 1}"))

    keyboard = InlineKeyboardMarkup([buttons]) if buttons else None
    await message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def listusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return
    await send_users_page(update.message, page=0)


async def send_users_page(message, page: int):
    PAGE_SIZE = 10
    users = db.list_users_paginated(page, PAGE_SIZE)
    total = db.count_users()

    if total == 0:
        await message.reply_text("Aún no hay usuarios.")
        return

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    active = db.count_active_users()
    lines = []
    for i, u in enumerate(users):
        status = "🚫 bloqueado" if u.get("blocked") else "✅ activo"
        lines.append(f"{i + 1 + page * PAGE_SIZE}. `{u['telegram_id']}` @{u.get('username', '?')} — {status}")

    text = (
        f"👥 *Todos los usuarios*\n"
        f"📊 Total: *{total}* usuarios\n"
        f"🟢 Activos últimos 30 días: *{active}*\n\n"
        f"Página {page + 1}/{total_pages}:\n\n"
        + "\n".join(lines)
    )

    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"users_page_{page - 1}"))
    if (page + 1) < total_pages:
        buttons.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"users_page_{page + 1}"))

    keyboard = InlineKeyboardMarkup([buttons]) if buttons else None
    await message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def blockuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: /blockuser <telegram_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID de Telegram no válido.")
        return
    db.set_user_blocked(target_id, blocked=True)
    await update.message.reply_text(f"🚫 El usuario `{target_id}` ha sido bloqueado.", parse_mode="Markdown")


async def unblockuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: /unblockuser <telegram_id>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID de Telegram no válido.")
        return
    db.set_user_blocked(target_id, blocked=False)
    await update.message.reply_text(f"✅ El usuario `{target_id}` ha sido desbloqueado.", parse_mode="Markdown")


async def requestlogs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return

    if not context.args:
        await update.message.reply_text(
            "Uso: /requestlogs `<telegram_id>`\n\n"
            "Ejemplo: `/requestlogs 123456789`",
            parse_mode="Markdown"
        )
        return

    try:
        target_id = int(context.args[0].strip())
    except ValueError:
        await update.message.reply_text("❌ ID de Telegram no válido.")
        return

    requests = db.get_user_email_requests(target_id)
    total = db.count_user_requests(target_id)

    if total == 0:
        await update.message.reply_text(
            f"📭 El usuario `{target_id}` no ha realizado ninguna solicitud.",
            parse_mode="Markdown"
        )
        return

    lines = []
    for i, r in enumerate(requests):
        last = r["last_requested"].strftime("%d/%m/%Y %H:%M")
        lines.append(
            f"{i + 1}. `{r['_id']}`\n"
            f"   🔁 {r['count']} solicitudes — último: {last}"
        )

    text = (
        f"📋 *Solicitudes del usuario* `{target_id}`\n"
        f"📊 Total de solicitudes: *{total}*\n\n"
        + "\n".join(lines)
    )

    await update.message.reply_text(text, parse_mode="Markdown")


async def rankings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return

    data = db.get_user_rankings()

    if not data:
        await update.message.reply_text("📭 No hay datos de solicitudes todavía.")
        return

    lines = []
    for i, entry in enumerate(data):
        tid = entry["_id"]["telegram_id"]
        username = entry["_id"].get("username") or "?"
        total = entry["total"]
        if i == 0:
            medal = "🥇"
        elif i == 1:
            medal = "🥈"
        elif i == 2:
            medal = "🥉"
        else:
            medal = f"{i + 1}."
        lines.append(f"{medal} `{tid}` @{username} — *{total}* solicitudes")

    top = data[0]
    top_tid = top["_id"]["telegram_id"]
    top_username = top["_id"].get("username") or "?"
    top_total = top["total"]

    text = (
        f"🏆 *Ranking de usuarios*\n\n"
        f"👑 *Más activo:* `{top_tid}` @{top_username} con *{top_total}* solicitudes\n\n"
        + "\n".join(lines)
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def adminhelp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await admin_only(update):
        return
    text = (
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
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─────────────────────────────────────────────
# Pagination callback
# ─────────────────────────────────────────────

async def pagination_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.answer("⛔ Solo administradores.", show_alert=True)
        return

    data = query.data

    if data.startswith("mails_page_"):
        page = int(data.split("_")[-1])
        PAGE_SIZE = 10
        emails = db.list_emails_paginated(page, PAGE_SIZE)
        total = db.count_emails()
        total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        lines = [f"{i + 1 + page * PAGE_SIZE}. `{e['email']}`" for i, e in enumerate(emails)]
        text = (
            f"📋 *Correos registrados*\n"
            f"📊 Total: *{total}* correos\n\n"
            f"Página {page + 1}/{total_pages}:\n\n"
            + "\n".join(lines)
        )
        buttons = []
        if page > 0:
            buttons.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"mails_page_{page - 1}"))
        if (page + 1) < total_pages:
            buttons.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"mails_page_{page + 1}"))
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
            status = "🚫 bloqueado" if u.get("blocked") else "✅ activo"
            lines.append(f"{i + 1 + page * PAGE_SIZE}. `{u['telegram_id']}` @{u.get('username', '?')} — {status}")
        text = (
            f"👥 *Todos los usuarios*\n"
            f"📊 Total: *{total}* usuarios\n"
            f"🟢 Activos últimos 30 días: *{active}*\n\n"
            f"Página {page + 1}/{total_pages}:\n\n"
            + "\n".join(lines)
        )
        buttons = []
        if page > 0:
            buttons.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"users_page_{page - 1}"))
        if (page + 1) < total_pages:
            buttons.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"users_page_{page + 1}"))
        keyboard = InlineKeyboardMarkup([buttons]) if buttons else None
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


# ─────────────────────────────────────────────
# Help & fallback
# ─────────────────────────────────────────────

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await guard(update):
        return
    text = (
        "📖 *Comandos Disponibles*\n\n"
        "/start — Regístrate y empieza a usar el bot\n"
        "/code `<correo>` — Obtén el último código de 6 dígitos enviado a ese correo\n\n"
        "_Ejemplo:_ `/code tu@dominio.com`\n\n"
        "Si el correo no ha sido registrado por un administrador, recibirás un error."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Comando desconocido. Usa /help para obtener más información.")


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

    # Pagination
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
