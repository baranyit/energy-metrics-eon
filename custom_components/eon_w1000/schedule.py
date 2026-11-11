"""When to ask the Apps Script for new e-mails (no Home Assistant imports).

E.ON sends the scheduled export once a day. After an e-mail has been
processed, the next one cannot arrive for about a day, so polling is paused
for QUIET_PERIOD after the newest processed e-mail and resumes hourly after
that until the next e-mail shows up.
"""

from __future__ import annotations

from datetime import datetime, timedelta

QUIET_PERIOD = timedelta(hours=22)


def quiet_until(last_email: datetime | None, retry: bool) -> datetime | None:
    """End of the current quiet period, or None if polling is due."""
    if retry or last_email is None:
        return None
    return last_email + QUIET_PERIOD


def should_poll(now: datetime, last_email: datetime | None, retry: bool) -> bool:
    """True if the bridge should be asked for new e-mails now."""
    until = quiet_until(last_email, retry)
    return until is None or now >= until


def next_check(
    now: datetime,
    last_email: datetime | None,
    retry: bool,
    interval: timedelta,
) -> datetime:
    """Time of the first scheduled update that will actually poll.

    Updates run every `interval`; the first one at or after the end of the
    quiet period polls.
    """
    until = quiet_until(last_email, retry)
    if until is None or until <= now + interval:
        return now + interval
    ticks = -(-(until - now) // interval)  # ceiling division
    return now + ticks * interval
