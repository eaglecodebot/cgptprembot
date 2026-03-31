import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()


class Database:
    def __init__(self):
        uri = os.getenv("MONGO_URI")
        self.client = MongoClient(uri)
        db_name = os.getenv("MONGO_DB_NAME", "telegram_mail_bot")
        self.db = self.client[db_name]

        self.users = self.db["users"]
        self.emails = self.db["registered_emails"]
        self.admins = self.db["admins"]

        self._seed_admins()

    # ─────────────────────────────────────────────
    # Seed admins from env
    # ─────────────────────────────────────────────

    def _seed_admins(self):
        raw = os.getenv("ADMIN_IDS", "")
        new_ids = []
        for id_str in raw.split(","):
            id_str = id_str.strip()
            if id_str.isdigit():
                new_ids.append(int(id_str))

        self.admins.delete_many({"telegram_id": {"$nin": new_ids}})

        for tid in new_ids:
            self.admins.update_one(
                {"telegram_id": tid},
                {"$setOnInsert": {"telegram_id": tid}},
                upsert=True,
            )

    # ─────────────────────────────────────────────
    # Admin helpers
    # ─────────────────────────────────────────────

    def is_admin(self, telegram_id: int) -> bool:
        return self.admins.find_one({"telegram_id": telegram_id}) is not None

    # ─────────────────────────────────────────────
    # User helpers
    # ─────────────────────────────────────────────

    def register_user(self, telegram_id: int, username: str):
        from datetime import datetime
        self.users.update_one(
            {"telegram_id": telegram_id},
            {
                "$setOnInsert": {
                    "telegram_id": telegram_id,
                    "username": username,
                    "blocked": False,
                },
                "$set": {"last_seen": datetime.utcnow()}
            },
            upsert=True,
        )

    def list_users(self) -> list[dict]:
        return list(self.users.find({}, {"_id": 0}))

    def is_user_blocked(self, telegram_id: int) -> bool:
        user = self.users.find_one({"telegram_id": telegram_id})
        if user is None:
            return False
        return user.get("blocked", False)

    def set_user_blocked(self, telegram_id: int, blocked: bool):
        self.users.update_one(
            {"telegram_id": telegram_id},
            {"$set": {"blocked": blocked}},
            upsert=True,
        )

    # ─────────────────────────────────────────────
    # Email registry helpers
    # ─────────────────────────────────────────────

    def is_email_registered(self, email: str) -> bool:
        return self.emails.find_one({"email": email.lower()}) is not None

    def add_email(self, email: str, added_by: int):
        from datetime import datetime
        self.emails.update_one(
            {"email": email.lower()},
            {"$setOnInsert": {
                "email": email.lower(),
                "added_by": added_by,
                "created_at": datetime.utcnow()
            }},
            upsert=True,
        )

    def get_email_credentials(self, email: str):
        return self.emails.find_one({"email": email.lower()}, {"_id": 0})

    def remove_email(self, email: str):
        self.emails.delete_one({"email": email.lower()})

    def list_emails(self) -> list[dict]:
        return list(self.emails.find({}, {"_id": 0, "imap_pass": 0}))

    def list_emails_paginated(self, page: int, page_size: int) -> list[dict]:
        return list(
            self.emails.find({}, {"_id": 0, "imap_pass": 0})
            .sort("created_at", -1)
            .skip(page * page_size)
            .limit(page_size)
        )

    def count_emails(self) -> int:
        return self.emails.count_documents({})

    def list_users_paginated(self, page: int, page_size: int) -> list[dict]:
        return list(
            self.users.find({}, {"_id": 0})
            .sort("_id", -1)
            .limit(page_size)
            .skip(page * page_size)
        )

    def count_users(self) -> int:
        return self.users.count_documents({})

    def count_active_users(self) -> int:
        from datetime import datetime, timedelta
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        return self.users.count_documents({"last_seen": {"$gte": thirty_days_ago}})

    # ─────────────────────────────────────────────
    # Code request logging
    # ─────────────────────────────────────────────

    def log_code_request(self, telegram_id: int, username: str, email: str):
        from datetime import datetime
        self.db["code_requests"].insert_one({
            "telegram_id": telegram_id,
            "username": username,
            "email": email,
            "requested_at": datetime.utcnow()
        })

    def get_user_email_requests(self, telegram_id: int) -> list[dict]:
        pipeline = [
            {"$match": {"telegram_id": telegram_id}},
            {"$group": {
                "_id": "$email",
                "count": {"$sum": 1},
                "last_requested": {"$max": "$requested_at"}
            }},
            {"$sort": {"count": -1}}
        ]
        return list(self.db["code_requests"].aggregate(pipeline))

    def count_user_requests(self, telegram_id: int) -> int:
        return self.db["code_requests"].count_documents({"telegram_id": telegram_id})

    def get_user_rankings(self) -> list[dict]:
        pipeline = [
            {"$group": {
                "_id": {"telegram_id": "$telegram_id", "username": "$username"},
                "total": {"$sum": 1}
            }},
            {"$sort": {"total": -1}}
        ]
        return list(self.db["code_requests"].aggregate(pipeline))
