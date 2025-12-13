"""Main entry point for Santa Eshkere bot"""

import logging
import sys

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    PicklePersistence,
    filters,
)

from .config import config
from .database.session import close_db, init_db
from .handlers import admin, group, user
from .utils.auth import is_admin

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)


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


async def error_handler(update: object, context) -> None:
    """Log errors"""
    logger.error("Exception while handling an update:", exc_info=context.error)

    # In webhook mode, we need to ensure errors don't crash the server
    if update:
        logger.error(f"Update that caused error: {update}")


async def log_update(update, context) -> None:
    """Log all incoming updates for debugging"""
    logger.info(f"Received update: {update.update_id if update else 'None'}")
    raise Exception("Update received and logged")


async def handle_text_message(update, context) -> None:
    """Route text messages to appropriate handler"""
    if not update.effective_chat:
        return

    # Admin text handlers (in private chat)
    if update.effective_chat.type == "private" and update.effective_user:
        if is_admin(update.effective_user.id):
            await admin.handle_admin_text(update, context)
            return

        # User text handlers
        await user.handle_text_message(update, context)


def main() -> None:
    """Start the bot"""
    try:
        config.validate()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        logger.info("Please set TELEGRAM_BOT_TOKEN and ADMIN_TELEGRAM_ID environment variables")
        logger.info("You can get your Telegram ID from @userinfobot")
        sys.exit(1)

    # Create persistence
    persistence = PicklePersistence(filepath="bot_data.pkl")

    # Create application
    application = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .persistence(persistence)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

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

    # Callback query handlers
    application.add_handler(
        CallbackQueryHandler(
            admin.handle_select_group_callback,
            pattern="^select_group_"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            admin.handle_addrule_page_navigation,
            pattern="^addrule_page_"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            admin.handle_addrule_first_user_callback,
            pattern="^addrule_first_"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            admin.handle_addrule_second_user_callback,
            pattern="^addrule_second_"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            admin.handle_remove_rule_callback,
            pattern="^remove_rule_"
        )
    )
    # Ignore noop callbacks (page indicator)
    application.add_handler(
        CallbackQueryHandler(
            lambda update, context: update.callback_query.answer(),
            pattern="^addrule_noop$"
        )
    )

    # Text message handler (for registration flow, wishlist updates, etc)
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text_message
        )
    )

    # Add update logger as first handler (for debugging webhook)
    if config.USE_WEBHOOK:
        from telegram.ext import TypeHandler
        application.add_handler(TypeHandler(type=object, callback=log_update), group=-1)

    # Error handler
    application.add_error_handler(error_handler)

    # Run bot
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
                allowed_updates=["message", "callback_query"],
                drop_pending_updates=True,
            )
        except Exception as e:
            logger.error(f"Webhook failed to start: {e}", exc_info=True)
            raise
    else:
        logger.info("Starting bot in polling mode...")
        application.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
