import logging
import sys
from logging import LogRecord

from ai_engine.core.context import _trace_id_var


class TraceIdFilter(logging.Filter):
    """从协程上下文中提取 trace_id  注入到 LogRecord"""

    def filter(self, record: LogRecord) -> bool | LogRecord:
        record.trace_id = _trace_id_var.get("system")
        return True


def setup_logging(debug: bool = False) -> None:
    """初始化全局结构化日志格式"""
    log_level = logging.DEBUG if debug else logging.INFO
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(trace_id)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(TraceIdFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)


logger = logging.getLogger("ai_engine")
