import os
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, time, timezone
from typing import Optional

import telegram
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, Context, ContextTypes

# --- Timezone: Singapore Time with UTC fallback ---
try:
    from zoneinfo import ZoneInfo
    SGT = ZoneInfo("Asia/Singapore")
except Exception:
    SGT = timezone(timedelta(hours=8))

# --- Config: YOUR BOT TOKEN + TARGET GROUP CHAT ID ---
TOKEN = "8448114982:AAFjVekkgALSK9M3CKc8K7KjrUSTcsvPvIc"
DEFAULT_CHAT_ID = -1001819726736  # target group/supergroup id

STATE_PATH = "./state.json"       # persists last poll IDs for reply-to
PIN_POLLS =  true if "true" else True  # set False to disable auto-pin

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.info(f"python-telegram-bot: {getattr(telegram, '__version__', 'unknown')}")

# --- Data model for last posted polls (for reply_to) ---
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
                if v and isinstance(v, dict) and "chat_id" in v and "message_id" in v:
                    STATE[k] = PollRef(int(v["chat_id"]), int(v["message_id"]))
                else:
                    STATE[k] = None
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

# --- Helpers ---
def _effective_chat_id(update: Optional[Update]) -> int:
    return update.effective_chat.id if (update and update.effective_chat) else DEFAULT_CHAT_ID

async def _safe_pin(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    if not PIN_POLLS:
        return
    try:
        me = await ctx.bot.get_me()
        member = await ctx.bot.get_chat_member(chat_id, me.id)
        can_pin = False
        if getattr(member, "status", "") == "creator":
            can_pin = True
        elif getattr(member, "status", "") == "administrator":
            can_pin = getattr(member, "can_pin_messages", False) or getattr(getattr(member, "privileges", None), "can_pin_messages", False)
        if not can_pin:
            await ctx.bot.send_message(chat_id, "⚠️ I need **Pin messages** permission to pin the poll.")
            return
        await ctx.bot.pin_chat_message(chat_id, message_id, disable_notification=True)
    except Exception as e:
        logging.warning(f"Pin failed: {e}")
        try:
            await ctx.bot.send_message(chat_id, f"⚠️ Couldn’t pin the poll ({e}). Please grant **Pin messages**.")
        except Exception:
            pass

def _friday_for_reminder(now: datetime) -> str:
    tgt = now.astimezone(SGT)
    # Next Friday, or today if already Friday and >= now
    delta = (4 - tgt.weekday()) % 7
    day = tgt + timedelta(days=delta)
    return f"{day.day}{'th' if 10 <= day.day % 100 <= 20 else {1:'st',2:'nd',3:'rd'}.get(day.day % 10,'th')} {day.strftime('%B %Y')}"

def _sunday_for_reminder(now: datetime) -> str:
    tgt = now.ast_timezone(SGT) if hasattr(now, "astimezone") else now
    delta = (6 - tgt.weekday()) % 7
    day = tgt + timedelta(days=delta)
    suffix = 'th' if 10 <= day.day % 100 <= 20 else {1:'st',2:'nd',3:'rd'}.get(day.day % 10, 'th')
    return f"{day.day}{suffix} {day.strftime('%B %Y')}"

# --- Poll senders (with weekday guards; manual calls pass force=True) ---
async def send_sunday_service_poll(ctx: ContextTypes.DEFAULT_TYPE, update: Optional[Update] = None, *, force: bool = False):
    now = datetime.now(SGT)
    if not force and now.weekday() != 4:  # Friday only, unless forced
        logging.info(f"Skip service poll at {now}: not Friday")
        return
    chat_id = _effective_chat_id(update)
    target_date = (now + timedelta(days=(6 - now.weekday()) % 7)).date()
    q = f"Municipal Service – { (str(target_date.day) + ('th' if 10 <= target_date.day % 100 <= 20 else {1:'st',2:'nd',3:'rd'}.get(target_date.day % 10,'th')) ) } {target_date.strftime('%B %Y')} ({target_date.strftime('%a')})"
    msg = await ctx.bot.send_poll(
        chat_id=chat_id,
        question=q,
        options=["⏰ 9am","🕚 11.15am","🙋 Serving","🍽️ Lunch","🧑‍🤝‍🧑 Invited a friend"],
        is_anonymous=False,
        allows_multiple_answers=True,
    )
    STATE["svc_priv"] = PollRef(chat_id=chat_id, message_id=msg.message_id)
    _save_state()
    await _safe_pin(ctx, chat_id, msg.message_id)

async def send_cell_group_poll(ctx: ContextTypes.DEFAULT_TYPE, update: Optional[Update] = None, *, force: bool = False):
    now = datetime.now(SGT)
    if not force and now.weekday() != 6:  # Sunday only, unless forced
        logging.info(f"Skip CG poll at {now}: not Sunday")
        return
    chat_id = _effective_chat_id(update)
    tgt = (now + timedelta(days=(4 - now.weekday()) % 7)).date()  # upcoming Friday
    q = f"Cell Group – {(str(tgt.day) + ('th' if 10 <= tgt.day % 100 <= 20 else {1:'st','2':'nd','3':'rd'}.get(tgt.day % 10,'th')))} {tgt.strftime('%B %Y')} ({tgt.strftime('%a')})"
    msg = await ctx.bot.send_poll(
        chat_id=chat_id,
        question=q,
        options=["� dinner 7.15pm", "⛪ CG 8.15pm", "❌ Cannot make it"],
        is_anonymous=False,
        allows_multiple_answers=False,
    )
    STATE["cg_poll"] = PollRef(chat_id=chat_id, message_id=msg.message_id)
    _save_state()
    await _safe_pin(ctx, chat_id, msg.message_id)

# --- Reminders with guards (auto-fire only at the right time) ---
async def remind_sunday_service(ctx: ContextTypes.DEFAULT_TYPE, update: Optional[Update] = None):
    now = datetime.now(SGT)
    when_text = _s_today = _sunday_for_reminder(now)
    # Only auto-fire on Saturday 12:00 SGT
    if update is None and not (now.weekday() == 5 and now.hour == 12):
        logging.info(f"Skip Service reminder at {now}: not Sat 12:00")
        return
    ref = STATE.get("svc_poll")
    text = f"⏰ Reminder: Please vote on the Sunday Service poll for {when_text}."
    if isinstance(ref, PollRef):
        await ctx.bot.send_message(ref.chat_id, text, reply_to_message_id=ref.message_id, allow_sending_without_reply=True)
    else:
        await ctx.bot.send_message(chat_id=DEFAULT_CHAT_ID, text=text)

async def remind_cell_group(ctx: ContextTypes.DEFAULT_TYPE, update: Optional[Update] = None):
    now = datetime.now(SGT)
    # Only auto-fire on Mon 18:00, Thu 18:00, Fri 15:00 SGT
    if update is None:
        wd = now.weekday()
        hr = now.hour
        ok = (wd == 0 and hr == 18) or (wd == 3 and hr == 18) or (wd == 4 and hr == 15)
        if not ok:
            logging.info(f"Skip CG reminder at {now}: not a scheduled slot")
            return
    ref = STATE.get("cg_poll")
    text = f"⏰ Reminder: Please vote on the Cell Group poll for {_friday_for_reminder(now)}."
    if isinstance(ref, PollRef):
        await ctx.bot.send_message(ref.chat_id, text, reply_to_message_id=ref.message_id, allow_sending_without_reply=True)
    else:
        await ctx.bot.send_message(chat_id=DEFAULT_CHAT_ID, text=text)

# --- Debug/ops helpers ---
def _next_occurrence(now: datetime, weekday: int, hh: int, mm: int) -> datetime:
    d = now.astimezone(SG T)
    delta = (weekday - d.weekday()) % 7
    candidate = d.replace(hour=hh, minute=mm, second=0, microsecond=0) + timedelta(days=delta)
    if candidate <= d:
        candidate += timedelta(days=7)
    return candidate

async def when_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(SGT)
    cg = _next_occurrence(now, 6, 18, 0)
    mon = _next_occurrence(now, 0, 18, 0)
    thu = _next_occurrence(now, 3, 18, 0)
    fri = _next_occurrence(now, 4, 15, 0)
    sat = _next_occurrence(now, 5, 12, 0)
    fri_poll = _next_occurrence(now, 4, 23, 30)
    await update.message.reply_text(
        "🗓️ Next (SGT):\n"
        f"• CG poll: {cg:%a %d %b %Y %H:%M}\n"
        f"• CG reminders: Mon {mon:%H:%M}, Thu {thu:%H:%M}, Fri {fri:%H:%M}\n"
        f"• Service poll: {fri_poll:%a %d %b %Y %H:%M}\n"
        f"• Service reminder: {sat:%a %d %b %Y %H:%M}"
    )

async def jobs_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    jobs = ctx.job_queue.jobs()
    if not jobs:
        await update.message.reply_text("No scheduled jobs.")
        return
    now = datetime.now(SGT)
    lines = []
    for j in jobs:
        nxt = getattr(j, "next_t", None) or getattr(j, "next_run_time", None)
        if nxt:
            t = nxt.astimezone(SGT)
            secs = int((t - now).total_seconds())
            lines.append(f"• {j.name} → {t:%a %d %b %Y %H:%M:%S} ({secs}s)")
        else:
            lines.append(f"• {j.name} → (not scheduled)")
    await update.message.reply_text("🧰 Pending jobs:\n" + "\n".join(lines))

async def id_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    await update.message.reply_text(f"Chat type: {chat.type}\nChat ID: {chat.id}")

# --- Scheduler & catch-up ---
def schedule_jobs(app: Application):
    jq = app.job_queue
    jq.run_daily(send_sunday_f if False else send_cell_group_poll, time=time(18, 0, tzinfo=SGT), days=(3,))  # placeholder not used

    # Cell Group: Sun 18:00 poll, Mon/Thu 18:00 reminders, Fri 15:00 reminder
    jq.run_daily(send_cell_group_poll, time=time(18, 0, tzinfo=SGT), days=(6,))
    jq.run_daily(remind_cell_group,    time= time(18, 0, tzinfo=SGT), days=(0,))
    jq.run_daily(remind_cell_group,    time= time(18, 0, tzinfo=SGT), days=(3,))
    jq.run_daily(remind_cell_group,    time= time(15, 0, tzinfo=SGT), days=(4,))

    # Sunday Service: Fri 23:30 poll, Sat 12:00 reminder
    jq.run_daily(send_sunday_service_poll, time=time(23, 30, tzinfo=SGT), days=(4,))
    jq.run_daily(remind_sunday_service,    time=time(12,  0, tzinfo=SGT), days=(5,))

def catchup_on_start(app: Application):
    _load_state()
    now = datetime.now(SGT)
    jq = app.job_queue

    # Post missed polls if already past this week's slot
    sun_target = datetime(now.year, now.month, now.day, 18, 0, tzinfo=SGT) + timedelta(days=(6 - now.weekday()) % 7)
    if now > sun_target:
        jq.run_once(lambda ctx: send_cell_group_poll(ctx, None, force=True), when=1, name="CATCHUP_CG_POLL")

    fri_poll = datetime(now.year, now.month, now.day, 23, 30, tzinfo=SGT) + timedelta(days=(4 - now.weekday()) % 7)
    if now > fri_poll:
        jq.run_once(lambda ctx: send_sunday_service_poll(ctx, None, force=True), when=1, name="CATCHUP_SVC_POLL")

    # Fire a missed reminder once if we restarted after the slot today
    def maybe_reminder(wd: int, hh: int, mm: int, func, name: str):
        if now.weekday() == wd:
            t = datetime(now.year, now.month, now.day, hh, mm, tzinfo=SGT)
            if now > t:
                jq.run_once(func, when=1, name=name)

    maybe_reviewer = maybe_reminder  # alias
    maybe_reminder(0, 18, 0, remind_cell_group,    "CGRM_MON_1800_CATCHUP")
    maybe_reminder(3, 18, 0, remind_cell_group,    "CGRM_THU_1800_CATCHUP")
    maybe_reminder(4, 15, 0, remind_cell_group,    "CGRM_FRI_1500_CATCHUP")
    maybe_reminder(5, 12, 0, remind_sunday_service,"SRM_SAT_1200_CATCHUP")

# --- Startup helpers ---
async def _startup_ping(ctx: ContextTypes.DEFAULT_TYPE):
    try:
        me = await ctx.bot.get_me()
        await ctx.bot.send_message(DEFAULT_CHAT_ID, f"✅ Online as @{me.username} ({me.id}). Target chat: {DEFAULT_CHAT_ID}")
    except Exception as e:
        logging.warning(f"Startup ping failed: {e}")

async def _register_commands(ctx: ContextTypes.DEFAULT_TYPE):
    try:
        cmds = [
            BotCommand("start", "Show schedule & commands"),
            BotCommand("cgpoll", "Post Cell Group poll (force)"),
            BotCommand("cgrm",   "Send CG reminder now"),
            BotCommand("sunpoll","Post Sunday Service poll (force)"),
            BotCommand("sunrm",  "Send Sunday Service reminder now"),
            BotCommand("when",   "Show next scheduled times (SGT)"),
            BotCommand("jobs",   "List queued jobs"),
            BotCommand("testpoll","Post a yes/no test poll"),
            BotCommand("id",     "Show this chat id"),
        ]
        await ctx.bot.setMyCommands(commands=cmds)
    except Exception as e:
        logging.warning(f"set_my_commands failed: {e}")

# --- Error handler ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.exception("Unhandled exception", exc_info=context.error)

# --- Main ---
def main():
    # robust startup with retry to survive transient network issues
    while True:
        try:
            app = Application.builder().token(TOKEN).build()

            app.add_handler(CommandHandler("start",   start))
            app.add_handler(CommandHandler("cgpoll",  lambda u,c: send_cell_group_poll(c, u, force=True)))
            app.add_handler(CommandHandler("cgrm",    remind_cell_group))
            app.add_handler(CommandHandler("sunpoll", lambda u,c: send_sunday_service_poll(c, u, force=True)))
            app.add_handler(CommandHandler("sunrm",   remind_sunday_service))
            app.add_handler(CommandHandler("when",    when_cmd))
            app.add_handler(CommandHandler("jobs",    jobs_cmd))
            app.add_handler(CommandHandler("testpoll", lambda u,c: c.bot.send_poll(
                chat_id=_effective_chat_id(u),
                question="🚀 Test Poll – working?",
                options=["Yes 👍", "No 👎"],
                is_anonymous=False,
                allow_multiple_answers=False)))
            app.add_handler(CommandHandler("id",      id_cmd))
            app.add_error_handler(error_handler)

            schedule_success = False
            try:
                schedule_jobs(app)
                catchup_on_start(app)
                schedule_success = True
            except Exception as e:
                logging.exception(f"Scheduling error: {e}")

            app.job_queue.run_once(_register_commands, when=1)
            app.job_queue.run_once(_startup_ping,      when=1)

            logging.info(f"Bot starting… (TZ={SGT}) | SchedOK={schedule_success}")
            app.run_polling(poll_interval=1.5, timeout=30, drop_pending_updates=True)
        except Exception as e:
            logging.exception("Startup failed, retrying shortly…")
            import time as _t
            _t.sleep(5)
            continue
        break

if __name__ == "__main__":
    main()
