"""
Azure Pricing Data Collector Function

This Azure Function runs on a schedule and collects pricing data from the Azure Pricing API
based on filters stored in Azure App Configuration. The data is sent to Azure Data Explorer (ADX)
for analytics and visualization in Grafana.

Features:
- Timer-triggered execution (configurable schedule)
- HTTP trigger for manual execution
- Configuration stored in Azure App Configuration
- Rate limiting and retry logic for Azure Pricing API
- Batch processing for ADX ingestion
- Comprehensive logging and error handling
"""

import logging
import json
import asyncio
import os
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from uuid import uuid4

import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.appconfiguration import AzureAppConfigurationClient
import aiohttp
from asyncio_throttle import Throttler

from adx_client import ADXClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Reduce verbosity of Azure SDK libraries
logging.getLogger('azure').setLevel(logging.WARNING)
logging.getLogger('azure.core').setLevel(logging.WARNING)
logging.getLogger('azure.identity').setLevel(logging.WARNING)
logging.getLogger('azure.kusto').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('aiohttp').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Configuration from environment variables
class Config:
    """Configuration from environment variables."""

    # Azure App Configuration
    APP_CONFIG_ENDPOINT = os.getenv("APP_CONFIG_ENDPOINT")

    # Azure Data Explorer
    ADX_CLUSTER_URI = os.getenv("ADX_CLUSTER_URI")
    ADX_DATABASE_NAME = os.getenv("ADX_DATABASE_NAME", "pricing-metrics")
    ADX_TABLE_NAME = os.getenv("ADX_TABLE_NAME", "pricing_metrics")

    # Azure Pricing API
    AZURE_PRICING_API_BASE = "https://prices.azure.com/api/retail/prices"
    RATE_LIMIT_REQUESTS_PER_MINUTE = 100
    REQUEST_TIMEOUT = 30
    MAX_RETRIES = 3
    RETRY_BACKOFF_FACTOR = 2
    BATCH_SIZE = 1000
    MAX_CONCURRENT_REQUESTS = 10

    # Processing limits
    MAX_PRICING_ITEMS = int(os.getenv("MAX_PRICING_ITEMS", "-1"))  # -1 = unlimited

    @classmethod
    def validate(cls) -> bool:
        """Validate required configuration."""
        if not cls.APP_CONFIG_ENDPOINT:
            logger.error("APP_CONFIG_ENDPOINT environment variable is required")
            return False
        if not cls.ADX_CLUSTER_URI:
            logger.error("ADX_CLUSTER_URI environment variable is required")
            return False
        return True

# Azure Pricing Client
class AzurePricingClient:
    """Client for fetching data from Azure Pricing API."""

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.throttler = Throttler(rate_limit=Config.RATE_LIMIT_REQUESTS_PER_MINUTE, period=60)

    async def __aenter__(self):
        connector = aiohttp.TCPConnector(limit=Config.MAX_CONCURRENT_REQUESTS)
        timeout = aiohttp.ClientTimeout(total=Config.REQUEST_TIMEOUT)
        self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def _make_request_with_retry(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make HTTP request with exponential backoff retry logic."""
        for attempt in range(Config.MAX_RETRIES):
            try:
                async with self.throttler:
                    async with self.session.get(url, params=params) as response:
                        if response.status == 200:
                            return await response.json()
                        elif response.status == 429:  # Rate limited
                            wait_time = Config.RETRY_BACKOFF_FACTOR ** attempt
                            logger.warning(f"Rate limited, waiting {wait_time}s before retry {attempt + 1}/{Config.MAX_RETRIES}")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"HTTP {response.status}: {await response.text()}")
                            response.raise_for_status()
            except asyncio.TimeoutError:
                wait_time = Config.RETRY_BACKOFF_FACTOR ** attempt
                logger.warning(f"Request timeout, retrying in {wait_time}s (attempt {attempt + 1}/{Config.MAX_RETRIES})")
                await asyncio.sleep(wait_time)
            except Exception as e:
                if attempt < Config.MAX_RETRIES - 1:
                    wait_time = Config.RETRY_BACKOFF_FACTOR ** attempt
                    logger.warning(f"Request failed: {e}, retrying in {wait_time}s (attempt {attempt + 1}/{Config.MAX_RETRIES})")
                    await asyncio.sleep(wait_time)
                else:
                    raise

        raise Exception(f"Failed to fetch data after {Config.MAX_RETRIES} attempts")

    async def fetch_pricing_data(self, filters: Dict[str, str], currency_code: str = "USD") -> List[Dict[str, Any]]:
        """Fetch pricing data with pagination."""
        all_items = []
        skip_value = None
        page_number = 0
        total_processed = 0

        base_params = {
            "currencyCode": currency_code,
            "$top": Config.BATCH_SIZE
        }

        # Add filters
        if filters:
            filter_conditions = []
            for key, value in filters.items():
                filter_conditions.append(f"{key} eq '{value}'")
            if filter_conditions:
                base_params["$filter"] = " and ".join(filter_conditions)

        logger.info(f"Starting pricing data fetch with filters: {filters}")
        logger.info(f"Max items limit: {'unlimited' if Config.MAX_PRICING_ITEMS == -1 else Config.MAX_PRICING_ITEMS}")

        try:
            while True:
                page_number += 1
                params = base_params.copy()

                if skip_value:
                    params["$skip"] = skip_value

                logger.info(f"Fetching page {page_number} (processed: {total_processed})")

                # Fetch page data
                data = await self._make_request_with_retry(Config.AZURE_PRICING_API_BASE, params)

                items = data.get("Items", [])
                if not items:
                    logger.info(f"No more items found on page {page_number}")
                    break

                # Add items to result
                all_items.extend(items)
                total_processed += len(items)

                logger.info(f"Page {page_number}: fetched {len(items)} items (total: {total_processed})")

                # Check if we've reached the limit
                if Config.MAX_PRICING_ITEMS != -1 and total_processed >= Config.MAX_PRICING_ITEMS:
                    logger.info(f"Reached max items limit ({Config.MAX_PRICING_ITEMS}), stopping")
                    break

                # Check for next page
                next_page_link = data.get("NextPageLink")
                if not next_page_link:
                    logger.info("No more pages available")
                    break

                # Extract skip value from next page link
                skip_value = total_processed

        except Exception as e:
            logger.error(f"Error fetching pricing data: {e}")
            raise

        logger.info(f"Completed pricing data fetch: {total_processed} total items across {page_number} pages")
        return all_items

# Configuration Manager
class ConfigurationManager:
    """Manages configuration from Azure App Configuration."""

    def __init__(self):
        self.credential = DefaultAzureCredential()
        self.client = AzureAppConfigurationClient(
            base_url=Config.APP_CONFIG_ENDPOINT,
            credential=self.credential
        )

    def get_pricing_filters(self) -> Dict[str, str]:
        """Get pricing filters from App Configuration."""
        try:
            # Get the pricing filters configuration
            config_setting = self.client.get_configuration_setting(key="pricing-filters")
            if config_setting and config_setting.value:
                filters = json.loads(config_setting.value)
                logger.info(f"Retrieved pricing filters: {filters}")
                return filters
            else:
                logger.warning("No pricing filters found in App Configuration, using empty filters")
                return {}
        except Exception as e:
            logger.error(f"Failed to get pricing filters from App Configuration: {e}")
            return {}

    def get_currency_code(self) -> str:
        """Get currency code from App Configuration."""
        try:
            config_setting = self.client.get_configuration_setting(key="currency-code")
            if config_setting and config_setting.value:
                currency = config_setting.value
                logger.info(f"Retrieved currency code: {currency}")
                return currency
            else:
                logger.info("No currency code found in App Configuration, using USD")
                return "USD"
        except Exception as e:
            logger.error(f"Failed to get currency code from App Configuration: {e}")
            return "USD"

# Main function app
app = func.FunctionApp()

@app.function_name(name="PricingDataCollectorTimer")
@app.timer_trigger(schedule="0 0 2 * * *",  # Daily at 2 AM UTC
                   arg_name="timer",
                   run_on_startup=False,
                   use_monitor=False)
async def pricing_data_collector_timer(timer: func.TimerRequest) -> None:
    """Timer-triggered function to collect pricing data daily."""
    execution_id = str(uuid4())
    logger.info(f"Timer trigger started (execution: {execution_id})")

    if timer.past_due:
        logger.warning(f"Timer function is running late (execution: {execution_id})")

    try:
        await collect_pricing_data(execution_id)
        logger.info(f"Timer execution completed successfully (execution: {execution_id})")
    except Exception as e:
        logger.error(f"Timer execution failed (execution: {execution_id}): {e}")
        raise

@app.function_name(name="PricingDataCollectorHttp")
@app.http_trigger(methods=["POST"],
                  auth_level=func.AuthLevel.FUNCTION,
                  route="collect")
async def pricing_data_collector_http(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP-triggered function to manually collect pricing data."""
    execution_id = str(uuid4())
    logger.info(f"HTTP trigger started (execution: {execution_id})")

    try:
        # Check for custom filters in request body
        custom_filters = {}
        custom_currency = "USD"

        try:
            if req.get_body():
                body = req.get_json()
                custom_filters = body.get("filters", {})
                custom_currency = body.get("currency_code", "USD")
                logger.info(f"Using custom filters from request: {custom_filters}")
        except ValueError:
            pass  # No JSON body, use default configuration

        result = await collect_pricing_data(execution_id, custom_filters, custom_currency)

        return func.HttpResponse(
            json.dumps({
                "execution_id": execution_id,
                "status": "success",
                "message": "Pricing data collection completed",
                "items_processed": result["items_processed"],
                "adx_records_sent": result["adx_records_sent"],
                "duration_seconds": result["duration_seconds"]
            }),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"HTTP execution failed (execution: {execution_id}): {e}")
        return func.HttpResponse(
            json.dumps({
                "execution_id": execution_id,
                "status": "error",
                "message": str(e)
            }),
            status_code=500,
            mimetype="application/json"
        )

async def collect_pricing_data(execution_id: str,
                             custom_filters: Optional[Dict[str, str]] = None,
                             custom_currency: Optional[str] = None) -> Dict[str, Any]:
    """Main logic for collecting pricing data."""
    start_time = datetime.now(timezone.utc)

    # Validate configuration
    if not Config.validate():
        raise Exception("Invalid configuration")

    # Get configuration
    config_manager = ConfigurationManager()

    if custom_filters is not None:
        filters = custom_filters
        currency_code = custom_currency or "USD"
        logger.info(f"Using custom configuration: filters={filters}, currency={currency_code}")
    else:
        filters = config_manager.get_pricing_filters()
        currency_code = config_manager.get_currency_code()
        logger.info(f"Using App Configuration: filters={filters}, currency={currency_code}")

    # Initialize ADX client
    adx_client = ADXClient()
    await adx_client.ensure_table_exists()

    # Fetch pricing data
    logger.info(f"Starting pricing data collection (execution: {execution_id})")

    async with AzurePricingClient() as pricing_client:
        pricing_data = await pricing_client.fetch_pricing_data(filters, currency_code)

    logger.info(f"Fetched {len(pricing_data)} pricing items")

    # Send data to ADX in batches
    adx_records_sent = 0
    batch_size = 100  # ADX batch size

    for i in range(0, len(pricing_data), batch_size):
        batch = pricing_data[i:i + batch_size]

        # Add metadata to each record
        for item in batch:
            item["timestamp"] = start_time.isoformat()
            item["execution_id"] = execution_id

        # Send batch to ADX
        success = await adx_client.send_pricing_metrics_batch(batch)

        if success:
            adx_records_sent += len(batch)
            logger.info(f"Sent batch {i//batch_size + 1} to ADX ({len(batch)} records)")
        else:
            logger.error(f"Failed to send batch {i//batch_size + 1} to ADX")

    end_time = datetime.now(timezone.utc)
    duration = (end_time - start_time).total_seconds()

    logger.info(f"Collection completed (execution: {execution_id}): "
                f"{len(pricing_data)} items fetched, "
                f"{adx_records_sent} records sent to ADX, "
                f"duration: {duration:.2f}s")

    return {
        "items_processed": len(pricing_data),
        "adx_records_sent": adx_records_sent,
        "duration_seconds": duration
    }
