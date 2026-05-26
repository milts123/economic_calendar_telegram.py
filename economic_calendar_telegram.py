"""
Economic Calendar Telegram Bot — Don Milton
Fuente   : Forex Factory (scraping, vista semanal)
Envío    : Telegram Bot API
Scheduler: GitHub Actions
Lógica   : Rolling window — muestra desde hoy hasta el viernes
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pytz
import os
import sys

# ─────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
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


def scrape_week_events(days):
    """
    Scrapea Forex Factory con la vista semanal (1 request para toda la semana).
    Retorna dict {date: [events]}
    """
    # Usar el lunes de la semana como anchor
    anchor = days[0]
    # Retroceder al lunes si no lo es
    while anchor.weekday() != 0:
        anchor -= timedelta(days=1)

    url = f"https://www.forexfactory.com/calendar?week={anchor.strftime('%b%d.%Y').lower()}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
        "Cache-Control":   "no-cache",
    }

    print(f"[INFO] Scrapeando: {url}")
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        print(f"[INFO] Status HTTP: {resp.status_code}")
    except requests.RequestException as e:
        print(f"[ERROR] Request fallida: {e}")
        return {d: [] for d in days}

    if resp.status_code != 200:
        print(f"[WARN] Forex Factory respondió {resp.status_code}. Posible bloqueo Cloudflare.")
        print(f"[DEBUG] Body primeros 300 chars: {resp.text[:300]}")
        return {d: [] for d in days}

    # Detectar bloqueo Cloudflare silencioso
    if "cf-browser-verification" in resp.text or "Just a moment" in resp.text:
        print("[WARN] Cloudflare está bloqueando la solicitud.")
        return {d: [] for d in days}

    soup = BeautifulSoup(resp.text, "html.parser")
    rows = soup.select("tr.calendar__row")
    print(f"[INFO] Rows encontradas en el HTML: {len(rows)}")

    if len(rows) == 0:
        print("[WARN] No se encontraron rows. El HTML puede haber cambiado.")
        print(f"[DEBUG] Primeros 500 chars del body: {resp.text[:500]}")

    # Inicializar resultado
    result      = {d: [] for d in days}
    current_row_date = None
    current_time = ""

    for row in rows:
        classes = row.get("class", [])

        # Detectar row de cambio de día
        if "calendar__row--day-breaker" in classes:
            date_el = row.select_one("td span.calendar__date")
            if date_el:
                date_text = date_el.get_text(strip=True)
                # Parsear fecha (ej: "Tue May 27")
                try:
                    parsed = datetime.strptime(f"{date_text} {anchor.year}", "%a %b %d %Y").date()
                    current_row_date = parsed
                    current_time = ""
                except ValueError:
                    pass
            continue

        if current_row_date is None or current_row_date not in result:
            continue

        # Moneda
        currency_el = row.select_one("td.calendar__currency")
        if not currency_el or currency_el.get_text(strip=True) != "USD":
            continue

        # Impacto — buscar span con clase que contenga "high"
        impact_el = row.select_one("td.calendar__impact span")
        if not impact_el:
            continue
        impact_classes = " ".join(impact_el.get("class", [])).lower()
        if "high" not in impact_classes:
            continue

        # Hora
        time_el = row.select_one("td.calendar__time")
        if time_el:
            t = time_el.get_text(strip=True)
            if t:
                current_time = t

        # Nombre
        event_el   = row.select_one("td.calendar__event span.calendar__event-title")
        event_name = event_el.get_text(strip=True) if event_el else "—"

        def get_val(cls):
            el = row.select_one(f"td.{cls}")
            return el.get_text(strip=True) if el else "—"

        result[current_row_date].append({
            "time"    : current_time or "All Day",
            "event"   : event_name,
            "forecast": get_val("calendar__forecast") or "—",
            "previous": get_val("calendar__previous") or "—",
            "actual"  : get_val("calendar__actual")   or "—",
        })

    # Log resumen
    for d in days:
        print(f"[INFO] {d.strftime('%a %d/%m')}: {len(result[d])} eventos high-impact USD")

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
                actual_str = f" \\| Act: `{escape_md(ev['actual'])}`" if ev["actual"] not in ("—","","Actual") else ""
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
        print(f"[ERROR] Fallo al enviar a Telegram: {e}")
        try:
            print(f"[RESP ] {resp.text}")
        except Exception:
            pass
        sys.exit(1)


def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[ERROR] Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID.")
        sys.exit(1)

    days         = get_remaining_weekdays()
    events_by_day = scrape_week_events(days)
    message      = format_message(days, events_by_day)
    send_telegram(message)


if __name__ == "__main__":
    main()
