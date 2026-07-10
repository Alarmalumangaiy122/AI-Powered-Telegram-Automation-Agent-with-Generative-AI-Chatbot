"""
Aria — Telegram AI Bot with Scheduled Gmail
===========================================

Install:
pip install groq python-telegram-bot apscheduler pytz PyPDF2

Run:
python aria_bot.py
"""

import io
import re
import logging
import smtplib
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import pytz
from groq import Groq
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from telegram import (
    Update,
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ═══════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GMAIL_SENDER = os.getenv("GMAIL_SENDER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

TIMEZONE = "Asia/Kolkata"

DEFAULT_MODEL = "llama-3.3-70b-versatile"

MODELS = {
    "1": ("llama-3.3-70b-versatile", " LLaMA 3.3 70B"),
    "2": ("llama3-70b-8192", " LLaMA 3 70B"),
    "3": ("llama3-8b-8192", " LLaMA 3 8B"),
    "4": ("mixtral-8x7b-32768", " Mixtral"),
    "5": ("gemma2-9b-it", " Gemma"),
}

SYSTEM_PROMPT = (
    "You are Aria, a helpful Telegram AI assistant. "
    "Keep replies concise and clear."
)
MAX_HISTORY = 20
MAX_FILE_CHARS = 12000

# ═══════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════
# GLOBALS
# ═══════════════════════════════════════════════

groq_client = Groq(api_key=GROQ_API_KEY)

scheduler = AsyncIOScheduler(timezone=TIMEZONE)

user_data = {}

awaiting_body = {}

pending_emails = {}

# ═══════════════════════════════════════════════
# USER STATE
# ═══════════════════════════════════════════════


def get_user(chat_id: int):

    if chat_id not in user_data:
        user_data[chat_id] = {
            "history": [],
            "model": DEFAULT_MODEL,
            "awaiting_model": False,
        }

    return user_data[chat_id]


# ═══════════════════════════════════════════════
# TIME PARSER
# ═══════════════════════════════════════════════

def parse_time(text: str):

    tz = pytz.timezone(TIMEZONE)

    now = datetime.now(tz)

    tl = text.lower()

    # in 30 minutes
    m = re.search(r"in\s+(\d+)\s*(minute|min|hour|hr)s?", tl)

    if m:
        n = int(m.group(1))
        unit = m.group(2)

        delta = (
            timedelta(hours=n)
            if "hour" in unit or unit == "hr"
            else timedelta(minutes=n)
        )

        return now + delta

    tomorrow = "tomorrow" in tl

    tp = re.search(
        r"(\d{1,2})[\.:h](\d{2})\s*(am|pm)?|(\d{1,2})\s*(am|pm)",
        tl,
    )

    if not tp:
        return None

    if tp.group(1):

        hour = int(tp.group(1))
        minute = int(tp.group(2))
        ampm = tp.group(3)

    else:

        hour = int(tp.group(4))
        minute = 0
        ampm = tp.group(5)

    if ampm == "pm" and hour != 12:
        hour += 12

    elif ampm == "am" and hour == 12:
        hour = 0

    target = now.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )

    if tomorrow:
        target += timedelta(days=1)

    elif target <= now:
        target += timedelta(days=1)

    return target


# ═══════════════════════════════════════════════
# EMAIL DETECTION
# ═══════════════════════════════════════════════

EMAIL_TRIGGERS = (
    "schedule email",
    "send email",
    "send a mail",
    "schedule a mail",
    "email to",
    "mail to",
    "send mail",
)


def is_email_request(text: str):

    return any(kw in text.lower() for kw in EMAIL_TRIGGERS)


def extract_email(text: str):

    m = re.search(r"[\w\.\+\-]+@[\w\.\-]+\.\w+", text)

    return m.group(0) if m else None


# ═══════════════════════════════════════════════
# GMAIL SENDER
# ═══════════════════════════════════════════════

def send_gmail(to: str, subject: str, body: str):

    msg = MIMEMultipart("alternative")

    msg["From"] = GMAIL_SENDER
    msg["To"] = to
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:

        srv.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)

        srv.sendmail(
            GMAIL_SENDER,
            to,
            msg.as_string(),
        )

    logger.info(f"Email sent → {to}")


# ═══════════════════════════════════════════════
# SCHEDULED JOB
# ═══════════════════════════════════════════════

async def scheduled_send(bot, chat_id, to, subject, body):

    try:

        send_gmail(to, subject, body)

        tz = pytz.timezone(TIMEZONE)

        now = datetime.now(tz).strftime("%I:%M %p")

        await bot.send_message(
            chat_id=chat_id,
            text=(
                f" *Email delivered!*\n\n"
                f"*To:* `{to}`\n"
                f" *Subject:* {subject}\n"
                f" *Sent at:* {now}"
            ),
            parse_mode="Markdown",
        )

    except Exception as e:

        logger.error(e)

        await bot.send_message(
            chat_id=chat_id,
            text=f" Failed: {e}",
        )


# ═══════════════════════════════════════════════
# GROQ CHAT
# ═══════════════════════════════════════════════

def ask_groq(history, model):

    resp = groq_client.chat.completions.create(
        model=model,
        max_tokens=1024,
        temperature=0.7,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            }
        ]
        + history[-MAX_HISTORY:],
    )

    return resp.choices[0].message.content


# ═══════════════════════════════════════════════
# COMMANDS
# ═══════════════════════════════════════════════

async def cmd_start(update: Update, ctx):

    await update.message.reply_text(
        "✨ *Aria AI Assistant*\n\n"
        "📧 Schedule email example:\n\n"
        "`schedule email to abc@gmail.com at 5pm | hello boss`\n\n"
        "Then confirm it.",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, ctx):

    await update.message.reply_text(
        "📧 Example:\n"
        "`schedule email to abc@gmail.com at 5pm | Hello boss`\n\n"
        "Commands:\n"
        "/clear\n"
        "/model\n"
        "/switch\n"
        "/scheduled",
        parse_mode="Markdown",
    )


async def cmd_clear(update: Update, ctx):

    chat_id = update.effective_chat.id

    get_user(chat_id)["history"] = []

    awaiting_body.pop(chat_id, None)

    pending_emails.pop(chat_id, None)

    await update.message.reply_text("🗑 Cleared")


async def cmd_model(update: Update, ctx):

    user = get_user(update.effective_chat.id)

    await update.message.reply_text(
        f"🤖 Current Model:\n`{user['model']}`",
        parse_mode="Markdown",
    )


async def cmd_switch(update: Update, ctx):

    lines = ["*Choose Model*\n"]

    for num, (_, label) in MODELS.items():
        lines.append(f"`{num}` → {label}")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
    )

    get_user(update.effective_chat.id)["awaiting_model"] = True


async def cmd_scheduled(update: Update, ctx):

    chat_id = update.effective_chat.id

    jobs = [
        j for j in scheduler.get_jobs()
        if str(chat_id) in j.id
    ]

    if not jobs:
        await update.message.reply_text("📭 No scheduled emails.")
        return

    lines = ["📬 Scheduled Emails:\n"]

    for j in jobs:
        t = j.next_run_time.strftime("%d %b %I:%M %p")
        lines.append(f"• {t}")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
    )


# ═══════════════════════════════════════════════
# CALLBACK
# ═══════════════════════════════════════════════

async def callback_email(update: Update, ctx):

    query = update.callback_query

    chat_id = query.message.chat_id

    await query.answer()

    draft = pending_emails.pop(chat_id, None)

    if query.data == "email_confirm" and draft:

        tz = pytz.timezone(TIMEZONE)

        scheduler.add_job(
            scheduled_send,
            trigger=DateTrigger(
                run_date=draft["send_at"],
                timezone=tz,
            ),
            args=[
                ctx.application.bot,
                chat_id,
                draft["to"],
                draft["subject"],
                draft["body"],
            ],
            id=f"{chat_id}_{int(draft['send_at'].timestamp())}",
            replace_existing=True,
        )

        await query.edit_message_text(
            f"✅ *Email Scheduled*\n\n"
            f"📧 `{draft['to']}`\n"
            f"⏰ {draft['send_at'].strftime('%I:%M %p')}",
            parse_mode="Markdown",
        )

    else:

        await query.edit_message_text(" Cancelled")


# ═══════════════════════════════════════════════
# MAIN TEXT HANDLER
# ═══════════════════════════════════════════════

async def handle_text(update: Update, ctx):

    chat_id = update.effective_chat.id

    user = get_user(chat_id)

    text = update.message.text.strip()

    # MODEL SWITCH

    if user["awaiting_model"]:

        user["awaiting_model"] = False

        if text in MODELS:

            mid, label = MODELS[text]

            user["model"] = mid

            await update.message.reply_text(
                f" Switched to {label}"
            )

        else:

            await update.message.reply_text(
                " Invalid model"
            )

        return

    # EMAIL REQUEST

    if is_email_request(text):

        recipient = extract_email(text)

        send_at = parse_time(text)

        if not recipient:

            await update.message.reply_text(
                " Email not found"
            )

            return

        if not send_at:

            await update.message.reply_text(
                " Time not understood"
            )

            return

        # MESSAGE USING |
        body = ""

        if "|" in text:

            parts = text.split("|", 1)

            body = parts[1].strip()

        else:

            body = text

            for kw in EMAIL_TRIGGERS:
                body = re.sub(
                    re.escape(kw),
                    "",
                    body,
                    flags=re.IGNORECASE,
                )

            body = body.replace(recipient, "")

            body = re.sub(
                r"\bat\s*\d{1,2}([:\.h]\d{1,2})?\s*(am|pm)?",
                "",
                body,
                flags=re.IGNORECASE,
            )

            body = re.sub(
                r"\bin\s+\d+\s*(minute|min|hour|hr)s?",
                "",
                body,
                flags=re.IGNORECASE,
            )

            body = re.sub(
                r"\btomorrow\b",
                "",
                body,
                flags=re.IGNORECASE,
            )

            body = re.sub(
                r"\b(to|send|mail|email)\b",
                "",
                body,
                flags=re.IGNORECASE,
            )

            body = re.sub(
                r"\s+",
                " ",
                body,
            ).strip(" ,.-")

        # ASK BODY

        if not body:

            awaiting_body[chat_id] = {
                "to": recipient,
                "send_at": send_at,
            }

            await update.message.reply_text(
                " What's the message?"
            )

            return

        # SUBJECT

        subject = body[:50]

        pending_emails[chat_id] = {
            "to": recipient,
            "send_at": send_at,
            "subject": subject,
            "body": body,
        }

        preview = (
            f"📧 *Email Preview*\n\n"
            f"📨 *To:* `{recipient}`\n"
            f"📌 *Subject:* {subject}\n"
            f"⏰ *Time:* {send_at.strftime('%I:%M %p')}\n\n"
            f"────────────\n"
            f"{body}\n"
            f"────────────"
        )

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        " Confirm",
                        callback_data="email_confirm",
                    ),
                    InlineKeyboardButton(
                        " Cancel",
                        callback_data="email_cancel",
                    ),
                ]
            ]
        )

        await update.message.reply_text(
            preview,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

        return

    # NORMAL AI CHAT

    user["history"].append(
        {
            "role": "user",
            "content": text,
        }
    )

    thinking = await update.message.reply_text(
        "✦ Thinking..."
    )

    try:

        reply = ask_groq(
            user["history"],
            user["model"],
        )

        user["history"].append(
            {
                "role": "assistant",
                "content": reply,
            }
        )

        await thinking.delete()

        for chunk in [
            reply[i:i + 4000]
            for i in range(0, len(reply), 4000)
        ]:
            await update.message.reply_text(chunk)

    except Exception as e:

        await thinking.delete()

        await update.message.reply_text(
            f" Error:\n{e}"
        )


# ═══════════════════════════════════════════════
# DOCUMENT HANDLER
# ═══════════════════════════════════════════════

async def handle_document(update: Update, ctx):

    chat_id = update.effective_chat.id

    user = get_user(chat_id)

    doc = update.message.document

    thinking = await update.message.reply_text(
        "📎 Reading file..."
    )

    try:

        file_obj = await ctx.bot.get_file(doc.file_id)

        raw = bytes(
            await file_obj.download_as_bytearray()
        )

        ext = doc.file_name.rsplit(".", 1)[-1].lower()

        if ext == "pdf":

            import PyPDF2

            reader = PyPDF2.PdfReader(io.BytesIO(raw))

            content = "\n".join(
                page.extract_text() or ""
                for page in reader.pages
            )

        else:

            content = raw.decode(
                "utf-8",
                errors="replace",
            )

        if len(content) > MAX_FILE_CHARS:

            content = (
                content[:MAX_FILE_CHARS]
                + "\n[TRUNCATED]"
            )

        prompt = (
            f"Summarize this file:\n\n{content}"
        )

        user["history"].append(
            {
                "role": "user",
                "content": prompt,
            }
        )

        reply = ask_groq(
            user["history"],
            user["model"],
        )

        await thinking.delete()

        await update.message.reply_text(reply)

    except Exception as e:

        await thinking.delete()

        await update.message.reply_text(
            f" File Error:\n{e}"
        )


# ═══════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════

async def post_init(app: Application):

    scheduler.start()

    await app.bot.set_my_commands(
        [
            BotCommand("start", "Start bot"),
            BotCommand("help", "Help"),
            BotCommand("clear", "Clear chat"),
            BotCommand("model", "Current model"),
            BotCommand("switch", "Switch model"),
            BotCommand("scheduled", "Scheduled emails"),
        ]
    )


async def post_shutdown(app: Application):

    scheduler.shutdown()


# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════

def main():

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(CommandHandler("switch", cmd_switch))
    app.add_handler(CommandHandler("scheduled", cmd_scheduled))

    app.add_handler(
        CallbackQueryHandler(
            callback_email,
            pattern="^email_",
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Document.ALL,
            handle_document,
        )
    )

    logger.info("✨ Aria running...")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
