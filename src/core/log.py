import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path("logs")
_FORMAT = "%(asctime)s %(levelname)s %(message)s"


def setup(name: str = "assistant") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:  # 二重初期化防止(テスト等で複数回呼ばれても安全)
        return logger

    LOG_DIR.mkdir(exist_ok=True)
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(_FORMAT)

    # タスクスケジューラ実行はコンソールが見えないため、ファイルが正
    file_handler = RotatingFileHandler(
        LOG_DIR / f"{name}.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)
    return logger
