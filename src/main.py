"""Main entry point for Santa Eshkere bot"""

import hashlib
import logging
import sys

from telegram import Update
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


async def post_shutdown(application: Application) -> None:
    """Cleanup on shutdown"""
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
    application.add_handler(CommandHandler("join", group.join_command))
    application.add_handler(CommandHandler("kickitoff", group.kickitoff_command))
    application.add_handler(CommandHandler("newseason", group.newseason_command))
    application.add_handler(MessageHandler(filters.StatusUpdate.MIGRATE, group.chat_migrated))

    # Participant DM
    application.add_handler(CommandHandler("start", user.start_dm, filters=private))
    application.add_handler(CommandHandler("status", user.status_command))
    application.add_handler(CommandHandler("wishlist", user.wishlist_command))
    application.add_handler(CommandHandler("cancel", user.cancel_command))

    # Admin DM
    application.add_handler(CommandHandler("listgroups", admin.listgroups_command))
    application.add_handler(CommandHandler("selectgroup", admin.selectgroup_command))
    application.add_handler(CommandHandler("disband", admin.disband_command))
    application.add_handler(CommandHandler("addrule", admin.addrule_command))
    application.add_handler(CommandHandler("listrules", admin.listrules_command))
    application.add_handler(CommandHandler("removerule", admin.removerule_command))
    application.add_handler(CommandHandler("listjoined", admin.listjoined_command))
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

    application = build_application(config.TELEGRAM_BOT_TOKEN)

    if config.USE_WEBHOOK:
        logger.info("Starting bot in webhook mode...")
        logger.info(f"Webhook URL: {config.WEBHOOK_URL}/webhook")
        logger.info(f"Listening on: 0.0.0.0:{config.PORT}")

        try:
            application.run_webhook(
                listen="0.0.0.0",
                port=config.PORT,
                url_path="/webhook",
                webhook_url=f"{config.WEBHOOK_URL}/webhook",
                secret_token=webhook_secret(config.TELEGRAM_BOT_TOKEN, config.WEBHOOK_SECRET),
                allowed_updates=ALLOWED_UPDATES,
                # Keep updates sent while a deploy was in progress
                drop_pending_updates=False,
            )
        except Exception as e:
            logger.error(f"Webhook failed to start: {e}", exc_info=True)
            raise
    else:
        logger.info("Starting bot in polling mode...")
        application.run_polling(allowed_updates=ALLOWED_UPDATES)


if __name__ == "__main__":
    main()
