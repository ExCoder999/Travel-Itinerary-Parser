import sys
import logging

logger = logging.getLogger(__name__)


def load_email(path: str) -> str:
    if path == "-":
        logger.info("Reading email from stdin")
        return sys.stdin.read()
    logger.info("Reading email from file: %s", path)
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()
