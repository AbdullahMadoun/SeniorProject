"""
Tests for structured logging configuration.
"""
from __future__ import annotations

import json
import logging
import pytest
from io import StringIO
from unittest.mock import patch

class TestJSONFormatter:
    """Tests for JSON log formatting."""
    
    def test_formats_as_json(self):
        """Log output must be valid JSON."""
        from autonomy.drone_system.logging_config import SkylinkJSONFormatter
        
        formatter = SkylinkJSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["message"] == "Test message"
        assert parsed["level"] == "INFO"
        assert "timestamp" in parsed
    
    def test_includes_job_id(self):
        """Log output must include job_id when set."""
        from autonomy.drone_system.logging_config import SkylinkJSONFormatter
        
        formatter = SkylinkJSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test",
            args=(),
            exc_info=None,
        )
        record.job_id = "abc123"
        
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["job_id"] == "abc123"
    
    def test_includes_extra_fields(self):
        """Extra fields appear in output."""
        from autonomy.drone_system.logging_config import SkylinkJSONFormatter
        
        formatter = SkylinkJSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test",
            args=(),
            exc_info=None,
        )
        record.wind_mps = 5.2
        record.battery_percent = 85
        
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["wind_mps"] == 5.2
        assert parsed["battery_percent"] == 85
    
    def test_includes_version(self):
        """Log output must include version."""
        from autonomy.drone_system.logging_config import SkylinkJSONFormatter, LOG_FORMAT_VERSION
        
        formatter = SkylinkJSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test",
            args=(),
            exc_info=None,
        )
        
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["version"] == LOG_FORMAT_VERSION


class TestSetupLogging:
    """Tests for logging setup."""
    
    def test_console_output_json_format(self):
        """setup_logging outputs JSON to console when configured."""
        from autonomy.drone_system.logging_config import setup_logging, SkylinkJSONFormatter
        
        stream = StringIO()
        
        with patch("sys.stdout", stream):
            setup_logging(level=logging.INFO, json_format=True)
            logger = logging.getLogger("test_setup")
            logger.info("Test message")
        
        output = stream.getvalue()
        parsed = json.loads(output.strip())
        assert parsed["message"] == "Test message"
    
    def test_console_output_text_format(self):
        """setup_logging outputs text when configured."""
        from autonomy.drone_system.logging_config import setup_logging
        
        stream = StringIO()
        
        with patch("sys.stdout", stream):
            setup_logging(level=logging.INFO, json_format=False)
            logger = logging.getLogger("test_setup_text")
            logger.info("Test message")
        
        output = stream.getvalue()
        assert "Test message" in output
        assert "INFO" in output


class TestGetLogger:
    """Tests for get_logger with correlation IDs."""
    
    def test_returns_logger_adapter(self):
        """get_logger returns LoggerAdapter."""
        from autonomy.drone_system.logging_config import get_logger
        
        logger = get_logger("test", job_id="abc123")
        assert isinstance(logger, logging.LoggerAdapter)
    
    def test_context_in_json_output(self):
        """Context appears in JSON log output."""
        from autonomy.drone_system.logging_config import setup_logging, get_logger
        
        stream = StringIO()
        
        with patch("sys.stdout", stream):
            setup_logging(level=logging.INFO, json_format=True)
            logger = get_logger("test_context", job_id="abc123")
            logger.info("Test with context")
        
        output = stream.getvalue()
        parsed = json.loads(output.strip())
        assert parsed["job_id"] == "abc123"
        assert parsed["logger"] == "test_context"


class TestSafetyLog:
    """Tests for safety_log function."""
    
    def test_upgrades_to_warning(self):
        """safety_log upgrades DEBUG/INFO to WARNING."""
        from autonomy.drone_system.logging_config import safety_log, setup_logging
        import logging
        
        stream = StringIO()
        
        # Ensure clean logging state
        root = logging.getLogger()
        root.handlers.clear()
        
        with patch("sys.stdout", stream):
            setup_logging(level=logging.INFO, json_format=True)
            safety_log(logging.INFO, "Safety event", job_id="test")
        
        output = stream.getvalue()
        parsed = json.loads(output.strip())
        assert parsed["level"] == "WARNING"
    
    def test_includes_safety_event_flag(self):
        """safety_log includes safety_event flag."""
        from autonomy.drone_system.logging_config import safety_log, setup_logging
        import logging
        
        stream = StringIO()
        
        # Ensure clean logging state
        root = logging.getLogger()
        root.handlers.clear()
        
        with patch("sys.stdout", stream):
            setup_logging(level=logging.INFO, json_format=True)
            safety_log(logging.WARNING, "Safety event", job_id="test")
        
        output = stream.getvalue()
        parsed = json.loads(output.strip())
        assert parsed["safety_event"] is True
