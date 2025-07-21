"""
Azure Data Explorer (ADX) client for Azure Pricing Function.
Simplified version focused only on pricing data ingestion.
"""

import os
import logging
import datetime
from typing import Dict, Any, List, Optional

from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
from azure.kusto.data.exceptions import KustoServiceError
from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)

class ADXClient:
    """Simplified ADX client for pricing data ingestion."""

    def __init__(self):
        self.cluster_uri = os.getenv("ADX_CLUSTER_URI")
        self.database_name = os.getenv("ADX_DATABASE_NAME", "pricing-metrics")
        self.table_name = os.getenv("ADX_TABLE_NAME", "pricing_metrics")

        if not self.cluster_uri:
            raise ValueError("ADX_CLUSTER_URI environment variable is required")

        # Use Managed Identity authentication (recommended for Azure Functions)
        try:
            kcsb = KustoConnectionStringBuilder.with_aad_managed_service_identity_authentication(
                self.cluster_uri
            )
            self.client = KustoClient(kcsb)
            logger.info(f"ADX client initialized with Managed Identity for cluster: {self.cluster_uri}")
        except Exception as e:
            logger.error(f"Failed to initialize ADX client with Managed Identity: {e}")
            raise

    async def ensure_table_exists(self) -> bool:
        """Ensure the pricing metrics table exists with the correct schema."""
        try:
            # Check if table exists
            check_table_query = f".show table {self.table_name}"

            try:
                self.client.execute_mgmt(self.database_name, check_table_query)
                logger.info(f"Table {self.table_name} already exists in database {self.database_name}")
                return True
            except KustoServiceError:
                # Table doesn't exist, create it
                logger.info(f"Table {self.table_name} doesn't exist, creating it...")

            # Create table with pricing data schema
            create_table_command = f"""
.create table {self.table_name} (
    timestamp: datetime,
    execution_id: string,
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
    reservationTerm: string
)
            """

            self.client.execute_mgmt(self.database_name, create_table_command)
            logger.info(f"Table {self.table_name} created successfully in database {self.database_name}")
            return True

        except KustoServiceError as e:
            logger.error(f"Failed to create table: {e}")
            return False

    async def send_pricing_metrics_batch(self, metrics: List[Dict[str, Any]]) -> bool:
        """Send multiple pricing metrics to ADX in a batch."""
        try:
            # Prepare batch data with proper CSV formatting
            def escape_csv_value(value):
                if value is None:
                    return ""
                str_value = str(value)
                # If value contains comma, newline, or quote, wrap in quotes and escape internal quotes
                if ',' in str_value or '\n' in str_value or '"' in str_value:
                    return '"' + str_value.replace('"', '""') + '"'
                return str_value

            data_lines = []
            for metric in metrics:
                timestamp = metric.get("timestamp", datetime.datetime.utcnow().isoformat())

                # Build CSV line with proper escaping
                csv_line = ",".join([
                    escape_csv_value(timestamp),
                    escape_csv_value(metric.get("execution_id", "")),
                    escape_csv_value(metric.get("currencyCode", "")),
                    str(metric.get("tierMinimumUnits", 0)),
                    str(metric.get("retailPrice", 0)),
                    str(metric.get("unitPrice", 0)),
                    escape_csv_value(metric.get("armRegionName", "")),
                    escape_csv_value(metric.get("location", "")),
                    escape_csv_value(metric.get("effectiveStartDate", "")),
                    escape_csv_value(metric.get("meterId", "")),
                    escape_csv_value(metric.get("meterName", "")),
                    escape_csv_value(metric.get("productId", "")),
                    escape_csv_value(metric.get("skuId", "")),
                    escape_csv_value(metric.get("productName", "")),
                    escape_csv_value(metric.get("skuName", "")),
                    escape_csv_value(metric.get("serviceName", "")),
                    escape_csv_value(metric.get("serviceId", "")),
                    escape_csv_value(metric.get("serviceFamily", "")),
                    escape_csv_value(metric.get("unitOfMeasure", "")),
                    escape_csv_value(metric.get("type", "")),
                    str(metric.get("isPrimaryMeterRegion", False)).lower(),
                    escape_csv_value(metric.get("armSkuName", "")),
                    escape_csv_value(metric.get("reservationTerm", ""))
                ])
                data_lines.append(csv_line)

            # Build the batch ingestion command
            ingest_command = f".ingest inline into table {self.table_name} <|\n" + "\n".join(data_lines)

            logger.debug(f"Executing ADX batch ingest command with {len(data_lines)} rows")
            self.client.execute_mgmt(self.database_name, ingest_command)
            logger.info(f"Successfully sent {len(metrics)} metrics to ADX in batch")
            return True

        except KustoServiceError as e:
            logger.error(f"Failed to send metrics batch to ADX: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error in batch ingestion: {e}")
            return False

    async def test_connection(self) -> bool:
        """Test ADX connection and basic operations."""
        try:
            # Test basic connectivity
            query = f".show database {self.database_name} schema"
            result = self.client.execute(self.database_name, query)
            logger.info("ADX connection test successful")
            return True
        except Exception as e:
            logger.error(f"ADX connection test failed: {e}")
            return False
