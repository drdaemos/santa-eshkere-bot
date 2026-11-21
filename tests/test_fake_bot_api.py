"""The fake Bot API is only useful if it fails where Telegram fails."""

import pytest

from tests.harness.formatting import EntityParseError, parse_html, parse_markdown_legacy, render


class TestLegacyMarkdown:
    @pytest.mark.parametrize(
        ("raw", "plain"),
        [
            ("*bold* and _italic_", "bold and italic"),
            ("`code_with_underscores`", "code_with_underscores"),
            ("[link](https://example.com/a_b)", "link"),
            (r"snake\_case", "snake_case"),
            ("**Office**", "Office"),  # double asterisks are two empty bold entities, not bold
            # even underscores parse "fine" -- as italics, silently breaking the link
            ("https://ozon.ru/nastolnaya_igra_123", "https://ozon.ru/nastolnayaigra123"),
            ("> quote", "> quote"),  # no blockquote in legacy Markdown
            (r"Анна\-Мария", r"Анна\-Мария"),  # backslash only escapes _ * ` [
        ],
    )
    def test_renders(self, raw, plain):
        assert parse_markdown_legacy(raw) == plain

    @pytest.mark.parametrize(
        "raw",
        [
            "https://www.wildberries.ru/catalog/123/detail_aspx",  # odd number of underscores
            "размер * не XL",
            "unclosed `code",
            "[unclosed link",
        ],
    )
    def test_rejects_unbalanced(self, raw):
        with pytest.raises(EntityParseError):
            parse_markdown_legacy(raw)


class TestHtml:
    def test_renders_and_unescapes(self):
        assert parse_html("<b>Алиса</b> &lt;3 &amp; <i>книги</i>") == "Алиса <3 & книги"

    @pytest.mark.parametrize("raw", ["a < b", "<b>unclosed", "<b><i>bad</b></i>", "<div>nope</div>"])
    def test_rejects(self, raw):
        with pytest.raises(EntityParseError):
            parse_html(raw)


def test_markdown_v2_needs_a_validator_first():
    with pytest.raises(NotImplementedError):
        render("x", "MarkdownV2")


async def test_cannot_dm_user_who_never_opened_chat(world):
    from telegram.error import Forbidden

    alice = world.user("Alice")

    with pytest.raises(Forbidden):
        await world.harness.app.bot.send_message(chat_id=alice.id, text="hi")
    await alice.dm("/start")
    await world.harness.app.bot.send_message(chat_id=alice.id, text="hi")


async def test_blocked_user_is_forbidden(world):
    from telegram.error import Forbidden

    alice = world.user("Alice")
    await alice.dm("/start")
    alice.block_bot()
    with pytest.raises(Forbidden, match="blocked"):
        await world.harness.app.bot.send_message(chat_id=alice.id, text="hi")


async def test_message_too_long_is_rejected(world):
    from telegram.error import BadRequest

    alice = world.user("Alice")
    await alice.dm("/start")
    with pytest.raises(BadRequest, match="too long"):
        await world.harness.app.bot.send_message(chat_id=alice.id, text="я" * 4097)


async def test_edit_to_identical_content_is_rejected(world):
    from telegram.error import BadRequest

    alice = world.user("Alice")
    await alice.dm("/start")
    bot = world.harness.app.bot
    msg = await bot.send_message(chat_id=alice.id, text="same")
    with pytest.raises(BadRequest, match="not modified"):
        await bot.edit_message_text(chat_id=alice.id, message_id=msg.message_id, text="same")
