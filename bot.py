import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    ChatMemberRestricted,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
    User,
)
from aiogram.utils.deep_linking import create_start_link
from aiogram.filters.command import CommandObject
import database as db
from config import (
    ADMIN_REFRESH_CB,
    INVITE_CB,
    MAIN_MENU_CB,
    MATERIALS_CB,
    RECHECK_CB,
    REQUIRED_REFERRALS,
    get_admin_ids,
    get_bot_token,
    get_channel_join_url,
    get_channel_username,
    get_materials_channel_link,
)


logger = logging.getLogger(__name__)

CHANNEL_USERNAME = get_channel_username()
_raw_join_url = get_channel_join_url(CHANNEL_USERNAME)
if _raw_join_url.startswith("http"):
    CHANNEL_JOIN_URL = _raw_join_url
else:
    CHANNEL_JOIN_URL = "https://t.me/" + _raw_join_url.lstrip("@").lstrip("/")
MATERIALS_CHANNEL_LINK = get_materials_channel_link()
ADMIN_IDS = get_admin_ids()

dp = Dispatcher()

SUBSCRIBED_STATUSES = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.CREATOR,
}


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def parse_referrer_id(start_args: str | None) -> int | None:
    if not start_args:
        return None
    payload = start_args.strip()
    if payload.startswith("ref_") and payload[4:].isdigit():
        return int(payload[4:])
    if payload.startswith("ref") and payload[3:].isdigit():
        return int(payload[3:])
    return None


def is_start_command(text: str | None) -> bool:
    if not text:
        return False
    return text.split()[0].split("@")[0] == "/start"


async def is_subscribed(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
    except Exception:
        logger.exception("Failed to check subscription for user %s", user_id)
        return False

    if member.status in SUBSCRIBED_STATUSES:
        return True

    if member.status == ChatMemberStatus.RESTRICTED:
        return isinstance(member, ChatMemberRestricted) and member.is_member

    return False


def subscribe_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Join channel", url=CHANNEL_JOIN_URL)],
            [InlineKeyboardButton(text="✅ Done", callback_data=RECHECK_CB)],
        ]
    )


def main_menu_keyboard(*, has_materials_access: bool) -> InlineKeyboardMarkup:
    if has_materials_access:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📚 Open materials",
                        url=MATERIALS_CHANNEL_LINK,
                    )
                ],
            ]
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📎 My invite link", callback_data=INVITE_CB)],
            [InlineKeyboardButton(text="📚 Get materials", callback_data=MATERIALS_CB)],
        ]
    )


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Refresh stats", callback_data=ADMIN_REFRESH_CB)],
        ]
    )


def welcome_text(*, valid_referrals: int, has_materials_access: bool) -> str:
    if has_materials_access:
        return (
            "🎉 <b>Done!</b>\n\n"
            "You unlocked <b>25 IELTS Reading passages</b>\n"
            "and a <b>bonus 30‑day 7+ study plan</b>.\n"
            "Tap the button below to join."
        )

    remaining = max(REQUIRED_REFERRALS - valid_referrals, 0)
    return (
        "👋 <b>IELTS/SAT Prep Bot</b>\n\n"
        "Invite <b>3 friends</b> and get <b>25 IELTS Reading passages</b>\n"
        "+ a <b>bonus 30‑day 7+ study plan</b>.\n\n"
        f"Your progress: <b>{valid_referrals}/{REQUIRED_REFERRALS}</b>\n"
        f"Need <b>{remaining}</b> more friend(s)\n\n"
        "Each friend must:\n"
        "1. Open your invite link\n"
        f"2. Subscribe to {CHANNEL_USERNAME}"
    )


def invite_text(link: str, *, valid_referrals: int) -> str:
    return (
        "<b>Your invite link</b>\n\n"
        f"<code>{link}</code>\n\n"
        "Send it to your friends.\n"
        "When they join and subscribe, your progress updates.\n\n"
        f"Progress: <b>{valid_referrals}/{REQUIRED_REFERRALS}</b>"
    )


def materials_locked_text(*, valid_referrals: int) -> str:
    remaining = max(REQUIRED_REFERRALS - valid_referrals, 0)
    return (
        "🔒 <b>Materials locked</b>\n\n"
        f"Progress: <b>{valid_referrals}/{REQUIRED_REFERRALS}</b>\n"
        f"Invite <b>{remaining}</b> more friend(s) to unlock."
    )


def materials_unlocked_text() -> str:
    return (
        "🎉 <b>Materials unlocked!</b>\n\n"
        "You got:\n"
        "• <b>25 IELTS Reading materials</b>\n"
        "• <b>Bonus 30‑day 7+ study plan</b>\n\n"
        "Tap the button below to join the private channel."
    )


def new_invite_text(*, valid_referrals: int) -> str:
    remaining = max(REQUIRED_REFERRALS - valid_referrals, 0)
    if remaining == 0:
        return (
            "✅ <b>+1 friend!</b>\n\n"
            f"Progress: <b>{valid_referrals}/{REQUIRED_REFERRALS}</b>\n"
            "You unlocked the materials!"
        )
    return (
        "✅ <b>+1 friend!</b>\n\n"
        f"Progress: <b>{valid_referrals}/{REQUIRED_REFERRALS}</b>\n"
        f"Invite <b>{remaining}</b> more to unlock materials."
    )


def subscribe_prompt_text() -> str:
    return (
        "👋 <b>Welcome!</b>\n\n"
        "First, subscribe to our channel.\n"
        "Then tap <b>Done</b>."
    )


def format_admin_stats(stats: dict[str, Any]) -> str:
    lines = [
        "<b>📊 Admin panel</b>",
        "",
        f"👥 Total bot users: <b>{stats['total_users']}</b>",
        f"✅ Subscribed users: <b>{stats['subscribed_users']}</b>",
        f"📚 Materials unlocked: <b>{stats['materials_unlocked']}</b>",
        "",
        f"🔗 Total referrals: <b>{stats['total_referrals']}</b>",
        f"✅ Valid referrals: <b>{stats['valid_referrals']}</b>",
        f"⏳ Pending referrals: <b>{stats['pending_referrals']}</b>",
        f"🚀 Active referrers: <b>{stats['active_referrers']}</b>",
        f"🏁 Users with 3+ valid invites: <b>{stats['users_ready_for_materials']}</b>",
    ]

    top = stats["top_referrers"]
    if top:
        lines.extend(["", "<b>Top referrers</b>"])
        for index, row in enumerate(top, start=1):
            label = row["username"] or row["first_name"] or str(row["user_id"])
            lines.append(f"{index}. @{label.lstrip('@')} — {row['valid_count']} valid")
    else:
        lines.extend(["", "No valid referrals yet."])

    return "\n".join(lines)


async def referral_link(bot: Bot, user_id: int) -> str:
    return await create_start_link(bot, payload=f"ref_{user_id}")


async def register_user(user: User, *, referrer_id: int | None = None) -> None:
    db.upsert_user(
        user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        referred_by=referrer_id,
    )


async def sync_referral_for_user(bot: Bot, user_id: int) -> tuple[int | None, bool]:
    subscribed = await is_subscribed(bot, user_id)
    db.set_subscription_status(user_id, subscribed)
    return db.set_referral_validity(user_id, subscribed)


async def notify_referrer_new_invite(bot: Bot, referrer_id: int) -> None:
    valid_count = db.count_valid_referrals(referrer_id)
    try:
        await bot.send_message(referrer_id, new_invite_text(valid_referrals=valid_count))
    except Exception:
        logger.exception("Failed to notify referrer %s about new invite", referrer_id)


async def maybe_unlock_materials(
    bot: Bot,
    user_id: int,
    *,
    notify: bool = True,
) -> bool:
    if db.has_materials_access(user_id):
        return True

    valid_count = db.count_valid_referrals(user_id)
    if valid_count < REQUIRED_REFERRALS:
        return False

    if not db.grant_materials_access(user_id):
        return db.has_materials_access(user_id)

    if notify:
        try:
            await bot.send_message(
                user_id,
                materials_unlocked_text(),
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="📚 Open materials",
                                url=MATERIALS_CHANNEL_LINK,
                            )
                        ]
                    ]
                ),
            )
        except Exception:
            logger.exception("Failed to notify user %s about unlocked materials", user_id)

    return True


async def process_new_referral(referrer_id: int, referred_user: User) -> None:
    if referrer_id == referred_user.id:
        return

    await register_user(referred_user)
    created = db.create_referral(referrer_id, referred_user.id)
    if created:
        logger.info("Referral created: %s -> %s", referrer_id, referred_user.id)


async def refresh_user_state(
    bot: Bot,
    user: User,
    *,
    notify_unlock: bool = True,
) -> tuple[int, bool]:
    subscribed = await is_subscribed(bot, user.id)
    db.upsert_user(
        user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        is_subscribed=subscribed,
    )

    referrer_id, newly_validated = await sync_referral_for_user(bot, user.id)
    if referrer_id is not None and newly_validated:
        await notify_referrer_new_invite(bot, referrer_id)
        await maybe_unlock_materials(bot, referrer_id, notify=notify_unlock)

    unlocked = await maybe_unlock_materials(bot, user.id, notify=notify_unlock)
    valid_count = db.count_valid_referrals(user.id)
    return valid_count, unlocked or db.has_materials_access(user.id)


async def send_main_menu(
    bot: Bot,
    chat_id: int,
    user: User,
    *,
    edit_message: Message | None = None,
) -> None:
    valid_count, has_access = await refresh_user_state(bot, user, notify_unlock=True)
    text = welcome_text(valid_referrals=valid_count, has_materials_access=has_access)
    keyboard = main_menu_keyboard(has_materials_access=has_access)

    if edit_message:
        try:
            await edit_message.edit_text(text, reply_markup=keyboard)
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise
    else:
        await bot.send_message(chat_id, text, reply_markup=keyboard)


class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        bot: Bot = data["bot"]
        user: User | None = None

        if isinstance(event, CallbackQuery):
            user = event.from_user
            if event.data == RECHECK_CB:
                return await handler(event, data)
        elif isinstance(event, Message):
            user = event.from_user
            if user and is_admin(user.id) and event.text and event.text.startswith("/admin"):
                return await handler(event, data)

        if user and is_admin(user.id):
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            if not event.from_user:
                return None
            if await is_subscribed(bot, event.from_user.id):
                return await handler(event, data)
            await event.answer("Subscribe to the channel first.", show_alert=True)
            return None

        if isinstance(event, Message):
            if not event.from_user:
                return None

            # Always let /start through so the referral payload is captured
            # and the handler can show the subscribe prompt itself.
            if is_start_command(event.text):
                return await handler(event, data)

            if await is_subscribed(bot, event.from_user.id):
                return await handler(event, data)

            await bot.send_message(
                chat_id=event.chat.id,
                text=subscribe_prompt_text(),
                reply_markup=subscribe_keyboard(),
            )
            return None

        return await handler(event, data)


dp.message.middleware(SubscriptionMiddleware())
dp.callback_query.middleware(SubscriptionMiddleware())


@dp.message(CommandStart())
async def start_handler(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return

    # Register user and capture referral payload first
    referrer_id = parse_referrer_id(command.args)
    await register_user(message.from_user)
    if referrer_id and referrer_id != message.from_user.id:
        await process_new_referral(referrer_id, message.from_user)

    # If not subscribed yet, show the subscribe prompt and stop
    if not await is_subscribed(message.bot, message.from_user.id):
        await message.answer(
            subscribe_prompt_text(),
            reply_markup=subscribe_keyboard(),
        )
        return

    await send_main_menu(message.bot, message.chat.id, message.from_user)


@dp.callback_query(F.data == RECHECK_CB)
async def recheck_subscription(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return

    if not await is_subscribed(callback.bot, callback.from_user.id):
        await callback.answer("Not subscribed yet.", show_alert=True)
        return

    await callback.answer("Done!", show_alert=False)

    referrer_id, newly_validated = await sync_referral_for_user(
        callback.bot,
        callback.from_user.id,
    )
    if referrer_id is not None and newly_validated:
        await notify_referrer_new_invite(callback.bot, referrer_id)
        await maybe_unlock_materials(callback.bot, referrer_id, notify=True)

    await send_main_menu(
        callback.bot,
        callback.message.chat.id,
        callback.from_user,
        edit_message=callback.message,
    )


@dp.callback_query(F.data == MAIN_MENU_CB)
async def main_menu_handler(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return

    valid_count, has_access = await refresh_user_state(
        callback.bot,
        callback.from_user,
        notify_unlock=True,
    )
    try:
        await callback.message.edit_text(
            welcome_text(valid_referrals=valid_count, has_materials_access=has_access),
            reply_markup=main_menu_keyboard(has_materials_access=has_access),
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await callback.answer()


@dp.callback_query(F.data == INVITE_CB)
async def invite_handler(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return

    link = await referral_link(callback.bot, callback.from_user.id)
    valid_count, has_access = await refresh_user_state(
        callback.bot,
        callback.from_user,
        notify_unlock=False,
    )
    keyboard = main_menu_keyboard(has_materials_access=has_access)
    if not has_access:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                *keyboard.inline_keyboard,
                [InlineKeyboardButton(text="◀️ Back", callback_data=MAIN_MENU_CB)],
            ]
        )
    try:
        await callback.message.edit_text(
            invite_text(link, valid_referrals=valid_count),
            reply_markup=keyboard,
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await callback.answer()


@dp.callback_query(F.data == MATERIALS_CB)
async def materials_handler(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return

    valid_count, has_access = await refresh_user_state(
        callback.bot,
        callback.from_user,
        notify_unlock=True,
    )

    if has_access:
        text = materials_unlocked_text()
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📚 Open materials",
                        url=MATERIALS_CHANNEL_LINK,
                    )
                ],
                [InlineKeyboardButton(text="◀️ Back", callback_data=MAIN_MENU_CB)],
            ]
        )
    else:
        text = materials_locked_text(valid_referrals=valid_count)
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📎 My invite link", callback_data=INVITE_CB)],
                [InlineKeyboardButton(text="◀️ Back", callback_data=MAIN_MENU_CB)],
            ]
        )

    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await callback.answer()


@dp.message(Command("admin"))
async def admin_handler(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return

    stats = db.get_admin_stats()
    await message.answer(format_admin_stats(stats), reply_markup=admin_keyboard())


@dp.callback_query(F.data == ADMIN_REFRESH_CB)
async def admin_refresh_handler(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("Access denied.", show_alert=True)
        return

    if not callback.message:
        return

    stats = db.get_admin_stats()
    try:
        await callback.message.edit_text(
            format_admin_stats(stats), reply_markup=admin_keyboard()
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await callback.answer("Stats updated.")


async def validate_channel(bot: Bot) -> None:
    me = await bot.get_me()
    if CHANNEL_USERNAME.lstrip("@") == me.username:
        raise RuntimeError(
            f"CHANNEL_USERNAME ({CHANNEL_USERNAME}) matches the bot username (@{me.username})."
        )

    chat = await bot.get_chat(CHANNEL_USERNAME)
    if chat.type != ChatType.CHANNEL:
        raise RuntimeError(f"{CHANNEL_USERNAME} is not a channel.")

    logger.info("Public channel: %s", CHANNEL_USERNAME)
    logger.info("Admin IDs: %s", ", ".join(str(x) for x in sorted(ADMIN_IDS)))


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    db.init_db()

    bot = Bot(
        token=get_bot_token(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await bot.delete_webhook(drop_pending_updates=False)
    try:
        await validate_channel(bot)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
