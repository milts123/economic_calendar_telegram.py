"""
Economic Calendar Telegram Bot — Don Milton
Fuente  : Forex Factory (scraping)
Envío   : Telegram Bot API
Scheduler: GitHub Actions (cron)
Lógica  : Rolling window — muestra desde hoy hasta el viernes de la semana
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pytz
import os
import sys

# ─────────────────────────────────────────────────────────────────
# CONFIGURACIÓN  (valores reales van en GitHub Secrets)
# ─────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TIMEZONE        = "America/Santiago"
# ─────────────────────────────────────────────────────────────────


def get_remaining_weekdays():
    """
    Retorna lista de fechas desde hoy (inclusive) hasta el viernes.
    Si es domingo → devuelve lunes a viernes de la semana siguiente.
    """
    tz    = pytz.timezone(TIMEZONE)
    today = datetime.now(tz).date()
    wd    = today.weekday()  # 0=Lun … 6=Dom

    start = today + timedelta(days=1) if wd == 6 else today

    days, current = [], start
    while current.weekday() < 5:          # 0-4 = Lun-Vie
        days.append(current)
        current += timedelta(days=1)
    return days


def scrape_forex_factory(target_date):
    """
    Scrapea Forex Factory y retorna eventos high-impact USD
    para la fecha indicada.
    """
    url = f"https://www.forexfactory.com/calendar?day={target_date.strftime('%b%d.%Y').lower()}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[ERROR] No se pudo acceder a Forex Factory: {e}")
        return []

    soup   = BeautifulSoup(resp.text, "html.parser")
    rows   = soup.select("tr.calendar__row")
    events = []
    current_time = ""

    for row in rows:
        # Saltar filas de separador de día
        if "calendar__row--day-breaker" in row.get("class", []):
            continue

        # Detectar moneda
        currency_el = row.select_one("td.calendar__currency")
        if not currency_el:
            continue
        currency = currency_el.get_text(strip=True)
        if currency != "USD":
            continue

        # Detectar impacto
        impact_el = row.select_one("td.calendar__impact span")
        if not impact_el:
            continue
        impact_class = " ".join(impact_el.get("class", []))
        if "high" not in impact_class.lower():
            continue

        # Hora (puede estar vacía si el evento comparte hora con el anterior)
        time_el = row.select_one("td.calendar__time")
        if time_el:
            t = time_el.get_text(strip=True)
            if t:
                current_time = t

        # Nombre del evento
        event_el = row.select_one("td.calendar__event span.calendar__event-title")
        event_name = event_el.get_text(strip=True) if event_el else "—"

        # Valores
        def get_val(cls):
            el = row.select_one(f"td.{cls}")
            return el.get_text(strip=True) if el else "—"

        forecast = get_val("calendar__forecast")
        previous = get_val("calendar__previous")
        actual   = get_val("calendar__actual")

        events.append({
            "time"    : current_time or "All Day",
            "event"   : event_name,
            "forecast": forecast or "—",
            "previous": previous or "—",
            "actual"  : actual   or "—",
        })

    return events


def format_message(days_data):
    """
    Formatea el mensaje completo para Telegram (Markdown v2 compatible).
    days_data = list of (date, events_list)
    """
    tz    = pytz.timezone(TIMEZONE)
    now   = datetime.now(tz)
    wd    = now.weekday()

    # Título dinámico
    if wd == 6:
        title_line = "📅 *SEMANA COMPLETA — Lun → Vie*"
    elif wd == 0:
        title_line = "📅 *HOY + RESTO DE SEMANA — Lun → Vie*"
    else:
        day_names = ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"]
        title_line = f"📅 *DESDE {day_names[wd].upper()} → VIE*"

    lines = [
        title_line,
        "🔴 Solo eventos HIGH IMPACT \\(USD\\)",
        f"🕐 Generado: {now.strftime('%d/%m/%Y %H:%M')} Santiago",
        "━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    day_names_full = {
        0: "Lunes", 1: "Martes", 2: "Miércoles",
        3: "Jueves", 4: "Viernes"
    }

    for date, events in days_data:
        day_label = day_names_full.get(date.weekday(), "")
        date_str  = date.strftime("%d/%m")
        lines.append(f"\n📌 *{day_label} {date_str}*")

        if not events:
            lines.append("   ✅ Sin eventos high impact")
        else:
            for ev in events:
                actual_str = f" | Act: `{ev['actual']}`" if ev["actual"] not in ("—", "", "Actual") else ""
                lines.append(
                    f"   🕐 `{ev['time']}` — *{escape_md(ev['event'])}*\n"
                    f"   Prev: `{ev['previous']}` | Fcst: `{ev['forecast']}`{actual_str}"
                )

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("⚡ _Bot by Don Milton_")
    return "\n".join(lines)


def escape_md(text):
    """Escapa caracteres especiales para Telegram MarkdownV2."""
    special = r"\_*[]()~`>#+-=|{}.!"
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text


def send_telegram(message):
    """Envía mensaje vía Telegram Bot API."""
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
        print(f"[RESP ] {resp.text if 'resp' in dir() else 'sin respuesta'}")
        sys.exit(1)


def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[ERROR] Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID en variables de entorno.")
        sys.exit(1)

    days      = get_remaining_weekdays()
    days_data = []

    for day in days:
        print(f"  Scrapeando {day.strftime('%A %d/%m')}...")
        events = scrape_forex_factory(day)
        days_data.append((day, events))

    message = format_message(days_data)
    send_telegram(message)


if __name__ == "__main__":
    main()
