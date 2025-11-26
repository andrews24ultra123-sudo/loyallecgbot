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
    # Next Friday (for the CG title)
    days_ahead = (4 - d.weekday()) % 7  # 4 = Friday
    target = d + timedelta(days=days_ahead)
    question = f"Cell Group – {_format_date_long(target)}"
    options = [
        "🍽️ Dinner 7.15pm",
        "⛪ CG 8.15pm",
        "❌ Cannot make it",
    ]
    await send_poll(question, options, allows_multiple=False)


async def send_service_poll():
    now = datetime.now(TZ)
    d = now
    # Next Sunday (for the Service title)
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
    # One-time CG poll 60s after startup, just to prove it's alive
    await asyncio.sleep(60)
    now = datetime.now(TZ)
    print(f"[one_off_debug_poll] Firing debug CG poll at {now}")
    await send_cg_poll()


async def scheduler_loop():
    """
    Simple loop that checks SGT time every 15 seconds and fires events once per day.
    """
    fired_today = set()  # set of event_name strings
    last_date = datetime.now(TZ).date()

    while True:
        now = datetime.now(TZ)
        today = now.date()
        wd = now.weekday()  # 0=Mon,1=Tue,2=Wed,3=Thu,4=Fri,5=Sat,6=Sun
        h = now.hour
        m = now.minute

        # Reset per-day markers at midnight
        if today != last_date:
            fired_today.clear()
            last_date = today

        # Wednesday 16:52 → CG poll
        if wd == 2 and h == 16 and m == 52:
            event = "CG_WED_1652"
            if event not in fired_today:
                print(f"[scheduler_loop] Triggering {event} at {now}")
                await send_cg_poll()
                fired_today.add(event)

        # Wednesday 16:54 → Service poll
        if wd == 2 and h == 16 and m == 54:
            event = "SVC_WED_1654"
            if event not in fired_today:
                print(f"[scheduler_loop] Triggering {event} at {now}")
                await send_service_poll()
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

    # Send online message once
    await send_online_message()

    # Fire one debug CG poll after 60s (optional but helpful)
    asyncio.create_task(one_off_debug_poll())

    # Start the main scheduler loop
    await scheduler_loop()


if __name__ == "__main__":
    asyncio.run(main())
