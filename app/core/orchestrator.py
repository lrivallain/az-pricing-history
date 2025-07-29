#!/usr/bin/env python3
"""
Job Orchestrator
================

This module orchestrates the execution of multiple data collectors in a coordinated manner.
It manages collector lifecycle, ADX client sharing, error handling, and results aggregation.

Key Features:
- Multi-collector execution with shared resources
- Centralized error handling and logging
- Results aggregation and reporting
- ADX logging integration
- Graceful failure handling
"""

import logging
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from shared.config import ConfigManager
from shared.adx_client import ADXClientManager
from collectors.azure_pricing_collector import AzurePricingCollector
from collectors.azure_cost_collector import AzureCostCollector

# Import ADX logger for error logging
try:
    from adx_logger import setup_adx_logging, create_crash_logger
    ADX_LOGGING_AVAILABLE = True
except ImportError:
    print("ADX logging module not available - continuing without ADX error logging", file=sys.stderr)
    ADX_LOGGING_AVAILABLE = False


class JobOrchestrator:
    """Orchestrates execution of multiple data collectors."""

    def __init__(self):
        """Initialize the job orchestrator."""
        # Logging should already be configured by main(), so just get a logger
        self.logger = logging.getLogger(__name__)

        self.logger.info("=== Initializing Job Orchestrator ===")

        # Initialize configuration
        self.config_manager = ConfigManager()
        self.config_manager.validate_global_config()
        self.config_manager.log_diagnostics()        # Job metadata
        self.job_id = str(uuid.uuid4())
        self.job_datetime = datetime.now(timezone.utc)
        global_config = self.config_manager.get_global_config()
        self.job_type = global_config['job_type']
        self.is_local = self.job_type.startswith('local') or global_config['environment'] == 'local'

        # Initialize ADX client manager
        adx_cluster_uri = global_config['adx_cluster_uri']
        self.adx_client_manager = ADXClientManager(adx_cluster_uri, self.is_local)

        # Collectors and results
        self.collectors = {}
        self.results = []
        self.adx_log_handler = None

        self.logger.info(f"Job Orchestrator initialized - Job ID: {self.job_id}")
        self.logger.info(f"Environment: {'local' if self.is_local else 'production'}")

    def _setup_adx_logging(self, adx_client):
        """Set up ADX logging using the shared ADX client."""
        if ADX_LOGGING_AVAILABLE:
            try:
                self.logger.info("Setting up ADX error logging with shared client...")

                global_config = self.config_manager.get_global_config()
                adx_log_level = global_config.get('adx_log_level', 'INFO')

                self.adx_log_handler = setup_adx_logging(
                    kusto_client=adx_client,
                    adx_database=global_config['adx_database'],
                    job_id=self.job_id,
                    job_type=self.job_type,
                    is_local=self.is_local,
                    log_level=adx_log_level
                )

                if self.adx_log_handler:
                    self.logger.info(f"ADX logging configured with level: {adx_log_level}")

                    # Set up crash logger for uncaught exceptions
                    create_crash_logger(
                        kusto_client=adx_client,
                        adx_database=global_config['adx_database'],
                        job_id=self.job_id,
                        job_type=self.job_type,
                        is_local=self.is_local
                    )
                    self.logger.info("Crash logger configured successfully on ADX")
                else:
                    self.logger.warning("ADX logging setup failed")

            except Exception as e:
                self.logger.warning(f"ADX logging setup failed: {e}")
                self.adx_log_handler = None

    def _initialize_collectors(self, collector_names: List[str]) -> None:
        """
        Initialize specified collectors.

        Args:
            collector_names: List of collector names to initialize
        """
        self.logger.info(f"Initializing collectors: {collector_names}")

        for collector_name in collector_names:
            try:
                self.logger.info(f"Initializing {collector_name} collector...")

                # Get collector-specific configuration
                collector_config = self.config_manager.get_collector_config(collector_name)

                # Create collector instance
                if collector_name == 'azure_pricing':
                    collector = AzurePricingCollector(
                        job_id=self.job_id,
                        job_datetime=self.job_datetime,
                        job_type=self.job_type,
                        config=collector_config
                    )
                elif collector_name == 'azure_cost':
                    collector = AzureCostCollector(
                        job_id=self.job_id,
                        job_datetime=self.job_datetime,
                        job_type=self.job_type,
                        config=collector_config
                    )
                else:
                    raise ValueError(f"Unknown collector: {collector_name}")

                # Ensure the collector's logger inherits the correct level
                self._configure_collector_logging(collector)

                self.collectors[collector_name] = collector
                self.logger.info(f"{collector_name} collector initialized successfully")

            except Exception as e:
                error_msg = f"Failed to initialize {collector_name} collector: {e}"
                self.logger.error(error_msg)
                raise

    def _configure_collector_logging(self, collector) -> None:
        """
        Configure logging level for a collector instance.
        
        Args:
            collector: Collector instance to configure
        """
        # Get the current log level from environment
        import os
        log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
        app_level = getattr(logging, log_level)
        
        # Set the level for this specific collector's logger
        collector.logger.setLevel(app_level)
        
        self.logger.debug(f"Set logging level for {collector.collector_name} to {log_level}")

    def _setup_adx_logging(self, adx_client):
        """Set up ADX logging using the shared ADX client."""
        if ADX_LOGGING_AVAILABLE:
            try:
                self.logger.info("Setting up ADX error logging with shared client...")

                global_config = self.config_manager.get_global_config()
                adx_log_level = global_config.get('adx_log_level', 'INFO')

                self.adx_log_handler = setup_adx_logging(
                    kusto_client=adx_client,
                    adx_database=global_config['adx_database'],
                    job_id=self.job_id,
                    job_type=self.job_type,
                    is_local=self.is_local,
                    log_level=adx_log_level
                )

                if self.adx_log_handler:
                    self.logger.info(f"ADX logging configured with level: {adx_log_level}")

                    # Set up crash logger for uncaught exceptions
                    create_crash_logger(
                        kusto_client=adx_client,
                        adx_database=global_config['adx_database'],
                        job_id=self.job_id,
                        job_type=self.job_type,
                        is_local=self.is_local
                    )
                    self.logger.info("Crash logger configured successfully on ADX")
                else:
                    self.logger.warning("ADX logging setup failed")

            except Exception as e:
                self.logger.warning(f"ADX logging setup failed: {e}")
                self.adx_log_handler = None

    def run_collectors(self, collector_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Run specified collectors or all configured collectors.

        Args:
            collector_names: List of collector names to run. If None, runs all configured collectors.

        Returns:
            List of execution results for each collector
        """
        if collector_names is None:
            collector_names = self.config_manager.get_collectors_to_run()

        self.logger.info(f"Starting job execution with collectors: {collector_names}")

        start_time = datetime.now(timezone.utc)

        try:
            # Get shared ADX client
            adx_client = self.adx_client_manager.get_client()
            self.logger.info("ADX client created successfully")

            # Set up ADX logging with shared client
            self._setup_adx_logging(adx_client)

            # Initialize collectors
            self._initialize_collectors(collector_names)

            # Run each collector
            for collector_name in collector_names:
                collector_start_time = datetime.now(timezone.utc)

                try:
                    self.logger.info(f"Starting {collector_name} collector execution...")

                    collector = self.collectors[collector_name]
                    result = collector.run(adx_client)

                    self.results.append(result)
                    self.logger.info(f"{collector_name} collector completed successfully")

                except Exception as e:
                    collector_end_time = datetime.now(timezone.utc)
                    duration = (collector_end_time - collector_start_time).total_seconds()

                    error_result = {
                        'collector_name': collector_name,
                        'status': 'error',
                        'job_id': self.job_id,
                        'job_datetime': self.job_datetime.isoformat(),
                        'job_type': self.job_type,
                        'start_time': collector_start_time.isoformat(),
                        'end_time': collector_end_time.isoformat(),
                        'duration_seconds': duration,
                        'error': str(e)
                    }

                    self.results.append(error_result)
                    self.logger.error(f"{collector_name} collector failed: {e}")

                    # Decide whether to continue with other collectors or fail the entire job
                    # For now, we'll continue with other collectors
                    continue

            end_time = datetime.now(timezone.utc)
            total_duration = (end_time - start_time).total_seconds()

            # Log overall results
            successful_collectors = [r for r in self.results if r['status'] == 'success']
            failed_collectors = [r for r in self.results if r['status'] == 'error']

            self.logger.info(f"Job execution completed in {total_duration:.1f}s")
            self.logger.info(f"Successful collectors: {len(successful_collectors)}")
            self.logger.info(f"Failed collectors: {len(failed_collectors)}")

            if failed_collectors:
                self.logger.warning(f"Some collectors failed: {[r['collector_name'] for r in failed_collectors]}")

            return self.results

        except Exception as e:
            end_time = datetime.now(timezone.utc)
            total_duration = (end_time - start_time).total_seconds()

            error_msg = f"Job execution failed after {total_duration:.1f}s: {e}"
            self.logger.error(error_msg)
            raise

    def get_job_summary(self) -> Dict[str, Any]:
        """Get a summary of the job execution."""
        successful_results = [r for r in self.results if r['status'] == 'success']
        failed_results = [r for r in self.results if r['status'] == 'error']

        total_items_collected = sum(r.get('total_collected', 0) for r in successful_results)
        total_items_ingested = sum(r.get('total_ingested', 0) for r in successful_results)

        return {
            'job_id': self.job_id,
            'job_datetime': self.job_datetime.isoformat(),
            'job_type': self.job_type,
            'total_collectors': len(self.results),
            'successful_collectors': len(successful_results),
            'failed_collectors': len(failed_results),
            'total_items_collected': total_items_collected,
            'total_items_ingested': total_items_ingested,
            'collectors': self.results
        }

    def cleanup(self):
        """Clean up resources."""
        try:
            # Clean up ADX logger first (to flush any pending logs)
            if self.adx_log_handler:
                try:
                    self.logger.info("Flushing ADX error logs...")
                    self.adx_log_handler.close()
                    # Give it a moment to flush
                    time.sleep(2)
                    self.logger.info("ADX error logs flushed")
                except Exception as adx_error:
                    self.logger.warning(f"Error flushing ADX logs: {adx_error}")
                self.adx_log_handler = None

            # Clean up ADX client
            if self.adx_client_manager:
                self.adx_client_manager.close()
                self.logger.info("ADX client closed")

        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")


def main():
    """Main entry point for the job orchestrator."""
    import os

    # Set up basic logging first - use LOG_LEVEL environment variable
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stderr)]
    )

    # Ensure our application loggers also pick up the configured level
    app_level = getattr(logging, log_level)

    # Set level for all our application modules
    logging.getLogger("core").setLevel(app_level)
    logging.getLogger("collectors").setLevel(app_level)
    logging.getLogger("shared").setLevel(app_level)

    # Reduce Azure SDK noise
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("azure.core").setLevel(logging.WARNING)
    logging.getLogger("azure.identity").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)

    logger.info("=== History Data Collection Job Starting ===")
    logger.info(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")

    orchestrator = None
    exit_code = 0

    try:
        orchestrator = JobOrchestrator()
        results = orchestrator.run_collectors()

        # Log summary
        summary = orchestrator.get_job_summary()
        logger.info("=== Job Summary ===")
        logger.info(f"Job ID: {summary['job_id']}")
        logger.info(f"Total collectors: {summary['total_collectors']}")
        logger.info(f"Successful: {summary['successful_collectors']}")
        logger.info(f"Failed: {summary['failed_collectors']}")
        logger.info(f"Total items collected: {summary['total_items_collected']}")
        logger.info(f"Total items ingested: {summary['total_items_ingested']}")

        if summary['failed_collectors'] > 0:
            logger.warning("Some collectors failed - check logs for details")
            exit_code = 1
        else:
            logger.info("SUCCESS: All collectors completed successfully")

    except KeyboardInterrupt:
        logger.warning("Application interrupted by user")
        exit_code = 130

    except Exception as e:
        logger.error(f"FATAL ERROR: {e}")
        traceback.print_exc(file=sys.stderr)

        # Log fatal error to ADX if possible
        try:
            if orchestrator and orchestrator.logger:
                orchestrator.logger.error(f"FATAL APPLICATION ERROR: {e}", exc_info=True)
        except:
            pass  # Don't fail on logging failure

        exit_code = 1

    finally:
        if orchestrator:
            try:
                orchestrator.cleanup()
            except Exception as cleanup_error:
                logger.error(f"Error during cleanup: {cleanup_error}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
