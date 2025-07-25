#!/usr/bin/env python3
"""
Synchronous Azure Pricing Collection Tool
Simplified version using requests instead of aiohttp for better reliability
"""

import json
import logging
import os
import sys
import uuid
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import traceback
from urllib.parse import quote

import requests
from azure.identity import DefaultAzureCredential
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
from azure.kusto.data.exceptions import KustoServiceError

# Import ADX logger for error logging
try:
    from sync_adx_logger import setup_adx_logging, create_crash_logger
    ADX_LOGGING_AVAILABLE = True
except ImportError:
    # Can't use logger yet, so use stderr
    import sys
    print("ADX logging module not available - continuing without ADX error logging", file=sys.stderr)
    ADX_LOGGING_AVAILABLE = False


class SyncPricingCollector:
    """Synchronous Azure Pricing API data collector with ADX integration."""

    def __init__(self):
        """Initialize the collector."""
        # Setup basic logging first so we can use logger throughout initialization
        self.setup_basic_logging()
        self.logger = logging.getLogger(__name__)

        self.logger.info("=== Initializing Sync Pricing Collector ===")

        # Basic configuration
        self.adx_cluster_uri = os.getenv('ADX_CLUSTER_URI')
        self.adx_database = os.getenv('ADX_DATABASE_NAME', 'pricing-metrics')
        self.max_items_str = os.getenv('MAX_PRICING_ITEMS', '5000')
        self.logger.warning(f"MAX_PRICING_ITEMS environment variable = '{self.max_items_str}'")
        self.max_items = float('inf') if self.max_items_str == '-1' else int(self.max_items_str)
        self.logger.warning(f"Parsed max_items = {self.max_items}")
        self.job_type = os.getenv('JOB_TYPE', 'manual')
        self.is_local = self.job_type.startswith('local') or os.getenv('ENVIRONMENT', 'production') == 'local'

        # API retry configuration
        self.api_retry_attempts = int(os.getenv('API_RETRY_ATTEMPTS', '3'))
        self.api_retry_delay = float(os.getenv('API_RETRY_DELAY', '2.0'))

        # API filtering configuration
        self.filters_json = os.getenv('FILTERS_JSON')
        self.api_filters = None
        # if self.filters_json:
        #     try:
        #         filters_data = json.loads(self.filters_json)
        #         self.api_filters = filters_data.get('filters', {})
        #         print(f"✓ API filters loaded: {self.api_filters}", file=sys.stderr, flush=True)
        #     except json.JSONDecodeError as e:
        #         print(f"✗ Invalid FILTERS_JSON format: {e}", file=sys.stderr, flush=True)
        self.api_filters = None

        # Job metadata
        self.job_id = str(uuid.uuid4())
        self.job_datetime = datetime.now(timezone.utc)

        # Clients
        self.kusto_client = None
        self.adx_log_handler = None

        # Setup enhanced logging with ADX integration
        self.setup_enhanced_logging()

        # Validate configuration
        if not self.adx_cluster_uri:
            raise ValueError("ADX_CLUSTER_URI environment variable is required")
        if not self.adx_database:
            raise ValueError("ADX_DATABASE_NAME environment variable is required")

        # Print diagnostic information
        self._print_diagnostics()

        self.logger.info(f"Job ID: {self.job_id}")
        self.logger.warning(f"Max items: {'unlimited' if self.max_items == float('inf') else self.max_items} (from env: '{self.max_items_str}')")
        self.logger.info(f"Environment: {'local' if self.is_local else 'production'}")
        self.logger.info(f"API retry attempts: {self.api_retry_attempts}")
        self.logger.info(f"API retry delay: {self.api_retry_delay}s")
        if self.api_filters:
            self.logger.info(f"API filtering enabled with {len(self.api_filters)} filters")

        self.logger.info(f"Sync Pricing Collector initialized - Job ID: {self.job_id}")

    def _print_diagnostics(self):
        """Print diagnostic information about the environment."""
        self.logger.info("=== Environment Diagnostics ===")

        # Key environment variables
        env_vars = [
            'AZURE_CLIENT_ID', 'ADX_CLUSTER_URI', 'ADX_DATABASE_NAME',
            'JOB_TYPE', 'JOB_EXECUTION_ID', 'MSI_ENDPOINT',
            'IDENTITY_ENDPOINT', 'IDENTITY_HEADER'
        ]

        for var in env_vars:
            value = os.getenv(var)
            if var == 'IDENTITY_HEADER':
                self.logger.info(f"{var}: {'SET' if value else 'NOT SET'}")
            else:
                self.logger.info(f"{var}: {value}")

    def setup_basic_logging(self):
        """Configure basic logging before full initialization."""
        log_level = os.getenv('LOG_LEVEL', 'DEBUG').upper()

        # Configure root logger
        logging.basicConfig(
            level=getattr(logging, log_level),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(sys.stderr)
            ]
        )

        # Reduce Azure SDK noise
        logging.getLogger("azure").setLevel(logging.WARNING)
        logging.getLogger("azure.core").setLevel(logging.WARNING)
        logging.getLogger("azure.identity").setLevel(logging.WARNING)

    def setup_enhanced_logging(self):
        """Configure enhanced logging with ADX integration."""
        # We'll set up ADX logging later, after the Kusto client is created
        pass

    def setup_adx_logging_with_client(self, kusto_client):
        """Set up ADX logging using an existing authenticated Kusto client."""
        # Set up ADX logging for ERROR level and above (if available)
        if ADX_LOGGING_AVAILABLE:
            try:
                self.logger.info("Setting up ADX error logging with existing Kusto client...")
                self.adx_log_handler = setup_adx_logging(
                    kusto_client=kusto_client,
                    adx_database=self.adx_database,
                    job_id=self.job_id,
                    job_type=self.job_type,
                    is_local=self.is_local,
                    log_level='WARNING'  # Only log WARNING and above to ADX
                )

                if self.adx_log_handler:
                    self.logger.info("ADX error logging configured")

                    # Set up crash logger for uncaught exceptions
                    create_crash_logger(
                        kusto_client=kusto_client,
                        adx_database=self.adx_database,
                        job_id=self.job_id,
                        job_type=self.job_type,
                        is_local=self.is_local
                    )
                    self.logger.info("Crash logger configured")
                else:
                    self.logger.warning("ADX error logging setup failed")

            except Exception as e:
                self.logger.warning(f"ADX error logging setup failed: {e}")
                self.adx_log_handler = None

    def create_kusto_client(self) -> KustoClient:
        """Create Kusto client with retries and multiple auth methods."""
        if self.kusto_client:
            return self.kusto_client

        auth_methods = []

        # In production Container Apps, try Managed Identity first
        if not self.is_local:
            client_id = os.getenv('AZURE_CLIENT_ID')
            if client_id:
                # Container Apps uses user-assigned managed identity
                auth_methods.append(('User-assigned Managed Identity (Token)', lambda: self._create_kusto_with_default_credential()))
                auth_methods.append(('User-assigned Managed Identity (Direct)', lambda: self._create_kusto_with_managed_identity(client_id)))
            else:
                # Fallback to system-assigned if no client_id
                auth_methods.append(('System-assigned Managed Identity', lambda: self._create_kusto_with_managed_identity(None)))
                auth_methods.append(('DefaultAzureCredential', lambda: self._create_kusto_with_default_credential()))
        else:
            # Local development - try different methods
            auth_methods.append(('Azure CLI Token', lambda: self._create_kusto_with_cli_token()))
            auth_methods.append(('DefaultAzureCredential', lambda: self._create_kusto_with_default_credential()))

        last_exception = None

        for auth_name, auth_method in auth_methods:
            for attempt in range(3):  # 3 attempts per auth method
                try:
                    self.logger.info(f"Trying {auth_name} (attempt {attempt + 1})...")
                    self.logger.info(f"Attempting Kusto connection with {auth_name}, attempt {attempt + 1}")

                    self.kusto_client = auth_method()

                    # Test the connection
                    test_query = ".show version"
                    self.kusto_client.execute_mgmt("", test_query)

                    self.logger.info(f"Kusto client created successfully with {auth_name}")
                    return self.kusto_client

                except Exception as e:
                    last_exception = e
                    self.logger.warning(f"{auth_name} attempt {attempt + 1} failed: {e}")

                    if attempt < 2:  # Wait before retry
                        wait_time = (attempt + 1) * 5
                        self.logger.info(f"Waiting {wait_time} seconds before retry...")
                        time.sleep(wait_time)

        # All auth methods failed
        error_msg = f"Failed to create Kusto client with all authentication methods. Last error: {last_exception}"
        self.logger.error(error_msg)
        raise Exception(error_msg)

    def _create_kusto_with_managed_identity(self, client_id: Optional[str] = None) -> KustoClient:
        """Create Kusto client with Managed Identity."""
        # In Container Apps, we need to use the client_id for user-assigned managed identity
        if client_id:
            self.logger.info(f"Using User-assigned Managed Identity with client_id: {client_id}")
            kcsb = KustoConnectionStringBuilder.with_aad_managed_service_identity_authentication(
                self.adx_cluster_uri, client_id
            )
        else:
            self.logger.info("Using System-assigned Managed Identity")
            kcsb = KustoConnectionStringBuilder.with_aad_managed_service_identity_authentication(
                self.adx_cluster_uri
            )
        return KustoClient(kcsb)

    def _create_kusto_with_default_credential(self) -> KustoClient:
        """Create Kusto client with DefaultAzureCredential."""
        from azure.identity import ManagedIdentityCredential

        if self.is_local:
            # Local development - exclude managed identity
            credential = DefaultAzureCredential(exclude_managed_identity_credential=True)
            self.logger.info("Using DefaultAzureCredential (excluding managed identity)")
        else:
            # Container Apps environment - prioritize managed identity
            client_id = os.getenv('AZURE_CLIENT_ID')
            if client_id:
                self.logger.info(f"Using ManagedIdentityCredential with client_id: {client_id}")
                credential = ManagedIdentityCredential(client_id=client_id)
            else:
                self.logger.info("Using DefaultAzureCredential with managed identity")
                credential = DefaultAzureCredential()

        token = credential.get_token("https://help.kusto.windows.net/.default")
        kcsb = KustoConnectionStringBuilder.with_aad_user_token_authentication(
            self.adx_cluster_uri, token.token
        )
        return KustoClient(kcsb)

    def _create_kusto_with_cli_token(self) -> KustoClient:
        """Create Kusto client with Azure CLI token (local development)."""
        adx_token = os.getenv('AZURE_ADX_TOKEN')
        if adx_token:
            kcsb = KustoConnectionStringBuilder.with_aad_user_token_authentication(
                self.adx_cluster_uri, adx_token
            )
            return KustoClient(kcsb)
        else:
            raise Exception("AZURE_ADX_TOKEN not available")

    def make_api_request(self, session: requests.Session, url: str) -> Dict[str, Any]:
        """Make API request with retry logic for transient failures."""
        last_exception = None

        for attempt in range(self.api_retry_attempts):
            try:
                self.logger.debug(f"API request attempt {attempt + 1}/{self.api_retry_attempts}: {url}")

                response = session.get(url)

                # Handle different HTTP status codes
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    # Rate limiting - always retry with longer delay
                    retry_after = int(response.headers.get('Retry-After', self.api_retry_delay * 2))
                    self.logger.warning(f"Rate limited (429), waiting {retry_after}s before retry {attempt + 1}/{self.api_retry_attempts}")
                    time.sleep(retry_after)
                    last_exception = Exception(f"Rate limited (429) on attempt {attempt + 1}")
                    continue
                elif 500 <= response.status_code < 600:
                    # Server errors - retry
                    self.logger.warning(f"Server error {response.status_code} on attempt {attempt + 1}/{self.api_retry_attempts}")
                    last_exception = Exception(f"Server error {response.status_code}: {response.text}")
                else:
                    # Client errors (4xx except 429) - don't retry
                    raise Exception(f"API request failed with status {response.status_code}: {response.text}")

            except requests.exceptions.RequestException as e:
                # Network/connection errors - retry
                self.logger.warning(f"Network error on attempt {attempt + 1}/{self.api_retry_attempts}: {e}")
                last_exception = e

            # Wait before retry (except on last attempt)
            if attempt < self.api_retry_attempts - 1:
                self.logger.info(f"Waiting {self.api_retry_delay}s before retry...")
                time.sleep(self.api_retry_delay)

        # All retries exhausted
        raise Exception(f"API request failed after {self.api_retry_attempts} attempts: {last_exception}")

    def build_api_url(self, base_url: str = "https://prices.azure.com/api/retail/prices") -> str:
        """Build API URL with optional filters."""
        if not self.api_filters:
            return base_url

        # Build filter string for Azure Pricing API
        filter_parts = []
        for key, value in self.api_filters.items():
            # Escape single quotes in values
            escaped_value = str(value).replace("'", "''")
            filter_parts.append(f"{key} eq '{escaped_value}'")

        if filter_parts:
            filter_string = " and ".join(filter_parts)
            # URL encode the filter string
            encoded_filter = quote(filter_string)
            url_with_filters = f"{base_url}?$filter={encoded_filter}"
            self.logger.info(f"Using filtered API URL: {url_with_filters}")
            return url_with_filters

        return base_url

    def collect_and_ingest_pricing_data(self):
        """Collect pricing data from Azure API and ingest to ADX in real-time."""
        total_items = 0
        total_ingested = 0

        try:
            self.logger.info("Starting real-time pricing data collection and ingestion")

            # Initialize ADX client and table
            client = self.create_kusto_client()
            self.create_adx_table_if_not_exists(client)

            # Set up ADX logging now that we have an authenticated client
            self.setup_adx_logging_with_client(client)

            # Build initial API URL with optional filters
            api_url = self.build_api_url()
            next_page_link = api_url
            page_count = 0

            # Configure session
            session = requests.Session()
            session.timeout = 300  # 5 minutes

            self.logger.info(f"Starting collection from: {api_url}")

            while next_page_link and total_items < self.max_items:
                page_count += 1
                self.logger.info(f"Fetching and ingesting page {page_count}...")

                # Use retry logic for API request
                data = self.make_api_request(session, next_page_link)
                items = data.get('Items', [])

                if not items:
                    self.logger.info("No more items found, stopping pagination")
                    break

                # Process items for this page
                page_items = []
                for item in items:
                    # Check limit before processing the item
                    if total_items >= self.max_items:
                        self.logger.info(f"Stopping item processing: reached max items limit of {self.max_items}")
                        break

                    # Add job metadata to each item using the correct column names
                    enriched_item = {
                        **item,
                        'JobId': self.job_id,
                        'JobDateTime': self.job_datetime.isoformat(),
                        'JobType': self.job_type,
                        'CollectionTimestamp': datetime.now(timezone.utc).isoformat()
                    }
                    page_items.append(enriched_item)
                    total_items += 1

                # Ingest this page's items immediately to ADX
                if page_items:
                    success = self.ingest_batch_to_adx(client, page_items, f"page-{page_count}")
                    if success:
                        total_ingested += len(page_items)
                        self.logger.info(f"Page {page_count}: collected and ingested {len(page_items)} items (total: {total_ingested})")
                    else:
                        raise Exception(f"Failed to ingest page {page_count} with {len(page_items)} items")

                # Clear page items from memory
                page_items.clear()

                # Stop if we've reached the maximum before getting next page
                if total_items >= self.max_items:
                    self.logger.info(f"Reached maximum items limit ({self.max_items if self.max_items != float('inf') else 'unlimited'}), stopping collection")
                    break

                # Get next page
                next_page_link = data.get('NextPageLink')

                # Add delay to respect rate limits
                time.sleep(1)

            self.logger.info(f"Real-time collection and ingestion completed: {total_ingested} items processed")
            return total_ingested

        except Exception as e:
            error_msg = f"Real-time collection and ingestion failed: {e}"
            self.logger.error(error_msg)
            raise

    def create_adx_table_if_not_exists(self, client: KustoClient):
        """Create the pricing metrics table if it doesn't exist."""
        create_table_command = """
            .create table ['pricing_metrics'] (
                JobId: string,
                JobDateTime: datetime,
                JobType: string,
                CollectionTimestamp: datetime,
                currencyCode: string,
                tierMinimumUnits: real,
                retailPrice: real,
                unitPrice: real,
                armRegionName: string,
                location: string,
                effectiveStartDate: datetime,
                meterId: string,
                meterName: string,
                productId: string,
                skuId: string,
                productName: string,
                skuName: string,
                serviceName: string,
                serviceId: string,
                serviceFamily: string,
                unitOfMeasure: string,
                type: string,
                isPrimaryMeterRegion: bool,
                armSkuName: string,
                reservationTerm: string,
                savingsPlan: dynamic
            ) with (docstring = 'Azure pricing data collected from Azure Pricing API')
        """
        try:
            client.execute_mgmt(self.adx_database, create_table_command)
            self.logger.info("ADX table 'pricing_metrics' created or already exists")
        except KustoServiceError as e:
            if "already exists" in str(e).lower():
                self.logger.info("ADX table 'pricing_metrics' already exists")
            else:
                self.logger.error(f"Error creating ADX table: {e}")
                raise

    def ingest_batch_to_adx(self, client: KustoClient, items: List[Dict], batch_id: str) -> bool:
        """Ingest a batch of items to ADX and return success status."""
        try:
            if not items:
                return True

            self.logger.debug(f"Ingesting batch {batch_id} with {len(items)} items")

            # Log a sample item to verify the data structure
            if items:
                sample_item = items[0]
                self.logger.debug(f"Sample item keys: {list(sample_item.keys())}")
                self.logger.debug(f"JobId: {sample_item.get('JobId', 'MISSING')}")
                self.logger.debug(f"JobDateTime: {sample_item.get('JobDateTime', 'MISSING')}")
                self.logger.debug(f"JobType: {sample_item.get('JobType', 'MISSING')}")
                self.logger.debug(f"CollectionTimestamp: {sample_item.get('CollectionTimestamp', 'MISSING')}")

            # Convert to JSON Lines format
            json_lines = '\n'.join(json.dumps(item, default=str) for item in items)
            ingest_command = f".ingest inline into table pricing_metrics with (format='multijson') <|\n{json_lines}"

            client.execute(self.adx_database, ingest_command)
            self.logger.debug(f"Batch {batch_id} ingested successfully")
            return True

        except Exception as e:
            self.logger.error(f"Failed to ingest batch {batch_id}: {e}")
            return False

    def run(self):
        """Run the real-time collection and ingestion process."""
        start_time = datetime.now(timezone.utc)

        try:
            self.logger.info("=== Starting real-time pricing collection job ===")

            # Collect and ingest data in real-time
            total_processed = self.collect_and_ingest_pricing_data()

            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()

            success_msg = f"Job completed successfully: {total_processed} items in {duration:.1f} seconds"
            self.logger.info(success_msg)

        except Exception as e:
            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()

            error_msg = f"Job failed after {duration:.1f} seconds: {e}"
            self.logger.error(error_msg)
            raise
        finally:
            if self.kusto_client:
                pass  # Synchronous client doesn't need explicit closing

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

            # Clean up Kusto client
            if self.kusto_client:
                self.kusto_client = None
                self.logger.info("Kusto client cleaned up")

        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")


def main():
    """Main entry point."""
    # Set up basic logging first
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stderr)]
    )
    logger = logging.getLogger(__name__)

    logger.info("=== Azure Sync Pricing Collector Starting ===")
    logger.info(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")

    collector = None
    exit_code = 0

    try:
        collector = SyncPricingCollector()
        collector.run()
        logger.info("SUCCESS: Job completed")

    except KeyboardInterrupt:
        logger.warning("Application interrupted by user")
        exit_code = 130

    except Exception as e:
        logger.error(f"FATAL ERROR: {e}")
        traceback.print_exc(file=sys.stderr)

        # Log fatal error to ADX if possible
        try:
            if collector and collector.logger:
                collector.logger.error(f"FATAL APPLICATION ERROR: {e}", exc_info=True)
        except:
            pass  # Don't fail on logging failure

        exit_code = 1

    finally:
        if collector:
            try:
                collector.cleanup()
            except Exception as cleanup_error:
                logger.error(f"Error during cleanup: {cleanup_error}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
