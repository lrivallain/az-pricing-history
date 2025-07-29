#!/usr/bin/env python3
"""
Synchronous ADX Logger Module for Azure Pricing Collection Application
======================================================================

This module provides a custom logging handler that stores log messages in Azure Data Explorer (ADX)
using the synchronous azure-kusto-data library.

Key Features:
- Automatic table creation in ADX
- Synchronous batch processing of log messages
- Error handling to prevent logging failures from crashing the main application
- Structured log storage with job context
- Configurable log levels and batch sizes
"""

import json
import logging
import os
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from queue import Queue, Empty
from typing import Optional, Dict, Any, List

from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
from azure.kusto.data.exceptions import KustoServiceError


class SyncADXLogHandler(logging.Handler):
    """Synchronous ADX Log Handler that processes log records in a background thread."""

    def __init__(self, kusto_client: KustoClient, adx_database: str, job_id: str,
                 job_type: str, is_local: bool = False, log_level: str = 'ERROR',
                 batch_size: int = 50, flush_interval: int = 30):
        """
        Initialize the ADX log handler.

        Args:
            kusto_client: An existing authenticated Kusto client
            adx_database: The ADX database name
            job_id: The job ID for this execution
            job_type: The type of job (e.g., 'manual', 'scheduled')
            is_local: Whether running in local development mode
            log_level: Minimum log level to send to ADX (default: ERROR)
            batch_size: Number of log records to batch before sending
            flush_interval: Maximum seconds to wait before flushing logs
        """
        super().__init__()

        # Configuration
        self.kusto_client = kusto_client
        self.adx_database = adx_database
        self.job_id = job_id
        self.job_type = job_type
        self.is_local = is_local
        self.batch_size = batch_size
        self.flush_interval = flush_interval

        # Set log level
        level_map = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
            'CRITICAL': logging.CRITICAL
        }
        self.setLevel(level_map.get(log_level.upper(), logging.ERROR))

        # Threading components
        self.log_queue = Queue()
        self.shutdown_event = threading.Event()
        self.worker_thread = None

        # Initialize and start worker thread
        try:
            self._create_log_table()
            self._start_worker_thread()
        except Exception as e:
            print(f"Failed to initialize ADX logging: {e}", file=sys.stderr)
            raise

    def _create_log_table(self):
        """Create the job_logs table if it doesn't exist."""
        # First try to drop the table if it exists with old schema
        drop_table_command = ".drop table ['job_logs'] ifexists"

        create_table_command = """
            .create table ['job_logs'] (
                Timestamp: datetime,
                JobId: string,
                JobType: string,
                LogLevel: string,
                LoggerName: string,
                Message: string,
                ThreadName: string,
                ProcessName: string,
                FunctionName: string,
                LineNumber: int,
                ExceptionInfo: string,
                ExceptionType: string,
                StackTrace: string,
                Environment: string,
                AdditionalContext: string
            ) with (docstring = 'Application logs from Azure Pricing Collection jobs')
        """

        try:
            # Drop existing table to recreate with new schema
            self.kusto_client.execute_mgmt(self.adx_database, drop_table_command)
            # Create table with new schema
            self.kusto_client.execute_mgmt(self.adx_database, create_table_command)
        except KustoServiceError as e:
            if "already exists" not in str(e).lower():
                raise Exception(f"Failed to create job_logs table: {e}")

    def _start_worker_thread(self):
        """Start the background worker thread that processes log records."""
        self.worker_thread = threading.Thread(target=self._process_logs, daemon=True)
        self.worker_thread.start()

    def _process_logs(self):
        """Background worker that processes log records from the queue."""
        log_batch = []
        last_flush_time = time.time()

        while not self.shutdown_event.is_set():
            try:
                # Try to get a log record (with timeout)
                try:
                    log_record = self.log_queue.get(timeout=1.0)
                    log_batch.append(log_record)
                    self.log_queue.task_done()
                except Empty:
                    pass  # Timeout is expected, continue to check flush conditions

                # Check if we should flush the batch
                current_time = time.time()
                should_flush = (
                    len(log_batch) >= self.batch_size or
                    (log_batch and (current_time - last_flush_time) >= self.flush_interval)
                )

                if should_flush and log_batch:
                    self._flush_batch(log_batch)
                    log_batch.clear()
                    last_flush_time = current_time

            except Exception as e:
                # Don't let logging errors crash the worker thread
                print(f"Error in ADX log worker thread: {e}", file=sys.stderr)
                time.sleep(5)  # Wait before retrying

        # Flush any remaining logs on shutdown
        if log_batch:
            self._flush_batch(log_batch)

    def _flush_batch(self, log_batch: List[Dict[str, Any]]):
        """Flush a batch of log records to ADX."""
        if not log_batch:
            return

        try:
            # Convert to JSON Lines format
            json_lines = '\n'.join(json.dumps(record, default=str) for record in log_batch)
            ingest_command = f".ingest inline into table job_logs with (format='multijson') <|\n{json_lines}"

            self.kusto_client.execute(self.adx_database, ingest_command)

        except Exception as e:
            # Don't crash on logging failures - just print to stderr
            print(f"Failed to flush log batch to ADX: {e}", file=sys.stderr)

    def emit(self, record: logging.LogRecord):
        """Process a log record and add it to the queue for ADX ingestion."""
        try:
            # Extract exception information if present
            exception_info = ""
            exception_type = ""
            stack_trace = ""

            if record.exc_info:
                exception_type = record.exc_info[0].__name__ if record.exc_info[0] else ""
                exception_info = str(record.exc_info[1]) if record.exc_info[1] else ""
                stack_trace = self.format(record)

            # Get thread and process information
            thread_name = threading.current_thread().name if threading.current_thread() else ""
            process_name = os.getpid() if os.getpid() else ""

            # Format the log record for ADX
            log_entry = {
                'Timestamp': datetime.now(timezone.utc).isoformat(),
                'JobId': self.job_id,
                'JobType': self.job_type,
                'LogLevel': record.levelname,
                'LoggerName': record.name or "",
                'Message': record.getMessage(),
                'ThreadName': thread_name,
                'ProcessName': str(process_name),
                'FunctionName': getattr(record, 'funcName', '') or "",
                'LineNumber': getattr(record, 'lineno', 0) or 0,
                'ExceptionInfo': exception_info,
                'ExceptionType': exception_type,
                'StackTrace': stack_trace,
                'Environment': 'local' if self.is_local else 'production',
                'AdditionalContext': f"Module: {getattr(record, 'module', '')}, Pathname: {getattr(record, 'pathname', '')}"
            }

            # Add to queue (non-blocking)
            try:
                self.log_queue.put_nowait(log_entry)
            except:
                # Queue is full - drop the log to avoid blocking
                pass

        except Exception:
            # Don't let logging errors crash the application
            pass

    def close(self):
        """Close the handler and flush all pending logs."""
        try:
            # Signal shutdown
            self.shutdown_event.set()

            # Wait for worker thread to finish (with timeout)
            if self.worker_thread and self.worker_thread.is_alive():
                self.worker_thread.join(timeout=10)

            # Process any remaining items in the queue
            remaining_logs = []
            while not self.log_queue.empty():
                try:
                    remaining_logs.append(self.log_queue.get_nowait())
                except Empty:
                    break

            if remaining_logs:
                self._flush_batch(remaining_logs)

        except Exception as e:
            print(f"Error closing ADX log handler: {e}", file=sys.stderr)

        super().close()


def setup_adx_logging(kusto_client: KustoClient, adx_database: str, job_id: str,
                     job_type: str, is_local: bool = False, log_level: str = 'ERROR') -> Optional[SyncADXLogHandler]:
    """
    Set up ADX logging for the application.

    Args:
        kusto_client: An existing authenticated Kusto client
        adx_database: The ADX database name
        job_id: The job ID for this execution
        job_type: The type of job (e.g., 'manual', 'scheduled')
        is_local: Whether running in local development mode
        log_level: Minimum log level to send to ADX

    Returns:
        ADX log handler if successful, None otherwise
    """
    try:
        # Create ADX log handler
        adx_handler = SyncADXLogHandler(
            kusto_client=kusto_client,
            adx_database=adx_database,
            job_id=job_id,
            job_type=job_type,
            is_local=is_local,
            log_level=log_level
        )

        # Add to root logger
        root_logger = logging.getLogger()
        root_logger.addHandler(adx_handler)

        return adx_handler

    except Exception as e:
        print(f"Failed to setup ADX logging: {e}", file=sys.stderr)
        return None


def create_crash_logger(kusto_client: KustoClient, adx_database: str, job_id: str,
                       job_type: str, is_local: bool = False):
    """
    Set up a crash logger that captures unhandled exceptions and logs them to ADX.

    Args:
        kusto_client: An existing authenticated Kusto client
        adx_database: The ADX database name
        job_id: The job ID for this execution
        job_type: The type of job
        is_local: Whether running in local development mode
    """
    def exception_handler(exc_type, exc_value, exc_traceback):
        """Handle uncaught exceptions by logging them to ADX."""
        if issubclass(exc_type, KeyboardInterrupt):
            # Don't log keyboard interrupts
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        try:
            # Create a temporary ADX handler for crash logging
            crash_handler = SyncADXLogHandler(
                kusto_client=kusto_client,
                adx_database=adx_database,
                job_id=job_id,
                job_type=job_type,
                is_local=is_local,
                log_level='ERROR'
            )

            # Create logger and log the crash
            crash_logger = logging.getLogger('crash_logger')
            crash_logger.addHandler(crash_handler)
            crash_logger.setLevel(logging.ERROR)

            crash_logger.error(
                f"UNHANDLED EXCEPTION: {exc_type.__name__}: {exc_value}",
                exc_info=(exc_type, exc_value, exc_traceback)
            )

            # Give it a moment to flush
            time.sleep(2)
            crash_handler.close()

        except Exception:
            # If crash logging fails, fall back to default behavior
            pass

        # Call the default exception handler
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    # Set the exception handler
    sys.excepthook = exception_handler
