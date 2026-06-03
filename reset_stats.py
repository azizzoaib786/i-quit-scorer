"""
Reset all user stats and game history to zero.
Run this once after the idempotency/round-stats fixes to clear dirty test data.

Usage:
    python3 reset_stats.py              # reset ALL users
    python3 reset_stats.py azizzoaib786 hatim-bookie   # reset specific usernames
"""
import sys
import os
import boto3

AWS_REGION = os.getenv("AWS_REGION", "eu-west-1")
USERS_TABLE = os.getenv("USERS_TABLE", "iquit_users")
HISTORY_TABLE = os.getenv("HISTORY_TABLE", "iquit_history")

ddb = boto3.resource("dynamodb", region_name=AWS_REGION)
users_tbl = ddb.Table(USERS_TABLE)
history_tbl = ddb.Table(HISTORY_TABLE)

STAT_FIELDS = ["stat_games_played", "stat_games_won", "stat_total_iquits",
               "stat_rounds_played", "stat_rounds_won"]


def reset_user_stats(user: dict):
    users_tbl.update_item(
        Key={"user_id": user["user_id"]},
        UpdateExpression="SET " + ", ".join(f"{f} = :z" for f in STAT_FIELDS),
        ExpressionAttributeValues={":z": 0},
    )
    print(f"  ✅ Reset stats for {user.get('username', user['user_id'])}")


def delete_user_history(user_id: str):
    # Query all history records for this user and delete them
    resp = history_tbl.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("user_id").eq(user_id)
    )
    items = resp.get("Items", [])
    for item in items:
        history_tbl.delete_item(Key={"user_id": item["user_id"], "game_id": item["game_id"]})
    if items:
        print(f"  🗑️  Deleted {len(items)} history record(s)")


def main():
    target_usernames = set(sys.argv[1:])

    resp = users_tbl.scan()
    all_users = resp.get("Items", [])

    filtered = (
        [u for u in all_users if u.get("username") in target_usernames]
        if target_usernames
        else all_users
    )

    if not filtered:
        print("No matching users found.")
        return

    print(f"Resetting stats for {len(filtered)} user(s)...\n")
    for user in filtered:
        reset_user_stats(user)
        delete_user_history(user["user_id"])

    print("\nDone. All stats reset to 0 and history cleared.")


if __name__ == "__main__":
    main()
