"""Main entry point for Santa Eshkere bot"""

import asyncio
import hashlib
import logging
import sys

from telegram import (
    Bot,
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    Defaults,
    MessageHandler,
    filters,
)
from telegram.request import BaseRequest

from .config import config
from .database.session import close_db, init_db
from .handlers import admin, group, user
from .messages import Messages
from .services import deadlines, join_post
from .web import WEBHOOK_PATH, serve_webhook

logger = logging.getLogger(__name__)

ALLOWED_UPDATES = [Update.MESSAGE, Update.CALLBACK_QUERY]


def configure_logging() -> None:
    """Configure stdout logging.

    httpx logs every request URL at INFO, and Bot API URLs embed the bot token
    (https://api.telegram.org/bot<TOKEN>/method), so it must stay at WARNING.
    """
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def webhook_secret(token: str, override: str = "") -> str:
    """Secret Telegram must echo in X-Telegram-Bot-Api-Secret-Token.

    Derived from the bot token unless explicitly overridden, so it rotates
    together with the token and needs no extra configuration.
    """
    if override:
        return override
    return hashlib.sha256(f"webhook:{token}".encode()).hexdigest()


async def post_init(application: Application) -> None:
    """Initialize database after application is created"""
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized")
    logger.info(f"Bot username: @{(await application.bot.get_me()).username}")
    await set_command_menus(application.bot)
    # how each group looks to Telegram, and join posts brought up to date
    application.bot_data["group_check"] = asyncio.create_task(join_post.check_groups(application.bot))
    # passed joining deadlines: close the join post, tell the admin
    application.bot_data["deadline_checks"] = asyncio.create_task(
        deadlines.run_checks(application.bot, config.DEADLINE_CHECK_SECONDS)
    )


# What Telegram shows when someone types "/" (per chat type). Participants
# only see what they need; admin DM commands stay in /adminhelp.
COMMAND_MENUS: dict[str, list[tuple[str, str]]] = {
    "private": [
        ("status", "Мой статус и задание"),
        ("wishlist", "Изменить вишлист"),
        ("leave", "Выйти из игры"),
        ("cancel", "Отменить текущее действие"),
        ("adminhelp", "Команды для админов групп"),
    ],
    "groups": [
        ("join", "Участвовать в Тайном Санте"),
    ],
    "group_admins": [
        ("join", "Участвовать в Тайном Санте"),
        ("start", "Включить бота и показать кнопку участия"),
        ("kickitoff", "Запустить распределение"),
        ("deadline", "Дедлайн регистрации: /deadline 30.11 18:00"),
        ("newseason", "Закрыть сезон и открыть новый"),
    ],
}


async def set_command_menus(bot: Bot) -> None:
    scopes = {
        "private": BotCommandScopeAllPrivateChats(),
        "groups": BotCommandScopeAllGroupChats(),
        "group_admins": BotCommandScopeAllChatAdministrators(),
    }
    for name, commands in COMMAND_MENUS.items():
        try:
            await bot.set_my_commands([BotCommand(c, d) for c, d in commands], scope=scopes[name])
        except TelegramError as e:  # cosmetic: never block startup on it
            logger.warning("Setting the %s command menu failed: %s", name, e.__class__.__name__)


async def post_shutdown(application: Application) -> None:
    """Cleanup on shutdown"""
    for name in ("deadline_checks", "group_check"):
        task = application.bot_data.pop(name, None)
        if task is not None:
            task.cancel()
    logger.info("Closing database connections...")
    await close_db()
    logger.info("Shutdown complete")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors without leaking message contents (wishlists, names)"""
    details = []
    update_id = getattr(update, "update_id", None)
    if update_id is not None:
        details.append(f"update_id={update_id}")
    chat = getattr(update, "effective_chat", None)
    if chat is not None:
        details.append(f"chat_id={chat.id}")
    user_obj = getattr(update, "effective_user", None)
    if user_obj is not None:
        details.append(f"user_id={user_obj.id}")
    logger.error("Exception while handling an update (%s)", ", ".join(details) or "no update", exc_info=context.error)

    # Never leave a person in a DM without an answer
    if chat is not None and getattr(chat, "type", None) == "private":
        try:
            await context.bot.send_message(chat_id=chat.id, text=Messages.ERROR_SYSTEM)
        except TelegramError:
            pass


def register_handlers(application: Application) -> None:
    """Attach all handlers. Commands are split by chat type so each handler
    only ever sees the context it was written for."""
    private = filters.ChatType.PRIVATE
    groups = filters.ChatType.GROUPS

    # Group chat
    application.add_handler(CommandHandler("start", group.start_command, filters=groups))
    application.add_handler(CommandHandler("join", group.join_command, filters=groups))
    application.add_handler(CommandHandler("join", user.join_dm, filters=private))
    application.add_handler(CommandHandler("kickitoff", group.kickitoff_command))
    application.add_handler(CommandHandler("newseason", group.newseason_command))
    application.add_handler(CommandHandler("deadline", group.deadline_command))
    application.add_handler(MessageHandler(filters.StatusUpdate.MIGRATE, group.chat_migrated))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, group.bot_added))

    # Participant DM
    application.add_handler(CommandHandler("start", user.start_dm, filters=private))
    application.add_handler(CommandHandler("status", user.status_command))
    application.add_handler(CommandHandler("wishlist", user.wishlist_command))
    application.add_handler(CommandHandler("cancel", user.cancel_command))
    application.add_handler(CommandHandler("leave", user.leave_command))

    # Admin DM
    application.add_handler(CommandHandler("listgroups", admin.listgroups_command))
    application.add_handler(CommandHandler("selectgroup", admin.selectgroup_command))
    application.add_handler(CommandHandler("disband", admin.disband_command))
    application.add_handler(CommandHandler("addrule", admin.addrule_command))
    application.add_handler(CommandHandler("listrules", admin.listrules_command))
    application.add_handler(CommandHandler("removerule", admin.removerule_command))
    application.add_handler(CommandHandler("listjoined", admin.listjoined_command))
    application.add_handler(CommandHandler("removeparticipant", admin.removeparticipant_command))
    application.add_handler(CommandHandler("adminhelp", admin.adminhelp_command))
    application.add_handler(CommandHandler("reset", admin.reset_command))
    application.add_handler(CommandHandler("dryrunassignments", admin.dryrun_command))

    # All inline buttons
    application.add_handler(CallbackQueryHandler(admin.callback_router))

    # Free text / other messages in DM feed the pending flow
    application.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, user.dm_text))
    application.add_handler(
        MessageHandler(private & ~filters.TEXT & ~filters.COMMAND & ~filters.StatusUpdate.ALL, user.dm_non_text)
    )

    application.add_error_handler(error_handler)


def build_application(
    token: str,
    *,
    request: BaseRequest | None = None,
    base_url: str = "",
    with_lifecycle_hooks: bool = True,
) -> Application:
    """Build the bot Application.

    All conversation state lives in the database, so no PTB persistence is
    used (Railway's filesystem is wiped on every deploy anyway). Tests pass a
    fake `request` (in-process Bot API) and manage the database themselves.
    """
    builder = Application.builder().token(token).defaults(Defaults(parse_mode=ParseMode.HTML))
    if request is not None:
        builder = builder.request(request).get_updates_request(request)
    if base_url:
        builder = builder.base_url(base_url)
    if with_lifecycle_hooks:
        builder = builder.post_init(post_init).post_shutdown(post_shutdown)

    application = builder.build()
    register_handlers(application)
    return application


def main() -> None:
    """Start the bot"""
    configure_logging()

    try:
        config.validate()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    application = build_application(config.TELEGRAM_BOT_TOKEN, base_url=config.TELEGRAM_API_BASE_URL)
    if config.TELEGRAM_API_BASE_URL:
        logger.warning("Using a non-Telegram Bot API server (tests only)")

    if config.USE_WEBHOOK:
        logger.info("Starting bot in webhook mode...")
        logger.info(f"Webhook URL: {config.WEBHOOK_URL}{WEBHOOK_PATH}")
        try:
            asyncio.run(
                serve_webhook(
                    application,
                    port=config.PORT,
                    webhook_url=f"{config.WEBHOOK_URL}{WEBHOOK_PATH}",
                    secret=webhook_secret(config.TELEGRAM_BOT_TOKEN, config.WEBHOOK_SECRET),
                    allowed_updates=ALLOWED_UPDATES,
                )
            )
        except Exception as e:
            logger.error(f"Webhook failed to start: {e.__class__.__name__}", exc_info=True)
            raise
    else:
        logger.info("Starting bot in polling mode...")
        application.run_polling(allowed_updates=ALLOWED_UPDATES)


if __name__ == "__main__":
    main()
