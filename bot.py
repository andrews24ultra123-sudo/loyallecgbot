import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

# === CONFIG ===

TOKEN = "8448114982:AAFjVekkgALSK9M3CKc8K7KjrUSTcsvPvIc"
CHAT_ID = -1001819726736

BASE_URL = f"https://api.telegram.org/bot{TOKEN}"
TZ = ZoneInfo("Asia/Singapore")


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1:'st', 2:'nd', 3:'rd'}.get(n % 10, 'th')}"


def _format_date_long(d: datetime) -> str:
    return f"{_ordinal(d.day)} {d.strftime('%B %Y')} ({d.strftime('%a')})"


async def send_poll(question: str, options: list[str], allows_multiple: bool) -> None:
    """
    Send a poll directly via Telegram Bot API and pin it.
    """
    payload = {
        "chat_id": CHAT_ID,
        "question": question,
        "options": options,
        "is_anonymous": False,
        "allows_multiple_answers": allows_multiple,
    }

    async with httpx.AsyncClient() as client:
        try:
            print(f"[send_poll] Sending poll at {datetime.now(TZ)} → {question}")
            resp = await client.post(f"{BASE_URL}/sendPoll", json=payload, timeout=20)
            print("DEBUG sendPoll:", resp.status_code, resp.text)

            if resp.status_code != 200:
                return

            data = resp.json()
            if not data.get("ok"):
                print("DEBUG sendPoll not ok:", data)
                return

            msg = data.get("result", {})
            message_id = msg.get("message_id")
            if message_id:
                # Try to pin (best-effort)
                pin_payload = {
                    "chat_id": CHAT_ID,
                    "message_id": message_id,
                    "disable_notification": True,
                }
                pin_resp = await client.post(f"{BASE_URL}/pinChatMessage", json=pin_payload, timeout=20)
                print("DEBUG pinChatMessage:", pin_resp.status_code, pin_resp.text)

        except Exception as e:
            print("Error in send_poll:", e)


async def job_cg_poll():
    now = datetime.now(TZ)
    print(f"[job_cg_poll] Fired at {now}")
    d = now
    # Next Friday
    days_ahead = (4 - d.weekday()) % 7
    target = d + timedelta(days=days_ahead)
    question = f"Cell Group – {_format_date_long(target)}"

    options = [
        "🍽️ Dinner 7.15pm",
        "⛪ CG 8.15pm",
        "❌ Cannot make it",
    ]
    await send_poll(question, options, allows_multiple=False)


async def job_service_poll():
    now = datetime.now(TZ)
    print(f"[job_service_poll] Fired at {now}")
    d = now
    # Next Sunday
    days_ahead = (6 - d.weekday()) % 7
    target = d + timedelta(days=days_ahead)
    question = f"Sunday Service – {_format_date_long(target)}"

    options = [
        "⏰ 9am",
        "🕚 11.15am",
        "🙋 Serving",
        "🍽️ Lunch",
        "🧑‍🤝‍🧑 Invited a friend",
    ]
    await send_poll(question, options, allows_multiple=True)


async def debug_message():
    now = datetime.now(TZ)
    payload = {
        "chat_id": CHAT_ID,
        "text": f"✅ Scheduler online at {now:%a %d %b %Y %H:%M:%S} (SGT)",
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(f"{BASE_URL}/sendMessage", json=payload, timeout=10)
            print("DEBUG sendMessage:", resp.status_code, resp.text)
        except Exception as e:
            print("Error in debug_message:", e)


async def debug_one_off_poll():
    now = datetime.now(TZ)
    print(f"[debug_one_off_poll] Fired at {now}")
    await job_cg_poll()


async def main():
    print("=== Scheduler START ===")
    print("DEBUG UTC now:", datetime.utcnow())
    print("DEBUG SGT now:", datetime.now(TZ))

    scheduler = AsyncIOScheduler(timezone=TZ)

    # === One-time debug message 30s after startup ===
    scheduler.add_job(
        debug_message,
        DateTrigger(run_date=datetime.now(TZ) + timedelta(seconds=30)),
        name="DEBUG_STARTUP_MESSAGE",
    )

    # === Weekly schedule (SGT) ===

    # Wednesday 16:07 → CG poll
    scheduler.add_job(
        job_cg_poll,
        CronTrigger(day_of_week="wed", hour=16, minute=7),
        name="CG_WED_1607",
    )

    # Wednesday 16:09 → Service poll
    scheduler.add_job(
        job_service_poll,
        CronTrigger(day_of_week="wed", hour=16, minute=9),
        name="SVC_WED_1609",
    )

    # Friday 23:00 → Service poll
    scheduler.add_job(
        job_service_poll,
        CronTrigger(day_of_week="fri", hour=23, minute=0),
        name="SVC_FRI_2300",
    )

    # Sunday 14:00 → CG poll
    scheduler.add_job(
        job_cg_poll,
        CronTrigger(day_of_week="sun", hour=14, minute=0),
        name="CG_SUN_1400",
    )

    # One-off CG poll 60s after startup (diagnostic)
    scheduler.add_job(
        debug_one_off_poll,
        DateTrigger(run_date=datetime.now(TZ) + timedelta(seconds=60)),
        name="DEBUG_CG_ONCE_60S",
    )

    # Print jobs BEFORE start
    print("=== Jobs before start() ===")
    for job in scheduler.get_jobs():
        print(f"JOB {job.name}: next_run_time={job.next_run_time}")

    scheduler.start()

    # Print jobs AFTER start
    print("=== Jobs after start() ===")
    for job in scheduler.get_jobs():
        print(f"JOB {job.name}: next_run_time={job.next_run_time}")

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
