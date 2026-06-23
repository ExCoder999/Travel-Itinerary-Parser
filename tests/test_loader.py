import io
from unittest.mock import patch

from loader import load_email


def test_load_email_from_stdin() -> None:
    with patch("sys.stdin", io.StringIO("hello email")):
        assert load_email("-") == "hello email"
