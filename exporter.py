import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def export_json(data: Dict[str, Any], output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    logger.info("JSON exported to: %s", output_path)
