"""
Economic Calendar Telegram Bot — Don Milton
Fuente   : Forex Factory XML feed (nfs.faireconomy.media) — sin API key, sin JS
Envío    : Telegram Bot API
Scheduler: GitHub Actions
Lógica   : Rolling window — desde hoy hasta el viernes
"""

import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import pytz
import os
import sys

# ─────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TIMEZONE         = "America/Santiago"

FF_XML_THIS_WEEK = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
FF_XML_NEXT_WEEK = "https://nfs.faireconomy.media/ff_calendar_nextweek.xml"
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


def fetch_xml(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/xml,text/xml,*/*",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        print(f"[INFO] {url} → HTTP {resp.status_code}")
        if resp.status_code != 200:
            return None
        if "<!DOCTYPE" in resp.text[:100] or "Request Denied" in resp.text:
            print(f"[WARN] Forex Factory bloqueó la solicitud: {resp.text[:200]}")
            return None
        return resp.text
    except requests.RequestException as e:
        print(f"[ERROR] Request fallida para {url}: {e}")
        return None


def parse_ff_xml(xml_text, target_days):
    """
    Parsea el XML de Forex Factory y retorna dict {date: [events]}
    Solo eventos USD con impact=High.
    """
    result = {d: [] for d in target_days}

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"[ERROR] XML inválido: {e}")
        print(f"[DEBUG] Primeros 300 chars: {xml_text[:300]}")
        return result

    # El XML tiene elementos <event> o <eventdata> según la versión
    events = root.findall("event") or root.findall("eventdata") or root.findall(".//event")
    print(f"[INFO] Eventos totales en XML: {len(events)}")

    for ev in events:
        # Campos del XML de Forex Factory
        country = (ev.findtext("country") or "").strip().upper()
        impact  = (ev.findtext("impact")  or "").strip().lower()
        title   = (ev.findtext("title")   or ev.findtext("name") or "—").strip()
        date_s  = (ev.findtext("date")    or "").strip()
        time_s  = (ev.findtext("time")    or "All Day").strip()
        forecast = (ev.findtext("forecast") or "—").strip() or "—"
        previous = (ev.findtext("previous") or "—").strip() or "—"
        actual   = (ev.findtext("actual")   or "—").strip() or "—"

        if country != "USD" or impact != "high":
            continue

        # Parsear fecha — FF usa formato "May 28, 2026"
        try:
            ev_date = datetime.strptime(date_s, "%b %d, %Y").date()
        except ValueError:
            # Intentar formato alternativo "05-28-2026"
            try:
                ev_date = datetime.strptime(date_s, "%m-%d-%Y").date()
            except ValueError:
                print(f"[WARN] No se pudo parsear fecha: '{date_s}'")
                continue

        if ev_date not in result:
            continue

        result[ev_date].append({
            "time"    : time_s,
            "event"   : title,
            "forecast": forecast,
            "previous": previous,
            "actual"  : actual,
        })

    for d in target_days:
        print(f"[INFO] {d.strftime('%a %d/%m')}: {len(result[d])} eventos HIGH USD")

    return result


def get_events(days):
    """
    Descarga el XML correcto según si es domingo o día de semana.
    Domingo → usa nextweek; resto → thisweek.
    """
    tz  = pytz.timezone(TIMEZONE)
    wd  = datetime.now(tz).weekday()  # 6 = Domingo

    if wd == 6:
        # Domingo: intentar nextweek primero, luego thisweek como fallback
        print("[INFO] Es domingo — intentando nextweek.xml")
        xml = fetch_xml(FF_XML_NEXT_WEEK)
        if not xml:
            print("[WARN] nextweek.xml no disponible, usando thisweek.xml")
            xml = fetch_xml(FF_XML_THIS_WEEK)
    else:
        xml = fetch_xml(FF_XML_THIS_WEEK)

    if not xml:
        print("[ERROR] No se pudo obtener el XML de Forex Factory.")
        return {d: [] for d in days}

    return parse_ff_xml(xml, days)


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

    days          = get_remaining_weekdays()
    events_by_day = get_events(days)
    message       = format_message(days, events_by_day)
    send_telegram(message)


if __name__ == "__main__":
    main()
