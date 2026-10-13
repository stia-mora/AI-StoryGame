import os
from pathlib import Path
from dotenv import load_dotenv

# Automatically load rpg/.env for pytest suite
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
