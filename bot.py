import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, time
from typing import Optional, Dict

# ---- Telegram imports (and version log) ----
import telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ======== HARD-CODED TOKEN & DEFAULT CHAT ID ========
TOKEN = "8448114982:AAFjVekkgALSK9M3CKc8K7KjrUSTcsvPvIc"
DEFAULT_CHAT_ID = -1001819726736  # your group chat ID

# Pin polls? (True/False)
PIN_POLLS = True  # keep pinning enabled

# ---- Timezone: ZoneInfo with pytz fallback ----
try:
    from zoneinfo import ZoneInfo
    SGT = ZoneInfo("Asia/Singapore")
except Exception:
    try:
        import pytz  # type: ignore
        SGT = pytz.timezone("Asia/Singapore")
    except Exception:
        from datetime import timezone as _tz
        SGT = _tz.utc  # last resort; use UTC

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.info(f"python-telegram-bot version: {getattr(telegram, '__version__', 'unknown')}")

# ---------- Poll tracking (stores chat_id + message_id) ----------
@dataclass
class PollRef:
    chat_id: int
    message_id: int

# In-memory storage (resets if container restarts)
STATE: Dict[str, Optional[PollRef]] = {"cg_poll": None, "svc_poll": None}

# ---------- Date helpers ----------
def next_weekday_date_exclusive(now_dt: datetime, weekday: int):
    days_ahead = (weekday - now_dt.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (now_dt + timedelta(days=days_ahead)).date()

def next_or_same_weekday_date(now_dt: datetime, weekday: int):
    days_ahead = (weekday - now_dt.weekday()) % 7
    return (now_dt + timedelta(days=days_ahead)).date()

def upcoming_friday_for_poll(now_dt: datetime):
    return next_weekday_date_exclusive(now_dt, 4)  # Fri = 4

def upcoming_sunday_for_poll(now_dt: datetime):
    return next_weekday_date_exclusive(now_dt, 6)  # Sun = 6

def friday_for_reminder(now_dt: datetime):
    return next_or_same_weekday_date(now_dt, 4)

def sunday_for_reminder(now_dt: datetime):
    return next_or_same_weekday_date(now_dt, 6)

def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"

def format_date_long(d) -> str:
    # e.g., 31st August 2025 (Sun)
    return f"{ordinal(d.day)} {d.strftime('%B %Y')} ({d.strftime('%a')})"

def format_date_plain(d) -> str:
    # e.g., 31st August 2025
    return f"{ordinal(d.day)} {d.strftime('%B %Y')}"

def _effective_target_chat(update: Optional[Update]) -> int:
    if update and update.effective_chat:
        return update.effective_chat.id
    return DEFAULT_CHAT_ID

async def _safe_pin(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    if not PIN_POLLS:
        return
    try:
        await ctx.bot.pin_chat_message(chat_id, message_id, disable_notification=True)
    except Exception as e:
        logging.warning(f"Pin failed: {e}")

async def _remind_with_reply_fallback(
    ctx: ContextTypes.DEFAULT_TYPE,
    target_chat_id: int,
    reply_to_msg_id: Optional[int],
    text_reply: str,
    text_plain: str,
):
    try:
        if reply_to_msg_id:
            await ctx.bot.send_message(
                chat_id=target_chat_id,
                text=text_reply,
                reply_to_message_id=reply_to_msg_id,
                allow_sending_without_reply=True,
            )
        else:
            await ctx.bot.send_message(chat_id=target_chat_id, text=text_plain)
    except Exception as e:
        logging.warning(f"Reply failed ({e}); sending plain reminder instead.")
        try:
            await ctx.bot.send_message(chat_id=target_chat_id, text=text_plain)
        except Exception as e2:
            logging.exception(f"Plain reminder also failed: {e2}")

# ---------- Poll senders (with fun emojis) ----------
async def send_sunday_service_poll(ctx: ContextTypes.DEFAULT_TYPE, update: Optional[Update] = None):
    target_chat = _effective_target_chat(update)
    now = datetime.now(SGT)
    target = upcoming_sunday_for_poll(now)
    msg = await ctx.bot.send_poll(
        chat_id=target_chat,
        question=f"Sunday Service – {format_date_long(target)}",
        options=[
            "⏰ 9am",
            "🕚 11.15am",
            "🙋 Serving",
            "🍽️ Lunch",
            "🧑‍🤝‍🧑 Invited a friend",
        ],
        is_anonymous=False,
        allows_multiple_answers=True,
    )
    STATE["svc_poll"] = PollRef(chat_id=target_chat, message_id=msg.message_id)
    await _safe_pin(ctx, target_chat, msg.message_id)

async def send_cell_group_poll(ctx: ContextTypes.DEFAULT_TYPE, update: Optional[Update] = None):
    target_chat = _effective_target_chat(update)
    now = datetime.now(SGT)
    target = upcoming_friday_for_poll(now)
    msg = await ctx.bot.send_poll(
        chat_id=target_chat,
        question=f"Cell Group – {format_date_long(target)}",
        options=[
            "🍽️ Dinner 7.15pm",
            "⛪ CG 8.15pm",
            "❌ Cannot make it",
        ],
        is_anonymous=False,
        allows_multiple_answers=False,
    )
    STATE["cg_poll"] = PollRef(chat_id=target_chat, message_id=msg.message_id)
    await _safe_pin(ctx, target_chat, msg.message_id)

# ---------- Reminders ----------
async def remind_sunday_service(ctx: ContextTypes.DEFAULT_TYPE, update: Optional[Update] = None):
    now = datetime.now(SGT)
    target_date = sunday_for_reminder(now)
    date_txt = format_date_plain(target_date)

    ref = STATE.get("svc_poll")
    text_reply = f"⏰ Reminder: Please vote on the Sunday Service poll above for {date_txt}."
    text_plain = f"⏰ Reminder: Please vote on the Sunday Service poll for {date_txt}."
    if ref:
        await _remind_with_reply_fallback(ctx, ref.chat_id, ref.message_id, text_reply, text_plain)
    else:
        target_chat = _effective_target_chat(update)
        await _remind_with_reply_fallback(ctx, target_chat, None, "", text_plain)

async def remind_cell_group(ctx: ContextTypes.DEFAULT_TYPE, update: Optional[Update] = None):
    now = datetime.now(SGT)
    target_date = friday_for_reminder(now)
    date_txt = format_date_plain(target_date)

    ref = STATE.get("cg_poll")
    text_reply = f"⏰ Reminder: Please vote on the Cell Group poll above for {date_txt}."
    text_plain = f"⏰ Reminder: Please vote on the Cell Group poll for {date_txt}."
    if ref:
        await _remind_with_reply_fallback(ctx, ref.chat_id, ref.message_id, text_reply, text_plain)
    else:
        target_chat = _effective_target_chat(update)
        await _remind_with_reply_fallback(ctx, target_chat, None, "", text_plain)

# ---------- One-off helpers (auto-post poll if needed) ----------
async def one_off_cg_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    if STATE.get("cg_poll") is None:
        await send_cell_group_poll(ctx, update=None)
    await remind_cell_group(ctx, update=None)

async def one_off_svc_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    if STATE.get("svc_poll") is None:
        await send_sunday_service_poll(ctx, update=None)
    await remind_sunday_service(ctx, update=None)

def _parse_hhmm_to_delay_seconds(hhmm: Optional[str]) -> tuple[float, str]:
    now_local = datetime.now(SGT)
    if not hhmm:
        when = now_local + timedelta(minutes=2)
        return (120.0, when.strftime("%H:%M"))
    s = hhmm.strip()
    if ":" in s:
        hh, mm = s.split(":", 1)
    elif len(s) == 4 and s.isdigit():
        hh, mm = s[:2], s[2:]
    else:
        raise ValueError("Time must be HH:MM or HHHH, e.g., 17:45 or 1745")
    h, m = int(hh), int(mm)
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError("Invalid time (00:00 to 23:59)")
    target = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
    if target <= now_local:
        target = now_local + timedelta(minutes=2)
    return ((target - now_local).total_seconds(), target.strftime("%H:%M"))

# ---------- Commands ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Schedule (SGT):\n"
        "• Cell Group (Friday):\n"
        "  - Sun 6:00 PM → post poll\n"
        "  - Mon 6:00 PM → reminder\n"
        "  - Thu 6:00 PM → reminder\n"
        "  - Fri 3:00 PM → reminder\n"
        "• Sunday Service:\n"
        "  - Fri 11:30 PM → post poll\n"
        "  - Sat 12:00 PM → reminder\n\n"
        "Manual commands:\n"
        "/cgpoll → post CG poll (in this chat)\n"
        "/cgrm → reminder for last CG poll\n"
        "/sunpoll → post Service poll (in this chat)\n"
        "/sunrm → reminder for last Service poll\n"
        "/armtest HH:MM → one-off CG reminder today (auto-posts poll if needed)\n"
        "/armsun HH:MM → one-off Sunday Service reminder today (auto-posts poll if needed)\n"
        "/testpoll → test poll\n"
        "/id → show chat id"
    )

async def cgpoll_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await send_cell_group_poll(ctx, update)

async def cgrm_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await remind_cell_group(ctx, update)

async def sunpoll_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await send_sunday_service_poll(ctx, update)

async def sunrm_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await remind_sunday_service(ctx, update)

async def testpoll_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    target_chat = _effective_target_chat(update)
    await ctx.bot.send_poll(
        chat_id=target_chat,
        question="🚀 Test Poll – working?",
        options=["Yes 👍", "No 👎"],
        is_anonymous=False,
        allows_multiple_answers=False,
    )

async def id_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    await update.message.reply_text(f"Chat type: {chat.type}\nChat ID: {chat.id}")

async def armtest_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        time_arg = ctx.args[0] if ctx.args else None
        delay_sec, when_str = _parse_hhmm_to_delay_seconds(time_arg)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}\nUsage: /armtest 17:45")
        return

    await update.message.reply_text(
        f"🔔 One-off **Cell Group** reminder scheduled for today at {when_str} SGT.\n"
        f"(Will auto-post a CG poll if none exists.)"
    )
    ctx.job_queue.run_once(one_off_cg_reminder, when=delay_sec, name=f"ONE_OFF_CG_{when_str}")

async def armsun_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        time_arg = ctx.args[0] if ctx.args else None
        delay_sec, when_str = _parse_hhmm_to_delay_seconds(time_arg)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}\nUsage: /armsun 11:30")
        return

    await update.message.reply_text(
        f"🔔 One-off **Sunday Service** reminder scheduled for today at {when_str} SGT.\n"
        f"(Will auto-post a Sunday Service poll if none exists.)"
    )
    ctx.job_queue.run_once(one_off_svc_reminder, when=delay_sec, name=f"ONE_OFF_SVC_{when_str}")

# ---------- Scheduler ----------
def schedule_jobs(app: Application):
    jq = app.job_queue
    # CG: poll Sun, reminders Mon + Thu + Fri(3pm)
    jq.run_daily(send_cell_group_poll, time=time(18, 0, tzinfo=SGT), days=(6,))  # Sunday 6pm → POST POLL
    jq.run_daily(remind_cell_group,    time=time(18, 0, tzinfo=SGT), days=(0,))  # Monday 6pm → REMINDER
    jq.run_daily(remind_cell_group,    time=time(18, 0, tzinfo=SGT), days=(3,))  # Thursday 6pm → REMINDER
    jq.run_daily(remind_cell_group,    time=time(15, 0, tzinfo=SGT), days=(4,))  # Friday 3pm → REMINDER
    # Service: poll Fri, reminder Sat
    jq.run_daily(send_sunday_service_poll, time=time(23, 30, tzinfo=SGT), days=(4,))  # Friday 11:30pm → POST POLL
    jq.run_daily(remind_sunday_service,    time=time(12, 0,  tzinfo=SGT), days=(5,))  # Saturday 12pm → REMINDER

# ---------- Global error handler ----------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.exception("Unhandled exception while handling update: %s", update, exc_info=context.error)

# ---------- Main ----------
def main():
    app = Application.builder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cgpoll", cgpoll_cmd))
    app.add_handler(CommandHandler("cgrm", cgrm_cmd))
    app.add_handler(CommandHandler("sunpoll", sunpoll_cmd))
    app.add_handler(CommandHandler("sunrm", sunrm_cmd))
    app.add_handler(CommandHandler("testpoll", testpoll_cmd))
    app.add_handler(CommandHandler("id", id_cmd))
    app.add_handler(CommandHandler("armtest", armtest_cmd))
    app.add_handler(CommandHandler("armsun", armsun_cmd))

    # Errors
    app.add_error_handler(error_handler)

    # Jobs
    schedule_jobs(app)

    logging.info("Bot starting…")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

