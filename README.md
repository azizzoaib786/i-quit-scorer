# I Quit — Scoreboard

A mobile-first scoreboard app for the "I Quit" card game with real-time updates, player profiles, and game history.

## Features

- 🔐 **Auth** — Login/register, password change, session management
- 🎮 **Scorer role** — Create & manage games, add players, score rounds
- 👤 **Player role** — View personal profile, stats, and game history
- 🎯 **Round system** — Multiple rounds per game, per-round target scoring
- 🏆 **Winner detection** — Auto popup when round ends, no duplicates
- 📊 **Player stats** — Rounds played/won, win rate, I Quits, game history with round chips
- 👥 **Multi-select players** — Search and add multiple players at once
- 📺 **Live view** — Read-only spectator link with auto-refresh
- 📱 **PWA** — Installable, pull-to-refresh, service worker caching
- 👑 **Admin panel** — Manage users, games, activate/deactivate accounts

## Tech Stack

- **Backend**: FastAPI + Python
- **Frontend**: HTMX + Tailwind CSS
- **Database**: AWS DynamoDB
- **Deployment**: Uvicorn + Nginx + EC2

## Quick Start

```bash
pip install -r requirements.txt
python setup_db.py        # creates tables + default admin
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

Default admin: `admin` / `xxx` — change immediately via `/change-password`.

## Utility Scripts

```bash
python reset_stats.py username1 username2   # reset player stats & history
python backfill_roles.py                    # set role=scorer on legacy users
```
