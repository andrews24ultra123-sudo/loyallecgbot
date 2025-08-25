import logging
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from telegram.ext import Application, CommandHandler, ContextTypes

# ======== HARD-CODED TOKEN & CHAT ID ========
TOKEN = "8448114982:AAFjVekkgALSK9M3CKc8K7KjrUSTcsvPvIc"
CHAT_ID = int("54380770")  # your group id

SGT = ZoneInfo("Asia/Singapore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------- Helpers ----------
def next_weekday_date(now_dt: datetime, weekday: int):
    days_ahead = (weekday - now_dt.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (now_dt + timedelta(days=days_ahead)).date()

def upcoming_wednesday(now_dt: datetime): return next_weekday_date(now_dt, 2)
def upcoming_sunday(now_dt: datetime):    return next_weekday_date(now_dt, 6)

# ---------- Poll senders ----------
async def send_sunday_service(ctx: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(SGT)
    target = upcoming_sunday(now)
    await ctx.bot.send_poll(
        chat_id=CHAT_ID,
        question=f"Sunday Service – {target:%Y-%m-%d (%a)}",
        options=["9am", "11.15am", "Serving", "Lunch", "Invited a friend"],
        is_anonymous=False,
        allows_multiple_answers=True,
    )

async def send_cell_group(ctx: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(SGT)
    target = upcoming_wednesday(now)
    await ctx.bot.send_poll(
        chat_id=CHAT_ID,
        question=f"Cell Group – {target:%Y-%m-%d (%a)}",
        options=["Dinner 7.15pm", "CG 8.15pm", "Cannot make it"],
        is_anonymous=False,
        allows_multiple_answers=False,
    )

async def send_test_poll(ctx: ContextTypes.DEFAULT_TYPE):
    await ctx.bot.send_poll(
        chat_id=CHAT_ID,
        question="🚀 Test Poll – Is the bot working?",
        options=["Yes 👍", "No 👎"],
        is_anonymous=False,
        allows_multiple_answers=False,
    )

# ---------- Commands ----------
async def start(update, ctx):
    await update.message.reply_text(
        "👋 Hi! I post reminders on this schedule (SGT):\n"
        "• Cell Group: Sun 6:00 PM & Mon 6:00 PM (for Wed)\n"
        "• Sunday Service: Fri 11:30 PM & Sat 12:00 PM (for Sun)\n\n"
        "Manual commands:\n"
        "/cgpoll → Cell Group (upcoming Wed)\n"
        "/sunpoll → Sunday Service (upcoming Sun)\n"
        "/testpoll → Quick test poll"
    )

async def cgpoll_cmd(update, ctx):  await send_cell_group(ctx)
async def sunpoll_cmd(update, ctx): await send_sunday_service(ctx)
async def testpoll_cmd(update, ctx): await send_test_poll(ctx)

# ---------- Scheduler ----------
def schedule_jobs(app: Application):
    jq = app.job_queue
    jq.run_daily(send_cell_group,     time=time(18, 0, tzinfo=SGT), days=(6,))  # Sunday 6pm
    jq.run_daily(send_cell_group,     time=time(18, 0, tzinfo=SGT), days=(0,))  # Monday 6pm
    jq.run_daily(send_sunday_service, time=time(23,30, tzinfo=SGT), days=(4,))  # Friday 11:30pm
    jq.run_daily(send_sunday_service, time=time(12, 0, tzinfo=SGT),  days=(5,))  # Saturday 12pm

# ---------- Main ----------
def main():
    app = Application.builder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cgpoll", cgpoll_cmd))
    app.add_handler(CommandHandler("sunpoll", sunpoll_cmd))
    app.add_handler(CommandHandler("testpoll", testpoll_cmd))

    # Jobs
    schedule_jobs(app)

    logging.info("Starting bot with run_polling() …")
    app.run_polling(allowed_updates=None)  # correct pattern; no .updater.start_polling()

if __name__ == "__main__":
    main()
