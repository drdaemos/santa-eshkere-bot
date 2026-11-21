"""Input validation rules and the HTML validity of every message template."""

import string

import pytest

from src.config import Config
from src.formatting import render
from src.messages import Messages
from src.validation import (
    NAME_MAX_LENGTH,
    WISHLIST_MAX_LENGTH,
    ValidationError,
    callback,
    clean_name,
    clean_wishlist,
    parse_callback,
    parse_index,
)
from tests.harness.formatting import parse_html


class TestName:
    @pytest.mark.parametrize(("raw", "clean"), [("  Алиса  ", "Алиса"), ("Анна   Мария", "Анна Мария"), ("Саша_К <3", "Саша_К <3")])
    def test_accepts(self, raw, clean):
        assert clean_name(raw) == clean

    @pytest.mark.parametrize("raw", ["", "   ", "Алиса\nСпам", "А" * (NAME_MAX_LENGTH + 1), "12345", "🎅🎅", "​​"])
    def test_rejects(self, raw):
        with pytest.raises(ValidationError):
            clean_name(raw)


class TestWishlist:
    def test_accepts_and_trims(self):
        assert clean_wishlist("  настолки\n\n\n\nкофе  ") == "настолки\n\nкофе"

    @pytest.mark.parametrize("raw", ["", "ок", "Не знаю", "я не знаю!", "-", "x" * (WISHLIST_MAX_LENGTH + 1)])
    def test_rejects(self, raw):
        with pytest.raises(ValidationError):
            clean_wishlist(raw)


class TestCallbackData:
    def test_round_trip(self):
        parsed = parse_callback(callback("rs", 12, 345, 6789))
        assert parsed is not None and parsed.kind == "rs" and parsed.args == (12, 345, 6789)

    @pytest.mark.parametrize(
        "data",
        [None, "", "rs:1:2", "rs:1:2:3:4", "zz:1", "rr:-1", "rr:01", "rr:1e3", "rr: 1", "rr:" + "9" * 30, "sg:1:" + "x" * 70],
    )
    def test_rejects_malformed(self, data):
        assert parse_callback(data) is None


@pytest.mark.parametrize(("args", "count"), [([], 3), (["x"], 3), (["0"], 3), (["4"], 3), (["1", "2"], 3)])
def test_parse_index_rejects(args, count):
    with pytest.raises(ValidationError):
        parse_index(args, count)


HOSTILE = "<b>&amp; *_`[x](y)"


def _templates():
    for name, value in vars(Messages).items():
        if name.isupper() and isinstance(value, str) and not name.endswith("_BUTTON"):
            yield pytest.param(value, id=name)


@pytest.mark.parametrize("template", _templates())
def test_every_message_is_valid_html_whatever_the_user_typed(template):
    fields = {f for _, f, _, _ in string.Formatter().parse(template) if f}
    rendered = render(template, **dict.fromkeys(fields, HOSTILE))
    plain = parse_html(rendered)
    if fields:
        assert HOSTILE in plain, "user text must come out verbatim"


def test_production_refuses_sqlite(monkeypatch):
    monkeypatch.setattr(Config, "TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setattr(Config, "USE_WEBHOOK", True)
    monkeypatch.setattr(Config, "WEBHOOK_URL", "https://santa.example")
    monkeypatch.setattr(Config, "DATABASE_URL", "sqlite+aiosqlite:///./db.db")
    monkeypatch.setattr(Config, "ON_RAILWAY", False)
    Config.validate()  # fine locally
    monkeypatch.setattr(Config, "ON_RAILWAY", True)
    with pytest.raises(ValueError, match="Postgres"):
        Config.validate()


@pytest.mark.parametrize(
    ("url", "ok"),
    [("https://santa.example", True), ("http://127.0.0.1:8443", True), ("http://localhost:1", True), ("http://santa.example", False), ("", False)],
)
def test_webhook_url_must_be_https_except_localhost(monkeypatch, url, ok):
    monkeypatch.setattr(Config, "TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setattr(Config, "USE_WEBHOOK", True)
    monkeypatch.setattr(Config, "ON_RAILWAY", False)
    monkeypatch.setattr(Config, "WEBHOOK_URL", url)
    if ok:
        Config.validate()
    else:
        with pytest.raises(ValueError, match="https"):
            Config.validate()
