#!/usr/bin/env python3
"""
Azure Pricing Data Collector
============================

This module implements data collection from the Azure Pricing API.
It extends the BaseCollector interface to provide pricing-specific functionality.

Key Features:
- Real-time data collection and ingestion
- API retry logic with exponential backoff
- FILTERS_JSON support for targeted data collection
- Rate limiting and throttling management
"""

import json
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

import requests
from azure.kusto.data.exceptions import KustoServiceError

from core.base_collector import BaseCollector


class AzurePricingCollector(BaseCollector):
    """Azure Pricing API data collector."""

    def __init__(self, job_id: str, job_datetime: datetime, job_type: str, config: Dict[str, Any]):
        """Initialize the Azure Pricing collector."""
        super().__init__(job_id, job_datetime, job_type, config)

        # API configuration
        self.api_url = "https://prices.azure.com/api/retail/prices"
        self.api_retry_attempts = int(config.get('api_retry_attempts', 3))
        self.api_retry_delay = float(config.get('api_retry_delay', 2.0))

        # ADX ingestion retry configuration
        self.adx_retry_attempts = 5
        self.adx_retry_delay = 30 # seconds

        # Filters configuration
        self.filters_json = config.get('filters_json', '{}')

        # Max items - treat -1 as unlimited
        max_items_config = int(config.get('max_items', float('inf')))
        self.max_items = float('inf') if max_items_config == -1 else max_items_config

        self.logger.info(f"Azure Pricing Collector initialized - Max items: {'unlimited' if self.max_items == float('inf') else self.max_items}")
        self.logger.info(f"API retry: {self.api_retry_attempts} attempts, {self.api_retry_delay}s delay")
        self.logger.info(f"ADX retry: {self.adx_retry_attempts} attempts, {self.adx_retry_delay}s delay")

    @property
    def collector_name(self) -> str:
        """Return the name of this collector."""
        return "azure_pricing"

    @property
    def table_name(self) -> str:
        """Return the ADX table name for pricing data."""
        return "pricing_metrics"

    @property
    def table_schema(self) -> str:
        """Return the ADX table creation command for pricing data."""
        return """
            .create table ['pricing_metrics'] (
                jobId: string,
                jobDateTime: datetime,
                jobType: string,
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

    def validate_config(self) -> None:
        """Validate Azure Pricing collector configuration."""
        required_configs = ['adx_database']

        for config_key in required_configs:
            if not self.config.get(config_key):
                raise ValueError(f"Required configuration '{config_key}' is missing")

        # Validate filters_json if provided
        if self.filters_json and self.filters_json != '{}':
            try:
                json.loads(self.filters_json)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid FILTERS_JSON format: {e}")

    def build_filter_params(self) -> Dict[str, str]:
        """
        Build filter parameters for the API request.

        Returns:
            Dictionary of query parameters for the API request
        """
        params = {}

        if not self.filters_json or self.filters_json == '{}':
            return params

        try:
            filters = json.loads(self.filters_json)
            if not filters:
                return params

            # Convert filters to OData format
            filter_parts = []
            for key, value in filters.items():
                if isinstance(value, str):
                    # String values need quotes and proper escaping for OData
                    # Note: Filter values are case-sensitive as per Azure API docs
                    escaped_value = value.replace("'", "''")
                    filter_parts.append(f"{key} eq '{escaped_value}'")
                elif isinstance(value, (int, float)):
                    filter_parts.append(f"{key} eq {value}")
                elif isinstance(value, bool):
                    filter_parts.append(f"{key} eq {str(value).lower()}")
                else:
                    self.logger.warning(f"Unsupported filter value type for {key}: {type(value)}")

            if filter_parts:
                odata_filter = " and ".join(filter_parts)
                params['$filter'] = odata_filter
                self.logger.info(f"Using filter: {odata_filter}")

        except Exception as e:
            self.logger.error(f"Error building filter parameters: {e}")

        return params

    def make_api_request(self, session: requests.Session, url: str, params: Dict[str, str] = None) -> Dict[str, Any]:
        """Make API request with retry logic for transient failures."""
        last_exception = None

        for attempt in range(self.api_retry_attempts):
            try:
                if params:
                    self.logger.debug(f"API request attempt {attempt + 1}/{self.api_retry_attempts}")
                    self.logger.info(f"URL: {url}")
                    self.logger.info(f"Params: {params}")
                    response = session.get(url, params=params)
                else:
                    self.logger.debug(f"API request attempt {attempt + 1}/{self.api_retry_attempts}")
                    self.logger.debug(f"Full URL: {url}")
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

    def ingest_batch_to_adx(self, adx_client, items: List[Dict], batch_id: str) -> bool:
        """Ingest a batch of items to ADX with retry logic for throttling."""
        if not items:
            return True

        last_exception = None

        for attempt in range(self.adx_retry_attempts):
            try:
                self.logger.debug(f"Ingesting batch {batch_id} with {len(items)} items (attempt {attempt + 1}/{self.adx_retry_attempts})")

                # Log a sample item to verify the data structure (only on first attempt)
                if attempt == 0 and items:
                    sample_item = items[0]
                    self.logger.debug(f"Sample item keys: {list(sample_item.keys())}")
                    self.logger.debug(f"jobId: {sample_item.get('jobId', 'MISSING')}")
                    self.logger.debug(f"jobDateTime: {sample_item.get('jobDateTime', 'MISSING')}")
                    self.logger.debug(f"jobType: {sample_item.get('jobType', 'MISSING')}")

                # Convert to JSON Lines format
                json_lines = '\n'.join(json.dumps(item, default=str) for item in items)
                ingest_command = f".ingest inline into table {self.table_name} with (format='multijson') <|\n{json_lines}"

                adx_database = self.config['adx_database']
                adx_client.execute(adx_database, ingest_command)

                if attempt > 0:
                    self.logger.info(f"Batch {batch_id} ingested successfully after {attempt + 1} attempts")
                else:
                    self.logger.debug(f"Batch {batch_id} ingested successfully")
                return True

            except KustoServiceError as e:
                error_msg = str(e)
                last_exception = e

                # Check if it's a throttling error (429)
                if "throttled" in error_msg.lower() or "429" in error_msg:
                    # Calculate exponential backoff delay for throttling
                    throttle_delay = self.adx_retry_delay * (2 ** attempt)
                    self.logger.warning(f"ADX throttling detected for batch {batch_id} on attempt {attempt + 1}/{self.adx_retry_attempts}, waiting {throttle_delay}s before retry")

                    if attempt < self.adx_retry_attempts - 1:
                        time.sleep(throttle_delay)
                        continue
                else:
                    # For other Kusto errors, use regular delay
                    self.logger.warning(f"ADX service error for batch {batch_id} on attempt {attempt + 1}/{self.adx_retry_attempts}: {error_msg}")

                    if attempt < self.adx_retry_attempts - 1:
                        time.sleep(self.adx_retry_delay)
                        continue

            except Exception as e:
                # Handle other exceptions (network, etc.)
                error_msg = str(e)
                last_exception = e

                self.logger.warning(f"Ingestion error for batch {batch_id} on attempt {attempt + 1}/{self.adx_retry_attempts}: {error_msg}")

                if attempt < self.adx_retry_attempts - 1:
                    time.sleep(self.adx_retry_delay)
                    continue

        # All retries exhausted
        self.logger.error(f"Failed to ingest batch {batch_id} after {self.adx_retry_attempts} attempts: {last_exception}")
        return False

    def collect_data(self, adx_client) -> int:
        """Collect pricing data from Azure API and ingest to ADX in real-time."""
        total_items = 0
        total_ingested = 0

        try:
            self.logger.info("Starting real-time pricing data collection and ingestion")

            # Build filter parameters
            filter_params = self.build_filter_params()

            # Start with base API URL
            next_page_link = self.api_url
            page_count = 0

            # Configure session
            session = requests.Session()
            session.timeout = 300  # 5 minutes

            if filter_params:
                self.logger.info(f"Starting collection from: {self.api_url} with filters: {filter_params}")
            else:
                self.logger.info(f"Starting collection from: {self.api_url} (no filters)")

            while next_page_link and total_items < self.max_items:
                page_count += 1
                self.logger.info(f"Fetching and ingesting page {page_count}...")

                # For first page, use base URL with filter params
                # For subsequent pages, use NextPageLink as-is (already contains filters + pagination)
                if page_count == 1:
                    # First page: apply our filters to the base API URL
                    data = self.make_api_request(session, next_page_link, filter_params)
                    self.logger.debug(f"First page request with filters applied")
                else:
                    # Subsequent pages: use NextPageLink directly (contains filters + $skip)
                    data = self.make_api_request(session, next_page_link)
                    self.logger.debug(f"Pagination request using NextPageLink: {next_page_link}")

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

                    # Add job metadata to each item
                    enriched_item = self.enrich_item(item)
                    page_items.append(enriched_item)
                    total_items += 1

                # Ingest this page's items immediately to ADX
                if page_items:
                    success = self.ingest_batch_to_adx(adx_client, page_items, f"page-{page_count}")
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

            self.total_collected = total_items
            self.total_ingested = total_ingested

            self.logger.info(f"Real-time collection and ingestion completed: {total_ingested} items processed")
            return total_ingested

        except Exception as e:
            error_msg = f"Real-time collection and ingestion failed: {e}"
            self.logger.error(error_msg)
            raise
