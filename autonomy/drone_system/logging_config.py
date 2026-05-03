"""
Structured JSON logging configuration for Skylink2.

Usage:
    from autonomy.drone_system.logging_config import setup_logging, get_logger
    
    setup_logging(level=logging.INFO)
    logger = get_logger("autonomy.safety_engine", job_id="abc123")
    
    logger.info("Assessing preflight", wind_mps=5.2, battery_percent=85)
    logger.warning("Battery low", battery_percent=18)
    logger.error("RTL triggered", reason="battery_emergency")
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_FORMAT_VERSION = "1.0"

class SkylinkJSONFormatter(logging.Formatter):
    """Formats log records as JSON for machine parsing."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "version": LOG_FORMAT_VERSION,
        }
        
        if hasattr(record, "job_id"):
            log_entry["job_id"] = record.job_id
        if hasattr(record, "phase"):
            log_entry["phase"] = record.phase
        
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "message", "pathname", "process", "processName", "relativeCreated",
                "stack_info", "exc_info", "exc_text", "thread", "threadName",
                "taskName", "job_id", "phase", "_thread_local",
            }:
                if not key.startswith("_"):
                    try:
                        json.dumps({key: value})
                        log_entry[key] = value
                    except (TypeError, ValueError):
                        log_entry[key] = str(value)
        
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
            }
        
        return json.dumps(log_entry, ensure_ascii=False)


class SkylinkTextFormatter(logging.Formatter):
    """Human-readable formatter with structured fields."""
    
    def format(self, record: logging.LogRecord) -> str:
        base = f"{self.formatTime(record)} [{record.levelname}] {record.name}: {record.getMessage()}"
        
        extra = []
        if hasattr(record, "job_id"):
            extra.append(f"job_id={record.job_id}")
        if hasattr(record, "phase"):
            extra.append(f"phase={record.phase}")
        
        for key, value in record.__dict__.items():
            if key not in {"name", "msg", "args", "created", "levelname", "levelno",
                          "message", "exc_info", "job_id", "phase", "_thread_local"}:
                if not key.startswith("_"):
                    extra.append(f"{key}={value}")
        
        if extra:
            base += " | " + " ".join(extra)
        
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        
        return base


def setup_logging(
    level: int = logging.INFO,
    json_format: bool | None = None,
    log_file: Path | None = None,
) -> None:
    """Configure structured logging for Skylink2."""
    if json_format is None:
        json_format = os.environ.get("SKYLINK_LOG_FORMAT", "").lower() == "json"
    
    handlers: list[logging.Handler] = []
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    if json_format:
        console_handler.setFormatter(SkylinkJSONFormatter())
    else:
        console_handler.setFormatter(SkylinkTextFormatter())
    handlers.append(console_handler)
    
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_handler.setFormatter(SkylinkJSONFormatter())
        handlers.append(file_handler)
    
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    for handler in handlers:
        root.addHandler(handler)


class _ContextLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that adds context to every log entry."""
    
    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        extra.update(self.extra)
        kwargs["extra"] = extra
        return msg, kwargs


def get_logger(
    name: str,
    job_id: str | None = None,
    phase: str | None = None,
) -> logging.LoggerAdapter:
    """Get a logger with correlation ID support."""
    logger = logging.getLogger(name)
    return _ContextLoggerAdapter(logger, {"job_id": job_id, "phase": phase})


_thread_local = threading.local()

def set_job_context(job_id: str, phase: str | None = None) -> None:
    """Set thread-local job context for logging."""
    _thread_local.job_id = job_id
    _thread_local.phase = phase


def clear_job_context() -> None:
    """Clear thread-local job context."""
    _thread_local.job_id = None
    _thread_local.phase = None


def safety_log(
    level: int,
    message: str,
    job_id: str | None = None,
    **kwargs,
) -> None:
    """Log a safety-critical event."""
    if level < logging.WARNING:
        level = logging.WARNING
    
    logger = logging.getLogger("autonomy.safety")
    logger.log(level, message, extra={"safety_event": True, **kwargs})
