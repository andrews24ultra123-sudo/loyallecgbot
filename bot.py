import logging
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from telegram import ReplyParameters
from telegram.ext import Application, CommandHandler, ContextTypes

# ======== HARD-CODED TOKEN & CHAT ID ========
TOKEN = "8448114982:AAFjVekkgALSK9M3CKc8K7KjrUSTcsvPvIc"
CHAT_ID = int("54380770")  # your group id

# Pin the original polls? (True/False)
PIN_POLLS = False

SGT = ZoneInfo("Asia/Singapore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# --- In-memory state for latest poll message IDs (lost on restart) ---
STATE = {
    "cg_poll_msg_id": None,      # last Cell Group poll message_id
    "svc_poll_msg_id": None,     # last Sunday Service poll message_id
}

# ---------- Helpers ----------
def next_weekday_date(now_dt: datetime, weekday: int):
    """Return date of the next given weekday (Mon=0..Sun=6). If today==weekday, return next week's."""
    days_ahead = (weekday - now_dt.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (now_dt + timedelta(days=days_ahead)).date()

def upcoming_friday(now_dt: datetime): return next_weekday_date(now_dt, 4)
def upcoming_sunday(now_dt: datetime): return next_weekday_date(now_dt, 6)

# ---------- Poll senders ----------
async def send_sunday_service_poll(ctx: ContextTypes.DEFAULT_TYPE):
    """Post the Sunday Service poll; store its message_id."""
    now = datetime.now(SGT)
    target = upcoming_sunday(now)
    msg = await ctx.bot.send_poll(
        chat_id=CHAT_ID,
        question=f"Sunday Service – {target:%Y-%m-%d (%a)}",
        options=["9am", "11.15am", "Serving", "Lunch", "Invited a friend"],
        is_anonymous=False,
        allows_multiple_answers=True,
    )
    STATE["svc_poll_msg_id"] = msg.message_id
    if PIN_POLLS:
        try:
            await ctx.bot.pin_chat_message(CHAT_ID, msg.message_id, disable_notification=True)
        except Exception as e:
            logging.warning(f"Pin failed: {e}")

async def send_cell_group_poll(ctx: ContextTypes.DEFAULT_TYPE):
    """Post the Cell Group poll for upcoming Friday; store its message_id."""
    now = datetime.now(SGT)
    target = upcoming_friday(now)
    msg = await ctx.bot.send_poll(
        chat_id=CHAT_ID,
        question=f"Cell Group – {target:%Y-%m-%d (%a)}",
        options=["Dinner 7.15pm", "CG 8.15pm", "Cannot make it"],
        is_anonymous=False,
        allows_multiple_answers=False,
    )
    STATE["cg_poll_msg_id"] = msg.message_id
    if PIN_POLLS:
        try:
            await ctx.bot.pin_chat_message(CHAT_ID, msg.message_id, disable_notification=True)
        except Exception as e:
            logging.warning(f"Pin failed: {e}")

# ---------- Reminder senders (reply to the existing poll) ----------
async def remind_sunday_service(ctx: ContextTypes.DEFAULT_TYPE):
    poll_id = STATE.get("svc_poll_msg_id")
    if poll_id:
        await ctx.bot.send_message(
            chat_id=CHAT_ID,
            text="⏰ *Reminder*: Please vote on the Sunday Service poll above. Thank you! 🙏",
            parse_mode="Markdown",
            reply_parameters=ReplyParameters(message_id=poll_id),
        )
    else:
        # Fallback if bot restarted and lost state
        await ctx.bot.send_message(
            chat_id=CHAT_ID,
            text="⏰ *Reminder*: Please vote on the Sunday Service poll (pinned/latest).",
            parse_mode="Markdown",
        )

async def remind_cell_group(ctx: ContextTypes.DEFAULT_TYPE):
    poll_id = STATE.get("cg_poll_msg_id")
    if poll_id:
        await ctx.bot.send_message(
            chat_id=CHAT_ID,
            text="⏰ *Reminder*: Please vote on the Cell Group poll above. See you Friday!",
            parse_mode="Markdown",
            reply_parameters=ReplyParameters(message_id=poll_id),
        )
    else:
        await ctx.bot.send_message(
            chat_id=CHAT_ID,
            text="⏰ *Reminder*: Please vote on the Cell Group poll (pinned/latest).",
            parse_mode="Markdown",
        )

# ---------- Commands ----------
async def start(update, ctx):
    await update.message.reply_text(
        "👋 Weekly schedule (SGT):\n"
        "• Cell Group (targets upcoming Friday):\n"
        "  - Sun 6:00 PM → post the poll\n"
        "  - Mon 6:00 PM → reminder (replies to same poll)\n"
        "• Sunday Service (targets upcoming Sunday):\n"
        "  - Fri 11:30 PM → post the poll\n"
        "  - Sat 12:00 PM → reminder (replies to same poll)\n\n"
        "Manual commands:\n"
        "/cgpoll → post CG poll now (for upcoming Friday)\n"
        "/cgrm   → reminder to the *last* CG poll\n"
        "/sunpoll → post Sunday Service poll now (for upcoming Sunday)\n"
        "/sunrm   → reminder to the *last* Sunday Service poll\n"
        "/testpoll → quick test poll"
    )

async def cgpoll_cmd(update, ctx):  await send_cell_group_poll(ctx)
async def cgrm_cmd(update, ctx):     await remind_cell_group(ctx)
async def sunpoll_cmd(update, ctx):  await send_sunday_service_poll(ctx)
async def sunrm_cmd(update, ctx):    await remind_sunday_service(ctx)

async def testpoll_cmd(update, ctx):
    await ctx.bot.send_poll(
        chat_id=CHAT_ID,
        question="🚀 Test Poll – Is the bot working?",
        options=["Yes 👍", "No 👎"],
        is_anonymous=False,
        allows_multiple_answers=False,
    )

# ---------- Scheduling ----------
def schedule_jobs(app: Application):
    jq = app.job_queue
    # Cell Group (upcoming Friday):
    jq.run_daily(send_cell_group_poll, time=time(18, 0, tzinfo=SGT), days=(6,))  # Sunday 6pm → POST POLL
    jq.run_daily(remind_cell_group,    time=time(18, 0, tzinfo=SGT), days=(0,))  # Monday 6pm → REMINDER

    # Sunday Service (upcoming Sunday):
    jq.run_daily(send_sunday_service_poll, time=time(23,30, tzinfo=SGT), days=(4,))  # Friday 11:30pm → POST POLL
    jq.run_daily(remind_sunday_service,    time=time(12,  0, tzinfo=SGT), days=(5,))  # Saturday 12pm → REMINDER

# ---------- Main ----------
def main():
    app = Application.builder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("cgpoll",   cgpoll_cmd))
    app.add_handler(CommandHandler("cgrm",     cgrm_cmd))
    app.add_handler(CommandHandler("sunpoll",  sunpoll_cmd))
    app.add_handler(CommandHandler("sunrm",    sunrm_cmd))
    app.add_handler(CommandHandler("testpoll", testpoll_cmd))

    # Jobs
    schedule_jobs(app)

    logging.info("Starting bot with run_polling() …")
    app.run_polling(allowed_updates=None)

if __name__ == "__main__":
    main()
