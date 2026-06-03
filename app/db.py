import os
import boto3
from boto3.dynamodb.conditions import Key, Attr
from typing import Any, Dict, List, Optional

# AWS configuration
AWS_REGION = os.getenv("AWS_REGION", "me-central-1")
GAMES_TABLE = os.getenv("GAMES_TABLE", "iquit_games")
EVENTS_TABLE = os.getenv("EVENTS_TABLE", "iquit_events")
USERS_TABLE = os.getenv("USERS_TABLE", "iquit_users")
HISTORY_TABLE = os.getenv("HISTORY_TABLE", "iquit_history")

ddb = boto3.resource("dynamodb", region_name=AWS_REGION)
games = ddb.Table(GAMES_TABLE)
events = ddb.Table(EVENTS_TABLE)
users = ddb.Table(USERS_TABLE)
history_tbl = ddb.Table(HISTORY_TABLE)


def put_game(item: Dict[str, Any]) -> None:
    # Create new game
    games.put_item(Item=item)


def get_game(game_id: str) -> Optional[Dict[str, Any]]:
    # Get game by ID
    resp = games.get_item(Key={"game_id": game_id})
    return resp.get("Item")


def list_games(limit: int = 20) -> List[Dict[str, Any]]:
    # List recent games
    resp = games.scan(Limit=limit)
    items = resp.get("Items", [])
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return items


def update_game(game_id: str, update_expr: str, expr_vals: Dict[str, Any]) -> None:
    # Update game attributes
    games.update_item(
        Key={"game_id": game_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_vals,
    )


def list_events(game_id: str) -> List[Dict[str, Any]]:
    # Get all scoring events
    resp = events.query(
        KeyConditionExpression=Key("game_id").eq(game_id),
        ScanIndexForward=True,
    )
    return resp.get("Items", [])


def put_event(item: Dict[str, Any]) -> None:
    # Record scoring event
    events.put_item(Item=item)


def mark_event_undone(game_id: str, ts: str, undone: bool) -> None:
    # Mark event as undone
    events.update_item(
        Key={"game_id": game_id, "ts": ts},
        UpdateExpression="SET undone = :u",
        ExpressionAttributeValues={":u": undone},
    )


def create_user(user_id: str, username: str, password_hash: str, is_admin: bool = False, email: str = "", role: str = "scorer") -> None:
    # Create new user
    users.put_item(Item={
        "user_id": user_id,
        "username": username,
        "password_hash": password_hash,
        "is_admin": is_admin,
        "is_active": is_admin,  # Admins active by default, regular users inactive
        "email": email,
        "role": role,
        "stat_rounds_played": 0,
        "stat_rounds_won": 0,
        "stat_games_played": 0,
        "stat_games_won": 0,
        "stat_total_iquits": 0,
    })


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    # Get user by username
    resp = users.scan(
        FilterExpression="username = :u",
        ExpressionAttributeValues={":u": username}
    )
    items = resp.get("Items", [])
    return items[0] if items else None


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    # Get user by ID
    resp = users.get_item(Key={"user_id": user_id})
    return resp.get("Item")


def list_games_by_user(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    # List games created by user
    resp = games.scan(
        FilterExpression="user_id = :uid",
        ExpressionAttributeValues={":uid": user_id},
        Limit=limit
    )
    items = resp.get("Items", [])
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return items


def delete_game(game_id: str) -> None:
    # Delete game and all its events
    games.delete_item(Key={"game_id": game_id})
    # Delete all events for this game
    ev = list_events(game_id)
    for e in ev:
        events.delete_item(Key={"game_id": game_id, "ts": e["ts"]})


def update_user_password(user_id: str, new_password_hash: str) -> None:
    # Update user password
    users.update_item(
        Key={"user_id": user_id},
        UpdateExpression="SET password_hash = :ph",
        ExpressionAttributeValues={":ph": new_password_hash}
    )


def toggle_user_active(user_id: str, is_active: bool) -> None:
    # Toggle user active status
    users.update_item(
        Key={"user_id": user_id},
        UpdateExpression="SET is_active = :a",
        ExpressionAttributeValues={":a": is_active}
    )


def list_all_users() -> List[Dict[str, Any]]:
    # List all users (admin only)
    resp = users.scan()
    return resp.get("Items", [])


def delete_user(user_id: str) -> None:
    # Delete user (admin only)
    users.delete_item(Key={"user_id": user_id})


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    # Find user by email address
    resp = users.scan(
        FilterExpression=Attr("email").eq(email)
    )
    items = resp.get("Items", [])
    return items[0] if items else None


def search_users(query: str, exclude_ids: List[str] = None) -> List[Dict[str, Any]]:
    # Search all registered users by username (case-insensitive), regardless of active status
    exclude_ids = exclude_ids or []
    resp = users.scan()
    q = query.lower()
    results = [
        {"user_id": u["user_id"], "username": u["username"]}
        for u in resp.get("Items", [])
        if q in u.get("username", "").lower() and u["user_id"] not in exclude_ids
    ]
    return results[:10]


def save_game_history(record: Dict[str, Any]) -> None:
    # Write a game history record for a player
    history_tbl.put_item(Item=record)


def game_history_exists(user_id: str, game_id: str) -> bool:
    # Check if ANY history record exists for this user+game (idempotency — SK is now game_id#round_id)
    resp = history_tbl.query(
        KeyConditionExpression=Key("user_id").eq(user_id) & Key("game_id").begins_with(game_id + "#"),
        Limit=1
    )
    return len(resp.get("Items", [])) > 0


def get_user_history(user_id: str) -> List[Dict[str, Any]]:
    # Get all game history records for a user
    resp = history_tbl.query(
        KeyConditionExpression=Key("user_id").eq(user_id),
        ScanIndexForward=False
    )
    return resp.get("Items", [])


def update_user_stats(user_id: str, won: bool, iquit_count: int) -> None:
    # Increment aggregated stats for a user after a game
    users.update_item(
        Key={"user_id": user_id},
        UpdateExpression="ADD stat_games_played :one, stat_games_won :w, stat_total_iquits :iq",
        ExpressionAttributeValues={
            ":one": 1,
            ":w": 1 if won else 0,
            ":iq": iquit_count,
        }
    )


def update_round_stats(user_id: str, survived: bool) -> None:
    # Increment per-round stats for a user after each round ends
    users.update_item(
        Key={"user_id": user_id},
        UpdateExpression="ADD stat_rounds_played :one, stat_rounds_won :s",
        ExpressionAttributeValues={
            ":one": 1,
            ":s": 1 if survived else 0,
        }
    )
