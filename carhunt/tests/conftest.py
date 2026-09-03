import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db  # noqa: E402
from app.config import settings  # noqa: E402


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Ogni test lavora su un database SQLite usa e getta."""
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.sqlite3"))
    db.init_db()
    return settings.db_path
