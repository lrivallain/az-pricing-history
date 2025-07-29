#!/usr/bin/env python3
"""
Azure Cost Management Data Collector (Example Template)
=======================================================

This module demonstrates how to implement a new collector for the history data collection system.
This is a template/example for collecting Azure Cost Management data.

Key Features:
- Extends BaseCollector interface
- Implements collector-specific data retrieval
- Defines custom ADX table schema
- Provides configuration validation
"""

import json
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

from azure.kusto.data.exceptions import KustoServiceError
from core.base_collector import BaseCollector


class AzureCostCollector(BaseCollector):
    """Azure Cost Management data collector (example template)."""

    def __init__(self, job_id: str, job_datetime: datetime, job_type: str, config: Dict[str, Any]):
        """Initialize the Azure Cost collector."""
        super().__init__(job_id, job_datetime, job_type, config)

        # Cost-specific configuration
        self.subscription_id = config.get('azure_subscription_id')
        self.cost_timeframe = config.get('cost_timeframe', 'MonthToDate')  # MonthToDate, LastMonth, etc.
        self.cost_granularity = config.get('cost_granularity', 'Daily')  # Daily, Monthly

        self.logger.info(f"Azure Cost Collector initialized - Subscription: {self.subscription_id}")
        self.logger.info(f"Timeframe: {self.cost_timeframe}, Granularity: {self.cost_granularity}")

    @property
    def collector_name(self) -> str:
        """Return the name of this collector."""
        return "azure_cost"

    @property
    def table_name(self) -> str:
        """Return the ADX table name for cost data."""
        return "cost_metrics"

    @property
    def table_schema(self) -> str:
        """Return the ADX table creation command for cost data."""
        return """
            .create table ['cost_metrics'] (
                jobId: string,
                jobDateTime: datetime,
                jobType: string,
                collectorName: string,
                subscriptionId: string,
                resourceGroupName: string,
                resourceName: string,
                resourceType: string,
                serviceFamily: string,
                serviceName: string,
                location: string,
                meterCategory: string,
                meterSubCategory: string,
                meterName: string,
                usageDate: datetime,
                currency: string,
                pretaxCost: real,
                cost: real,
                unitOfMeasure: string,
                billingAccountId: string,
                billingProfileId: string,
                invoiceSectionId: string,
                tags: dynamic
            ) with (docstring = 'Azure cost data collected from Azure Cost Management API')
        """

    def validate_config(self) -> None:
        """Validate Azure Cost collector configuration."""
        required_configs = ['adx_database', 'azure_subscription_id']

        for config_key in required_configs:
            if not self.config.get(config_key):
                raise ValueError(f"Required configuration '{config_key}' is missing")

        # Validate timeframe
        valid_timeframes = ['MonthToDate', 'BillingMonthToDate', 'TheLastMonth', 'TheLastBillingMonth']
        if self.cost_timeframe not in valid_timeframes:
            raise ValueError(f"Invalid cost_timeframe '{self.cost_timeframe}'. Valid values: {valid_timeframes}")

        # Validate granularity
        valid_granularities = ['Daily', 'Monthly']
        if self.cost_granularity not in valid_granularities:
            raise ValueError(f"Invalid cost_granularity '{self.cost_granularity}'. Valid values: {valid_granularities}")

    def collect_data(self, adx_client) -> int:
        """
        Collect cost data from Azure Cost Management API and ingest to ADX.

        NOTE: This is a template implementation. The actual implementation would
        require Azure Cost Management SDK and proper authentication.
        """
        total_ingested = 0

        try:
            self.logger.info("Starting Azure Cost Management data collection")

            # This is where you would implement the actual cost data collection
            # Example pseudocode:

            # 1. Authenticate with Azure Cost Management API
            # from azure.mgmt.consumption import ConsumptionManagementClient
            # cost_client = ConsumptionManagementClient(credential, self.subscription_id)

            # 2. Query cost data
            # cost_data = cost_client.usage_details.list(
            #     scope=f"/subscriptions/{self.subscription_id}",
            #     expand="properties/meterDetails",
            #     filter=f"properties/usageStart ge '{start_date}' and properties/usageEnd le '{end_date}'"
            # )

            # 3. Process and enrich data
            # For this template, we'll simulate some data
            sample_cost_data = self._generate_sample_cost_data()

            # 4. Ingest data to ADX in batches
            batch_size = 1000
            for i in range(0, len(sample_cost_data), batch_size):
                batch = sample_cost_data[i:i + batch_size]

                # Enrich each item with job metadata
                enriched_batch = [self.enrich_item(item) for item in batch]

                # Ingest to ADX
                success = self.ingest_batch_to_adx(adx_client, enriched_batch, f"batch-{i//batch_size + 1}")
                if success:
                    total_ingested += len(enriched_batch)
                    self.logger.info(f"Ingested batch {i//batch_size + 1}: {len(enriched_batch)} items (total: {total_ingested})")
                else:
                    raise Exception(f"Failed to ingest batch {i//batch_size + 1}")

                # Rate limiting
                time.sleep(0.1)

            self.total_collected = len(sample_cost_data)
            self.total_ingested = total_ingested

            self.logger.info(f"Azure Cost Management collection completed: {total_ingested} items processed")
            return total_ingested

        except Exception as e:
            error_msg = f"Azure Cost Management collection failed: {e}"
            self.logger.error(error_msg)
            raise

    def _generate_sample_cost_data(self) -> List[Dict[str, Any]]:
        """Generate sample cost data for template demonstration."""
        # This is just example data - replace with actual API calls
        sample_data = []

        base_date = datetime.now(timezone.utc) - timedelta(days=30)

        for i in range(100):  # Generate 100 sample records
            usage_date = base_date + timedelta(days=i % 30)

            sample_data.append({
                'subscriptionId': self.subscription_id,
                'resourceGroupName': f'rg-example-{i % 5}',
                'resourceName': f'vm-example-{i % 10}',
                'resourceType': 'Microsoft.Compute/virtualMachines',
                'serviceFamily': 'Compute',
                'serviceName': 'Virtual Machines',
                'location': ['eastus', 'westus2', 'northeurope'][i % 3],
                'meterCategory': 'Virtual Machines',
                'meterSubCategory': 'Dv3/DSv3 Series',
                'meterName': 'D2s v3',
                'usageDate': usage_date.isoformat(),
                'currency': 'USD',
                'pretaxCost': round(24.56 + (i * 0.1), 2),
                'cost': round(26.79 + (i * 0.11), 2),
                'unitOfMeasure': 'Hours',
                'billingAccountId': '12345678-1234-1234-1234-123456789012',
                'billingProfileId': 'ABCD-EFGH-1234-5678',
                'invoiceSectionId': 'IJKL-MNOP-9876-5432',
                'tags': json.dumps({
                    'Environment': ['Dev', 'Test', 'Prod'][i % 3],
                    'CostCenter': f'CC{1000 + (i % 3)}',
                    'Owner': ['alice', 'bob', 'charlie'][i % 3]
                })
            })

        return sample_data

    def ingest_batch_to_adx(self, adx_client, items: List[Dict], batch_id: str) -> bool:
        """Ingest a batch of cost items to ADX and return success status."""
        try:
            if not items:
                return True

            self.logger.debug(f"Ingesting cost batch {batch_id} with {len(items)} items")

            # Convert to JSON Lines format
            json_lines = '\n'.join(json.dumps(item, default=str) for item in items)
            ingest_command = f".ingest inline into table {self.table_name} with (format='multijson') <|\n{json_lines}"

            adx_database = self.config['adx_database']
            adx_client.execute(adx_database, ingest_command)
            self.logger.debug(f"Cost batch {batch_id} ingested successfully")
            return True

        except Exception as e:
            self.logger.error(f"Failed to ingest cost batch {batch_id}: {e}")
            return False


# Example configuration for this collector:
# {
#     "azure_subscription_id": "12345678-1234-1234-1234-123456789012",
#     "cost_timeframe": "MonthToDate",
#     "cost_granularity": "Daily",
#     "adx_database": "pricing-metrics"
# }
