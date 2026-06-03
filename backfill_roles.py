#!/usr/bin/env python3
"""
One-off script to backfill 'role' = 'scorer' for all users missing a role.
Safe to run multiple times — only updates users where role is not set.
"""
import boto3
import os

AWS_REGION = os.getenv("AWS_REGION", "eu-west-1")
USERS_TABLE = os.getenv("USERS_TABLE", "iquit_users")

ddb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = ddb.Table(USERS_TABLE)

def backfill_roles():
    resp = table.scan()
    users = resp.get("Items", [])
    updated = 0
    skipped = 0
    for u in users:
        if "role" not in u:
            table.update_item(
                Key={"user_id": u["user_id"]},
                UpdateExpression="SET #r = :r",
                ExpressionAttributeNames={"#r": "role"},
                ExpressionAttributeValues={":r": "scorer"},
            )
            print(f"  ✅ Set role=scorer for: {u['username']}")
            updated += 1
        else:
            print(f"  — Skipped (already has role={u['role']}): {u['username']}")
            skipped += 1

    print(f"\nDone. Updated: {updated}, Skipped: {skipped}")

if __name__ == "__main__":
    print(f"Backfilling scorer role for users in '{USERS_TABLE}' ({AWS_REGION})...\n")
    backfill_roles()
