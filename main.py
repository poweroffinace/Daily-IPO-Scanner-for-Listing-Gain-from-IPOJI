#!/usr/bin/env python3
"""
IPO Dashboard Scraper & Telegram Bot
Fully self-contained script designed for GitHub Actions.
"""

import os
import re
import html
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone

# ============ CONFIGURATION ============
# Best practice for GitHub Actions: read from secrets via os.getenv()
# It will fall back to your provided strings if environment variables are not set.
BOT_TOKEN = os.getenv("BOT_TOKEN", "8714686561:AAGCBPEIwHFMdI6bFa1_LXNbIxM1ipsteKY")
CHAT_ID = os.getenv("CHAT_ID", "1161965312")
DRY_RUN = os.getenv("DRY_RUN", "False").lower() == "true"

IST = timezone(timedelta(hours=5, minutes=30))
TG_LIMIT = 4000  # Telegram max is 4096
SEP = "\n" + "─" * 16 + "\n"
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ============ SCRAPER CONSTANTS ============
IPO_LIST_PAGE_URL = 'https://www.ipoji.com/ipo'
BASE_URL = 'https://www.ipoji.com'
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ============ SCRAPER LOGIC ============
def scrape_ipo_list_page():
    try:
        response = requests.get(IPO_LIST_PAGE_URL, headers=HEADERS, timeout=10)
        response.raise_for_status()
        html_content = response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching IPO list: {e}")
        return [{"error": str(e)}]

    soup = BeautifulSoup(html_content, "html.parser")
    ipo_cards = soup.find_all('article', class_='ipo-card')
    
    live_ipos = []
    
    for card in ipo_cards:
        status_badge = card.find('span', class_='ipo-card-status-badge')
        
        if status_badge and 'Live' in status_badge.get_text(strip=True):
            name_elem = card.find('h3', class_='ipo-card-name')
            ipo_name = name_elem.get_text(strip=True) if name_elem else 'Unknown'
            board_type = card.get('data-ipo-board', 'Unknown').capitalize()
            
            url_path = card.get('data-agent-href')
            if not url_path:
                link_elem = card.find('a', class_='viewBtn')
                url_path = link_elem.get('href') if link_elem else ''
            
            full_url = f"{BASE_URL}{url_path}" if url_path else "Unknown"
            
            live_ipos.append({
                "ipo_name_base": ipo_name,
                "board": board_type,
                "url": full_url,
                "status": "Live"
            })

    return live_ipos

def scrape_ipo_page(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}

    soup = BeautifulSoup(response.text, "html.parser")
    ipo_data = {}

    title_tag = soup.find("h1", id="ipo-page-heading") or soup.find("h1")
    ipo_data["ipo_name_detailed"] = title_tag.get_text(strip=True) if title_tag else "N/A"

    subtitle_tag = soup.find("p", class_="section-subtitle")
    ipo_data["summary"] = subtitle_tag.get_text(strip=True) if subtitle_tag else "N/A"

    ipo_dates = "N/A"
    for fact_item in soup.select(".fact-item"):
        label = fact_item.find("dt", class_="fact-label")
        value = fact_item.find("dd", class_="fact-value")
        if label and "IPO Dates" in label.get_text():
            ipo_dates = value.get_text(strip=True) if value else "N/A"
            break
    ipo_data["ipo_dates"] = ipo_dates

    key_details = {}
    for row in soup.select(".detail-list__row"):
        dt = row.find("dt")
        dd = row.find("dd")
        if dt and dd:
            key = (
                dt.get_text(" ", strip=True)
                .lower()
                .replace(" ", "_")
                .replace("(", "")
                .replace(")", "")
            )
            val = dd.get_text(" ", strip=True)
            val = re.sub(r"Read more.*", "", val).strip()
            key_details[key] = val
    ipo_data["key_details"] = key_details

    gmp_history = []
    gmp_table = soup.select_one(".ipo-gmp-trend__details table, .ipo-gmp-card table")
    if gmp_table:
        headers_list = [th.get_text(strip=True) for th in gmp_table.select("thead th")]
        for tr in gmp_table.select("tbody tr"):
            cols = [td.get_text(strip=True) for td in tr.find_all(["th", "td"])]
            if cols:
                gmp_history.append(dict(zip(headers_list, cols)))
    ipo_data["gmp_history_table"] = gmp_history

    subscription_data = []
    sub_table = soup.select_one("table.premium-table, #Subscription_Details table")
    if sub_table:
        sub_headers = [
            re.sub(r"\s+", " ", th.get_text(" ", strip=True)).strip()
            for th in sub_table.select("thead th")
        ]

        for tr in sub_table.select("tbody tr"):
            cells = [
                re.sub(r"\s+", " ", td.get_text(" ", strip=True))
                .replace(" x", "x")
                .strip()
                for td in tr.find_all(["th", "td"])
            ]
            if cells:
                subscription_data.append(cells)
        ipo_data["subscription_table"] = {
            "headers": sub_headers,
            "rows": subscription_data,
        }

    return ipo_data

def fetch_live_ipos():
    print("Fetching live IPOs...")
    live_ipos = scrape_ipo_list_page()
    
    if not live_ipos or "error" in live_ipos[0]:
        print("Failed to fetch IPO list.")
        return []

    filtered_live_ipos = []
    
    for ipo in live_ipos:
        if ipo["url"] != "Unknown":
            print(f"Scraping details for: {ipo['ipo_name_base']}...")
            details = scrape_ipo_page(ipo["url"])
            combined_data = {**ipo, **details}
            
            key_details = combined_data.get("key_details", {})
            
            gmp_history_full = combined_data.get("gmp_history_table", [])
            gmp_history_filtered = [
                {
                    "Date & time": entry.get("Date & time", "N/A"),
                    "GMP %": entry.get("GMP %", "N/A")
                }
                for entry in gmp_history_full
            ]
            
            sub_table = combined_data.get("subscription_table", {})
            headers = sub_table.get("headers", [])
            rows = sub_table.get("rows", [])
            
            qib_index = -1
            for i, header in enumerate(headers):
                if "qib" in header.lower():
                    qib_index = i
                    break
                    
            qib_subscriptions = []
            if qib_index != -1 and len(rows) > 1:
                for row in rows[1:]:
                    if len(row) > qib_index:
                        qib_subscriptions.append(row[qib_index])
            
            filtered_ipo = {
                "ipo_name": combined_data.get("ipo_name_base", "N/A"),
                "board": combined_data.get("board", "N/A"),
                "ipo_dates": combined_data.get("ipo_dates", "N/A"),
                "total_issue": key_details.get("total_issue_size", "N/A"),
                "fresh_issue": key_details.get("fresh_issue", "N/A"),
                "offer_for_sale": key_details.get("offer_for_sale_ofs", "N/A"),
                "gmp_history": gmp_history_filtered,
                "qib_subscriptions": qib_subscriptions
            }
            filtered_live_ipos.append(filtered_ipo)
        else:
            filtered_live_ipos.append({"ipo_name": ipo["ipo_name_base"], "error": "No URL found"})
            
    return filtered_live_ipos

# ============ TELEGRAM FORMATTING & LOGIC ============
def parse_dates(s):
    # Try to handle common separators (dash or en-dash)
    separator = "–" if "–" in s else "-"
    try:
        start, end = [x.strip() for x in s.split(separator)]
        fmt = "%b %d, %Y"
        return datetime.strptime(start, fmt).date(), datetime.strptime(end, fmt).date()
    except Exception:
        # Fallback if dates are malformed
        today = datetime.now(IST).date()
        return today, today + timedelta(days=1)

def crore(s):
    m = re.search(r"₹\s*([\d,.]+)\s*crore", s or "")
    return m.group(1) if m else None

def num(s):
    m = re.search(r"[\d.]+", s or "")
    return float(m.group()) if m else None

def qib_latest(ipo):
    vals = [num(q) for q in ipo.get("qib_subscriptions", [])]
    vals = [v for v in vals if v is not None]
    return vals[-1] if vals else None

def qib_sort_key(ipo):
    q = qib_latest(ipo)
    return q if q is not None else -1

def qib_emoji(x):
    if x is None: return "⚪"
    if x >= 10: return "🔥"
    if x >= 1: return "🟢"
    if x > 0: return "🟡"
    return "🔴"

def bar(x, width=10):
    if x is None: return "▱" * width
    filled = min(width, round(x * width))
    return "▰" * filled + "▱" * (width - filled)

def days_left_text(end, today):
    d = (end - today).days
    if d < 0: return "closed"
    if d == 0: return "closes TODAY"
    if d == 1: return "closes tomorrow"
    return f"{d} days left"

def gmp_text(history):
    vals = [num(h["GMP %"]) for h in history if num(h["GMP %"]) is not None]
    if not vals: return "N/A"
    latest = vals[0]
    icon = "📈" if latest > 0 else "➖"
    txt = f"{icon} <b>{latest:g}%</b>"
    if len(vals) > 1:
        trend = " → ".join(f"{v:g}%" for v in reversed(vals[:5]))
        txt += f"  <i>({trend})</i>"
    return txt

def size_text(ipo):
    total, fresh, ofs = crore(ipo.get("total_issue", "")), crore(ipo.get("fresh_issue", "")), crore(ipo.get("offer_for_sale", ""))
    txt = f"₹{total} Cr" if total else "N/A"
    parts = []
    if fresh: parts.append(f"Fresh ₹{fresh}")
    if ofs: parts.append(f"OFS ₹{ofs}")
    if len(parts) > 1: txt += f"  <i>({' + '.join(parts)})</i>"
    return txt

def card(ipo, today):
    start, end = parse_dates(ipo.get("ipo_dates", ""))
    qib = qib_latest(ipo)
    name = html.escape(ipo.get("ipo_name", "Unknown"))
    qib_line = f"<b>{qib:g}x</b> {bar(qib)}" if qib is not None else "N/A"
    
    date_str = f"📅 {start:%d %b} – {end:%d %b} · ⏳ {days_left_text(end, today)}" if start and end else "📅 Dates N/A"
    
    return (
        f"{qib_emoji(qib)} <b>{name}</b>\n"
        f"{date_str}\n"
        f"💰 {size_text(ipo)}\n"
        f"📊 GMP: {gmp_text(ipo.get('gmp_history', []))}\n"
        f"🏦 QIB: {qib_line}"
    )

def summary(ipos, today):
    main = [i for i in ipos if i.get("board", "").lower() == "mainboard"]
    sme = [i for i in ipos if i.get("board", "").lower() != "mainboard"]
    closing = [i.get("ipo_name", "") for i in ipos if 0 <= (parse_dates(i.get("ipo_dates", ""))[1] - today).days <= 2]
    top_qib = sorted(ipos, key=qib_sort_key, reverse=True)[:3]

    gmp_rows = []
    for i in ipos:
        g = [num(h.get("GMP %")) for h in i.get("gmp_history", []) if num(h.get("GMP %")) is not None]
        if g:
            gmp_rows.append((g[0], i.get("ipo_name", "Unknown")))
    gmp_rows.sort(reverse=True)

    lines = [
        f"📢 <b>IPO DASHBOARD</b> · {today:%a, %d %b %Y}",
        f"🏛 Mainboard: <b>{len(main)}</b>   🏪 SME: <b>{len(sme)}</b>",
        "",
        "🏆 <b>Top QIB subscription</b>",
    ]
    for n, i in enumerate(top_qib, 1):
        lines.append(f"{n}. {html.escape(i.get('ipo_name', ''))} — <b>{qib_sort_key(i):g}x</b>")
    if gmp_rows:
        lines += ["", "💹 <b>Highest GMP</b>"]
        for g, n in gmp_rows[:3]:
            lines.append(f"• {html.escape(n)} — <b>{g:g}%</b>")
    if closing:
        lines += ["", "⏰ <b>Closing within 2 days:</b>", html.escape(", ".join(closing))]
    lines += ["", "<i>Legend: 🔥 ≥10x · 🟢 ≥1x · 🟡 &lt;1x · 🔴 0x  (bar full = 1x)</i>"]
    return "\n".join(lines)

def section(title, ipos, today):
    ipos = sorted(ipos, key=qib_sort_key, reverse=True)
    msgs, cur = [], f"{title}  ({len(ipos)})"
    for c in (card(i, today) for i in ipos):
        if len(cur + SEP + c) > TG_LIMIT:
            msgs.append(cur)
            cur = c
        else:
            cur += SEP + c
    msgs.append(cur)
    return msgs

def build_messages(ipos, today):
    if not ipos:
        return ["⚠️ No live IPOs found today or scraping failed."]
        
    main = [i for i in ipos if i.get("board", "").lower() == "mainboard"]
    sme = [i for i in ipos if i.get("board", "").lower() != "mainboard"]
    msgs = [summary(ipos, today)]
    if main: msgs += section("🏛 <b>MAINBOARD IPOs</b>", main, today)
    if sme: msgs += section("🏪 <b>SME IPOs</b>", sme, today)
    return msgs

def detect_chat_id():
    r = requests.get(f"{API}/getUpdates", timeout=20)
    r.raise_for_status()
    for upd in reversed(r.json().get("result", [])):
        msg = upd.get("message") or upd.get("channel_post") or upd.get("my_chat_member")
        if msg and "chat" in msg:
            return str(msg["chat"]["id"])
    raise SystemExit("No chat found. Open your bot in Telegram, press Start, send 'hi', then run again.")

def send(chat_id, text):
    r = requests.post(
        f"{API}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=20,
    )
    if not r.ok:
        raise RuntimeError(f"Telegram error {r.status_code}: {r.text}")

def main():
    print("Starting IPO Scraping Process...")
    ipo_data = fetch_live_ipos()
    
    today = datetime.now(IST).date()
    msgs = build_messages(ipo_data, today)

    if DRY_RUN:
        for n, m in enumerate(msgs, 1):
            print(f"\n===== message {n}/{len(msgs)} ({len(m)} chars) =====\n{m}\n")
        return

    chat_id = CHAT_ID or detect_chat_id()
    if not CHAT_ID:
        print(f"Detected chat id: {chat_id} (Put it in GitHub secrets to skip detection)")

    for m in msgs:
        send(chat_id, m)
    print(f"Successfully sent {len(msgs)} message(s) to Telegram!")

if __name__ == "__main__":
    main()
