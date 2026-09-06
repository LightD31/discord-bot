"""Tests for the Zevent "record battu" announcement.

The record is a once-per-edition headline, so it is guarded harder than a
palier: it goes out exactly once, only to a tracker that actually watched the
previous edition's total fall, and it survives a reboot in both directions —
a crossing that happened while the bot was down is still announced, while one
already announced is never repeated.
"""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from extensions.zevent import tasks as module
from extensions.zevent.tasks import TasksMixin
from features.zevent.history import parse_metrics
from src.core.errors import DatabaseError

HOUR_MS = 3_600_000
REF_ORIGIN = int(datetime(2025, 9, 5, 16, 0, tzinfo=UTC).timestamp() * 1000)
REF_RAISING = datetime(2025, 9, 5, 8, 0, tzinfo=UTC)
THIS_START = datetime(2026, 9, 4, 16, 0, tzinfo=UTC)

RECORD = 16_000_000.0
CURVE = parse_metrics(
    {
        "donation_amount": int(RECORD * 100),
        "graph": {
            "donations": {
                "all": {
                    "labels": [REF_ORIGIN, REF_ORIGIN + HOUR_MS, REF_ORIGIN + 2 * HOUR_MS],
                    "values": [0, 1_000_000, RECORD],
                }
            }
        },
    },
    "2025",
    REF_RAISING,
)
assert CURVE is not None


class FakeChannel:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, content):
        self.sent.append(content)
        return SimpleNamespace(id=1)


class Tracker(TasksMixin):
    """The mixin under test, wired the way ``Zevent`` wires it."""

    def __init__(self, curve=CURVE, stats_event: dict | None = None) -> None:
        self.channel = FakeChannel()
        self._record_state: bool | None = None
        self._record_lock = asyncio.Lock()
        self._main_event_start = THIS_START
        self._stats_event = stats_event or {"id": "edition-2026"}
        self._curve = curve

    async def _ensure_reference_curve(self):
        return self._curve


class FakeStore:
    """Stands in for the Mongo-backed marker, keyed by edition like the real one."""

    def __init__(self) -> None:
        self.saved: dict[str | None, bool] = {}
        self.failing = False
        self.error: Exception = DatabaseError("mongo down")

    def __call__(self, guild_id):
        return self

    async def load_record(self, event_id):
        if self.failing:
            raise self.error
        return self.saved.get(event_id)

    async def save_record(self, event_id, announced):
        if self.failing:
            raise self.error
        self.saved[event_id] = announced


@pytest.fixture(autouse=True)
def _guild(monkeypatch):
    monkeypatch.setattr(module, "GUILD_ID", 809125340280520724)


@pytest.fixture(autouse=True)
def store(monkeypatch):
    """Always stubbed: no test may reach for a real MongoDB."""
    fake = FakeStore()
    monkeypatch.setattr(module, "ZeventStateRepository", fake)
    return fake


def run(coro):
    return asyncio.run(coro)


def test_the_record_falling_is_announced() -> None:
    tracker = Tracker()

    run(tracker.check_and_send_record(15_900_000))
    run(tracker.check_and_send_record(16_004_200))

    assert len(tracker.channel.sent) == 1
    message = tracker.channel.sent[0]
    assert "Record battu" in message
    assert "16 000 000 €" in message
    assert "16 004 200 €" in message
    assert "2025" in message


def test_the_record_is_announced_once() -> None:
    tracker = Tracker()

    run(tracker.check_and_send_record(15_900_000))
    for total in (16_004_200, 16_500_000, 17_000_000):
        run(tracker.check_and_send_record(total))

    assert len(tracker.channel.sent) == 1


def test_nothing_is_said_while_the_record_still_stands() -> None:
    tracker = Tracker()

    run(tracker.check_and_send_record(0))
    run(tracker.check_and_send_record(9_000_000))
    run(tracker.check_and_send_record(15_999_999))

    assert tracker.channel.sent == []


def test_an_edition_first_read_from_above_the_record_says_nothing() -> None:
    """A tracker configured mid-marathon never watched the record fall."""
    tracker = Tracker()

    run(tracker.check_and_send_record(16_400_000))
    run(tracker.check_and_send_record(16_500_000))

    assert tracker.channel.sent == []


def test_no_reference_edition_means_no_record_to_beat() -> None:
    tracker = Tracker(curve=None)

    run(tracker.check_and_send_record(16_400_000))

    assert tracker.channel.sent == []
    # Nothing was decided about this edition, so a curve loading later still
    # gets its chance rather than finding the marker already written.
    assert tracker._record_state is None


def test_a_total_that_dips_back_does_not_re_announce() -> None:
    """Zevent and Streamlabs disagree slightly; the higher one wins per cycle."""
    tracker = Tracker()

    run(tracker.check_and_send_record(15_900_000))
    run(tracker.check_and_send_record(16_004_200))
    run(tracker.check_and_send_record(15_998_000))
    run(tracker.check_and_send_record(16_010_000))

    assert len(tracker.channel.sent) == 1


def test_an_unusable_channel_leaves_the_announcement_pending() -> None:
    """Unlike a palier, this one never comes round again."""
    tracker = Tracker()
    run(tracker.check_and_send_record(15_900_000))
    tracker.channel = None

    run(tracker.check_and_send_record(16_004_200))
    tracker.channel = FakeChannel()
    run(tracker.check_and_send_record(16_010_000))

    assert len(tracker.channel.sent) == 1


# ─── Surviving a reboot ───────────────────────────────────────────────


def test_watching_below_the_record_is_persisted(store) -> None:
    tracker = Tracker()

    run(tracker.check_and_send_record(15_900_000))

    assert store.saved == {"edition-2026": False}


def test_the_announcement_is_persisted(store) -> None:
    tracker = Tracker()

    run(tracker.check_and_send_record(15_900_000))
    run(tracker.check_and_send_record(16_004_200))

    assert store.saved == {"edition-2026": True}


def test_a_record_broken_while_the_bot_was_down_is_still_announced(store) -> None:
    """The stored `False` is proof this tracker saw the record still standing."""
    store.saved["edition-2026"] = False
    tracker = Tracker()

    run(tracker.load_record_marker())
    run(tracker.check_and_send_record(16_400_000))

    assert len(tracker.channel.sent) == 1


def test_a_reboot_does_not_re_announce_a_record_already_broken(store) -> None:
    store.saved["edition-2026"] = True
    tracker = Tracker()

    run(tracker.load_record_marker())
    run(tracker.check_and_send_record(16_400_000))

    assert tracker.channel.sent == []


def test_a_new_edition_ignores_last_year_s_marker(store) -> None:
    """Otherwise the 2026 record would be announced as already broken."""
    store.saved["edition-2025"] = True
    tracker = Tracker(stats_event={"id": "edition-2026"})

    run(tracker.load_record_marker())
    run(tracker.check_and_send_record(1_000_000))
    run(tracker.check_and_send_record(16_400_000))

    assert len(tracker.channel.sent) == 1


def test_an_unreachable_database_still_announces(store) -> None:
    """Mongo is not in the path of an announcement — it only survives reboots."""
    store.failing = True
    tracker = Tracker()

    run(tracker.load_record_marker())
    run(tracker.check_and_send_record(15_900_000))
    run(tracker.check_and_send_record(16_004_200))

    assert len(tracker.channel.sent) == 1


def test_an_unconfigured_database_still_announces(store) -> None:
    """No `mongodb.url` raises RuntimeError, not DatabaseError, before the
    driver is ever reached — it must not break the refresh cycle either."""
    store.error = RuntimeError("MongoDB URL is not configured")
    store.failing = True
    tracker = Tracker()

    run(tracker.load_record_marker())
    run(tracker.check_and_send_record(15_900_000))
    run(tracker.check_and_send_record(16_004_200))

    assert len(tracker.channel.sent) == 1
