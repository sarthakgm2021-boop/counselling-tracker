#!/usr/bin/env python3
"""
Counselling Tracker
Scrapes JOSAA, JAC Delhi, JAC Chandigarh, FOT DU, GGSIPU for new notices.
Classifies action-required events via Groq (free).
Sends Telegram notifications twice daily.
Runs on GitHub Actions — your PC never needs to be on.
"""

import os, json, re, hashlib
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pytz

# ─── CONFIG ───────────────────────────────────────────────────────────────────

IST             = pytz.timezone("Asia/Kolkata")
SNAPSHOT_FILE   = "snapshot.json"
SCHEDULE_FILE   = "schedule.json"
YT_CACHE_FILE   = "yt_channel_cache.json"

TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID= os.environ.get("TELEGRAM_CHAT_ID", "")
GROQ_API_KEY    = os.environ.get("GROQ_API_KEY", "")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

# ─── PORTALS ──────────────────────────────────────────────────────────────────

PORTALS = {
    "JOSAA": {
        "url":    "https://josaa.nic.in/notices/",
        "parser": "nic_table",
    },
    "JAC Delhi": {
        "url":    "https://jacdelhi.admissions.nic.in/notices/",
        "parser": "nic_table",
    },
    "JAC Chandigarh": {
        "url":    "https://jacchd.admissions.nic.in/notices/",
        "parser": "nic_table",
    },
    "FOT DU": {
        "url":    "https://engineering.uod.ac.in/index.php/notifications/index",
        "parser": "samarth_table",
    },
    "GGSIPU": {
        "url":    "https://ipu.admissions.nic.in/",
        "parser": "ipu_homepage",
    },
}

# ─── YOUTUBE CHANNELS ─────────────────────────────────────────────────────────
# Known channel IDs are hardcoded. Handles are resolved at runtime and cached.

YT_CHANNELS = {
    "Ram Roop Sharma":      {"id":     "UCbBW3xfZf_O1JJSAcH5F_qA"},
    "Vashisht Academy":     {"id":     "UCL2eHcaS67jV1vmOk-tUitA"},
    "Vedantu JEE Made Ejee":{"id":     "UC91RZv71f8p0VV2gaFI07pg"},
    "Motion Online JEE":    {"id":     "UCfl4OhoOv8xF64D5KzJinnA"},
    "STBG Academy":         {"handle": "stbgacademy"},
    "9star Academy":        {"handle": "9staracademy01"},
    "Allen JEE":            {"handle": "ALLENJEE"},
    "Motion NV Sir":        {"handle": "MotionNVSir"},
}

# ─── FILE HELPERS ─────────────────────────────────────────────────────────────

def load_json(path: str, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default

def save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────

def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[WARN] Telegram credentials missing — skipping notification")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    # Telegram has a 4096 char limit per message
    for chunk in [message[i:i+4000] for i in range(0, len(message), 4000)]:
        try:
            r = requests.post(url, json={
                "chat_id":                  TELEGRAM_CHAT_ID,
                "text":                     chunk,
                "parse_mode":               "HTML",
                "disable_web_page_preview": True,
            }, timeout=10)
            r.raise_for_status()
        except Exception as e:
            print(f"[ERROR] Telegram: {e}")

# ─── SCRAPERS ─────────────────────────────────────────────────────────────────

def scrape_nic_table(url: str) -> list:
    """
    Standard NIC counselling CMS (JOSAA, JAC Delhi, JAC Chandigarh).
    Table structure: Title | Session | View/Download
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        notices = []
        for row in soup.select("table tr")[1:]:  # skip header row
            cols = row.find_all("td")
            if len(cols) < 2:
                continue
            title = cols[0].get_text(separator=" ", strip=True)
            # Find PDF link — usually in col[0] or col[2]
            link = ""
            for col in cols:
                a = col.find("a", href=True)
                if a:
                    href = a["href"]
                    link = href if href.startswith("http") else ("https:" + href if href.startswith("//") else href)
                    break
            if title and len(title) > 5:
                notices.append({"title": title, "link": link})
        print(f"    [{url.split('/')[2]}] {len(notices)} notices")
        return notices
    except Exception as e:
        print(f"[ERROR] NIC scrape {url}: {e}")
        return []

def scrape_samarth_table(url: str) -> list:
    """
    Samarth eGov platform (FOT DU).
    Table structure: Published On | Document | Title
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        notices = []
        for row in soup.select("table tr")[1:]:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue
            title = cols[2].get_text(strip=True)
            a = cols[1].find("a", href=True) or cols[2].find("a", href=True)
            link = a["href"] if a else ""
            if title and title != "No results found." and len(title) > 5:
                notices.append({"title": title, "link": link})
        print(f"    [FOT DU] {len(notices)} notices")
        return notices
    except Exception as e:
        print(f"[ERROR] Samarth scrape {url}: {e}")
        return []

def scrape_ipu_homepage(url: str) -> list:
    """
    GGSIPU admissions NIC portal homepage.
    Scrapes the 'Current Events' list items.
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        notices = []
        seen = set()
        # The homepage has a list of current events as <li><a> elements
        for a in soup.select("li a[href]"):
            title = a.get_text(separator=" ", strip=True)
            href  = a["href"]
            # Filter out nav items (short text, #anchors, external non-notice links)
            if (len(title) < 20 or href.startswith("#")
                    or "javascript" in href.lower()):
                continue
            link = href if href.startswith("http") else f"https://ipu.admissions.nic.in{href}"
            if title not in seen:
                seen.add(title)
                notices.append({"title": title, "link": link})
        notices = notices[:25]  # cap at top 25
        print(f"    [GGSIPU] {len(notices)} notices")
        return notices
    except Exception as e:
        print(f"[ERROR] IPU scrape {url}: {e}")
        return []

PARSERS = {
    "nic_table":     scrape_nic_table,
    "samarth_table": scrape_samarth_table,
    "ipu_homepage":  scrape_ipu_homepage,
}

def scrape_all_portals() -> dict:
    results = {}
    for name, cfg in PORTALS.items():
        print(f"  Scraping {name}...")
        results[name] = PARSERS[cfg["parser"]](cfg["url"])
    return results

# ─── YOUTUBE ──────────────────────────────────────────────────────────────────

def resolve_handle(handle: str, cache: dict) -> str | None:
    """Resolve YouTube @handle → channel ID. Cached after first resolution."""
    if handle in cache:
        return cache[handle]
    try:
        url = f"https://www.youtube.com/@{handle}"
        r = requests.get(url, headers=HEADERS, timeout=15)
        # Method 1: canonical link tag
        soup = BeautifulSoup(r.text, "html.parser")
        canon = soup.find("link", rel="canonical")
        if canon and "/channel/" in canon.get("href", ""):
            cid = canon["href"].split("/channel/")[1].strip("/")
            cache[handle] = cid
            return cid
        # Method 2: externalId in page source
        m = re.search(r'"externalId":"(UC[^"]{22})"', r.text)
        if m:
            cache[handle] = m.group(1)
            return m.group(1)
    except Exception as e:
        print(f"  [WARN] Could not resolve @{handle}: {e}")
    return None

def check_youtube(snapshot_yt: dict) -> tuple[list, dict]:
    """
    Fetch last 5 videos per channel via RSS.
    Returns (new_videos_list, full_current_snapshot_dict).
    """
    cache = load_json(YT_CACHE_FILE, {})
    current_snapshot = {}
    new_videos = []

    for name, cfg in YT_CHANNELS.items():
        channel_id = cfg.get("id") or resolve_handle(cfg.get("handle", ""), cache)
        if not channel_id:
            print(f"  [WARN] Skipping {name} — channel ID unresolved")
            continue

        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        try:
            feed = feedparser.parse(feed_url)
            recent_links = [e.get("link", "") for e in feed.entries[:5]]
            current_snapshot[name] = recent_links
            seen_links = set(snapshot_yt.get(name, []))
            for entry in feed.entries[:5]:
                link = entry.get("link", "")
                if link and link not in seen_links:
                    new_videos.append({
                        "channel":   name,
                        "title":     entry.get("title", "Untitled"),
                        "link":      link,
                        "published": entry.get("published", ""),
                    })
        except Exception as e:
            print(f"  [ERROR] YouTube RSS {name}: {e}")

    save_json(YT_CACHE_FILE, cache)
    print(f"  {len(new_videos)} new video(s) detected")
    return new_videos, current_snapshot

# ─── GROQ CLASSIFICATION ──────────────────────────────────────────────────────

def classify_notice(title: str, counselling: str) -> dict:
    """
    Ask Groq (free LLM) whether a notice requires candidate action.
    Returns structured JSON with action_required + events list.
    """
    if not GROQ_API_KEY:
        return {"action_required": False, "events": []}

    today = datetime.now(IST).strftime("%Y-%m-%d")
    prompt = f"""You are parsing Indian engineering counselling notices.
Today: {today}. Counselling: {counselling}.
Notice: "{title}"

Does this require candidate action (choice filling, fee payment, seat allotment, registration, document verification, withdrawal)?

Reply ONLY with JSON, no markdown, no explanation:
{{
  "action_required": true or false,
  "events": [
    {{
      "date": "YYYY-MM-DD or null",
      "event": "one-line action description",
      "counselling": "{counselling}"
    }}
  ]
}}
If action_required is false, events must be []."""

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model":       "llama-3.1-8b-instant",
                "messages":    [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens":  256,
            },
            timeout=20,
        )
        raw = r.json()["choices"][0]["message"]["content"].strip()
        raw = re.sub(r"```json|```", "", raw).strip()
        return json.loads(raw)
    except Exception as e:
        print(f"  [WARN] Groq classification failed: {e}")
        return {"action_required": False, "events": []}

# ─── SCHEDULE ─────────────────────────────────────────────────────────────────

def update_schedule(new_events: list) -> list:
    """Merge new action-required events into schedule.json. Returns added events."""
    schedule = load_json(SCHEDULE_FILE, {"events": []})
    existing_keys = {
        (e.get("date"), e.get("counselling"), e.get("event"))
        for e in schedule["events"]
    }
    added = []
    for ev in new_events:
        if not ev.get("date"):
            continue
        key = (ev["date"], ev["counselling"], ev["event"])
        if key not in existing_keys:
            schedule["events"].append(ev)
            existing_keys.add(key)
            added.append(ev)
    if added:
        schedule["events"].sort(key=lambda x: x.get("date") or "9999-99-99")
        save_json(SCHEDULE_FILE, schedule)
        print(f"  → {len(added)} new event(s) added to schedule")
    return added

def get_upcoming_events(days_ahead: int = 1) -> list:
    """Return events from schedule.json due within the next N days."""
    schedule = load_json(SCHEDULE_FILE, {"events": []})
    today  = datetime.now(IST).date()
    cutoff = today + timedelta(days=days_ahead)
    upcoming = []
    for ev in schedule["events"]:
        raw_date = ev.get("date")
        if not raw_date:
            continue
        try:
            ev_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
            if today <= ev_date <= cutoff:
                upcoming.append(ev)
        except ValueError:
            pass
    return upcoming

# ─── DIFF ─────────────────────────────────────────────────────────────────────

def diff_portals(current: dict, snapshot: dict) -> dict:
    """Return only notices not seen in the previous snapshot."""
    new = {}
    for portal, notices in current.items():
        seen_titles = {n["title"] for n in snapshot.get(portal, [])}
        fresh = [n for n in notices if n["title"] not in seen_titles]
        if fresh:
            new[portal] = fresh
    return new

# ─── TELEGRAM MESSAGE BUILDERS ────────────────────────────────────────────────

def build_summary(new_notices: dict, new_videos: list, added_events: list) -> str:
    now = datetime.now(IST).strftime("%d %b %Y — %I:%M %p IST")
    lines = [f"<b>📋 Counselling Update | {now}</b>"]

    if not new_notices and not new_videos:
        lines += ["", "✅ No new notices or videos since last check."]
    else:
        if new_notices:
            lines.append("")
            for portal, notices in new_notices.items():
                lines.append(f"<b>⚠️ {portal}</b> — {len(notices)} new notice(s)")
                for n in notices[:4]:
                    t = n["title"][:90]
                    l = n.get("link", "")
                    lines.append(f'  • <a href="{l}">{t}</a>' if l else f"  • {t}")

        if new_videos:
            lines.append("")
            lines.append(f"<b>🎬 New YouTube ({len(new_videos)} video(s))</b>")
            for v in new_videos[:5]:
                lines.append(f'  • [{v["channel"]}] <a href="{v["link"]}">{v["title"][:65]}</a>')

    if added_events:
        lines.append("")
        lines.append("<b>📅 Auto-added to your schedule:</b>")
        for e in added_events:
            lines.append(f'  📌 {e["date"]} — {e["counselling"]}: {e["event"]}')

    return "\n".join(lines)

def build_upcoming_alert(events: list) -> str:
    lines = ["<b>⏰ ACTION REQUIRED IN THE NEXT 24 HOURS</b>", ""]
    for e in events:
        lines.append(f"🔴 <b>{e['counselling']}</b>")
        lines.append(f"   {e['event']}")
        lines.append(f"   Date: <b>{e['date']}</b>")
        if e.get("source_notice"):
            lines.append(f"   Notice: {e['source_notice'][:80]}")
        lines.append("")
    lines.append("⚡ Log in to the portal and complete the action before the deadline.")
    return "\n".join(lines)

def build_full_schedule() -> str:
    """Format the full upcoming schedule as a readable message."""
    schedule = load_json(SCHEDULE_FILE, {"events": []})
    today = datetime.now(IST).date()
    upcoming = [
        e for e in schedule["events"]
        if e.get("date") and datetime.strptime(e["date"], "%Y-%m-%d").date() >= today
    ]
    if not upcoming:
        return "📅 <b>Schedule</b>\n\nNo upcoming events on record yet."
    lines = ["📅 <b>Upcoming Counselling Events</b>", ""]
    for e in upcoming[:15]:
        lines.append(f"  {e['date']}  |  {e['counselling']:<15}  |  {e['event']}")
    return "\n".join(lines)

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    now_str = datetime.now(IST).strftime("%d %b %Y %I:%M %p IST")
    print(f"\n{'='*55}")
    print(f"  Counselling Tracker  —  {now_str}")
    print(f"{'='*55}\n")

    # Load previous snapshot
    snapshot      = load_json(SNAPSHOT_FILE, {})
    snapshot_yt   = snapshot.pop("_youtube", {})   # separate key for YT

    # ── 1. Scrape portals ─────────────────────────────────────────────────────
    print("[ Scraping portals ]")
    current_portals = scrape_all_portals()

    # ── 2. YouTube RSS ────────────────────────────────────────────────────────
    print("\n[ Checking YouTube RSS feeds ]")
    new_videos, current_yt = check_youtube(snapshot_yt)

    # ── 3. Diff against snapshot ──────────────────────────────────────────────
    print("\n[ Diffing against last snapshot ]")
    new_notices = diff_portals(current_portals, snapshot)
    total_new   = sum(len(v) for v in new_notices.values())
    print(f"  Portal notices: {total_new} new | YouTube: {len(new_videos)} new")

    # ── 4. Classify new notices with Groq ─────────────────────────────────────
    all_new_events = []
    if new_notices and GROQ_API_KEY:
        print("\n[ Classifying with Groq ]")
        for portal, notices in new_notices.items():
            for notice in notices:
                print(f"  → {notice['title'][:70]}")
                result = classify_notice(notice["title"], portal)
                if result.get("action_required") and result.get("events"):
                    for ev in result["events"]:
                        ev["counselling"]   = portal
                        ev["source_notice"] = notice["title"][:100]
                        all_new_events.append(ev)
    elif new_notices:
        print("\n[INFO] GROQ_API_KEY not set — skipping auto-classification")

    # ── 5. Update schedule ────────────────────────────────────────────────────
    added_events = []
    if all_new_events:
        print("\n[ Updating schedule.json ]")
        added_events = update_schedule(all_new_events)

    # ── 6. Persist updated snapshot ───────────────────────────────────────────
    new_snapshot          = dict(current_portals)
    new_snapshot["_youtube"] = current_yt
    save_json(SNAPSHOT_FILE, new_snapshot)

    # ── 7. Send Telegram summary ──────────────────────────────────────────────
    print("\n[ Sending Telegram ]")
    summary = build_summary(new_notices, new_videos, added_events)
    send_telegram(summary)

    # ── 8. Send 24-hour upcoming event alert if any ───────────────────────────
    upcoming = get_upcoming_events(days_ahead=1)
    if upcoming:
        print(f"  ⚠ {len(upcoming)} event(s) due in 24 hours — sending alert")
        send_telegram(build_upcoming_alert(upcoming))

    print("\n✅ Done\n")

if __name__ == "__main__":
    main()
