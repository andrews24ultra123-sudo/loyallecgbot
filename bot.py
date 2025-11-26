import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

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
    Send a poll directly via Telegram Bot API and pin it (best-effort).
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
            now = datetime.now(TZ)
            print(f"[send_poll] Sending poll at {now} → {question}")
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
                # Try to pin
                pin_payload = {
                    "chat_id": CHAT_ID,
                    "message_id": message_id,
                    "disable_notification": True,
                }
                pin_resp = await client.post(
                    f"{BASE_URL}/pinChatMessage", json=pin_payload, timeout=20
                )
                print("DEBUG pinChatMessage:", pin_resp.status_code, pin_resp.text)

        except Exception as e:
            print("Error in send_poll:", e)


async def send_cg_poll():
    now = datetime.now(TZ)
    d = now
    # Compute next Friday for the CG poll title
    days_ahead = (4 - d.weekday()) % 7  # 4 = Friday
    target = d + timedelta(days=days_ahead)
    question = f"Cell Group – {_format_date_long(target)}"
    options = ["🍽️ Dinner 7.15pm", "⛪ CG 8.15pm", "❌ Cannot make it"]
    await send_poll(question, options, allows_multiple=False)


async def send_service_poll():
    now = datetime.now(TZ)
    d = now
    # Compute next Sunday for the Service poll title
    days_ahead = (6 - d.weekday()) % 7  # 6 = Sunday
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


async def send_online_message():
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
            print("Error in send_online_message:", e)


async def one_off_debug_poll():
    # Fires once 60 seconds after startup
    await asyncio.sleep(60)
    now = datetime.now(TZ)
    print(f"[one_off_debug_poll] Firing debug CG poll at {now}")
    await send_cg_poll()


async def send_cg_reminder():
    """
    Weekly text reminder for CG poll.
    """
    now = datetime.now(TZ)
    text = "📝 Remember to vote for the CG Poll if you have not done so yet!"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
    }
    async with httpx.AsyncClient() as client:
        try:
            print(f"[send_cg_reminder] Sending reminder at {now}")
            resp = await client.post(f"{BASE_URL}/sendMessage", json=payload, timeout=10)
            print("DEBUG reminder sendMessage:", resp.status_code, resp.text)
        except Exception as e:
            print("Error in send_cg_reminder:", e)


async def scheduler_loop():
    """
    Simple loop that checks SGT time every 15 seconds 
    and fires events once per day.
    """
    fired_today = set()
    last_date = datetime.now(TZ).date()

    while True:
        now = datetime.now(TZ)
        today = now.date()
        wd = now.weekday()  # 0=Mon ... 2=Wed ... 4=Fri ... 6=Sun
        h = now.hour
        m = now.minute

        # Reset day-state at midnight
        if today != last_date:
            fired_today.clear()
            last_date = today

        # === FINAL SCHEDULE ===

        # Wednesday 17:30 → CG reminder text
        if wd == 2 and h == 17 and m == 30:
            event = "REM_WED_1730"
            if event not in fired_today:
                print(f"[scheduler_loop] Triggering {event} at {now}")
                await send_cg_reminder()
                fired_today.add(event)

        # Friday 23:00 → Service poll
        if wd == 4 and h == 23 and m == 0:
            event = "SVC_FRI_2300"
            if event not in fired_today:
                print(f"[scheduler_loop] Triggering {event} at {now}")
                await send_service_poll()
                fired_today.add(event)

        # Sunday 14:00 → CG poll
        if wd == 6 and h == 14 and m == 0:
            event = "CG_SUN_1400"
            if event not in fired_today:
                print(f"[scheduler_loop] Triggering {event} at {now}")
                await send_cg_poll()
                fired_today.add(event)

        await asyncio.sleep(15)


async def main():
    print("=== Simple Scheduler START ===")
    print("DEBUG SGT now:", datetime.now(TZ))

    # Online message
    await send_online_message()

    # Debug CG poll 60s after startup
    asyncio.create_task(one_off_debug_poll())

    # Start schedule loop
    await scheduler_loop()


if __name__ == "__main__":
    asyncio.run(main())
