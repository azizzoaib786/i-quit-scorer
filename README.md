<div align="center">

# 🎴 I-Quit Scorer

**The flagship mobile-first scoreboard for the *I Quit* card game.**

Real-time scoring · Voice input · Live spectator view · PWA · Multi-round tournaments

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com/)
[![HTMX](https://img.shields.io/badge/HTMX-1.9-3D72D7.svg)](https://htmx.org/)
[![DynamoDB](https://img.shields.io/badge/AWS-DynamoDB-232F3E.svg)](https://aws.amazon.com/dynamodb/)
[![PWA](https://img.shields.io/badge/PWA-ready-5A0FC8.svg)](https://web.dev/progressive-web-apps/)

**Live** → [52patta.azizzoaib.com](https://52patta.azizzoaib.com)

</div>

---

## ✨ Why I-Quit Scorer?

Card nights should be about the cards, not the calculator. **I-Quit Scorer** turns your phone into a real-time tournament dashboard: score by voice, project a live leaderboard to the group, and never argue about who called *"I quit!"* again.

Built and battle-tested over hundreds of real games. This is the flagship scoring product for the *I Quit* card game community.

---

## 🚀 Features

### 🎙️ Voice Input *(flagship)*
Tap the mic, speak scores hands-free — even mid-game with cards in your hand.

- **Continuous listening** — say *"Aziz ten, Ali minus five, MK twenty five"*, pause, say more.
- **Fuzzy name matching** — Dice-coefficient matcher handles mispronunciations, accents, and speech-to-text quirks.
- **Word-number parsing** — *"one hundred and ten"*, *"minus five"*, *"twenty five"* all work.
- **Voice commands** — *"clear all"*, *"clear Ali"*, *"undo"*, *"make all zero"* for on-the-fly corrections.
- **Confidence scores** — every parse shows a match % so you can review before saving.

### 🎮 Complete Game Management
- 🔐 **Auth & roles** — Scorer, Player, Admin with proper permission boundaries.
- 🃏 **Multi-round games** — Configurable per-round target, lock rounds when complete.
- 👥 **Bulk player add** — Paste comma-separated names, dedupe automatically.
- 🏆 **Auto winner detection** — Popup on round end, no duplicate triggers.
- ↩️ **Undo & edit** — Every score is an event; full history is auditable.

### 📊 Player Experience
- 👤 **Personal profile** — Rounds played/won, win rate, I-Quit count, per-game round chips.
- 📺 **Live spectator link** — Share a read-only URL, auto-refreshing leaderboard for the room.
- 🎯 **Live I-Quit counter** — Total chip on the leaderboard + per-player badge in the current round.

### 📱 Progressive Web App
- Installable on iOS + Android home screens.
- Pull-to-refresh, service-worker caching, offline-friendly shell.
- Mobile-first design — thumb-reachable buttons, giant score inputs.

### 👑 Admin Panel
- User CRUD, activate/deactivate accounts, reset stats.
- Game oversight with soft-delete and history retention.

---

## 🧱 Tech Stack

| Layer          | Choice                                                |
|----------------|-------------------------------------------------------|
| **Backend**    | FastAPI · Python 3.11+ · Uvicorn                      |
| **Frontend**   | Jinja2 · HTMX 1.9 · Tailwind CSS (CDN) · Vanilla JS   |
| **Voice**      | Web Speech API + custom parser (Dice bigram matcher)  |
| **Database**   | AWS DynamoDB (`me-central-1`)                         |
| **Auth**       | Session cookies · bcrypt password hashing             |
| **Deployment** | EC2 · systemd · Nginx reverse proxy · Let's Encrypt   |
| **PWA**        | Service worker · Web App Manifest · Add-to-Home       |

---

## ⚡ Quick Start

### Prerequisites
- Python 3.11+
- AWS credentials with DynamoDB access (or `dynamodb-local` for dev)

### Local dev
```bash
git clone https://github.com/azizzoaib/i-quit-scorer.git
cd i-quit-scorer
pip install -r requirements.txt
python setup_db.py        # creates tables + default admin
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

Open <http://localhost:8001>. Default admin: `admin` / `xxx` — **change it immediately** via `/change-password`.

### Voice input
Voice input requires a browser that supports the Web Speech API (Chrome, Edge, Safari). Requires HTTPS in production (localhost works over HTTP for dev).

---

## 🛠 Utility Scripts

```bash
python reset_stats.py username1 username2   # wipe a player's stats & history
python backfill_roles.py                    # set role=scorer on legacy users
```

---

## 🚢 Deployment

Production runs on an EC2 instance behind Nginx with automated redeploy:

```bash
./deploy.sh      # first-time provisioning
./redeploy.sh    # pull, install deps, restart systemd unit
```

The systemd unit `i-quit-scorer.service` runs Uvicorn with `--proxy-headers --forwarded-allow-ips="127.0.0.1"` so `request.url_for()` produces correct HTTPS links behind the reverse proxy.

---

## 📁 Project Layout

```
i-quit-scorer/
├── app/
│   ├── main.py              # FastAPI routes
│   ├── auth.py              # session + password logic
│   ├── db.py                # DynamoDB clients
│   ├── logic.py             # scoring rules, winner detection
│   ├── static/
│   │   ├── app.js           # HTMX helpers, PWA registration
│   │   └── voice.js         # Web Speech API driver + parser
│   └── templates/
│       ├── game.html
│       └── partials/round_panel.html   # HTMX-swappable game panel
├── setup_db.py              # DynamoDB table provisioning
├── deploy.sh / redeploy.sh  # EC2 lifecycle
└── requirements.txt
```

---

## 🗺 Roadmap

- [ ] Multi-language voice commands (Arabic, Hindi, Urdu)
- [ ] Offline-first scoring with sync-on-reconnect
- [ ] Tournament mode with brackets and seed rankings
- [ ] Native iOS/Android wrappers
- [ ] Group / clan leaderboards across games

---

## 🤝 Contributing

Issues and PRs welcome. For substantial changes, open an issue first to discuss the direction.

---

## 📜 License

[MIT](./LICENSE) © 2026 **Aziz Zoaib**

---

<div align="center">

**Built with ❤️ by [Aziz Zoaib](https://github.com/azizzoaib)**

*If this app made your card night better, ⭐ the repo.*

</div>
