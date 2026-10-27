import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Automatically load rpg/.env for pytest suite
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


@pytest.fixture(scope="session")
def live_server():
    from psycopg.conninfo import conninfo_to_dict
    assert conninfo_to_dict(os.environ["DATABASE_URL"])["dbname"].startswith("authoring_test_")
    from tests.integration.test_authoring_http import start_server
    yield from start_server()
