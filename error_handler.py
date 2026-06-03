"""
Error Handler: unified exception handling and logging.
"""

import asyncio
import logging
import traceback
import json
from datetime import datetime
from typing import Optional, Dict
from enum import Enum
import os


class ErrorSeverity(Enum):
    """Error severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ErrorLog:
    """Single error log entry."""

    def __init__(
        self,
        error_id: str,
        message: str,
        context: str,
        severity: ErrorSeverity,
        traceback_str: str = "",
    ):
        self.error_id = error_id
        self.timestamp = datetime.now().isoformat()
        self.message = message
        self.context = context
        self.severity = severity.value
        self.traceback = traceback_str

    def to_dict(self) -> Dict:
        return {
            "error_id": self.error_id,
            "timestamp": self.timestamp,
            "message": self.message,
            "context": self.context,
            "severity": self.severity,
            "traceback": self.traceback,
        }


class ErrorHandler:
    """
    Central error handler: capture, classify, log, and count errors.
    """

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = log_dir
        self.error_logs: Dict[str, ErrorLog] = {}
        self.error_stats: Dict[str, int] = {
            "info": 0,
            "warning": 0,
            "error": 0,
            "critical": 0,
        }
        os.makedirs(log_dir, exist_ok=True)
        self._setup_logging()

    def _setup_logging(self):
        log_file = os.path.join(self.log_dir, "app.log")
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
        )
        self.logger = logging.getLogger("AppErrorHandler")

    def handle_error(
        self,
        error: Exception,
        context: str = "unknown",
        severity: ErrorSeverity = ErrorSeverity.ERROR,
    ) -> str:
        """
        Log an error and return a tracking error_id.
        """
        import uuid

        error_id = f"err_{uuid.uuid4().hex[:8]}"
        tb_str = traceback.format_exc()
        error_log = ErrorLog(
            error_id=error_id,
            message=str(error),
            context=context,
            severity=severity,
            traceback_str=tb_str,
        )
        self.error_logs[error_id] = error_log
        self.error_stats[error_log.severity] += 1
        log_method = getattr(self.logger, severity.value.lower(), self.logger.error)
        log_method(f"[{error_id}] {context}: {str(error)}")
        self._save_error_log(error_log)
        return error_id

    def handle_exception(self, exception: Exception, context: str = "unknown") -> str:
        """Handle exception with auto severity."""
        if isinstance(exception, (KeyError, ValueError, TypeError, asyncio.TimeoutError)):
            severity = ErrorSeverity.WARNING
        else:
            severity = ErrorSeverity.ERROR
        return self.handle_error(exception, context, severity)

    def _save_error_log(self, error_log: ErrorLog):
        log_file = os.path.join(self.log_dir, "errors.jsonl")
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(error_log.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            self.logger.error(f"Failed to save error log: {e}")

    def get_error_log(self, error_id: str) -> Optional[Dict]:
        if error_id in self.error_logs:
            return self.error_logs[error_id].to_dict()
        return None


error_handler = ErrorHandler()
