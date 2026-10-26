"""Run with: python -m filmvale"""

import logging
import os
import sys

from .bot import FilmvaleBot, load_dotenv


def main() -> None:
    load_dotenv()
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        sys.exit("DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in.")
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    FilmvaleBot().run(token, log_handler=None)


if __name__ == "__main__":
    main()
