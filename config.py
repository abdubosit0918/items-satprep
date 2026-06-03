import os

from dotenv import load_dotenv


load_dotenv()

RECHECK_CB = "recheck_sub"
MAIN_MENU_CB = "main_menu"
INVITE_CB = "get_invite_link"
MATERIALS_CB = "get_materials"
ADMIN_REFRESH_CB = "admin_refresh"

REQUIRED_REFERRALS = 3

SUBSCRIBED_STATUSES = {"member", "administrator", "creator"}


def _clean(value: str) -> str:
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        value = value[1:-1].strip()
    return value


def get_bot_token() -> str:
    token = _clean(os.getenv("BOT_TOKEN", ""))
    if not token:
        raise RuntimeError("BOT_TOKEN is not set in .env")
    return token


def get_channel_username() -> str:
    channel = _clean(os.getenv("CHANNEL_USERNAME", ""))
    if not channel:
        raise RuntimeError(
            "CHANNEL_USERNAME is not set in .env (use your public channel @username)."
        )
    if not channel.startswith("@"):
        channel = f"@{channel}"
    return channel


def get_channel_join_url(channel_username: str) -> str:
    invite_link = _clean(os.getenv("CHANNEL_INVITE_LINK", ""))
    if invite_link:
        return invite_link
    return f"https://t.me/{channel_username.lstrip('@')}"


def get_materials_channel_link() -> str:
    link = _clean(os.getenv("MATERIALS_CHANNEL_LINK", ""))
    if not link:
        raise RuntimeError("MATERIALS_CHANNEL_LINK is not set in .env")
    return link


def get_admin_ids() -> set[int]:
    raw = _clean(os.getenv("ADMIN_IDS", "7897407913"))
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    if not ids:
        raise RuntimeError("ADMIN_IDS is not set in .env")
    return ids


def get_db_path() -> str:
    return _clean(os.getenv("DB_PATH", "bot.db")) or "bot.db"
