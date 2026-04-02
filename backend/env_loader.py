from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"


def load_environment() -> None:
    load_dotenv(ENV_PATH, override=False)
