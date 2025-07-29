# Azure Cost Collector (Template)

The Azure Cost Collector is a **template implementation** demonstrating how to create new collectors for the modular history data collection system. This collector shows how to collect Azure Cost Management data.

⚠️ **Note**: This is currently a template/example implementation. It generates sample data for demonstration purposes and would need to be connected to the actual Azure Cost Management API for production use.

## Overview

This collector serves as a reference implementation showing:

- **BaseCollector interface** implementation
- **Custom ADX table schema** definition
- **Batch processing** patterns
- **Configuration validation** practices
- **Error handling** best practices

## Configuration

### Required Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `ADX_CLUSTER_URI` | Azure Data Explorer cluster URI | `https://mycluster.region.kusto.windows.net` |
| `ADX_DATABASE_NAME` | ADX database name | `pricing-metrics` |
| `AZURE_SUBSCRIPTION_ID` | Azure subscription ID for cost data | `12345678-1234-1234-1234-123456789012` |

### Optional Environment Variables

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `ENABLE_COST_COLLECTOR` | Enable the cost collector | `false` | `true` |
| `COST_TIMEFRAME` | Cost data timeframe | `MonthToDate` | `LastMonth`, `BillingMonthToDate` |
| `COST_GRANULARITY` | Data granularity | `Daily` | `Monthly` |
| `MAX_ITEMS` | Maximum cost records to collect | `5000` | `10000` or `-1` (unlimited) |

## Data Schema

The collector creates and populates the `cost_metrics` table with the following schema:

```sql
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
```

### Job Metadata Fields

Every record includes standard job metadata:

- **jobId**: Unique identifier for the job execution
- **jobDateTime**: Timestamp when the job started
- **jobType**: Type of execution (scheduled, manual, local-test)
- **collectorName**: Always "azure_cost" for this collector

## Features (Template Implementation)

### Sample Data Generation

The current template implementation generates realistic sample cost data including:

- **Multiple resource types** (Virtual Machines, Storage, etc.)
- **Various Azure regions** (East US, West US 2, North Europe)
- **Cost calculations** with pre-tax and final amounts
- **Resource tagging** (Environment, Cost Center, Owner)
- **Billing hierarchy** (Account, Profile, Invoice Section)

### Configurable Timeframes

Supports different cost analysis timeframes:

- **MonthToDate**: Current month from start to now
- **BillingMonthToDate**: Current billing month to now
- **TheLastMonth**: Complete previous month
- **TheLastBillingMonth**: Complete previous billing month

### Granularity Options

Data can be collected at different granularities:

- **Daily**: One record per day per resource
- **Monthly**: Aggregated monthly data per resource

## Enabling the Collector

To enable this template collector:

```bash
# Local development
export ENABLE_COST_COLLECTOR="true"
export AZURE_SUBSCRIPTION_ID="your-subscription-id"
export COST_TIMEFRAME="MonthToDate"

cd app
python main.py
```

```bash
# Container Apps
az containerapp job start \
  --resource-group "your-rg" \
  --name "pricing-manual-job" \
  --env-vars ENABLE_COST_COLLECTOR=true \
             AZURE_SUBSCRIPTION_ID=your-subscription-id
```

## Production Implementation

To convert this template into a production collector:

### 1. Add Azure Cost Management SDK

```bash
pip install azure-mgmt-consumption azure-mgmt-billing
```

### 2. Implement Real Data Collection

Replace the `_generate_sample_cost_data()` method with actual API calls:

```python
from azure.mgmt.consumption import ConsumptionManagementClient
from azure.identity import DefaultAzureCredential

def collect_data(self, adx_client) -> int:
    # Authenticate with Cost Management API
    credential = DefaultAzureCredential()
    cost_client = ConsumptionManagementClient(credential, self.subscription_id)

    # Query cost data
    scope = f"/subscriptions/{self.subscription_id}"
    usage_details = cost_client.usage_details.list(
        scope=scope,
        expand="properties/meterDetails",
        filter=f"properties/usageStart ge '{start_date}' and properties/usageEnd le '{end_date}'"
    )

    # Process and ingest data
    for usage in usage_details:
        # Transform usage data to match schema
        cost_item = self._transform_usage_data(usage)
        enriched_item = self.enrich_item(cost_item)
        # Batch and ingest to ADX
```

### 3. Add Authentication Configuration

Extend configuration to support Cost Management API authentication:

```python
# In shared/config.py
elif collector_name == 'azure_cost':
    config.update({
        'azure_subscription_id': self._config['azure_subscription_id'],
        'cost_timeframe': self._config['cost_timeframe'],
        'cost_granularity': self._config['cost_granularity'],
        'azure_client_id': self._config['azure_client_id'],  # For managed identity
        'azure_tenant_id': self._config['azure_tenant_id'],
    })
```

### 4. Update Configuration Validation

```python
def validate_config(self) -> None:
    required_configs = ['adx_database', 'azure_subscription_id']

    for config_key in required_configs:
        if not self.config.get(config_key):
            raise ValueError(f"Required configuration '{config_key}' is missing")

    # Validate Azure subscription ID format
    subscription_id = self.config['azure_subscription_id']
    if not re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', subscription_id):
        raise ValueError(f"Invalid Azure subscription ID format: {subscription_id}")
```

## Usage Examples

### Template Testing

```bash
# Test the template implementation
export ENABLE_COST_COLLECTOR="true"
export AZURE_SUBSCRIPTION_ID="12345678-1234-1234-1234-123456789012"
export MAX_ITEMS="50"
export LOG_LEVEL="DEBUG"

cd app
python main.py
```

### Integration with Pricing Collector

```bash
# Run both pricing and cost collectors
export MAX_PRICING_ITEMS="1000"
export ENABLE_COST_COLLECTOR="true"
export COST_TIMEFRAME="LastMonth"

python main.py
```

## Monitoring Template Data

### View Generated Sample Data

```kql
// Check template cost data
cost_metrics
| where collectorName == "azure_cost"
| where jobDateTime > ago(1d)
| summarize
    RecordCount = count(),
    TotalCost = sum(cost),
    UniqueResources = dcount(resourceName),
    CostByService = dcount(serviceName)
  by jobId
| order by jobDateTime desc
```

### Analyze Sample Patterns

```kql
// Analyze sample data patterns
cost_metrics
| where collectorName == "azure_cost"
| extend Tags = parse_json(tags)
| summarize
    TotalCost = sum(cost),
    AvgDailyCost = avg(cost)
  by
    Environment = tostring(Tags.Environment),
    ServiceName = serviceName,
    Location = location
| order by TotalCost desc
```

## Development Guidelines

This template demonstrates best practices for collector development:

### 1. Configuration Management

```python
def validate_config(self) -> None:
    # Always validate required configuration
    # Provide helpful error messages
    # Check format/syntax of configuration values
```

### 2. Data Enrichment

```python
def collect_data(self, adx_client) -> int:
    # Always use self.enrich_item() to add job metadata
    enriched_item = self.enrich_item(raw_data_item)
    batch_items.append(enriched_item)
```

### 3. Error Handling

```python
try:
    # Data collection logic
    success = self.ingest_batch_to_adx(adx_client, batch, batch_id)
    if not success:
        raise Exception(f"Failed to ingest batch {batch_id}")
except Exception as e:
    self.logger.error(f"Collection failed: {e}")
    raise  # Let orchestrator handle the failure
```

### 4. Performance Considerations

```python
# Process data in batches to manage memory
batch_size = 1000
for i in range(0, len(data), batch_size):
    batch = data[i:i + batch_size]
    # Process batch
    time.sleep(0.1)  # Rate limiting
```

## Creating Your Own Collector

Use this template as a starting point for your own collectors:

1. **Copy the template** structure
2. **Modify the collector name** and table schema
3. **Implement data collection** logic for your source
4. **Add configuration** parameters as needed
5. **Test thoroughly** with sample data first
6. **Add monitoring** and error handling
7. **Document** your collector's features and usage

This template provides a solid foundation for building production-ready data collectors in the modular system.
