import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, Form, HTTPException, Cookie, Response
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .db import (put_game, get_game, update_game, list_events, put_event,
                 list_games, create_user, get_user_by_username, get_user_by_id, list_games_by_user, delete_game, update_user_password,
                 get_user_by_email, search_users, save_game_history, game_history_exists, get_user_history, update_user_stats, update_round_stats)
from .logic import totals_by_player, per_round_scores, leaderboard, per_round_deltas
from .auth import hash_password, verify_password, create_session_token, verify_session_token

app = FastAPI(title="I Quit Scoreboard (HTMX)")
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/sw.js")
async def service_worker():
    return FileResponse(
        "app/static/sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


@app.get("/favicon.ico")
async def favicon():
    return FileResponse("app/static/icons/icon-192.png", media_type="image/png")


# Add custom Jinja2 filter for checking game expiration
def _is_game_expired_filter(game: Dict[str, Any]) -> bool:
    from datetime import timedelta
    created_at = game.get("created_at", "")
    if not created_at:
        return False
    try:
        created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return (now - created_dt) > timedelta(days=5)
    except:
        return False

templates.env.filters["is_expired"] = _is_game_expired_filter


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    # Custom 404 page
    return templates.TemplateResponse("404.html", {"request": request}, status_code=404)


def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    # Get current user from session cookie
    token = request.cookies.get("session")
    if not token:
        return None
    user_id = verify_session_token(token)
    if not user_id:
        return None
    return get_user_by_id(user_id)


def require_auth(request: Request) -> Dict[str, Any]:
    # Require authenticated user
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_admin(request: Request) -> Dict[str, Any]:
    # Require admin user
    user = require_auth(request)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def require_scorer(request: Request) -> Dict[str, Any]:
    # Require scorer role (blocks players)
    user = require_auth(request)
    if user.get("role", "scorer") == "player":
        raise HTTPException(status_code=403, detail="Scorer access required")
    return user


@app.post("/profile/request-scorer", response_class=HTMLResponse)
def request_scorer_access(request: Request):
    # Player requests scorer role — sets role=scorer, is_active=False, pending admin activation
    user = require_auth(request)
    if user.get("role", "scorer") != "player":
        raise HTTPException(400, "Only players can request scorer access")
    from .db import toggle_user_active
    # Set role to scorer and deactivate until admin approves
    from boto3.dynamodb.conditions import Key as DKey
    from .db import users as users_tbl
    users_tbl.update_item(
        Key={"user_id": user["user_id"]},
        UpdateExpression="SET #r = :r, is_active = :f",
        ExpressionAttributeNames={"#r": "role"},
        ExpressionAttributeValues={":r": "scorer", ":f": False},
    )
    return RedirectResponse(f"/profile/{user['user_id']}?scorer_requested=1", status_code=303)


def now_ts() -> str:
    # Generate unique timestamp for event ordering
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ") + "#" + uuid.uuid4().hex


def must_game(game_id: str) -> Dict[str, Any]:
    # Fetch game or raise 404
    g = get_game(game_id)
    if not g:
        raise HTTPException(status_code=404, detail="Game not found")
    return g


def check_game_access(request: Request, game_id: str) -> tuple[Dict[str, Any], Dict[str, Any]]:
    # Check if user can access game (returns user and game)
    user = require_auth(request)
    game = must_game(game_id)
    
    # Admins can access all games, users only their own
    if not user.get("is_admin") and game.get("user_id") != user["user_id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return user, game


def is_game_expired(game: Dict[str, Any]) -> bool:
    # Check if game is older than 5 days
    from datetime import timedelta
    created_at = game.get("created_at", "")
    if not created_at:
        return False
    
    try:
        created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return (now - created_dt) > timedelta(days=5)
    except:
        return False


def round_locked(game: Dict[str, Any], round_id: str) -> bool:
    # Check if round is locked
    for r in game.get("rounds", []):
        if r["round_id"] == round_id:
            return bool(r.get("locked", False))
    raise HTTPException(status_code=404, detail="Round not found")


def default_round_id(game: Dict[str, Any]) -> Optional[str]:
    # Pick the round to show when the user hasn't explicitly chosen one
    # (page refresh, spectator link, or after a player-list update).
    # Rounds are appended in chronological order, so the newest is last.
    # Prefer the most-recent *unlocked* round (the one scoring is happening
    # in). If every round is locked, fall back to the newest overall so a
    # completed game still shows its final round instead of round 1.
    rounds = game.get("rounds") or []
    if not rounds:
        return None
    for r in reversed(rounds):
        if not r.get("locked"):
            return r["round_id"]
    return rounds[-1]["round_id"]


def compute_view(game: Dict[str, Any], selected_round_id: Optional[str] = None) -> Dict[str, Any]:
    # Calculate all game stats for display
    ev = list_events(game["game_id"])

    # Filter events to selected round only
    if selected_round_id:
        round_events = [e for e in ev if e.get("round_id") == selected_round_id]
    else:
        round_events = ev

    totals = totals_by_player(game.get("players", []), round_events)

    # Pass round_events so out-timestamps are consistent with the displayed totals
    board = leaderboard(game.get("players", []), totals, int(game["target"]), events=round_events)
    round_scores = per_round_scores(ev)
    round_deltas = per_round_deltas(ev)
    is_expired = is_game_expired(game)
    return {"events": ev, "totals": totals, "board": board, "round_scores": round_scores, "round_deltas": round_deltas, "is_expired": is_expired}


def _write_game_history(game: Dict[str, Any], board: list, round_id: str) -> None:
    """Write history + update stats for all registered players (idempotent: stats only increment once per game)."""
    player_ids = game.get("player_ids", {})
    if not player_ids:
        return
    iquit_declarations = game.get("iquit_declarations", {})
    date = now_ts()
    # Score + rank for this specific round only
    all_events = list_events(game["game_id"])
    round_events = [e for e in all_events if e.get("round_id") == round_id]
    round_totals = totals_by_player(game.get("players", []), round_events)
    round_board = leaderboard(game.get("players", []), round_totals, int(game["target"]), events=round_events)
    round_rank_map = {e["player"]: e["rank"] for e in round_board}
    # Find round name for display
    round_name = next((r["name"] for r in game.get("rounds", []) if r["round_id"] == round_id), "Final Round")
    for entry in board:
        player_name = entry["player"]
        user_id = player_ids.get(player_name)
        if not user_id:
            continue
        # won = rank 1 in THIS round (not cumulative)
        round_rank = round_rank_map.get(player_name, 99)
        won = round_rank == 1
        iquit_count = int(iquit_declarations.get(player_name, 0))
        # Only increment game stats once per game (prevent double-count if winner fires multiple times)
        already_recorded = game_history_exists(user_id, game["game_id"])
        save_game_history({
            "user_id": user_id,
            "game_id": game["game_id"] + "#" + round_id,
            "game_name": game.get("name", "Unknown"),
            "round_name": round_name,
            "date": date,
            "players": game.get("players", []),
            "final_rank": round_rank,
            "final_score": int(round_totals.get(player_name, 0)),
            "iquit_count": iquit_count,
            "won": won,
        })
        if not already_recorded:
            # game-level stats use cumulative rank (who won the overall game)
            game_won = entry["rank"] == 1
            update_user_stats(user_id, won=game_won, iquit_count=iquit_count)


def _write_round_stats(game: Dict[str, Any], round_id: str) -> None:
    """Update per-round stats for all registered players after a round is locked.
    Survived = player's score in THIS round is below target (per-round basis).
    """
    player_ids = game.get("player_ids", {})
    if not player_ids:
        return
    # Use round-specific view to determine who survived this round
    round_view = compute_view(game, round_id)
    for entry in round_view["board"]:
        user_id = player_ids.get(entry["player"])
        if not user_id:
            continue
        survived = not entry["is_out"]
        update_round_stats(user_id, survived=survived)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    # Homepage with game history
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    # Players can only see their own profile
    if user.get("role", "scorer") == "player":
        return RedirectResponse(f"/profile/{user['user_id']}", status_code=303)

    # Show user's games only (admins see all)
    if user.get("is_admin"):
        recent_games = list_games(limit=50)
    else:
        recent_games = list_games_by_user(user["user_id"], limit=50)

    return templates.TemplateResponse("home.html", {
        "request": request,
        "user": user,
        "recent_games": recent_games
    })


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    # Login page
    user = get_current_user(request)
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(request: Request, response: Response, username: str = Form(...), password: str = Form(...)):
    # Authenticate user
    user = get_user_by_username(username)
    if not user or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid credentials"
        }, status_code=401)
    
    # Check if user is active
    if not user.get("is_active", True):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Your account has been deactivated. Contact Aziz Zoaib on +971 56 8103175 to activate your account."
        }, status_code=403)
    
    # Create session
    token = create_session_token(user["user_id"])
    # Players go straight to their profile, scorers/admins go to home
    if user.get("role", "scorer") == "player":
        redirect_to = f"/profile/{user['user_id']}"
    else:
        redirect_to = "/"
    response = RedirectResponse(redirect_to, status_code=303)
    response.set_cookie(key="session", value=token, httponly=True, max_age=86400 * 7)
    return response


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    # Registration page
    user = get_current_user(request)
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("register.html", {"request": request})


@app.post("/register")
async def register(request: Request, response: Response, username: str = Form(...), email: str = Form(...), password: str = Form(...)):
    # Create new scorer account. Player self-registration has been removed —
    # players are added as free-text names by a scorer during a game and do
    # not need their own login.
    existing_user = get_user_by_username(username)
    if existing_user:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Username already exists"
        }, status_code=400)

    existing_email = get_user_by_email(email)
    if existing_email:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Email already registered"
        }, status_code=400)

    user_id = uuid.uuid4().hex
    password_hash = hash_password(password)
    # Scorers always need admin activation before they can log in.
    create_user(user_id, username, password_hash, is_admin=False, email=email, role="scorer")

    success_msg = "Scorer account created! Contact Aziz Zoaib on +971 56 8103175 to activate your account before logging in."

    return templates.TemplateResponse("register.html", {
        "request": request,
        "success": success_msg
    })
    return response


@app.get("/logout")
def logout():
    # Logout user
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("session")
    return response


@app.get("/users/search")
def users_search(request: Request, q: str = "", exclude: str = ""):
    # Search registered active users by username (typeahead)
    require_auth(request)
    if len(q) < 2:
        return JSONResponse([])
    exclude_ids = [e for e in exclude.split(",") if e]
    results = search_users(q, exclude_ids=exclude_ids)
    return JSONResponse(results)


@app.get("/profile/{user_id}", response_class=HTMLResponse)
def profile_page(request: Request, user_id: str):
    current_user = require_auth(request)
    profile_user = get_user_by_id(user_id)
    if not profile_user:
        raise HTTPException(404, "User not found")
    game_history_raw = get_user_history(user_id)
    game_history_raw.sort(key=lambda x: x.get("date", ""), reverse=True)

    # Group rounds under each game (SK is game_id#round_id)
    from collections import OrderedDict
    grouped: OrderedDict = OrderedDict()
    for h in game_history_raw:
        sk = h.get("game_id", "")
        pure_game_id = sk.split("#")[0]
        if pure_game_id not in grouped:
            grouped[pure_game_id] = {
                "game_id": pure_game_id,
                "game_name": h.get("game_name", "Unknown"),
                "players": h.get("players", []),
                "date": h.get("date", ""),
                "won": False,
                "rounds": [],
            }
        grouped[pure_game_id]["rounds"].append({
            "round_name": h.get("round_name", ""),
            "final_score": h.get("final_score", 0),
            "final_rank": h.get("final_rank", 0),
            "iquit_count": h.get("iquit_count", 0),
            "won": h.get("won", False),
        })
    # Game-level won = the last round's won (decisive round wins the game)
    for g in grouped.values():
        g["rounds"].sort(key=lambda r: r["round_name"])
        g["won"] = g["rounds"][-1]["won"] if g["rounds"] else False
    game_history = list(grouped.values())
    games_played = int(profile_user.get("stat_games_played", 0))
    games_won = int(profile_user.get("stat_games_won", 0))
    rounds_played = int(profile_user.get("stat_rounds_played", 0))
    rounds_won = int(profile_user.get("stat_rounds_won", 0))
    stats = {
        "games_played": games_played,
        "games_won": games_won,
        "rounds_played": rounds_played,
        "rounds_won": rounds_won,
        "total_iquits": int(profile_user.get("stat_total_iquits", 0)),
        "win_rate": round(games_won / games_played * 100) if games_played > 0 else 0,
        "round_win_rate": round(rounds_won / rounds_played * 100) if rounds_played > 0 else 0,
    }
    scorer_requested = request.query_params.get("scorer_requested") == "1"
    return templates.TemplateResponse("profile.html", {
        "request": request,
        "current_user": current_user,
        "profile_user": profile_user,
        "game_history": game_history,
        "stats": stats,
        "scorer_requested": scorer_requested,
    })


@app.get("/change-password", response_class=HTMLResponse)
def change_password_page(request: Request):
    # Change password page
    user = require_auth(request)
    return templates.TemplateResponse("change_password.html", {
        "request": request,
        "user": user
    })


@app.post("/change-password")
def change_password(request: Request, 
                   current_password: str = Form(...),
                   new_password: str = Form(...),
                   confirm_password: str = Form(...)):
    # Update user password
    user = require_auth(request)
    
    # Verify current password
    if not verify_password(current_password, user["password_hash"]):
        return templates.TemplateResponse("change_password.html", {
            "request": request,
            "user": user,
            "error": "Current password is incorrect"
        })
    
    # Check new passwords match
    if new_password != confirm_password:
        return templates.TemplateResponse("change_password.html", {
            "request": request,
            "user": user,
            "error": "New passwords do not match"
        })
    
    # Check password length
    if len(new_password) < 6:
        return templates.TemplateResponse("change_password.html", {
            "request": request,
            "user": user,
            "error": "Password must be at least 6 characters"
        })
    
    # Update password
    new_hash = hash_password(new_password)
    update_user_password(user["user_id"], new_hash)
    
    return templates.TemplateResponse("change_password.html", {
        "request": request,
        "user": user,
        "success": "Password updated successfully!"
    })


@app.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request):
    # Admin panel
    admin = require_admin(request)
    all_games = list_games(limit=100)
    from .db import list_all_users
    all_users = list_all_users()
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "user": admin,
        "games": all_games,
        "all_users": all_users
    })


@app.post("/admin/games/{game_id}/delete")
async def admin_delete_game(request: Request, game_id: str):
    # Delete game (admin only)
    require_admin(request)
    delete_game(game_id)
    return HTMLResponse("", status_code=200)


@app.post("/admin/users/{user_id}/toggle-active")
async def admin_toggle_user(request: Request, user_id: str):
    # Toggle user active status (admin only)
    admin = require_admin(request)
    
    from .db import list_all_users, toggle_user_active
    all_users = list_all_users()
    
    # Find the user
    target_user = None
    for u in all_users:
        if u["user_id"] == user_id:
            target_user = u
            break
    
    if not target_user:
        raise HTTPException(404, "User not found")
    
    if target_user.get("is_admin"):
        raise HTTPException(400, "Cannot deactivate admin users")
    
    # Toggle active status
    new_status = not target_user.get("is_active", True)
    toggle_user_active(user_id, new_status)
    
    # Reload users and return partial
    all_users = list_all_users()
    
    return templates.TemplateResponse("partials/user_management.html", {
        "request": request,
        "all_users": all_users
    })


@app.post("/admin/users/{user_id}/revert-to-player")
async def admin_revert_to_player(request: Request, user_id: str):
    # Revert a scorer (pending activation) back to player and re-activate them
    require_admin(request)
    from .db import users as users_tbl
    users_tbl.update_item(
        Key={"user_id": user_id},
        UpdateExpression="SET #r = :r, is_active = :a",
        ExpressionAttributeNames={"#r": "role"},
        ExpressionAttributeValues={":r": "player", ":a": True},
    )
    from .db import list_all_users
    all_users = list_all_users()
    return templates.TemplateResponse("partials/user_management.html", {
        "request": request,
        "all_users": all_users
    })


@app.post("/admin/users/{user_id}/reset-password")
async def admin_reset_password(request: Request, user_id: str):
    # Generate a temp password and reset the user's password
    require_admin(request)
    import secrets, string
    alphabet = string.ascii_letters + string.digits
    temp_password = ''.join(secrets.choice(alphabet) for _ in range(10))
    new_hash = hash_password(temp_password)
    update_user_password(user_id, new_hash)
    from .db import list_all_users
    all_users = list_all_users()
    target = next((u for u in all_users if u["user_id"] == user_id), None)
    username = target["username"] if target else user_id
    return templates.TemplateResponse("partials/user_management.html", {
        "request": request,
        "all_users": all_users,
        "reset_password_msg": f"🔑 Temp password for {username}: {temp_password}",
    })


@app.delete("/admin/users/{user_id}")
async def admin_delete_user(request: Request, user_id: str):
    # Delete user (admin only)
    admin = require_admin(request)
    
    from .db import list_all_users, delete_user, list_games_by_user, delete_game
    all_users = list_all_users()
    
    # Find the user
    target_user = None
    for u in all_users:
        if u["user_id"] == user_id:
            target_user = u
            break
    
    if not target_user:
        raise HTTPException(404, "User not found")
    
    if target_user.get("is_admin"):
        raise HTTPException(400, "Cannot delete admin users")
    
    # Delete all user's games
    user_games = list_games_by_user(user_id)
    for game in user_games:
        delete_game(game["game_id"])
    
    # Delete user
    delete_user(user_id)
    
    # Reload users and return partial
    all_users = list_all_users()
    
    return templates.TemplateResponse("partials/user_management.html", {
        "request": request,
        "all_users": all_users
    })


@app.post("/games")
def create_game(request: Request, name: str = Form(...), target: int = Form(150)):
    # Create new game
    user = require_scorer(request)
    game_id = uuid.uuid4().hex
    put_game({
        "game_id": game_id,
        "name": name.strip(),
        "target": int(target),
        "players": [],
        "rounds": [],
        "created_at": now_ts(),
        "user_id": user["user_id"],
    })
    return RedirectResponse(f"/games/{game_id}", status_code=303)


@app.get("/games/{game_id}", response_class=HTMLResponse)
def game_page(request: Request, game_id: str, round_id: Optional[str] = None):
    user = require_scorer(request)
    game = must_game(game_id)
    
    # Check ownership (admins can access all games)
    if not user.get("is_admin") and game.get("user_id") != user["user_id"]:
        raise HTTPException(status_code=403, detail="Access denied")

    selected_round_id = round_id or default_round_id(game)

    view = compute_view(game, selected_round_id)

    return templates.TemplateResponse("game.html", {
        "request": request,
        "user": user,
        "game": game,
        "selected_round_id": selected_round_id,
        **view
    })


@app.get("/live/{game_id}", response_class=HTMLResponse)
def live_game(request: Request, game_id: str):
    # Read-only live view for spectators
    game = must_game(game_id)

    # Get round_id from query parameter
    round_id = request.query_params.get("round_id")
    
    selected_round_id = round_id or default_round_id(game)

    view = compute_view(game, selected_round_id)

    return templates.TemplateResponse("live.html", {
        "request": request,
        "game": game,
        "selected_round_id": selected_round_id,
        **view
    })


@app.post("/games/{game_id}/players", response_class=HTMLResponse)
def add_player(request: Request, game_id: str, player_user_id: str = Form(...)):
    # Add a registered user as a player
    user, game = check_game_access(request, game_id)

    target_user = get_user_by_id(player_user_id)
    if not target_user:
        raise HTTPException(400, "User not found")
    if not target_user.get("is_active", False):
        raise HTTPException(400, "User account is not active")

    player_name = target_user["username"]
    existing_players = game.get("players", [])
    existing_player_ids = game.get("player_ids", {})

    if player_name in existing_players:
        flash_msg = f"⚠️ {player_name} is already in the game"
    else:
        updated_players = existing_players + [player_name]
        updated_player_ids = {**existing_player_ids, player_name: player_user_id}
        update_game(game_id, "SET players = :p, player_ids = :pi", {
            ":p": updated_players,
            ":pi": updated_player_ids,
        })
        flash_msg = f"✅ Added {player_name}"

    game2 = must_game(game_id)
    selected = default_round_id(game2)
    view = compute_view(game2, selected)
    return templates.TemplateResponse("partials/round_panel.html", {
        "request": request, "user": user, "game": game2, "selected_round_id": selected, **view,
        "flash": flash_msg
    })


@app.post("/games/{game_id}/players/name", response_class=HTMLResponse)
def add_player_by_name(request: Request, game_id: str, player_name: str = Form(...)):
    # Add one or more free-text players by name (no login / registration
    # required). Accepts a comma-, newline-, or semicolon-separated list so
    # a scorer can paste an entire roster in one submit. Names are stored
    # as-is; they do not appear in `player_ids` because there is no linked
    # user account. Case-insensitive dedupe against existing players and
    # within the incoming batch itself.
    user, game = check_game_access(request, game_id)

    raw = (player_name or "").replace(";", ",").replace("\n", ",")
    incoming = [n.strip() for n in raw.split(",") if n.strip()]
    if not incoming:
        raise HTTPException(400, "Player name required")

    existing_players = list(game.get("players", []))
    lowered = {p.lower() for p in existing_players}
    added, skipped_dupe, skipped_long = [], [], []
    for name in incoming:
        if len(name) > 40:
            skipped_long.append(name[:20] + "…")
            continue
        key = name.lower()
        if key in lowered:
            skipped_dupe.append(name)
            continue
        lowered.add(key)
        existing_players.append(name)
        added.append(name)

    if added:
        update_game(game_id, "SET players = :p", {":p": existing_players})

    parts = []
    if added:
        parts.append(f"✅ Added {len(added)}: {', '.join(added[:6])}{'…' if len(added) > 6 else ''}")
    if skipped_dupe:
        parts.append(f"⚠️ Skipped {len(skipped_dupe)} already in game")
    if skipped_long:
        parts.append(f"⚠️ Skipped {len(skipped_long)} over 40 chars")
    flash_msg = " • ".join(parts) or "No players added"

    game2 = must_game(game_id)
    selected = default_round_id(game2)
    view = compute_view(game2, selected)
    return templates.TemplateResponse("partials/round_panel.html", {
        "request": request, "user": user, "game": game2, "selected_round_id": selected, **view,
        "flash": flash_msg
    })


@app.post("/games/{game_id}/players/batch", response_class=HTMLResponse)
async def add_players_batch(request: Request, game_id: str):
    # Add multiple registered users as players at once
    user, game = check_game_access(request, game_id)
    form_data = await request.form()
    user_ids = form_data.getlist("player_user_ids")
    if not user_ids:
        raise HTTPException(400, "No players selected")

    existing_players = list(game.get("players", []))
    existing_player_ids = dict(game.get("player_ids", {}))
    added = []
    for uid in user_ids:
        target_user = get_user_by_id(uid)
        if not target_user or not target_user.get("is_active", False):
            continue
        player_name = target_user["username"]
        if player_name not in existing_players:
            existing_players.append(player_name)
            existing_player_ids[player_name] = uid
            added.append(player_name)

    if added:
        update_game(game_id, "SET players = :p, player_ids = :pi", {
            ":p": existing_players,
            ":pi": existing_player_ids,
        })
        flash_msg = f"✅ Added: {', '.join(added)}"
    else:
        flash_msg = "⚠️ All selected players are already in the game"

    game2 = must_game(game_id)
    selected = default_round_id(game2)
    view = compute_view(game2, selected)
    return templates.TemplateResponse("partials/round_panel.html", {
        "request": request, "user": user, "game": game2, "selected_round_id": selected, **view,
        "flash": flash_msg
    })


@app.post("/games/{game_id}/players/remove", response_class=HTMLResponse)
def remove_player(request: Request, game_id: str, player_name: str = Form(...)):
    # Remove player from game (scorer or admin)
    user, game = check_game_access(request, game_id)
    
    name = player_name.strip()
    players = game.get("players", [])
    
    if name not in players:
        raise HTTPException(400, "Player not found")
    
    # Remove player from list
    players.remove(name)
    player_ids = game.get("player_ids", {})
    player_ids.pop(name, None)
    update_game(game_id, "SET players = :p, player_ids = :pi", {":p": players, ":pi": player_ids})
    
    # Delete all events for this player
    ev = list_events(game_id)
    from .db import events
    for e in ev:
        if e.get("player") == name:
            events.delete_item(Key={"game_id": game_id, "ts": e["ts"]})
    
    game2 = must_game(game_id)
    selected = default_round_id(game2)
    view = compute_view(game2, selected)
    return templates.TemplateResponse("partials/round_panel.html", {
        "request": request, "user": user, "game": game2, "selected_round_id": selected, **view,
        "flash": f"Removed player '{name}' and all their scores."
    })


@app.post("/games/{game_id}/iquit/{player_name}", response_class=HTMLResponse)
def declare_iquit(request: Request, game_id: str, player_name: str):
    # Player declares "I Quit"
    user, game = check_game_access(request, game_id)
    
    # Initialize iquit_declarations if not exists
    iquit_declarations = game.get("iquit_declarations", {})
    
    # Increment counter for this player
    iquit_declarations[player_name] = iquit_declarations.get(player_name, 0) + 1
    
    # Update game
    update_game(game_id, "SET iquit_declarations = :iq", {":iq": iquit_declarations})
    
    game2 = must_game(game_id)
    selected = request.query_params.get("round_id") or default_round_id(game2)
    
    view = compute_view(game2, selected)
    return templates.TemplateResponse("partials/round_panel.html", {
        "request": request, "user": user, "game": game2, "selected_round_id": selected, **view,
        "flash": f"🎲 {player_name} declared I QUIT! (Total: {iquit_declarations[player_name]})"
    })


@app.post("/games/{game_id}/rounds", response_class=HTMLResponse)
def add_round(request: Request, game_id: str, round_name: str = Form(...)):
    user, game = check_game_access(request, game_id)
    rn = round_name.strip()
    if not rn:
        raise HTTPException(400, "Empty round name")

    rid = uuid.uuid4().hex[:10]
    rounds = game.get("rounds", []) + [{"round_id": rid, "name": rn, "locked": False}]
    update_game(game_id, "SET rounds = :r", {":r": rounds})

    game2 = must_game(game_id)
    view = compute_view(game2, rid)
    return templates.TemplateResponse("partials/round_panel.html", {
        "request": request, "user": user, "game": game2, "selected_round_id": rid, **view,
        "flash": "Round added."
    })


@app.post("/games/{game_id}/rounds/select", response_class=HTMLResponse)
def select_round(request: Request, game_id: str, round_id: str = Form(...)):
    user, game = check_game_access(request, game_id)
    view = compute_view(game, round_id)
    return templates.TemplateResponse("partials/round_panel.html", {
        "request": request, "user": user, "game": game, "selected_round_id": round_id, **view
    })


@app.post("/games/{game_id}/rounds/toggle-lock", response_class=HTMLResponse)
def toggle_lock(request: Request, game_id: str, round_id: str = Form(...)):
    user, game = check_game_access(request, game_id)
    rounds = game.get("rounds", [])
    found = False
    for r in rounds:
        if r["round_id"] == round_id:
            r["locked"] = not bool(r.get("locked", False))
            found = True
            break
    if not found:
        raise HTTPException(404, "Round not found")

    update_game(game_id, "SET rounds = :r", {":r": rounds})

    game2 = must_game(game_id)
    view = compute_view(game2, round_id)
    return templates.TemplateResponse("partials/round_panel.html", {
        "request": request, "user": user, "game": game2, "selected_round_id": round_id, **view,
        "flash": "Round lock updated."
    })


@app.delete("/games/{game_id}/rounds/{round_id}", response_class=HTMLResponse)
def delete_round(request: Request, game_id: str, round_id: str):
    # Delete round and all its events (admin only)
    user, game = check_game_access(request, game_id)
    
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # Find and remove round from game
    rounds = game.get("rounds", [])
    round_name = None
    new_rounds = []
    for r in rounds:
        if r["round_id"] == round_id:
            round_name = r["name"]
        else:
            new_rounds.append(r)
    
    if round_name is None:
        raise HTTPException(404, "Round not found")
    
    # Update game with rounds removed
    update_game(game_id, "SET rounds = :r", {":r": new_rounds})
    
    # Delete all events for this round
    ev = list_events(game_id)
    from .db import events
    for e in ev:
        if e.get("round_id") == round_id:
            events.delete_item(Key={"game_id": game_id, "ts": e["ts"]})
    
    # Reload game and select first round if available
    game2 = must_game(game_id)
    selected = default_round_id(game2)
    view = compute_view(game2, selected)
    
    return templates.TemplateResponse("partials/round_panel.html", {
        "request": request, "user": user, "game": game2, "selected_round_id": selected, **view,
        "flash": f"Deleted round '{round_name}' and all its scores."
    })


@app.post("/games/{game_id}/rounds/end", response_class=HTMLResponse)
def end_round(request: Request, game_id: str, round_id: str = Form(...)):
    # End round and lock it
    user, game = check_game_access(request, game_id)
    rounds = game.get("rounds", [])
    found = False
    for r in rounds:
        if r["round_id"] == round_id:
            r["locked"] = True
            found = True
            break
    if not found:
        raise HTTPException(404, "Round not found")

    update_game(game_id, "SET rounds = :r", {":r": rounds})

    game2 = must_game(game_id)
    view = compute_view(game2, round_id)

    # Update per-round stats for every registered player after this round
    _write_round_stats(game2, round_id)

    # Winner detection is per-round
    active_players = [entry for entry in view["board"] if not entry["is_out"]]
    out_players = [entry for entry in view["board"] if entry["is_out"]]
    total_players = len(view["board"])

    flash_msg = "Round ended and locked."
    winner_name = None
    winner_score = None

    game_over = (len(active_players) == 1 and len(out_players) > 0) or \
                (len(active_players) == 0 and total_players > 1)
    if game_over:
        already_declared = bool(game2.get("winner_declared", False))

        if not already_declared:
            flash_msg += " 🎉 Game Over! Winner declared!"
            winner_entry = view["board"][0]
            winner_name = winner_entry["player"]
            winner_score = winner_entry["total"]

        update_game(game_id, "SET winner_declared = :w", {":w": True})
        cumulative = compute_view(game2, None)
        _write_game_history(game2, cumulative["board"], round_id)
    
    return templates.TemplateResponse("partials/round_panel.html", {
        "request": request, "user": user, "game": game2, "selected_round_id": round_id, **view,
        "flash": flash_msg,
        "winner_name": winner_name,
        "winner_score": winner_score
    })


@app.post("/games/{game_id}/scores", response_class=HTMLResponse)
def add_score(request: Request, game_id: str,
              round_id: str = Form(...),
              player: str = Form(...),
              delta: int = Form(...)):
    # Add score delta to player
    user, game = check_game_access(request, game_id)

    if player not in game.get("players", []):
        raise HTTPException(400, "Unknown player")

    if round_locked(game, round_id):
        raise HTTPException(409, "Round is locked")

    put_event({
        "game_id": game_id,
        "ts": now_ts(),
        "round_id": round_id,
        "player": player,
        "delta": int(delta),
        "undone": False
    })

    game2 = must_game(game_id)
    view = compute_view(game2, round_id)

    # Winner detection is per-round: a player is out when their score in THIS round hits target
    active_players = [entry for entry in view["board"] if not entry["is_out"]]
    out_players = [entry for entry in view["board"] if entry["is_out"]]
    total_players = len(view["board"])

    flash_msg = None
    winner_name = None
    winner_score = None

    game_over = (len(active_players) == 1 and len(out_players) > 0) or \
                (len(active_players) == 0 and total_players > 1)
    if game_over:
        flash_msg = "🎉 Game Over! Winner is the last player standing!"
        winner_entry = view["board"][0]
        winner_name = winner_entry["player"]
        winner_score = winner_entry["total"]
        update_game(game_id, "SET winner_declared = :w", {":w": True})
        cumulative = compute_view(game2, None)
        _write_game_history(game2, cumulative["board"], round_id)

    return templates.TemplateResponse("partials/round_panel.html", {
        "request": request, "user": user, "game": game2, "selected_round_id": round_id, **view,
        "flash": flash_msg,
        "winner_name": winner_name,
        "winner_score": winner_score
    })


@app.post("/games/{game_id}/scores/batch", response_class=HTMLResponse)
async def add_scores_batch(request: Request, game_id: str):
    # Batch add scores for multiple players
    user, game = check_game_access(request, game_id)
    form_data = await request.form()
    
    round_id = form_data.get("round_id")
    if not round_id:
        raise HTTPException(400, "Missing round_id")
    
    if round_locked(game, round_id):
        raise HTTPException(409, "Round is locked")
    
    # Process all player scores
    added_count = 0
    i = 0
    while True:
        player_key = f"player_{i}"
        delta_key = f"delta_{i}"
        
        if player_key not in form_data:
            break
            
        player = form_data.get(player_key)
        delta_str = form_data.get(delta_key, "").strip()
        
        # Default to 0 if empty
        delta = int(delta_str) if delta_str else 0
        
        if player not in game.get("players", []):
            raise HTTPException(400, f"Unknown player: {player}")
        
        put_event({
            "game_id": game_id,
            "ts": now_ts(),
            "round_id": round_id,
            "player": player,
            "delta": delta,
            "undone": False
        })
        added_count += 1
        i += 1
    
    game2 = must_game(game_id)
    view = compute_view(game2, round_id)

    # Winner detection is per-round: a player is out when their score in THIS round hits target
    active_players = [entry for entry in view["board"] if not entry["is_out"]]
    out_players = [entry for entry in view["board"] if entry["is_out"]]
    total_players = len(view["board"])

    flash_msg = None
    winner_name = None
    winner_score = None

    game_over = (len(active_players) == 1 and len(out_players) > 0) or \
                (len(active_players) == 0 and total_players > 1)
    if game_over:
        flash_msg = "🎉 Game Over! Winner is the last player standing!"
        winner_entry = view["board"][0]
        winner_name = winner_entry["player"]
        winner_score = winner_entry["total"]
        update_game(game_id, "SET winner_declared = :w", {":w": True})
        cumulative = compute_view(game2, None)
        _write_game_history(game2, cumulative["board"], round_id)
    elif added_count > 0:
        flash_msg = f"✅ Added scores for {added_count} player(s)"
    
    return templates.TemplateResponse("partials/round_panel.html", {
        "request": request, "user": user, "game": game2, "selected_round_id": round_id, **view,
        "flash": flash_msg,
        "winner_name": winner_name,
        "winner_score": winner_score
    })
