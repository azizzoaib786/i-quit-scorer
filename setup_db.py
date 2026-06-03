#!/usr/bin/env python3
"""
Setup script to create DynamoDB tables for I Quit Scoreboard
Run this once to initialize your database tables.
"""
import boto3
import os

AWS_REGION = os.getenv("AWS_REGION", "me-central-1")

ddb = boto3.client("dynamodb", region_name=AWS_REGION)

def create_users_table():
    """Create the users table"""
    try:
        ddb.create_table(
            TableName="iquit_users",
            KeySchema=[
                {"AttributeName": "user_id", "KeyType": "HASH"}
            ],
            AttributeDefinitions=[
                {"AttributeName": "user_id", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST"
        )
        print("Created iquit_users table")
        
        # Wait for table to be active
        print("Waiting for table to become active...")
        waiter = ddb.get_waiter('table_exists')
        waiter.wait(TableName="iquit_users")
        print("Table is ready")
        
    except ddb.exceptions.ResourceInUseException:
        print("iquit_users table already exists")

def create_history_table():
    """Create the game history table"""
    try:
        ddb.create_table(
            TableName="iquit_history",
            KeySchema=[
                {"AttributeName": "user_id", "KeyType": "HASH"},
                {"AttributeName": "game_id", "KeyType": "RANGE"}
            ],
            AttributeDefinitions=[
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "game_id", "AttributeType": "S"}
            ],
            BillingMode="PAY_PER_REQUEST"
        )
        print("Created iquit_history table")
        waiter = ddb.get_waiter('table_exists')
        waiter.wait(TableName="iquit_history")
        print("Table is ready")
    except ddb.exceptions.ResourceInUseException:
        print("iquit_history table already exists")


def create_admin_user():
    """Create initial admin user"""
    from app.auth import hash_password
    import uuid
    import time
    
    # Give table a moment to settle
    time.sleep(2)
    
    users_table = boto3.resource("dynamodb", region_name=AWS_REGION).Table("iquit_users")
    
    # Check if admin already exists
    resp = users_table.scan(
        FilterExpression="username = :u",
        ExpressionAttributeValues={":u": "admin"}
    )
    
    if resp.get("Items"):
        print("Admin user already exists")
        return
    
    # Create admin user with password "xxx"
    users_table.put_item(Item={
        "user_id": uuid.uuid4().hex,
        "username": "admin",
        "password_hash": hash_password("xxx"),
        "is_admin": True,
        "is_active": True
    })
    print("Created admin user (username: admin, password: xxx)")
    print("IMPORTANT: Change the admin password after first login!")

if __name__ == "__main__":
    print("Setting up I Quit Scoreboard database...")
    print()

    create_users_table()
    create_history_table()
    create_admin_user()
    
    print()
    print("Setup complete!")
    print()
    print("Next steps:")
    print("  1. Install dependencies: pip install -r requirements.txt")
    print("  2. Start server: uvicorn app.main:app --reload --host 0.0.0.0 --port 8001")
    print("  3. Login as admin (username: admin, password: xxx)")
    print("  4. Create your own user account and make it admin if needed")
