import os, json, logging
from dataclasses import dataclass
from datetime import datetime, timedelta, time, timezone
from typing import Optional

import telegram
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes, Defaults
from telegram.request import HTTPXRequest

# ===== Config =====
TOKEN = "8448114982:AAFjVekkgALSK9M3CKc8K7KjrUSTcsvPvIc"
DEFAULT_CHAT_ID = -1001819726736
PIN_POLLS = True
STATE_PATH = "./state.json"

# ===== Timezone (SGT) =====
try:
    from zoneinfo import ZoneInfo
    SGT = ZoneInfo("Asia/Singapore")
except Exception:
    SGT = timezone(timedelta(hours=8), name="SGT")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.info(f"python-telegram-bot: {getattr(telegram, '__version__', 'unknown')}")

# ===== State =====
@dataclass
class PollRef:
    chat_id: int
    message_id: int

STATE: dict[str, Optional[PollRef]] = {"cg_poll": None, "svc_poll": None}


def _load_state() -> None:
    global STATE
    try:
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for k in ("cg_poll", "svc_poll"):
                v = raw.get(k)
                STATE[k] = PollRef(int(v["chat_id"]), int(v["message_id"])) if v else None
    except Exception as e:
        logging.warning(f"STATE load error: {e}")


def _save_state() -> None:
    try:
        out = {}
        for k, v in STATE.items():
            out[k] = {"chat_id": v.chat_id, "message_id": v.message_id} if isinstance(v, PollRef) else None
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f)
    except Exception as e:
        logging.warning(f"STATE save error: {e}")


# ===== Helpers =====
def _effective_chat_id(update: Optional[Update]) -> int:
    return update.effective_chat.id if (update and update.effective_chat) else DEFAULT_CHAT_ID


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1:'st',2:'nd',3:'rd'}.get(n%10,'th')}"


def _format_date_long(d: datetime) -> str:
    return f"{_ordinal(d.day)} {d.strftime('%B %Y')} ({d.strftime('%a')})"


def _friday_for_text(now: datetime) -> str:
    d = now.astimezone(SGT)
    tgt = d + timedelta(days=(4 - d.weekday()) % 7)
    return f"{_ordinal(tgt.day)} {tgt.strftime('%B %Y')}"


def _sunday_for_text(now: datetime) -> str:
    d = now.astimezone(SGT)
    tgt = d + timedelta(days=(6 - d.weekday()) % 7)
    return f"{_ordinal(tgt.day)} {tgt.strftime('%B %Y')}"


async def _safe_pin(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    if not PIN_POLLS:
        return
    try:
        me = await ctx.bot.get_me()
        member = await ctx.bot.get_chat_member(chat_id, me.id)
        can_pin = (member.status == "creator") or (
            member.status == "administrator" and (
                getattr(member, "can_pin_messages", False) or
                getattr(getattr(member, "privileges", None), "can_pin_messages", False)
            )
        )
        if not can_pin:
            await ctx.bot.send_message(chat_id, "⚠️ I need **Pin messages** permission to pin polls.")
            return
        await ctx.bot.pin_chat_message(chat_id, message_id, disable_notification=True)
    except Exception as e:
        logging.warning(f"Pin failed: {e}")


# ===== Poll senders =====
async def send_cell_group_poll(ctx: ContextTypes.DEFAULT_TYPE, update: Optional[Update] = None, *, force: bool = False):
    now = datetime.now(SGT)
    chat_id = _effective_chat_id(update)
    friday = now + timedelta(days=(4 - now.weekday()) % 7)
    title = f"Cell Group – {_format_date_long(friday)}"
    msg = await ctx.bot.send_poll(
        chat_id=chat_id,
        question=title,
        options=["🍽️ Dinner 7.15pm", "⛪ CG 8.15pm", "❌ Cannot make it"],
        is_anonymous=False
    )
    STATE["cg_poll"] = PollRef(chat_id, msg.message_id)
    _save_state()
    await _safe_pin(ctx, chat_id, msg.message_id)


async def send_sunday_service_poll(ctx: ContextTypes.DEFAULT_TYPE, update: Optional[Update] = None, *, force: bool = False):
    now = datetime.now(SGT)
    chat_id = _effective_chat_id(update)
    sunday = now + timedelta(days=(6 - now.weekday()) % 7)
    title = f"Sunday Service – {_format_date_long(sunday)}"
    msg = await ctx.bot.send_poll(
        chat_id=chat_id,
        question=title,
        options=["⏰ 9am","🕚 11.15am","🙋 Serving","🍽️ Lunch","🧑‍🤝‍🧑 Invited a friend"],
        is_anonymous=False,
        allows_multiple_answers=True
    )
    STATE["svc_poll"] = PollRef(chat_id, msg.message_id)
    _save_state()
    await _safe_pin(ctx, chat_id, msg.message_id)


# ===== Commands =====
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Schedule (SGT):\n"
        "• CG poll: Tue 7:07 PM & Sun 2:00 PM\n"
        "• Sunday Service poll: Tue 7:09 PM & Fri 11:00 PM\n\n"
        "Manual:\n"
        "/cgpoll /sunpoll /when /jobs /id"
    )


async def cgpoll_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await send_cell_group_poll(ctx, update, force=True)


async def sunpoll_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await send_sunday_service_poll(ctx, update, force=True)


def _next_time(now: datetime, weekday: int, hh: int, mm: int) -> datetime:
    d = now.astimezone(SGT)
    delta = (weekday - d.weekday()) % 7
    t = d.replace(hour=hh, minute=mm, second=0, microsecond=0) + timedelta(days=delta)
    if t <= d:
        t += timedelta(days=7)
    return t


async def when_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(SGT)
    cg_tue = _next_time(now, 1, 19, 7)   # Tue 19:07
    svc_tue = _next_time(now, 1, 19, 9)  # Tue 19:09
    svc_fri = _next_time(now, 4, 23, 0)  # Fri 23:00
    cg_sun = _next_time(now, 6, 14, 0)   # Sun 14:00

    await update.message.reply_text(
        "🗓️ Next scheduled polls (SGT):\n"
        f"• CG poll (Tue): {cg_tue:%a %d %b %Y %H:%M}\n"
        f"• CG poll (Sun): {cg_sun:%a %d %b %Y %H:%M}\n"
        f"• Svc poll (Tue): {svc_tue:%a %d %b %Y %H:%M}\n"
        f"• Svc poll (Fri): {svc_fri:%a %d %b %Y %H:%M}"
    )


async def jobs_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(SGT)
    jobs = ctx.job_queue.jobs()
    if not jobs:
        await update.message.reply_text("No scheduled jobs.")
        return

    lines = []
    for j in jobs:
        t = j.next_run_time.astimezone(SGT)
        lines.append(f"• {j.name} → {t:%a %d %b %Y %H:%M:%S} (in {int((t-now).total_seconds())}s)")
    await update.message.reply_text("🧰 Pending jobs:\n" + "\n".join(lines))


async def id_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Chat ID: {update.effective_chat.id}")


# ===== Scheduler =====
def schedule_jobs(app: Application):
    jq = app.job_queue

    # Weekly polls (SGT)
    # Tue 19:07 → CG poll
    jq.run_daily(
        send_cell_group_poll,
        time=time(19, 7, tzinfo=SGT),
        days=(1,),  # Tuesday
        name="CG_TUE_1907",
    )

    # Tue 19:09 → Sunday Service poll
    jq.run_daily(
        send_sunday_service_poll,
        time=time(19, 9, tzinfo=SGT),
        days=(1,),  # Tuesday
        name="SVC_TUE_1909",
    )

    # Fri 23:00 → Sunday Service poll
    jq.run_daily(
        send_sunday_service_poll,
        time=time(23, 0, tzinfo=SGT),
        days=(4,),  # Friday
        name="SVC_FRI_2300",
    )

    # Sun 14:00 → CG poll
    jq.run_daily(
        send_cell_group_poll,
        time=time(14, 0, tzinfo=SGT),
        days=(6,),  # Sunday
        name="CG_SUN_1400",
    )


def catchup_on_start(app: Application):
    """
    Strong catch-up:
    If it's Tuesday and we start AFTER 19:07 / 19:09 SGT,
    still fire today's polls once.
    """
    _load_state()
    now = datetime.now(SGT)
    jq = app.job_queue

    if now.weekday() == 1:  # Tuesday
        # If current time is after or equal to 19:07 → catch up CG poll
        if now.time() >= time(19, 7):
            jq.run_once(send_cell_group_poll, when=5, name="CATCHUP_CG_TUE_1907")

        # If current time is after or equal to 19:09 → catch up SVC poll
        if now.time() >= time(19, 9):
            jq.run_once(send_sunday_service_poll, when=10, name="CATCHUP_SVC_TUE_1909")


# ===== Init =====
async def post_init(app: Application):
    me = await app.bot.get_me()
    await app.bot.set_my_commands([
        BotCommand("start","Show schedule"),
        BotCommand("cgpoll","Force CG poll"),
        BotCommand("sunpoll","Force Sunday Service poll"),
        BotCommand("when","Show next scheduled times"),
        BotCommand("jobs","List scheduled jobs"),
        BotCommand("id","Show chat ID"),
    ])
    await app.bot.send_message(DEFAULT_CHAT_ID, f"✅ Online as @{me.username} ({me.id})")


# ===== Build & Run =====
def build_app() -> Application:
    request = HTTPXRequest(
        connect_timeout=20,
        read_timeout=30,
        write_timeout=30,
        pool_timeout=30,
    )
    defaults = Defaults(tzinfo=SGT)

    app = (
        Application.builder()
        .token(TOKEN)
        .request(request)
        .defaults(defaults)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cgpoll", cgpoll_cmd))
    app.add_handler(CommandHandler("sunpoll", sunpoll_cmd))
    app.add_handler(CommandHandler("when", when_cmd))
    app.add_handler(CommandHandler("jobs", jobs_cmd))
    app.add_handler(CommandHandler("id", id_cmd))

    schedule_jobs(app)
    catchup_on_start(app)
    return app


def main():
    backoff = 8
    while True:
        try:
            app = build_app()
            logging.info("Bot starting…")
            app.run_polling(drop_pending_updates=True)
            break
        except Exception:
            logging.exception("Startup failed; retrying…")
            import time as t
            t.sleep(backoff)


if __name__ == "__main__":
    main()
