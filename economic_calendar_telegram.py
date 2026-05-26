"""
Economic Calendar Telegram Bot — Don Milton
Fuente   : Financial Modeling Prep API (economic calendar, impact=High, USD)
Envío    : Telegram Bot API
Scheduler: GitHub Actions
Lógica   : Rolling window — desde hoy hasta el viernes de la semana
"""

import requests
from datetime import datetime, timedelta
import pytz
import os
import sys

# ─────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
FMP_API_KEY      = os.environ.get("FMP_API_KEY", "")
TIMEZONE         = "America/Santiago"
# ─────────────────────────────────────────────────────────────────


def get_remaining_weekdays():
    tz    = pytz.timezone(TIMEZONE)
    today = datetime.now(tz).date()
    wd    = today.weekday()  # 0=Lun … 6=Dom
    start = today + timedelta(days=1) if wd == 6 else today
    days, current = [], start
    while current.weekday() < 5:
        days.append(current)
        current += timedelta(days=1)
    return days


def fetch_fmp_events(days):
    """
    Llama a FMP economic calendar API para el rango de días.
    Filtra: currency=USD, impact=High.
    Retorna dict {date: [events]}
    """
    from_date = days[0].strftime("%Y-%m-%d")
    to_date   = days[-1].strftime("%Y-%m-%d")

    url = (
        f"https://financialmodelingprep.com/api/v3/economic_calendar"
        f"?from={from_date}&to={to_date}&apikey={FMP_API_KEY}"
    )

    print(f"[INFO] Consultando FMP: {from_date} → {to_date}")

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[ERROR] FMP request fallida: {e}")
        return {d: [] for d in days}

    data = resp.json()

    if isinstance(data, dict) and "Error Message" in data:
        print(f"[ERROR] FMP respondió: {data['Error Message']}")
        return {d: [] for d in days}

    print(f"[INFO] FMP devolvió {len(data)} eventos en total")

    result = {d: [] for d in days}

    for item in data:
        # Filtrar solo USD high impact
        currency = item.get("currency", "")
        impact   = item.get("impact", "").lower()

        if currency != "USD" or impact != "high":
            continue

        # Parsear fecha del evento
        event_date_str = item.get("date", "")
        try:
            event_dt   = datetime.strptime(event_date_str[:10], "%Y-%m-%d").date()
        except ValueError:
            continue

        if event_dt not in result:
            continue

        # Hora (viene como "2026-05-28 08:30:00" o similar)
        try:
            time_str = datetime.strptime(event_date_str, "%Y-%m-%d %H:%M:%S").strftime("%I:%M %p")
        except ValueError:
            time_str = "All Day"

        result[event_dt].append({
            "time"    : time_str,
            "event"   : item.get("event", "—"),
            "actual"  : str(item.get("actual",   "")) or "—",
            "forecast": str(item.get("estimate", "")) or "—",
            "previous": str(item.get("previous", "")) or "—",
        })

    # Ordenar eventos de cada día por hora
    for d in result:
        result[d].sort(key=lambda x: x["time"])
        print(f"[INFO] {d.strftime('%a %d/%m')}: {len(result[d])} eventos HIGH USD")

    return result


def escape_md(text):
    special = r"\_*[]()~`>#+-=|{}.!"
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text


def format_message(days, events_by_day):
    tz  = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    wd  = now.weekday()

    day_names = ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"]
    if wd == 6:
        title_line = "📅 *SEMANA COMPLETA — Lun → Vie*"
    elif wd == 0:
        title_line = "📅 *HOY \\+ RESTO DE SEMANA — Lun → Vie*"
    else:
        title_line = f"📅 *DESDE {day_names[wd].upper()} → VIE*"

    lines = [
        title_line,
        "🔴 Solo eventos HIGH IMPACT \\(USD\\)",
        f"🕐 {escape_md(now.strftime('%d/%m/%Y %H:%M'))} Santiago",
        "━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    day_names_full = {0:"Lunes",1:"Martes",2:"Miércoles",3:"Jueves",4:"Viernes"}

    for d in days:
        events    = events_by_day.get(d, [])
        day_label = day_names_full.get(d.weekday(), "")
        date_str  = d.strftime("%d/%m")
        lines.append(f"\n📌 *{day_label} {date_str}*")

        if not events:
            lines.append("   ✅ Sin eventos high impact")
        else:
            for ev in events:
                actual_str = (
                    f" \\| Act: `{escape_md(ev['actual'])}`"
                    if ev["actual"] not in ("—", "", "None")
                    else ""
                )
                lines.append(
                    f"   🕐 `{escape_md(ev['time'])}` — *{escape_md(ev['event'])}*\n"
                    f"   Prev: `{escape_md(ev['previous'])}` \\| Fcst: `{escape_md(ev['forecast'])}`{actual_str}"
                )

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("⚡ _Bot by Don Milton_")
    return "\n".join(lines)


def send_telegram(message):
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id"   : TELEGRAM_CHAT_ID,
        "text"      : message,
        "parse_mode": "MarkdownV2",
    }
    try:
        resp = requests.post(url, data=data, timeout=15)
        resp.raise_for_status()
        print("✅ Mensaje enviado a Telegram")
    except requests.RequestException as e:
        print(f"[ERROR] Telegram: {e}")
        try:
            print(f"[RESP ] {resp.text}")
        except Exception:
            pass
        sys.exit(1)


def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[ERROR] Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID.")
        sys.exit(1)
    if not FMP_API_KEY:
        print("[ERROR] Falta FMP_API_KEY.")
        sys.exit(1)

    days          = get_remaining_weekdays()
    events_by_day = fetch_fmp_events(days)
    message       = format_message(days, events_by_day)
    send_telegram(message)


if __name__ == "__main__":
    main()
