import os
from pymongo import MongoClient
from pymongo.errors import OperationFailure
from dotenv import load_dotenv

load_dotenv()


class Database:
    def __init__(self):
        uri = os.getenv("MONGO_URI")
        if not uri:
            raise ValueError("MONGO_URI is not set in the environment / .env file")
        self.client = MongoClient(
            uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=10000,
        )
        # Trigger an actual connection check immediately
        self.client.admin.command("ping")
        db_name = os.getenv("MONGO_DB_NAME", "telegram_mail_bot")
        self.db = self.client[db_name]

        self.users = self.db["users"]
        self.emails = self.db["registered_emails"]
        self.admins = self.db["admins"]

        self._seed_admins()
        self._ensure_indexes()

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

    def _ensure_indexes(self):
        self.users.create_index("telegram_id", unique=True)
        self.users.create_index("last_seen")
        self.users.create_index("blocked")
        self.emails.create_index("email", unique=True)
        try:
            self.emails.create_index("created_at")
        except OperationFailure as e:
            # Ignore conflict if an older TTL index already exists on created_at
            if getattr(e, "code", None) != 85:
                raise
        self.admins.create_index("telegram_id", unique=True)
        self.db["code_requests"].create_index([("telegram_id", 1), ("requested_at", -1)])
        self.db["code_requests"].create_index([("telegram_id", 1), ("email", 1)])

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

    def get_user_language(self, telegram_id: int) -> str:
        user = self.users.find_one({"telegram_id": telegram_id})
        if user:
            return user.get("language", "es")
        return "es"

    def set_user_language(self, telegram_id: int, language: str):
        self.users.update_one(
            {"telegram_id": telegram_id},
            {"$set": {"language": language}},
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

    def get_registered_emails_subset(self, emails: list[str]) -> set[str]:
        if not emails:
            return set()
        rows = self.emails.find({"email": {"$in": [e.lower() for e in emails]}}, {"_id": 0, "email": 1})
        return {row["email"] for row in rows}

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

    def get_all_user_ids(self) -> list[int]:
        """Return telegram_ids of all non-blocked users."""
        return [
            u["telegram_id"]
            for u in self.users.find({"blocked": {"$ne": True}}, {"telegram_id": 1, "_id": 0})
        ]

    def assign_account(self, telegram_id: int, email: str):
        """Add email to user's assigned accounts list (no duplicates)."""
        self.users.update_one(
            {"telegram_id": telegram_id},
            {"$addToSet": {"assigned_accounts": email.lower()}},
            upsert=True,
        )

    def get_assigned_accounts(self, telegram_id: int) -> list[str]:
        """Return list of emails assigned to this user."""
        user = self.users.find_one({"telegram_id": telegram_id})
        if user:
            return user.get("assigned_accounts", [])
        return []

    def set_assigned_accounts(self, telegram_id: int, emails: list[str]):
        """Overwrite the assigned accounts list (used for cleanup)."""
        self.users.update_one(
            {"telegram_id": telegram_id},
            {"$set": {"assigned_accounts": emails}},
            upsert=True,
        )

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

    def get_user_email_requests_paginated(self, telegram_id: int, page: int, page_size: int) -> list[dict]:
        pipeline = [
            {"$match": {"telegram_id": telegram_id}},
            {"$group": {
                "_id": "$email",
                "count": {"$sum": 1},
                "last_requested": {"$max": "$requested_at"}
            }},
            {"$sort": {"count": -1, "last_requested": -1, "_id": 1}},
            {"$skip": page * page_size},
            {"$limit": page_size},
        ]
        return list(self.db["code_requests"].aggregate(pipeline))

    def count_user_requests(self, telegram_id: int) -> int:
        return self.db["code_requests"].count_documents({"telegram_id": telegram_id})

    def count_user_request_groups(self, telegram_id: int) -> int:
        pipeline = [
            {"$match": {"telegram_id": telegram_id}},
            {"$group": {"_id": "$email"}},
            {"$count": "total"},
        ]
        result = list(self.db["code_requests"].aggregate(pipeline))
        return result[0]["total"] if result else 0

    def get_user_rankings_paginated(self, page: int, page_size: int) -> list[dict]:
        pipeline = [
            {"$group": {
                "_id": {"telegram_id": "$telegram_id", "username": "$username"},
                "total": {"$sum": 1}
            }},
            {"$sort": {"total": -1, "_id.telegram_id": 1}},
            {"$skip": page * page_size},
            {"$limit": page_size},
        ]
        return list(self.db["code_requests"].aggregate(pipeline))

    def count_rankings(self) -> int:
        pipeline = [
            {"$group": {"_id": "$telegram_id"}},
            {"$count": "total"},
        ]
        result = list(self.db["code_requests"].aggregate(pipeline))
        return result[0]["total"] if result else 0

    def get_top_ranked_user(self):
        pipeline = [
            {"$group": {
                "_id": {"telegram_id": "$telegram_id", "username": "$username"},
                "total": {"$sum": 1}
            }},
            {"$sort": {"total": -1, "_id.telegram_id": 1}},
            {"$limit": 1},
        ]
        result = list(self.db["code_requests"].aggregate(pipeline))
        return result[0] if result else None
