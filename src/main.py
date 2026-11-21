"""Main entry point for Santa Eshkere bot"""

import hashlib
import logging
import sys

from telegram import Update
from telegram.ext import (
    Application,
    BasePersistence,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PicklePersistence,
    filters,
)
from telegram.request import BaseRequest

from .config import config
from .database.session import close_db, init_db
from .handlers import admin, group, user

logger = logging.getLogger(__name__)


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


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route text messages to appropriate handler"""
    if not update.effective_chat:
        return

    # In private chat, handle both admin and user text
    if update.effective_chat.type == "private":
        # Try admin handler first (for confirmation prompts, etc.)
        # Admin handlers will check if user has selected a group and is admin of it
        if context.user_data and "selected_group_id" in context.user_data:
            await admin.handle_admin_text(update, context)
        else:
            # User text handlers (registration flow, etc.)
            await user.handle_text_message(update, context)


def register_handlers(application: Application) -> None:
    """Attach all command, callback and message handlers"""
    # Group commands
    application.add_handler(CommandHandler("start", group.start_command))
    application.add_handler(CommandHandler("join", group.join_command))
    application.add_handler(CommandHandler("kickitoff", group.kickitoff_command))

    # User DM commands
    application.add_handler(CommandHandler("wishlist", user.wishlist_command))
    application.add_handler(CommandHandler("status", user.status_command))

    # Admin commands
    application.add_handler(CommandHandler("listgroups", admin.listgroups_command))
    application.add_handler(CommandHandler("selectgroup", admin.selectgroup_command))
    application.add_handler(CommandHandler("disband", admin.disband_command))
    application.add_handler(CommandHandler("addrule", admin.addrule_command))
    application.add_handler(CommandHandler("listrules", admin.listrules_command))
    application.add_handler(CommandHandler("removerule", admin.removerule_command))
    application.add_handler(CommandHandler("listjoined", admin.listjoined_command))
    application.add_handler(CommandHandler("adminhelp", admin.adminhelp_command))
    application.add_handler(CommandHandler("reset", admin.reset_command))
    application.add_handler(CommandHandler("dryrunassignments", admin.dryrunassignments_command))

    # Callback query handlers
    application.add_handler(CallbackQueryHandler(admin.handle_select_group_callback, pattern="^select_group_"))
    application.add_handler(CallbackQueryHandler(admin.handle_addrule_page_navigation, pattern="^addrule_page_"))
    application.add_handler(CallbackQueryHandler(admin.handle_addrule_first_user_callback, pattern="^addrule_first_"))
    application.add_handler(CallbackQueryHandler(admin.handle_addrule_second_user_callback, pattern="^addrule_second_"))
    application.add_handler(CallbackQueryHandler(admin.handle_remove_rule_callback, pattern="^remove_rule_"))
    # Ignore noop callbacks (page indicator)
    application.add_handler(
        CallbackQueryHandler(lambda update, context: update.callback_query.answer(), pattern="^addrule_noop$")
    )

    # Text message handler (for registration flow, wishlist updates, etc)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    # Error handler
    application.add_error_handler(error_handler)


def build_application(
    token: str,
    *,
    persistence: BasePersistence | None = None,
    request: BaseRequest | None = None,
    with_lifecycle_hooks: bool = True,
) -> Application:
    """Build the bot Application.

    Tests pass a fake `request` (in-process Bot API) and skip lifecycle hooks,
    managing the database themselves.
    """
    builder = Application.builder().token(token)
    if persistence is not None:
        builder = builder.persistence(persistence)
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

    application = build_application(
        config.TELEGRAM_BOT_TOKEN,
        persistence=PicklePersistence(filepath="bot_data.pkl"),
    )

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
                allowed_updates=["message", "callback_query"],
                # Keep updates sent while a deploy was in progress
                drop_pending_updates=False,
            )
        except Exception as e:
            logger.error(f"Webhook failed to start: {e}", exc_info=True)
            raise
    else:
        logger.info("Starting bot in polling mode...")
        application.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
