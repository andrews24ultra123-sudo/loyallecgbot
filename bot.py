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
    if not PIN_POLLS: return
    try:
        me = await ctx.bot.get_me()
        member = await ctx.bot.get_chat_member(chat_id, me.id)
        can_pin = (getattr(member, "status", "") == "creator") or (
            getattr(member, "status", "") == "administrator" and
            (getattr(member, "can_pin_messages", False) or getattr(getattr(member, "privileges", None), "can_pin_messages", False))
        )
        if not can_pin:
            await ctx.bot.send_message(chat_id, "⚠️ I need **Pin messages** permission to pin polls.")
            return
        await ctx.bot.pin_chat_message(chat_id, message_id, disable_notification=True)
    except Exception as e:
        logging.warning(f"Pin failed: {e}")

# ===== Poll senders =====
async def send_cell_group_poll(ctx: ContextTypes.DEFAULT_TYPE, update: Optional[Update] = None, *, force: bool=False):
    now = datetime.now(SGT)
    if not force and now.weekday() != 6:  # Sunday
        logging.info(f"Skip CG poll (not Sunday): {now}")
        return
    chat_id = _effective_chat_id(update)
    friday = now + timedelta(days=(4 - now.weekday()) % 7)
    q = f"Cell Group – {_format_date_long(friday)}"
    msg = await ctx.bot.send_poll(chat_id=chat_id, question=q,
                                  options=["🍽️ Dinner 7.15pm","⛪ CG 8.15pm","❌ Cannot make it"],
                                  is_anonymous=False, allows_multiple_answers=False)
    STATE["cg_poll"] = PollRef(chat_id=chat_id, message_id=msg.message_id)
    _save_state()
    await _safe_pin(ctx, chat_id, msg.message_id)

async def send_sunday_service_poll(ctx: ContextTypes.DEFAULT_TYPE, update: Optional[Update] = None, *, force: bool=False):
    now = datetime.now(SGT)
    if not force and now.weekday() != 4:  # Friday
        logging.info(f"Skip Service poll (not Friday): {now}")
        return
    chat_id = _effective_chat_id(update)
    sunday = now + timedelta(days=(6 - now.weekday()) % 7)
    q = f"Sunday Service – {_format_date_long(sunday)}"
    msg = await ctx.bot.send_poll(chat_id=chat_id, question=q,
                                  options=["⏰ 9am","🕚 11.15am","🙋 Serving","🍽️ Lunch","🧑‍🤝‍🧑 Invited a friend"],
                                  is_anonymous=False, allows_multiple_answers=True)
    STATE["svc_poll"] = PollRef(chat_id=chat_id, message_id=msg.message_id)
    _save_state()
    await _safe_pin(ctx, chat_id, msg.message_id)

# ===== Reminders (guards for scheduler; manual always allowed) =====
async def remind_cell_group(ctx: ContextTypes.DEFAULT_TYPE, update: Optional[Update]=None):
    now = datetime.now(SGT)
    if update is None:  # scheduler call
        wk, hr = now.weekday(), now.hour
        if not ((wk==0 and hr==18) or (wk==3 and hr==18) or (wk==4 and hr==15)):  # Mon 18:00, Thu 18:00, Fri 15:00
            logging.info(f"Skip CG reminder off-window: {now}")
            return
    ref = STATE.get("cg_poll")
    text = f"⏰ Reminder: Please vote on the Cell Group poll for {_friday_for_text(now)}."
    if isinstance(ref, PollRef):
        await ctx.bot.send_message(ref.chat_id, text, reply_to_message_id=ref.message_id, allow_sending_without_reply=True)
    else:
        await ctx.bot.send_message(DEFAULT_CHAT_ID, text)

async def remind_sunday_service(ctx: ContextTypes.DEFAULT_TYPE, update: Optional[Update]=None):
    now = datetime.now(SGT)
    if update is None:  # scheduler call
        if not (now.weekday()==5 and now.hour==12):  # Sat 12:00
            logging.info(f"Skip Service reminder off-window: {now}")
            return
    ref = STATE.get("svc_poll")
    text = f"⏰ Reminder: Please vote on the Sunday Service poll for {_sunday_for_text(now)}."
    if isinstance(ref, PollRef):
        await ctx.bot.send_message(ref.chat_id, text, reply_to_message_id=ref.message_id, allow_sending_without_reply=True)
    else:
        await ctx.bot.send_message(DEFAULT_CHAT_ID, text)

# ===== Commands =====
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Schedule (SGT):\n"
        "• CG poll: Sun 6:00 PM\n"
        "• CG reminders: Mon 6:00 PM, Thu 6:00 PM, Fri 3:00 PM\n"
        "• Service poll: Fri 11:30 PM\n"
        "• Service reminder: Sat 12:00 PM\n\n"
        "Manual:\n/cgpoll /cgrm /sunpoll /sunrm /when /jobs /id"
    )

async def cgpoll_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):  # force
    await send_cell_group_poll(ctx, update, force=True)

async def sunpoll_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):  # force
    await send_sunday_service_poll(ctx, update, force=True)

async def cgrm_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await remind_cell_group(ctx, update)

async def sunrm_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await remind_sunday_service(ctx, update)

def _next_time(now: datetime, weekday: int, hh: int, mm: int) -> datetime:
    d = now.astimezone(SGT)
    delta = (weekday - d.weekday()) % 7
    t = d.replace(hour=hh, minute=mm, second=0, microsecond=0) + timedelta(days=delta)
    if t <= d: t += timedelta(days=7)
    return t

async def when_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(SGT)
    cg_poll = _next_time(now, 6, 18, 0)
    cg_mon  = _next_time(now, 0, 18, 0)
    cg_thu  = _next_time(now, 3, 18, 0)
    cg_fri  = _next_time(now, 4, 15, 0)
    svc_poll= _next_time(now, 4, 23, 30)
    svc_rm  = _next_time(now, 5, 12, 0)
    await update.message.reply_text(
        "🗓️ Next (SGT):\n"
        f"• CG poll: {cg_poll:%a %d %b %Y %H:%M}\n"
        f"• CG reminders: Mon {cg_mon:%H:%M}, Thu {cg_thu:%H:%M}, Fri {cg_fri:%H:%M}\n"
        f"• Service poll: {svc_poll:%a %d %b %Y %H:%M}\n"
        f"• Service reminder: {svc_rm:%a %d %b %Y %H:%M}"
    )

async def jobs_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    jobs = ctx.job_queue.jobs()
    if not jobs:
        await update.message.reply_text("No scheduled jobs.")
        return
    now = datetime.now(SGT)
    lines = []
    for j in jobs:
        t = (j.next_t or j.next_run_time).astimezone(SGT) if (getattr(j, "next_t", None) or getattr(j, "next_run_time", None)) else None
        if t:
            lines.append(f"• {j.name} → {t:%a %d %b %Y %H:%M:%S} (in {int((t-now).total_seconds())}s)")
    await update.message.reply_text("🧰 Pending jobs:\n" + "\n".join(lines))

async def id_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Chat type: {update.effective_chat.type}\nChat ID: {update.effective_chat.id}")

# ===== Scheduler =====
def schedule_jobs(app: Application):
    jq = app.job_queue
    # CG: Sun poll; Mon/Thu/Fri reminders
    jq.run_daily(send_cell_group_poll, time=time(18, 0, tzinfo=SGT), days=(6,))
    jq.run_daily(remind_cell_group,    time=time(18, 0, tzinfo=SGT), days=(0,))
    jq.run_daily(remind_cell_group,    time=time(18, 0, tzinfo=SGT), days=(3,))
    jq.run_daily(remind_cell_group,    time=time(15, 0, tzinfo=SGT), days=(4,))
    # Service: Fri poll; Sat reminder
    jq.run_daily(send_sunday_service_poll, time=time(23, 30, tzinfo=SGT), days=(4,))
    jq.run_daily(remind_sunday_service,    time=time(12,  0, tzinfo=SGT), days=(5,))

def catchup_on_start(app: Application):
    _load_state()
    now = datetime.now(SGT)
    jq = app.job_queue

    # missed polls (this week)
    sun_target = datetime(now.year, now.month, now.day, 18, 0, tzinfo=SGT) + timedelta(days=(6 - now.weekday()) % 7)
    if now > sun_target:
        jq.run_once(lambda ctx: send_cell_group_poll(ctx, None, force=True), when=2, name="CATCHUP_CG_POLL")
    fri_poll = datetime(now.year, now.month, now.day, 23, 30, tzinfo=SGT) + timedelta(days=(4 - now.weekday()) % 7)
    if now > fri_poll:
        jq.run_once(lambda ctx: send_sunday_service_poll(ctx, None, force=True), when=2, name="CATCHUP_SVC_POLL")

    # missed reminders (today)
    def _maybe(wd, hh, mm, job, name):
        if now.weekday() == wd and now.time() >= time(hh, mm):
            jq.run_once(job, when=3, name=name)

    _maybe(0, 18, 0, remind_cell_group,     "CATCHUP_CG_MON_1800")
    _maybe(3, 18, 0, remind_cell_group,     "CATCHUP_CG_THU_1800")
    _maybe(4, 15, 0, remind_cell_group,     "CATCHUP_CG_FRI_1500")
    _maybe(5, 12, 0, remind_sunday_service, "CATCHUP_SVC_SAT_1200")

# ===== Post-init (reliable startup ping & commands) =====
async def post_init(app: Application):
    try:
        me = await app.bot.get_me()
        await app.bot.set_my_commands([
            BotCommand("start","Show schedule & commands"),
            BotCommand("cgpoll","Post Cell Group poll (force)"),
            BotCommand("cgrm","Send CG reminder now"),
            BotCommand("sunpoll","Post Sunday Service poll (force)"),
            BotCommand("sunrm","Send Sunday Service reminder now"),
            BotCommand("when","Show next scheduled times (SGT)"),
            BotCommand("jobs","List queued jobs"),
            BotCommand("id","Show this chat id"),
        ])
        await app.bot.send_message(DEFAULT_CHAT_ID, f"✅ Online as @{me.username} ({me.id}). Target chat: {DEFAULT_CHAT_ID}")
    except Exception as e:
        logging.warning(f"post_init failed: {e}")

# ===== Build & Run =====
def build_app() -> Application:
    request = HTTPXRequest(connect_timeout=20, read_timeout=30, write_timeout=30, pool_timeout=30)
    defaults = Defaults(tzinfo=SGT)
    app = Application.builder().token(TOKEN).request(request).defaults(defaults).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cgpoll", cgpoll_cmd))
    app.add_handler(CommandHandler("sunpoll", sunpoll_cmd))
    app.add_handler(CommandHandler("cgrm", cgrm_cmd))
    app.add_handler(CommandHandler("sunrm", sunrm_cmd))
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
        except Exception as e:
            logging.exception("Startup failed; retrying…")
            import time as _t; _t.sleep(backoff)

if __name__ == "__main__":
    main()
