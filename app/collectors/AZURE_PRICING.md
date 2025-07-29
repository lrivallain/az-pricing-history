# Azure Pricing Collector

The Azure Pricing Collector is responsible for collecting pricing data from the Azure Pricing API and ingesting it into Azure Data Explorer (ADX).

## Overview

This collector implements the `BaseCollector` interface to provide:

- **Real-time data collection** from the Azure Pricing API
- **API retry logic** with exponential backoff for reliability
- **Filtering support** via FILTERS_JSON for targeted data collection
- **Rate limiting** and throttling management
- **Automatic ADX table creation** and data ingestion

## Configuration

### Required Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `ADX_CLUSTER_URI` | Azure Data Explorer cluster URI | `https://mycluster.region.kusto.windows.net` |
| `ADX_DATABASE_NAME` | ADX database name | `pricing-metrics` |

### Optional Environment Variables

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `AZURE_PRICING_MAX_ITEMS` | Maximum items to collect per execution | `5000` | `10000` or `-1` (unlimited) |
| `AZURE_PRICING_API_RETRY_ATTEMPTS` | Number of retry attempts for failed API calls | `3` | `5` |
| `AZURE_PRICING_API_RETRY_DELAY` | Delay in seconds between retry attempts | `2.0` | `1.5` |
| `AZURE_PRICING_FILTERS` | JSON filters for targeted data collection | `{}` | See [Filtering](#filtering) section |

## Data Schema

The collector creates and populates the `pricing_metrics` table with the following schema:

```sql
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
```

### Job Metadata Fields

Every record includes job metadata for tracking and analysis:

- **jobId**: Unique identifier for the job execution
- **jobDateTime**: Timestamp when the job started
- **jobType**: Type of execution (scheduled, manual, local-test)

## Features

### API Retry Logic

The collector implements robust retry logic to handle transient failures:

- **Configurable retry attempts** via `AZURE_PRICING_API_RETRY_ATTEMPTS`
- **Exponential backoff** with configurable base delay
- **Rate limiting handling** - respects HTTP 429 responses and Retry-After headers
- **Error categorization** - different handling for client vs server errors

### Real-time Ingestion

Data is ingested to ADX as it's collected:

- **Page-by-page processing** - each API response page is immediately ingested
- **Memory efficiency** - avoids accumulating large datasets in memory
- **Batch processing** - efficient JSON Lines format for ADX ingestion
- **Error recovery** - failed batches are logged and reported

### Pagination and Filtering

The collector handles Azure API pagination correctly with filters:

1. **First Request**: Applies filters as query parameters to the base API URL
   ```
   GET https://prices.azure.com/api/retail/prices?$filter=serviceName eq 'Virtual Machines'
   ```

2. **Subsequent Requests**: Uses the `NextPageLink` from the API response as-is
   ```
   GET https://prices.azure.com:443/api/retail/prices?$filter=serviceName%20eq%20%27Virtual%20Machines%27&$skip=1000
   ```

3. **Filter Preservation**: The Azure API automatically includes original filters in all `NextPageLink` URLs

4. **No Parameter Modification**: The collector never modifies or adds parameters to `NextPageLink` URLs

This ensures that filters are correctly applied across all pages of results while respecting the API's pagination mechanism.

### Filtering

The Azure Pricing collector supports filtering using the `AZURE_PRICING_FILTERS` configuration parameter. This follows the official OData filter syntax as documented in the [Azure Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices).

#### Examples

**Virtual Machines only:**
```bash
export AZURE_PRICING_FILTERS='{"serviceName": "Virtual Machines"}'
```

**Virtual Machine reservations only:**
```bash
export AZURE_PRICING_FILTERS='{"serviceName": "Virtual Machines", "priceType": "Reservation"}'
```

**All Compute services:**
```bash
export AZURE_PRICING_FILTERS='{"serviceFamily": "Compute"}'
```

**Specific region:**
```bash
export AZURE_PRICING_FILTERS='{"armRegionName": "westeurope"}'
```

**Multiple conditions (all must match):**
```bash
export AZURE_PRICING_FILTERS='{"serviceName": "Virtual Machines", "armRegionName": "eastus", "priceType": "Consumption"}'
```

#### Supported Filter Fields

The following fields can be used in filters (case-sensitive):
- `armRegionName` - Azure region (e.g., "westeurope", "eastus")
- `location` - Location display name (e.g., "EU West", "US East")
- `meterId` - Unique meter identifier
- `meterName` - Meter name (e.g., "F16s Spot")
- `productId` - Product identifier
- `skuId` - SKU identifier
- `productName` - Product display name (e.g., "Virtual Machines FS Series Windows")
- `skuName` - SKU display name (e.g., "F16s Spot")
- `serviceName` - Service name (e.g., "Virtual Machines", "Storage")
- `serviceId` - Service identifier
- `serviceFamily` - Service family (e.g., "Compute", "Storage", "Networking")
- `priceType` - Price type ("Consumption", "Reservation", "DevTestConsumption")
- `armSkuName` - ARM SKU name (e.g., "Standard_F16s")

#### Filter Value Types

- **Strings**: Must match exactly (case-sensitive)
- **Numbers**: Numeric comparison
- **Booleans**: true/false values

#### Important Notes

- **Case Sensitivity**: Filter values are case-sensitive. Use exact case as returned by the API.
- **Multiple Conditions**: All conditions in the JSON object are combined with AND logic.
- **URL Encoding**: The collector automatically handles proper URL encoding of filter parameters.
- **API Compatibility**: Filters follow the official Azure Retail Prices API OData syntax.
- **Pagination**: Filters are applied only to the first request. Subsequent pagination requests use the `NextPageLink` as-is, which already contains both filter and pagination parameters.

## Usage Examples

### Local Development

```bash
# Basic collection with limits
export ADX_CLUSTER_URI="https://yourcluster.kusto.windows.net"
export ADX_DATABASE_NAME="pricing-metrics"
export MAX_PRICING_ITEMS="100"
export LOG_LEVEL="DEBUG"

cd app
python main.py
```

### Container Apps Manual Execution

```bash
# Unlimited collection
az containerapp job start \
  --resource-group "your-rg" \
  --name "pricing-manual-job" \
  --env-vars MAX_PRICING_ITEMS=-1

# Limited collection with filters
az containerapp job start \
  --resource-group "your-rg" \
  --name "pricing-manual-job" \
  --env-vars MAX_PRICING_ITEMS=5000 \
             FILTERS_JSON='{"serviceName": "Virtual Machines"}'
```

### Docker Execution

```bash
# Run with environment file
docker run --env-file .env.local your-registry/pricing-collector

# Run with specific configuration
docker run \
  -e ADX_CLUSTER_URI="https://yourcluster.kusto.windows.net" \
  -e ADX_DATABASE_NAME="pricing-metrics" \
  -e MAX_PRICING_ITEMS="1000" \
  your-registry/pricing-collector
```

## Monitoring and Troubleshooting

### Execution Statistics

The collector provides detailed execution statistics:

```kql
// View recent executions
pricing_metrics
| where jobDateTime > ago(1d)
| where collectorName == "azure_pricing"
| summarize
    ItemCount = count(),
    FirstItem = min(jobDateTime),
    LastItem = max(jobDateTime),
    UniqueServices = dcount(serviceName),
    UniqueRegions = dcount(armRegionName)
  by jobId
| order by LastItem desc
```

### Error Monitoring

Check the job_logs table for collector-specific errors:

```kql
// View collector errors
job_logs
| where TimeGenerated > ago(1d)
| where LoggerName contains "azure_pricing"
| where LogLevel in ("ERROR", "CRITICAL")
| project TimeGenerated, LogLevel, Message, ExceptionInfo
| order by TimeGenerated desc
```

### Performance Analysis

```kql
// Analyze collection performance
pricing_metrics
| where jobDateTime > ago(7d)
| where collectorName == "azure_pricing"
| summarize
    ItemCount = count(),
    AvgPriceUSD = avg(retailPrice),
    ServicesCollected = dcount(serviceName)
  by bin(jobDateTime, 1d)
| order by jobDateTime desc
```

## API Rate Limiting

The Azure Pricing API has rate limits. The collector handles this by:

1. **Respecting rate limits** - adds 1-second delay between API pages
2. **Handling 429 responses** - waits for the time specified in Retry-After header
3. **Exponential backoff** - increases delay for subsequent retries
4. **Graceful degradation** - logs rate limiting events for monitoring

## Common Issues and Solutions

### Authentication Errors

**Issue**: "Failed to create ADX client with all authentication methods"

**Solutions**:
- Ensure `az login` is completed for local development
- Verify Managed Identity has ADX Database Admin role in production
- Check `AZURE_CLIENT_ID` environment variable in Container Apps

### Data Collection Limits

**Issue**: Collection stops before expected completion

**Solutions**:
- Check `MAX_PRICING_ITEMS` setting (`-1` for unlimited)
- Monitor for API rate limiting in logs
- Verify ADX ingestion quotas and limits

### Filter Syntax Errors

**Issue**: "Invalid FILTERS_JSON format"

**Solutions**:
- Ensure valid JSON syntax: `{"key": "value"}`
- Use double quotes for JSON strings
- Validate JSON with online tools before deployment

### Memory Issues

**Issue**: Out of memory errors during collection

**Solutions**:
- The collector uses real-time ingestion to avoid memory issues
- If problems persist, reduce `MAX_PRICING_ITEMS`
- Check Container Apps memory allocation

## Advanced Configuration

### Development and Testing

```bash
# Test with minimal data
export MAX_PRICING_ITEMS="10"
export FILTERS_JSON='{"serviceName": "Storage"}'
export LOG_LEVEL="DEBUG"

# Test API retry logic
export API_RETRY_ATTEMPTS="5"
export API_RETRY_DELAY="1.0"
```

### Production Optimization

```bash
# Optimized for large-scale collection
export MAX_PRICING_ITEMS="-1"          # Unlimited
export API_RETRY_ATTEMPTS="3"          # Standard resilience
export API_RETRY_DELAY="2.0"           # Conservative rate limiting
export LOG_LEVEL="INFO"                # Reduced logging
```

## Integration with Other Collectors

The Azure Pricing Collector can run alongside other collectors in the modular system:

```bash
# Enable multiple collectors
export ENABLE_COST_COLLECTOR="true"
export MAX_PRICING_ITEMS="50000"

# Run the complete system
python main.py
```

This collector serves as a reference implementation for building additional collectors in the modular system.
