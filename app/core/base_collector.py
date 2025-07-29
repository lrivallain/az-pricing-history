#!/usr/bin/env python3
"""
Base Data Collector Interface
============================

This module defines the abstract base class for all data collectors in the history data collection system.
All collectors must implement this interface to ensure consistent behavior and orchestration.

Key Features:
- Standardized initialization and execution interface
- Common ADX integration patterns
- Shared configuration management
- Unified error handling and logging
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import logging
import uuid


class BaseCollector(ABC):
    """Abstract base class for all data collectors."""

    def __init__(self, job_id: str, job_datetime: datetime, job_type: str, config: Dict[str, Any]):
        """
        Initialize the collector with common parameters.

        Args:
            job_id: Unique identifier for this job execution
            job_datetime: Timestamp when the job started
            job_type: Type of job execution (e.g., 'manual', 'scheduled')
            config: Configuration dictionary containing collector-specific settings
        """
        self.job_id = job_id
        self.job_datetime = job_datetime
        self.job_type = job_type
        self.config = config
        self.logger = logging.getLogger(f"{self.__class__.__module__}.{self.__class__.__name__}")

        # Common configuration
        self.is_local = self.job_type.startswith('local') or config.get('environment', 'production') == 'local'
        self.max_items = self._parse_max_items(config.get('max_items', '5000'))

        # Statistics
        self.total_collected = 0
        self.total_ingested = 0
        self.start_time = None
        self.end_time = None

    def _parse_max_items(self, max_items_str: str) -> float:
        """Parse max items configuration, handling -1 as unlimited."""
        try:
            if max_items_str == '-1':
                return float('inf')
            return int(max_items_str)
        except (ValueError, TypeError):
            self.logger.warning(f"Invalid max_items value '{max_items_str}', defaulting to 5000")
            return 5000

    @property
    @abstractmethod
    def collector_name(self) -> str:
        """Return the name of this collector (e.g., 'azure_pricing')."""
        pass

    @property
    @abstractmethod
    def table_name(self) -> str:
        """Return the ADX table name for this collector's data."""
        pass

    @property
    @abstractmethod
    def table_schema(self) -> str:
        """Return the ADX table creation command for this collector's data."""
        pass

    @abstractmethod
    def validate_config(self) -> None:
        """
        Validate collector-specific configuration.

        Raises:
            ValueError: If configuration is invalid
        """
        pass

    @abstractmethod
    def collect_data(self, adx_client) -> int:
        """
        Collect data from the source and ingest to ADX.

        Args:
            adx_client: Authenticated ADX client for data ingestion

        Returns:
            Number of items successfully collected and ingested

        Raises:
            Exception: If collection fails
        """
        pass

    def initialize(self, adx_client) -> None:
        """
        Initialize the collector (create tables, validate connections, etc.).

        Args:
            adx_client: Authenticated ADX client
        """
        self.logger.info(f"Initializing {self.collector_name} collector")

        # Validate configuration
        self.validate_config()

        # Create ADX table if needed
        self._create_adx_table(adx_client)

        self.logger.info(f"{self.collector_name} collector initialized successfully")

    def run(self, adx_client) -> Dict[str, Any]:
        """
        Execute the data collection process.

        Args:
            adx_client: Authenticated ADX client

        Returns:
            Dictionary containing execution results and statistics
        """
        self.start_time = datetime.now(timezone.utc)

        try:
            self.logger.info(f"Starting {self.collector_name} data collection")

            # Initialize if not already done
            self.initialize(adx_client)

            # Collect data
            self.total_ingested = self.collect_data(adx_client)

            self.end_time = datetime.now(timezone.utc)
            duration = (self.end_time - self.start_time).total_seconds()

            result = {
                'collector_name': self.collector_name,
                'status': 'success',
                'job_id': self.job_id,
                'job_datetime': self.job_datetime.isoformat(),
                'job_type': self.job_type,
                'start_time': self.start_time.isoformat(),
                'end_time': self.end_time.isoformat(),
                'duration_seconds': duration,
                'total_collected': self.total_collected,
                'total_ingested': self.total_ingested,
                'table_name': self.table_name
            }

            self.logger.info(f"{self.collector_name} collection completed: {self.total_ingested} items in {duration:.1f}s")
            return result

        except Exception as e:
            self.end_time = datetime.now(timezone.utc)
            duration = (self.end_time - self.start_time).total_seconds() if self.start_time else 0

            result = {
                'collector_name': self.collector_name,
                'status': 'error',
                'job_id': self.job_id,
                'job_datetime': self.job_datetime.isoformat(),
                'job_type': self.job_type,
                'start_time': self.start_time.isoformat() if self.start_time else None,
                'end_time': self.end_time.isoformat(),
                'duration_seconds': duration,
                'total_collected': self.total_collected,
                'total_ingested': self.total_ingested,
                'table_name': self.table_name,
                'error': str(e)
            }

            self.logger.error(f"{self.collector_name} collection failed after {duration:.1f}s: {e}")
            raise

    def _create_adx_table(self, adx_client) -> None:
        """Create the ADX table if it doesn't exist."""
        try:
            from azure.kusto.data.exceptions import KustoServiceError

            adx_database = self.config['adx_database']
            adx_client.execute_mgmt(adx_database, self.table_schema)
            self.logger.info(f"ADX table '{self.table_name}' created or already exists")

        except KustoServiceError as e:
            if "already exists" in str(e).lower():
                self.logger.info(f"ADX table '{self.table_name}' already exists")
            else:
                self.logger.error(f"Error creating ADX table '{self.table_name}': {e}")
                raise

    def enrich_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Add common job metadata to a data item.

        Args:
            item: Original data item

        Returns:
            Enriched item with job metadata
        """
        return {
            **item,
            'jobId': self.job_id,
            'jobDateTime': self.job_datetime.isoformat(),
            'jobType': self.job_type
        }

    def get_stats(self) -> Dict[str, Any]:
        """Return current collection statistics."""
        duration = 0
        if self.start_time:
            end_time = self.end_time or datetime.now(timezone.utc)
            duration = (end_time - self.start_time).total_seconds()

        return {
            'collector_name': self.collector_name,
            'total_collected': self.total_collected,
            'total_ingested': self.total_ingested,
            'duration_seconds': duration,
            'items_per_second': self.total_ingested / duration if duration > 0 else 0
        }
