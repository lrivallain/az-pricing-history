#!/usr/bin/env python3
"""
Configuration Manager
====================

This module provides centralized configuration management for the history data collection system.
It handles environment variables, validation, and collector-specific configurations.

Key Features:
- Environment variable management with defaults
- Configuration validation
- Collector-specific configuration extraction
- Type conversion and parsing utilities
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Union


class ConfigManager:
    """Centralized configuration management."""

    def __init__(self):
        """Initialize configuration manager."""
        self.logger = logging.getLogger(__name__)

        # Load from .env.local file if available
        self._load_env_file()

        # Load configuration from environment variables
        self._config = self._load_config()

    def _load_env_file(self):
        """Load environment variables from .env.local file if it exists."""
        # Look for .env.local in the current directory and parent directories
        current_dir = Path.cwd()
        possible_locations = [
            current_dir / '.env.local',
            current_dir.parent / '.env.local',
            Path(__file__).parent.parent.parent / '.env.local',  # Go up from shared/config.py
        ]

        env_file = None
        for location in possible_locations:
            if location.exists():
                env_file = location
                break

        if env_file:
            self.logger.debug(f"Loading environment from: {env_file}")
            try:
                with open(env_file, 'r') as f:
                    for line_num, line in enumerate(f, 1):
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            try:
                                key, value = line.split('=', 1)
                                key = key.strip()
                                value = value.strip()

                                # Remove quotes if present
                                if value.startswith('"') and value.endswith('"'):
                                    value = value[1:-1]
                                elif value.startswith("'") and value.endswith("'"):
                                    value = value[1:-1]

                                # Only set if not already in environment (environment takes precedence)
                                if key not in os.environ:
                                    os.environ[key] = value

                            except ValueError:
                                self.logger.warning(f"Invalid line {line_num} in {env_file}: {line}")

            except Exception as e:
                self.logger.warning(f"Error loading {env_file}: {e}")
        else:
            self.logger.debug("No .env.local file found in standard locations")

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from environment variables."""
        config = {
            # ADX Configuration
            'adx_cluster_uri': os.getenv('ADX_CLUSTER_URI'),
            'adx_database': os.getenv('ADX_DATABASE_NAME'),

            # Job Configuration
            'job_type': os.getenv('JOB_TYPE', 'manual'),
            'environment': os.getenv('ENVIRONMENT', 'production'),

            # Azure Pricing Collector Configuration
            'enable_azure_pricing_collector': os.getenv('ENABLE_AZURE_PRICING_COLLECTOR', 'false').lower() == 'true',
            'azure_pricing_max_items': os.getenv('AZURE_PRICING_MAX_ITEMS', '-1'),
            'azure_pricing_api_retry_attempts': os.getenv('AZURE_PRICING_API_RETRY_ATTEMPTS', '3'),
            'azure_pricing_api_retry_delay': os.getenv('AZURE_PRICING_API_RETRY_DELAY', '2.0'),
            'azure_pricing_filters': os.getenv('AZURE_PRICING_FILTERS', '{}'),

            # Azure Cost Collector Configuration (example)
            'enable_cost_collector': os.getenv('ENABLE_COST_COLLECTOR', 'false').lower() == 'true',
            'cost_timeframe': os.getenv('COST_TIMEFRAME', 'MonthToDate'),
            'cost_granularity': os.getenv('COST_GRANULARITY', 'Daily'),

            # Logging Configuration
            'log_level': os.getenv('LOG_LEVEL', 'INFO'),
            'adx_log_level': os.getenv('ADX_LOG_LEVEL', 'WARNING'),

            # Azure Authentication
            'azure_client_id': os.getenv('AZURE_CLIENT_ID'),
            'azure_tenant_id': os.getenv('AZURE_TENANT_ID'),
            'azure_subscription_id': os.getenv('AZURE_SUBSCRIPTION_ID'),

            # Container Apps specific
            'job_execution_id': os.getenv('JOB_EXECUTION_ID'),
            'msi_endpoint': os.getenv('MSI_ENDPOINT'),
            'identity_endpoint': os.getenv('IDENTITY_ENDPOINT'),
            'identity_header': os.getenv('IDENTITY_HEADER'),
        }

        self.logger.debug("Configuration loaded from environment variables")
        return config

    def get_global_config(self) -> Dict[str, Any]:
        """Get global configuration applicable to all collectors."""
        return {
            'adx_cluster_uri': self._config['adx_cluster_uri'],
            'adx_database': self._config['adx_database'],
            'job_type': self._config['job_type'],
            'environment': self._config['environment'],
            'log_level': self._config['log_level'],
            'adx_log_level': self._config['adx_log_level'],
        }

    def get_collector_config(self, collector_name: str) -> Dict[str, Any]:
        """
        Get configuration specific to a collector.

        Args:
            collector_name: Name of the collector (e.g., 'azure_pricing')

        Returns:
            Dictionary containing collector-specific configuration
        """
        # Start with global config
        config = self.get_global_config()

        if collector_name == 'azure_pricing':
            config.update({
                'api_retry_attempts': self._config['azure_pricing_api_retry_attempts'],
                'api_retry_delay': self._config['azure_pricing_api_retry_delay'],
                'max_items': self.get_int('azure_pricing_max_items', '-1'),
                'filters_json': self.get_json('azure_pricing_filters', {}),
            })
        elif collector_name == 'azure_cost':
            config.update({
                'azure_subscription_id': self._config['azure_subscription_id'],
                'cost_timeframe': self._config['cost_timeframe'],
                'cost_granularity': self._config['cost_granularity'],
            })

        # Add more collectors here as needed
        # elif collector_name == 'other_collector':
        #     config.update({ ... })

        return config

    def validate_global_config(self) -> None:
        """
        Validate global configuration.

        Raises:
            ValueError: If required configuration is missing or invalid
        """
        required_configs = ['adx_cluster_uri', 'adx_database']

        for config_key in required_configs:
            if not self._config.get(config_key):
                raise ValueError(f"Required configuration '{config_key}' is missing")

        # Validate log levels
        valid_log_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if self._config['log_level'].upper() not in valid_log_levels:
            raise ValueError(f"Invalid log_level: {self._config['log_level']}")

        if self._config['adx_log_level'].upper() not in valid_log_levels:
            raise ValueError(f"Invalid adx_log_level: {self._config['adx_log_level']}")

    def get_collectors_to_run(self) -> list[str]:
        """
        Get list of collectors to run based on configuration.

        Returns:
            List of collector names to execute
        """
        # For now, we'll determine this based on environment variables
        # In the future, this could be configurable via COLLECTORS_TO_RUN env var

        collectors = []

        # Check if azure_pricing collector is enabled
        if self.get_bool('enable_azure_pricing_collector', False):
            collectors.append('azure_pricing')

        # Check if azure_cost collector is enabled
        if self.get_bool('enable_cost_collector', False):
            collectors.append('azure_cost')

        # Example: if os.getenv('ENABLE_OTHER_COLLECTOR') == 'true':
        #     collectors.append('other_collector')

        logging.debug(f"Collectors to run: {collectors}")

        return collectors

    def get_value(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value by key.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value
        """
        return self._config.get(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        """Get an integer configuration value."""
        value = self._config.get(key, default)
        try:
            return int(value)
        except (ValueError, TypeError):
            self.logger.warning(f"Invalid integer value for {key}: {value}, using default: {default}")
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        """Get a float configuration value."""
        value = self._config.get(key, default)
        try:
            return float(value)
        except (ValueError, TypeError):
            self.logger.warning(f"Invalid float value for {key}: {value}, using default: {default}")
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get a boolean configuration value."""
        value = self._config.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes', 'on')
        return default

    def get_json(self, key: str, default: Dict[str, Any] = None) -> Dict[str, Any]:
        """Get a JSON configuration value."""
        if default is None:
            default = '{}'

        value = self._config.get(key, '{}')
        # Remove quotes if present
        if isinstance(value, str) and (value.startswith('"') and value.endswith('"') or
                                       value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        try:
            json.loads(value)
            return value
        except json.JSONDecodeError as e:
            self.logger.warning(f"Invalid JSON value for {key}: {value}, using default: {default}")
            self.logger.error(f"JSON decode error: {e}")
            return default

    def log_diagnostics(self) -> None:
        """Log diagnostic information about the configuration."""
        self.logger.info("=== Configuration Diagnostics ===")

        # Key environment variables for diagnostics
        diagnostic_keys = [
            'adx_cluster_uri', 'adx_database', 'job_type',
            'environment', 'azure_client_id', 'job_execution_id'
        ]

        for key in diagnostic_keys:
            value = self._config.get(key)
            if key == 'identity_header':
                # Don't log sensitive values
                self.logger.info(f"{key}: {'SET' if value else 'NOT SET'}")
            else:
                self.logger.info(f"{key}: {value}")

        # Masked sensitive values
        sensitive_keys = ['msi_endpoint', 'identity_endpoint', 'identity_header']
        for key in sensitive_keys:
            value = self._config.get(key)
            self.logger.info(f"{key}: {'SET' if value else 'NOT SET'}")

    def __str__(self) -> str:
        """String representation of configuration (without sensitive values)."""
        safe_config = {k: v for k, v in self._config.items()
                      if 'token' not in k.lower() and 'secret' not in k.lower() and 'key' not in k.lower()}
        return f"ConfigManager({safe_config})"
