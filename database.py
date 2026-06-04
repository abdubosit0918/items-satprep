import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from config import get_db_path


def _now() -> str:
    return datetime.now(UTC).isoformat()


@contextmanager
def get_connection():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                joined_at TEXT NOT NULL,
                referred_by INTEGER,
                is_subscribed INTEGER NOT NULL DEFAULT 0,
                materials_access INTEGER NOT NULL DEFAULT 0,
                materials_granted_at TEXT
            );

            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                is_valid INTEGER NOT NULL DEFAULT 0,
                validated_at TEXT,
                FOREIGN KEY (referrer_id) REFERENCES users(user_id),
                FOREIGN KEY (referred_id) REFERENCES users(user_id)
            );

            CREATE INDEX IF NOT EXISTS idx_referrals_referrer
                ON referrals(referrer_id);
            CREATE INDEX IF NOT EXISTS idx_referrals_referred
                ON referrals(referred_id);
            """
        )


def upsert_user(
    user_id: int,
    *,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    referred_by: int | None = None,
    is_subscribed: bool | None = None,
) -> None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT user_id, referred_by FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()

        if row is None:
            conn.execute(
                """
                INSERT INTO users (
                    user_id, username, first_name, last_name,
                    joined_at, referred_by, is_subscribed
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    username,
                    first_name,
                    last_name,
                    _now(),
                    referred_by,
                    1 if is_subscribed else 0,
                ),
            )
            return

        updates = ["username = ?", "first_name = ?", "last_name = ?"]
        params: list[Any] = [username, first_name, last_name]

        if referred_by is not None and row["referred_by"] is None:
            updates.append("referred_by = ?")
            params.append(referred_by)

        if is_subscribed is not None:
            updates.append("is_subscribed = ?")
            params.append(1 if is_subscribed else 0)

        params.append(user_id)
        conn.execute(
            f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?",
            params,
        )


def get_user(user_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()


def set_subscription_status(user_id: int, is_subscribed: bool) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET is_subscribed = ? WHERE user_id = ?",
            (1 if is_subscribed else 0, user_id),
        )


def create_referral(referrer_id: int, referred_id: int) -> bool:
    if referrer_id == referred_id:
        return False

    with get_connection() as conn:
        referrer = conn.execute(
            "SELECT user_id FROM users WHERE user_id = ?",
            (referrer_id,),
        ).fetchone()
        if referrer is None:
            return False

        referred = conn.execute(
            "SELECT user_id, referred_by FROM users WHERE user_id = ?",
            (referred_id,),
        ).fetchone()

        if referred is None:
            return False

        if referred["referred_by"] is not None:
            return False

        existing = conn.execute(
            "SELECT id FROM referrals WHERE referred_id = ?",
            (referred_id,),
        ).fetchone()
        if existing:
            return False

        conn.execute(
            "UPDATE users SET referred_by = ? WHERE user_id = ? AND referred_by IS NULL",
            (referrer_id, referred_id),
        )
        conn.execute(
            """
            INSERT INTO referrals (referrer_id, referred_id, created_at, is_valid)
            VALUES (?, ?, ?, 0)
            """,
            (referrer_id, referred_id, _now()),
        )
        return True


def set_referral_validity(referred_id: int, is_valid: bool) -> tuple[int | None, bool]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, referrer_id, is_valid
            FROM referrals
            WHERE referred_id = ?
            """,
            (referred_id,),
        ).fetchone()
        if not row:
            return None, False

        # Never downgrade a referral that is already valid.
        # Once earned, it stays earned regardless of future subscription checks.
        if row["is_valid"] == 1:
            return row["referrer_id"], False

        # Only upgrade: invalid -> valid
        if not is_valid:
            return row["referrer_id"], False

        conn.execute(
            """
            UPDATE referrals
            SET is_valid = 1, validated_at = ?
            WHERE referred_id = ?
            """,
            (_now(), referred_id),
        )
        return row["referrer_id"], True


def count_valid_referrals(referrer_id: int) -> int:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM referrals
            WHERE referrer_id = ? AND is_valid = 1
            """,
            (referrer_id,),
        ).fetchone()
        return int(row["cnt"])


def grant_materials_access(user_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT materials_access FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return False
        if row["materials_access"]:
            return False

        conn.execute(
            """
            UPDATE users
            SET materials_access = 1, materials_granted_at = ?
            WHERE user_id = ?
            """,
            (_now(), user_id),
        )
        return True


def has_materials_access(user_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT materials_access FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return bool(row and row["materials_access"])


def get_admin_stats() -> dict[str, Any]:
    with get_connection() as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        subscribed_users = conn.execute(
            "SELECT COUNT(*) FROM users WHERE is_subscribed = 1"
        ).fetchone()[0]
        materials_unlocked = conn.execute(
            "SELECT COUNT(*) FROM users WHERE materials_access = 1"
        ).fetchone()[0]
        total_referrals = conn.execute("SELECT COUNT(*) FROM referrals").fetchone()[0]
        valid_referrals = conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE is_valid = 1"
        ).fetchone()[0]
        pending_referrals = total_referrals - valid_referrals
        active_referrers = conn.execute(
            """
            SELECT COUNT(DISTINCT referrer_id)
            FROM referrals
            WHERE is_valid = 1
            """
        ).fetchone()[0]
        users_ready = conn.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT referrer_id
                FROM referrals
                WHERE is_valid = 1
                GROUP BY referrer_id
                HAVING COUNT(*) >= 3
            )
            """
        ).fetchone()[0]

        top_referrers = conn.execute(
            """
            SELECT u.user_id, u.username, u.first_name, COUNT(r.id) AS valid_count
            FROM referrals r
            JOIN users u ON u.user_id = r.referrer_id
            WHERE r.is_valid = 1
            GROUP BY r.referrer_id
            ORDER BY valid_count DESC, u.user_id ASC
            LIMIT 5
            """
        ).fetchall()

        return {
            "total_users": total_users,
            "subscribed_users": subscribed_users,
            "materials_unlocked": materials_unlocked,
            "total_referrals": total_referrals,
            "valid_referrals": valid_referrals,
            "pending_referrals": pending_referrals,
            "active_referrers": active_referrers,
            "users_ready_for_materials": users_ready,
            "top_referrers": top_referrers,
        }
