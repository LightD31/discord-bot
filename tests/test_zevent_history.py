"""Unit tests for ``features.zevent.history``.

Shapes come from the community project's metrics cache
(``metrics/{event}/global.json``): a cumulative donation curve sampled every
ten minutes, in euros, while the file's top-level total is in centimes.

Editions are compared on **day of the marathon and time of day**, in Paris
time — donations follow the audience's clock. Coverage varies by edition: the
2024 file records its whole fundraising window exactly, while the 2025 one is
truncated at both ends and opens at 164 452 € already raised. No curve reaches
back to its own pre-event concert. Both facts are guarded here.
"""

from datetime import UTC, datetime

from features.zevent.history import (
    DISPLAY_TZ,
    align,
    comparable_editions,
    compare_milestone,
    edition_label,
    format_duration,
    format_euros,
    format_moment,
    parse_metrics,
    previous_record,
    reached_at,
    record_message,
)

HOUR_MS = 3_600_000
# 2025-09-05 16:00 UTC — a Friday, when the real 2025 curve begins.
REF_ORIGIN = int(datetime(2025, 9, 5, 16, 0, tzinfo=UTC).timestamp() * 1000)
# That edition's schedule_raising.start, eight hours before its curve does.
REF_RAISING = datetime(2025, 9, 5, 8, 0, tzinfo=UTC)
# 2026-09-04 16:00 UTC — a Friday, the real 2026 marathon start.
THIS_START = datetime(2026, 9, 4, 16, 0, tzinfo=UTC)


def _payload(values: list[float], *, origin: int = REF_ORIGIN, step: int = HOUR_MS) -> dict:
    return {
        "donation_amount": int(values[-1] * 100),  # centimes, unlike the graph
        "viewers_max": 752_185,
        "graph": {
            "viewers": {"labels": [], "values": []},
            "donations": {
                "all": {
                    "labels": [origin + i * step for i in range(len(values))],
                    "values": values,
                }
            },
        },
    }


CURVE = parse_metrics(
    _payload([0, 1_000_000, 4_000_000, 9_000_000, 16_000_000]), "2025", REF_RAISING
)
assert CURVE is not None


def test_the_tz_database_is_available() -> None:
    """Guarded explicitly: without tzdata every displayed hour is silently UTC."""
    assert str(DISPLAY_TZ) == "Europe/Paris"


# ── parsing ──────────────────────────────────────────────────────────


def test_parses_into_timestamps_and_euros() -> None:
    assert CURVE.label == "2025"
    assert CURVE.start == datetime(2025, 9, 5, 16, 0, tzinfo=UTC)
    assert CURVE.points[1] == (datetime(2025, 9, 5, 17, 0, tzinfo=UTC), 1_000_000.0)
    assert CURVE.total == 16_000_000.0


def test_the_anchor_is_the_edition_start_not_the_curve_start() -> None:
    """A curve's first sample is not reliably the edition's start.

    2024's coincides with it exactly; 2025's is eight hours late.
    """
    assert CURVE.anchor == REF_RAISING
    assert CURVE.anchor != CURVE.start
    # Without an edition start the curve's own beginning is the fallback.
    bare = parse_metrics(_payload([0, 1_000_000]), "x")
    assert bare is not None
    assert bare.anchor == bare.start


def test_the_floor_is_what_the_curve_already_held_when_it_began() -> None:
    floored = parse_metrics(_payload([164_452, 1_000_000, 4_000_000]), "2025", REF_RAISING)
    assert floored is not None
    assert floored.floor == 164_452.0


def test_unsorted_labels_are_ordered_before_anything_reads_the_start() -> None:
    """The 2024 file ships its labels reversed — trusting the order would break."""
    payload = _payload([0, 1_000_000, 4_000_000])
    block = payload["graph"]["donations"]["all"]
    block["labels"].reverse()
    block["values"].reverse()

    curve = parse_metrics(payload, "2024")
    assert curve is not None
    assert curve.start == datetime(2025, 9, 5, 16, 0, tzinfo=UTC)
    assert curve.total == 4_000_000.0


def test_unusable_payloads_disable_the_comparison_rather_than_raising() -> None:
    assert parse_metrics(None, "x") is None
    assert parse_metrics({}, "x") is None
    assert parse_metrics({"graph": "nope"}, "x") is None
    assert parse_metrics({"graph": {"donations": {"all": {}}}}, "x") is None
    assert parse_metrics(_payload([1_000_000]), "x") is None  # one point is not a curve

    payload = _payload([0, 1_000_000, 4_000_000])
    payload["graph"]["donations"]["all"]["values"] = [0, "beaucoup", 4_000_000]
    curve = parse_metrics(payload, "x")
    assert curve is not None
    assert len(curve.points) == 2


# ── calendar alignment ───────────────────────────────────────────────


def _paris(y: int, m: int, d: int, h: int, mi: int = 0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=DISPLAY_TZ)


def test_align_maps_the_same_marathon_day_and_time_of_day() -> None:
    # Day 0 at 22:00 Paris in 2026 is day 0 at 22:00 Paris in 2025 — Friday to
    # Friday, since both marathons open on a Friday.
    assert align(_paris(2026, 9, 4, 22), THIS_START, CURVE.anchor) == _paris(2025, 9, 5, 22)
    # Day 2 at 18:30 — Sunday to Sunday.
    assert align(_paris(2026, 9, 6, 18, 30), THIS_START, CURVE.anchor) == _paris(2025, 9, 7, 18, 30)


def test_align_keeps_the_time_of_day_when_editions_open_at_different_hours() -> None:
    """The point of aligning on the clock rather than on elapsed time.

    2025 opened at 08:00 UTC and 2026 at 16:00; 22:00 must still map to 22:00
    rather than being shifted by that eight-hour difference.
    """
    assert align(_paris(2026, 9, 4, 22), THIS_START, CURVE.anchor) == _paris(2025, 9, 5, 22)


def test_day_numbering_is_cut_at_paris_midnight_on_both_sides() -> None:
    """Both editions split at the same local midnight, so the mapping holds.

    22:30 UTC on the 5th is 00:30 Paris on the 6th — marathon day 2 by Paris
    dates, since the marathon opened on the 4th. It maps to day 2 of 2025,
    whose marathon opened on the 5th.
    """
    late = datetime(2026, 9, 5, 22, 30, tzinfo=UTC)
    assert align(late, THIS_START, CURVE.anchor) == _paris(2025, 9, 7, 0, 30)


# ── lookups ──────────────────────────────────────────────────────────


def test_reached_at_lands_on_a_sample_when_the_value_matches_one() -> None:
    assert reached_at(CURVE, 1_000_000) == datetime(2025, 9, 5, 17, 0, tzinfo=UTC)
    assert reached_at(CURVE, 99_000_000) is None


def test_reached_at_interpolates_inside_the_bracketing_pair() -> None:
    """Rounding up to the next sample would quantise every comparison.

    The fixture climbs 1 M€ -> 4 M€ between 17:00 and 18:00, so 2.5 M€ was
    crossed half way through, at 17:30 — not at 18:00.
    """
    assert reached_at(CURVE, 2_500_000) == datetime(2025, 9, 5, 17, 30, tzinfo=UTC)
    # A quarter of the way up that same segment.
    assert reached_at(CURVE, 1_750_000) == datetime(2025, 9, 5, 17, 15, tzinfo=UTC)


def test_reached_at_is_monotonic_in_the_amount_asked_for() -> None:
    """A larger milestone can never be reported as crossed earlier."""
    moments = [reached_at(CURVE, amount) for amount in range(100_000, 16_000_000, 250_000)]
    assert all(m is not None for m in moments)
    assert moments == sorted(moments)  # type: ignore[type-var]


def test_reached_at_names_the_first_sample_when_it_already_exceeds() -> None:
    """The crossing happened at or before recording began; say the earliest."""
    floored = parse_metrics(_payload([164_452, 1_000_000]), "2025", REF_RAISING)
    assert floored is not None
    assert reached_at(floored, 164_452) == floored.start
    assert reached_at(floored, 100_000) == floored.start


def test_reached_at_handles_a_flat_segment_without_dividing_by_zero() -> None:
    flat = parse_metrics(_payload([0, 1_000_000, 1_000_000, 4_000_000]), "x")
    assert flat is not None
    assert reached_at(flat, 1_000_000) == datetime(2025, 9, 5, 17, 0, tzinfo=UTC)


# ── the notification line ────────────────────────────────────────────


def test_being_ahead_of_the_reference_edition() -> None:
    # 4 M€ at day 0 17:00 in 2026; 2025 needed until day 0 18:00.
    line = compare_milestone(CURVE, 4_000_000, datetime(2026, 9, 4, 17, 0, tzinfo=UTC), THIS_START)
    assert line is not None
    assert "d'avance sur 2025" in line
    assert "vendredi à 20 h 00" in line  # 18:00 UTC rendered in Paris time


def test_being_behind_the_reference_edition() -> None:
    line = compare_milestone(CURVE, 4_000_000, datetime(2026, 9, 4, 21, 0, tzinfo=UTC), THIS_START)
    assert line is not None
    assert "de retard sur 2025" in line


def test_a_dead_heat_is_not_dressed_up_as_a_lead() -> None:
    line = compare_milestone(CURVE, 4_000_000, datetime(2026, 9, 4, 18, 1, tzinfo=UTC), THIS_START)
    assert line is not None
    assert "avance" not in line and "retard" not in line


def test_beating_the_reference_edition_outright() -> None:
    line = compare_milestone(CURVE, 20_000_000, datetime(2026, 9, 4, 20, 0, tzinfo=UTC), THIS_START)
    assert line is not None
    assert "Jamais atteint" in line
    assert "16 000 000 €" in line


def test_nothing_is_claimed_about_the_pre_event_concert() -> None:
    """Remote streamers now go live before the marathon opens.

    Milestones can therefore land on the Thursday. No published curve reaches
    back to its own pre-event period, so there is no counterpart to compare
    against and the line is omitted.
    """
    thursday = datetime(2026, 9, 3, 20, 0, tzinfo=UTC)
    assert compare_milestone(CURVE, 500_000, thursday, THIS_START) is None


def test_milestones_below_the_curve_floor_are_not_guessed() -> None:
    """2025's curve opens at 164 452 €, having missed everything before it.

    Reporting its first sample as the crossing time would overstate how long
    that edition took, making this year look better than it is.
    """
    floored = parse_metrics(_payload([164_452, 1_000_000, 4_000_000]), "2025", REF_RAISING)
    assert floored is not None
    during = datetime(2026, 9, 4, 20, 0, tzinfo=UTC)

    assert compare_milestone(floored, 100_000, during, THIS_START) is None
    # At or above the floor it can be dated, so the line comes back.
    assert compare_milestone(floored, 1_000_000, during, THIS_START) is not None


def test_no_comparison_without_data_or_before_the_marathon() -> None:
    assert (
        compare_milestone(None, 1_000_000, datetime(2026, 9, 4, 20, 0, tzinfo=UTC), THIS_START)
        is None
    )
    # Milestones crossed during the pre-event concert are not comparable.
    assert (
        compare_milestone(CURVE, 1_000_000, datetime(2026, 9, 3, 20, 0, tzinfo=UTC), THIS_START)
        is None
    )


# ── formatting ───────────────────────────────────────────────────────


def test_format_moment_gives_the_weekday_and_hour_in_paris_time() -> None:
    # 18:10 UTC is 20:10 in Paris; the calendar date is deliberately dropped —
    # it belongs to a past edition and would invite the wrong comparison.
    assert format_moment(datetime(2025, 9, 7, 18, 10, tzinfo=UTC)) == "dimanche à 20 h 10"
    assert format_moment(datetime(2025, 9, 5, 8, 5, tzinfo=UTC)) == "vendredi à 10 h 05"
    # Crossing midnight westward: 23:30 UTC Saturday is 01:30 Paris Sunday.
    assert format_moment(datetime(2025, 9, 6, 23, 30, tzinfo=UTC)) == "dimanche à 1 h 30"


def test_format_duration_is_coarse_on_purpose() -> None:
    assert format_duration(0) == "0 min"
    assert format_duration(3600) == "1 h"
    assert format_duration(3600 + 20 * 60) == "1 h 20"
    assert format_duration(86400 + 5 * 3600) == "1 j 5 h"
    assert format_duration(-50) == "0 min"


def test_format_euros_uses_space_separators() -> None:
    assert format_euros(16_178_394) == "16 178 394 €"


# ── edition selection ────────────────────────────────────────────────


def test_edition_label_prefers_the_year() -> None:
    assert edition_label("ZEvent 2025") == "2025"
    assert edition_label("Projet Avengers") == "Projet Avengers"
    assert edition_label("") == "l'édition précédente"


def _event(eid: str, name: str, start: str, group: str | None) -> dict:
    return {"id": eid, "name": name, "schedule": {"start": start}, "event_group_id": group}


ZEVENT_GROUP = "019f5bad-f48a-7cda-9817-ffba311f987c"
EVENTS = [
    _event("2026", "ZEvent 2026", "2026-09-03T18:00:00Z", ZEVENT_GROUP),
    _event("2025", "ZEvent 2025", "2025-09-04T10:00:00Z", ZEVENT_GROUP),
    _event("2024", "ZEvent 2024", "2024-09-05T16:00:00Z", ZEVENT_GROUP),
    _event("bop", "Birds Of Prey #6", "2025-11-08T13:00:00Z", None),
]


def test_only_past_editions_of_the_same_series_are_comparable() -> None:
    # Most recent first, and the ungrouped one-off never qualifies — measuring
    # a marathon against a weekend charity stream would be meaningless.
    assert [e["id"] for e in comparable_editions(EVENTS, EVENTS[0])] == ["2025", "2024"]


def test_an_ungrouped_event_has_nothing_to_compare_against() -> None:
    assert comparable_editions(EVENTS, EVENTS[3]) == []


def test_the_oldest_edition_has_no_predecessor() -> None:
    assert comparable_editions(EVENTS, EVENTS[2]) == []


def test_editions_without_a_usable_start_are_skipped_not_compared() -> None:
    """A malformed schedule must not crash the selection.

    Comparing a missing start against a real one raised TypeError before the
    guard existed.
    """
    broken = [
        {"id": "no-schedule", "name": "ZEvent ????", "event_group_id": ZEVENT_GROUP},
        {"id": "bad", "name": "x", "schedule": "nope", "event_group_id": ZEVENT_GROUP},
        {"id": "null", "name": "y", "schedule": {"start": None}, "event_group_id": ZEVENT_GROUP},
        EVENTS[1],
        "not even a dict",
    ]
    assert [e["id"] for e in comparable_editions(broken, EVENTS[0])] == ["2025"]


# ── the record a past edition set ────────────────────────────────────
#
# Real figures, read from the live API and the published 2025 metrics file:
#   /events amount_raised     16 658 660 €   what 2025 actually raised
#   file donation_amount      16 182 382 €   what its recording totalled
#   curve last sample         16 178 394 €   where that recording stops
# The gap between the first and the rest is the edition's missing last hours.

REAL_2025_TOTAL = 16_658_660.0
REAL_2025_FILE_TOTAL = 16_182_382.43
REAL_2025_CURVE_END = 16_178_394.01


def _truncated_2025() -> dict:
    payload = _payload([164_452.26, 8_000_000, REAL_2025_CURVE_END])
    payload["donation_amount"] = int(REAL_2025_FILE_TOTAL * 100)
    return payload


def test_the_api_total_wins_over_the_file_and_the_curve() -> None:
    """The file's own total is not the edition's: it stops where the tape does."""
    curve = parse_metrics(_truncated_2025(), "2025", REF_RAISING, final_total=REAL_2025_TOTAL)
    assert curve is not None
    assert curve.total == REAL_2025_CURVE_END
    assert curve.record == REAL_2025_TOTAL


def test_the_file_total_stands_in_when_the_api_total_is_unknown() -> None:
    """Better than the curve by 4 k€ — and never mistaken for the truth."""
    curve = parse_metrics(_truncated_2025(), "2025", REF_RAISING)
    assert curve is not None
    assert curve.record == REAL_2025_FILE_TOTAL


def test_the_record_falls_back_on_the_curve_without_any_total() -> None:
    payload = _payload([0, 1_000_000, 4_000_000])
    del payload["donation_amount"]

    curve = parse_metrics(payload, "2025", REF_RAISING)
    assert curve is not None
    assert curve.final_total is None
    assert curve.record == 4_000_000


def test_a_total_below_the_curve_never_lowers_the_record() -> None:
    """Whatever anyone reports, the curve is proof the edition got that far."""
    payload = _payload([0, 1_000_000, 4_000_000])

    curve = parse_metrics(payload, "2025", REF_RAISING, final_total=1_500_000)
    assert curve is not None
    assert curve.record == 4_000_000


def test_a_milestone_the_truncated_curve_misses_is_not_called_unreached() -> None:
    """Between the curve's end and the real total, only the fact is known."""
    curve = parse_metrics(_truncated_2025(), "2025", REF_RAISING, final_total=REAL_2025_TOTAL)
    assert curve is not None

    line = compare_milestone(curve, 16_400_000, datetime(2026, 9, 6, 20, 0, tzinfo=UTC), THIS_START)
    assert line is not None
    assert "Jamais atteint" not in line
    assert "Dépassé en 2025" in line
    assert "16 658 660 €" in line


def test_a_milestone_above_the_real_total_was_never_reached() -> None:
    curve = parse_metrics(_truncated_2025(), "2025", REF_RAISING, final_total=REAL_2025_TOTAL)
    assert curve is not None

    line = compare_milestone(curve, 17_000_000, datetime(2026, 9, 6, 20, 0, tzinfo=UTC), THIS_START)
    assert line is not None
    assert "Jamais atteint en 2025" in line
    assert "16 658 660 €" in line


# ── which edition holds the record ───────────────────────────────────

GROUP = "019f5bad-f48a-7cda-9817-ffba311f987c"
# The real series, with the totals the API reports (centimes on the wire).
SERIES = [
    {
        "id": "2021",
        "name": "ZEvent 2021",
        "amount_raised": 1_006_448_000,
        "event_group_id": GROUP,
        "schedule": {"start": "2021-10-28T19:00:00Z"},
    },
    {
        "id": "2022",
        "name": "ZEvent 2022",
        "amount_raised": 1_018_212_600,
        "event_group_id": GROUP,
        "schedule": {"start": "2022-09-08T19:00:00Z"},
    },
    {
        "id": "2024",
        "name": "ZEvent 2024",
        "amount_raised": 1_014_588_100,
        "event_group_id": GROUP,
        "schedule": {"start": "2024-09-05T19:00:00Z"},
    },
    {
        "id": "2025",
        "name": "ZEvent 2025",
        "amount_raised": 1_665_866_000,
        "event_group_id": GROUP,
        "schedule": {"start": "2025-09-04T10:00:00Z"},
    },
    {
        "id": "2026",
        "name": "ZEvent 2026",
        "amount_raised": 1_670_079_729,
        "event_group_id": GROUP,
        "schedule": {"start": "2026-09-03T18:00:00Z"},
    },
]
TRACKED_2026 = SERIES[-1]
TRACKED_2025 = SERIES[-2]


def test_the_record_is_the_best_past_edition() -> None:
    assert previous_record(SERIES, TRACKED_2026) == ("2025", 16_658_660.0)


def test_the_record_is_not_merely_last_year() -> None:
    """2024 finished 36 245 € below 2022, so 2025's record to beat was 2022's.

    Comparing against the most recent edition would have announced the record
    broken while it still stood — the bug this test exists to pin down.
    """
    assert previous_record(SERIES, TRACKED_2025) == ("2022", 10_182_126.0)


def test_the_tracked_edition_never_counts_as_its_own_record() -> None:
    label, record = previous_record(SERIES, TRACKED_2026) or ("", 0.0)
    assert record < TRACKED_2026["amount_raised"] / 100
    assert label == "2025"


def test_editions_without_a_usable_total_are_skipped() -> None:
    series = [dict(e) for e in SERIES]
    series[3].pop("amount_raised")  # 2025 has no figure
    series[1]["amount_raised"] = "beaucoup"

    # 2025 and 2022 both drop out, so the best remaining is 2024.
    assert previous_record(series, TRACKED_2026) == ("2024", 10_145_881.0)


def test_no_comparable_edition_means_no_record() -> None:
    lone = {
        "id": "solo",
        "name": "Charity Stream",
        "amount_raised": 500_000,
        "schedule": {"start": "2026-01-01T00:00:00Z"},
    }
    assert previous_record([lone], lone) is None


# ── the record announcement ──────────────────────────────────────────


def test_the_record_message_names_both_totals_and_the_edition() -> None:
    message = record_message(
        "2025", REAL_2025_TOTAL, 16_700_797, datetime(2026, 9, 6, 21, 0, tzinfo=UTC), THIS_START
    )

    assert "Record battu" in message
    assert "16 658 660 €" in message  # the record that just fell
    assert "16 700 797 €" in message  # where this edition stands
    assert "2025" in message
    assert "2 j 5 h de marathon" in message


def test_the_record_message_omits_a_duration_before_the_marathon_opens() -> None:
    """A crossing during the pre-event concert would render a negative delay."""
    message = record_message(
        "2025", REAL_2025_TOTAL, 16_700_797, datetime(2026, 9, 3, 21, 0, tzinfo=UTC), THIS_START
    )

    assert "Record battu" in message
    assert "marathon" not in message
