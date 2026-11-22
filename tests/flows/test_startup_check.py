"""At startup the bot checks every active group with Telegram and brings the
join posts up to date, so nothing stays stale after a deploy or a migration."""

import logging

from src.database.session import session_scope
from src.services import join_post as join_post_service
from src.services import seasons
from tests.harness import db
from tests.harness.scenario import join_post, listed, register


async def season(world, office, names=("Алиса",)):
    group, admin = office
    await admin.send(group, "/start")
    for i, name in enumerate(names):
        actor = world.user(f"U{i}")
        group.add(actor)
        await register(actor, group, name, "книги")
    return group, admin


async def test_lost_join_post_is_posted_again_at_startup(world, office):
    group, _ = await season(world, office)
    post = join_post(group)
    # the post was lost (e.g. a supergroup migration before the fix), and the list changed meanwhile
    world.api.messages.pop((group.id, post.message_id))
    event = (await db.events())[-1]
    async with session_scope() as s:
        stored = await seasons.get_event(s, event.id)
        stored.join_message_digest = "stale"
    await join_post_service.check_groups(world.harness.app.bot)
    fresh = join_post(group)
    assert fresh.message_id != post.message_id
    assert listed(fresh) == ["Алиса"]


async def test_changed_list_is_edited_at_startup(world, office):
    group, _ = await season(world, office)
    post = join_post(group)
    event = (await db.events())[-1]
    async with session_scope() as s:
        stored = await seasons.get_event(s, event.id)
        stored.join_message_digest = "stale"  # an edit failed before the restart
    await join_post_service.check_groups(world.harness.app.bot)
    assert join_post(group).message_id == post.message_id, "edited in place, not re-posted"


async def test_unchanged_posts_cost_no_calls(world, office):
    group, _ = await season(world, office)
    before = len(world.api.calls)
    await join_post_service.check_groups(world.harness.app.bot)
    methods = [c.method for c in world.api.calls[before:]]
    assert methods == ["getChat", "getChatMember"], methods


async def test_groups_are_logged_and_unreachable_ones_skipped(world, office, caplog):
    group, admin = await season(world, office)
    other = world.group("Gone", owner=admin)
    await admin.send(other, "/start")
    world.api.groups.pop(other.id)  # the bot was removed, or the id is stale
    caplog.set_level(logging.INFO)
    await join_post_service.check_groups(world.harness.app.bot)
    assert f"chat_id={group.id}: supergroup, bot is member" in caplog.text
    assert f"chat_id={other.id} unreachable: Chat not found" in caplog.text
