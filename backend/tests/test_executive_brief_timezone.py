from datetime import datetime, timezone

from services.executive_brief import greeting_for_timezone, normalize_timezone


def test_greeting_uses_the_users_iana_timezone():
    # 14:21 UTC is 19:51 in India, so it must not be "Good afternoon".
    now = datetime(2026, 8, 25, 14, 21, tzinfo=timezone.utc)
    assert greeting_for_timezone("Asia/Kolkata", now) == "Good evening"


def test_invalid_timezone_fails_safely_to_utc():
    assert normalize_timezone("not/a-timezone") == "UTC"
