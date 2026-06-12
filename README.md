# Counselling Tracker

Tracks JOSAA, JAC Delhi, JAC Chandigarh, FOT DU, GGSIPU + 8 YouTube channels.
Runs on GitHub's free servers — your PC never needs to be on.
Notifies via Telegram at 12:00 AM IST and 4:00 PM IST daily.

---

## One-Time Setup (~20 minutes)

### Step 1 — Create GitHub repo
1. Go to github.com → New repository → name it `counselling-tracker`
2. Push this entire folder to it

### Step 2 — Create Telegram Bot
1. Open Telegram → search `@BotFather` → send `/newbot`
2. Give it any name and username
3. Copy the **token** it gives you (looks like `7123456789:AAF...`)
4. Send `/start` to your new bot
5. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
6. Copy your **chat_id** from the JSON response (`"id": 123456789`)

### Step 3 — Get Groq API key (free)
1. Go to console.groq.com → sign up free
2. Go to API Keys → Create new key
3. Copy the key

### Step 4 — Add secrets to GitHub
Go to your repo → Settings → Secrets and variables → Actions → New secret

Add these three:
| Name | Value |
|------|-------|
| `TELEGRAM_TOKEN` | your bot token |
| `TELEGRAM_CHAT_ID` | your chat ID |
| `GROQ_API_KEY` | your Groq key |

### Step 5 — Done
Push the code. GitHub Actions will run automatically at:
- 12:00 AM IST (midnight)
- 4:00 PM IST

To test immediately: go to Actions tab → Counselling Tracker → Run workflow.

---

## What it does each run

1. Scrapes all 5 portals for new notices
2. Checks YouTube RSS feeds for new videos from all 8 channels
3. Sends any new notices to Groq for classification
4. Extracts action dates → auto-adds to `schedule.json`
5. Sends you a Telegram summary
6. If any event is due within 24 hours → sends a separate action alert
7. Commits updated `snapshot.json` + `schedule.json` back to repo

## Telegram message format

**No new notices:**
```
📋 Counselling Update | 12 Jun 2026 — 12:00 AM IST
✅ No new notices or videos since last check.
```

**New notice detected:**
```
📋 Counselling Update | 12 Jun 2026 — 04:00 PM IST

⚠️ JAC Delhi — 1 new notice(s)
  • Choice Filling for Round 2 opens June 19

📅 Auto-added to your schedule:
  📌 2026-06-19 — JAC Delhi: Choice Filling Round 2 Opens
```

**24-hour alert:**
```
⏰ ACTION REQUIRED IN THE NEXT 24 HOURS

🔴 GGSIPU
   Round 1 Seat Allotment Result
   Date: 2026-06-12

⚡ Log in to the portal and complete the action before the deadline.
```
