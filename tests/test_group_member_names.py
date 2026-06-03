"""Display names are reserved for all matched humans at group creation."""

from match_manager import MatchManager
from session_runtime import get_human_display_names


def test_create_group_preassigns_participant_names():
    mm = MatchManager()
    sid = mm.create_session(
        name="Test",
        group_size=3,
        bot_enabled=False,
        bots=[],
        participant_names=["a", "b", "c"],
        min_humans_per_group=3,
        max_humans_per_group=3,
    )
    gid = mm.create_group(sid, "GRP-TEST", members=["u1", "u2", "u3"])
    info = mm.get_group_info(sid, gid)
    assert info is not None
    assert set(info["member_names"].values()) == {"a", "b", "c"}
    assert info["member_names"]["u1"] == "a"
    assert info["member_names"]["u2"] == "b"
    assert info["member_names"]["u3"] == "c"


def test_ensure_group_member_names_backfills_legacy_group():
    mm = MatchManager()
    sid = mm.create_session(
        name="Test",
        group_size=2,
        bot_enabled=False,
        bots=[],
        participant_names=["x", "y"],
    )
    mm.active_rooms[sid] = {
        "GRP-OLD": {"members": ["p1", "p2"], "member_names": {"p1": "x"}},
    }
    info = mm.active_rooms[sid]["GRP-OLD"]
    mm.ensure_group_member_names(sid, info)
    assert info["member_names"]["p2"] == "y"


def test_human_display_names_not_hidden_by_bot_name_collision():
    mm = MatchManager()
    sid = mm.create_session(
        name="Bots share letters",
        group_size=3,
        bot_enabled=True,
        bots=[{"name": "a"}, {"name": "c"}],
        participant_names=["a", "b", "c"],
        min_humans_per_group=3,
        max_humans_per_group=3,
    )
    gid = mm.create_group(sid, "GRP-COL", members=["u1", "u2", "u3"])
    info = mm.get_group_info(sid, gid)
    session = mm.get_session(sid)
    assert get_human_display_names(session, info) == ["a", "b", "c"]


def test_queue_progress_lists_full_expected_roster():
    mm = MatchManager()
    sid = mm.create_session(
        name="Three humans",
        group_size=3,
        bot_enabled=False,
        bots=[],
        participant_names=["a", "b", "c"],
        min_humans_per_group=3,
        max_humans_per_group=3,
    )
    mm.add_to_queue(sid, "u1")
    prog = mm.get_queue_progress(sid, "u1")
    assert prog["teammate_display_names"] == ["a", "b", "c"]
    assert prog["humans_matched"] == 1
