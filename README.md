# Azure Pricing Data Collector

A simplified, serverless solution for collecting Azure pricing data and storing it in Azure Data Explorer (ADX) for analytics and visualization with Grafana.

## Features

- **Azure Function-based**: Serverless execution with timer and HTTP triggers
- **Azure App Configuration**: Centralized configuration management for pricing filters
- **Azure Data Explorer (ADX)**: High-performance analytics database for pricing data
- **Azure Managed Grafana**: Pre-configured dashboards for pricing analytics
- **Scheduled Execution**: Daily automatic data collection at 2 AM UTC
- **Manual Triggers**: HTTP endpoint for on-demand data collection
- **Rate Limiting**: Respects Azure Pricing API limits with exponential backoff
- **Managed Identity**: Secure authentication using Azure Managed Identity
- **Minimal Infrastructure**: Only essential components, no complex API management

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          Azure Function App                     │
│  ┌─────────────────────┐  ┌─────────────────────────────────────┐│
│  │   Timer Trigger     │  │        HTTP Trigger                 ││
│  │   (Daily 2 AM UTC)  │  │    (Manual execution)               ││
│  └─────────────────────┘  └─────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
           │                                   │
           ▼                                   ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  Azure App       │  │ Azure Data       │  │ Azure Managed    │
│  Configuration   │  │ Explorer (ADX)   │  │ Grafana          │
│  - Pricing       │  │ - Time Series    │  │ - Pre-built      │
│  - Filters       │  │ - Analytics      │  │ - Dashboards     │
│  - Currency      │  │ - KQL Queries    │  │ - Cost Analysis  │
└──────────────────┘  └──────────────────┘  └──────────────────┘
```

## Quick Start

### Prerequisites

- Azure CLI installed and configured
- Azure subscription with appropriate permissions
- Terraform installed (for infrastructure deployment)

### 1. Clone and Configure

```bash
git clone <repository-url>
cd azure-pricing-tool

# Copy and edit configuration
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# Edit terraform.tfvars with your subscription details
```

### 2. Deploy

**Windows (PowerShell):**
```powershell
.\deploy-function.ps1
```

**Linux/Mac (Bash):**
```bash
chmod +x deploy-function.sh
./deploy-function.sh
```

This deploys:
- Azure Function App with timer and HTTP triggers
- Azure App Configuration for settings management
- Azure Data Explorer cluster for analytics
- Azure Managed Grafana for visualization
- All necessary security and networking configurations

### 3. Configure Pricing Filters

After deployment, configure what pricing data to collect:

```bash
# Example: Collect all Virtual Machine pricing for East US
az appconfig kv set \
  --name <app-config-name> \
  --key pricing-filters \
  --value '{"serviceName":"Virtual Machines","armRegionName":"eastus"}'

# Example: Collect all Azure services (no filters)
az appconfig kv set \
  --name <app-config-name> \
  --key pricing-filters \
  --value '{}'
```

## Usage

### Automatic Execution

The function runs automatically daily at 2 AM UTC based on the timer trigger. No action required.

### Manual Execution

Trigger data collection manually via HTTP endpoint:

```bash
# Using curl
curl -X POST "https://<function-app-name>.azurewebsites.net/api/collect" \
  -H "Content-Type: application/json" \
  -d '{"filters":{"serviceName":"Virtual Machines"}}'

# Using PowerShell
Invoke-RestMethod -Uri "https://<function-app-name>.azurewebsites.net/api/collect" \
  -Method Post -ContentType "application/json" \
  -Body '{"filters":{"serviceName":"Virtual Machines"}}'
```

### Monitor Execution

```bash
# View function logs
az functionapp logs tail \
  --name <function-app-name> \
  --resource-group <resource-group-name>

# Check execution history in Azure Portal
```

## Configuration Options

### App Configuration Keys

| Key | Description | Example Value |
|-----|-------------|---------------|
| `pricing-filters` | JSON object with Azure Pricing API filters | `{"serviceName":"Virtual Machines"}` |
| `currency-code` | Currency for pricing data | `USD` |

### Available Filters

Filter pricing data using any of these parameters:

- `serviceName`: Azure service name (e.g., "Virtual Machines", "Storage")
- `serviceFamily`: Service family (e.g., "Compute", "Storage")
- `armRegionName`: Azure region (e.g., "eastus", "westeurope")
- `location`: Location name (e.g., "US East", "West Europe")
- `priceType`: Price type ("Consumption", "Reservation")
- `armSkuName`: SKU name (e.g., "Standard_D2s_v3")

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MAX_PRICING_ITEMS` | Maximum items to collect (-1 = unlimited) | `-1` |
| `APP_CONFIG_ENDPOINT` | App Configuration endpoint | Set by Terraform |
| `ADX_CLUSTER_URI` | ADX cluster URI | Set by Terraform |
| `ADX_DATABASE_NAME` | ADX database name | `pricing-metrics` |
| `ADX_TABLE_NAME` | ADX table name | `pricing_metrics` |

## Data Storage

### Azure Data Explorer Schema

The `pricing_metrics` table stores complete Azure pricing data:

| Field | Type | Description |
|-------|------|-------------|
| timestamp | datetime | When the data was recorded |
| execution_id | string | Unique execution identifier |
| currencyCode | string | Currency (e.g., "USD") |
| retailPrice | real | Retail price per unit |
| unitPrice | real | Unit price |
| armRegionName | string | ARM region name |
| location | string | Human-readable location |
| serviceName | string | Azure service name |
| skuName | string | SKU name |
| meterName | string | Meter name |
| productName | string | Product name |
| ... | ... | (20+ additional fields) |

### Sample KQL Queries

```kql
// Recent pricing data
pricing_metrics
| where timestamp >= ago(24h)
| order by timestamp desc
| limit 100

// VM pricing by region
pricing_metrics
| where serviceName == "Virtual Machines"
| summarize avg(retailPrice) by armRegionName, skuName
| order by avg_retailPrice desc

// Daily pricing trends
pricing_metrics
| where timestamp >= ago(30d)
| summarize avg(retailPrice) by bin(timestamp, 1d), serviceName
| render timechart
```

## Grafana Dashboards

Access pre-built dashboards via the Grafana URL provided in deployment outputs:

1. **Pricing Analytics**: Cost trends, regional comparisons, service analysis
2. **Execution Monitoring**: Function execution status, success rates, processing times
3. **Cost Optimization**: Identify pricing patterns and optimization opportunities

## Monitoring and Troubleshooting

### Function Logs

```bash
# Real-time logs
az functionapp logs tail --name <function-app> --resource-group <rg>

# Azure Portal
# Navigate to Function App > Monitor > Logs
```

### ADX Query Testing

```bash
# Test ADX connectivity
az kusto cluster show --name <cluster-name> --resource-group <rg>

# Query recent data
az kusto query --cluster-uri <cluster-uri> \
  --database <database-name> \
  --query "pricing_metrics | limit 10"
```

### Common Issues

1. **Function not triggering**: Check timer trigger configuration and time zone
2. **ADX connection failed**: Verify managed identity permissions on ADX cluster
3. **App Configuration access denied**: Check managed identity has "App Configuration Data Reader" role
4. **Pricing API rate limits**: Function includes automatic retry with exponential backoff

## Development

### Local Development

```bash
# Install Azure Functions Core Tools
npm install -g azure-functions-core-tools@4

# Navigate to function directory
cd function_app

# Install dependencies
pip install -r requirements.txt

# Configure local settings
cp local.settings.json.example local.settings.json
# Edit local.settings.json with your Azure connection strings

# Run locally
func start
```

### Testing

```bash
# Test HTTP trigger locally
curl -X POST "http://localhost:7071/api/collect" \
  -H "Content-Type: application/json" \
  -d '{"filters":{"serviceName":"Virtual Machines"}}'
```

## Security

- **Managed Identity**: All Azure service authentication uses managed identity
- **Function-level security**: HTTP triggers require function key by default
- **Network isolation**: Resources use private endpoints where available
- **Minimal permissions**: Each component has only required permissions
- **Secure configuration**: Sensitive settings stored in App Configuration

## Cost Optimization

- **Consumption Plan**: Functions scale to zero when not running
- **ADX Dev SKU**: Cost-optimized for development and testing
- **Efficient Data Collection**: Configurable filters to limit data scope
- **Managed Services**: Reduced operational overhead

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test with sample data
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

---

## Quick Reference

- 🚀 **Deploy**: Run `deploy-function.ps1` (Windows) or `deploy-function.sh` (Linux/Mac)
- ⚙️ **Configure**: Update App Configuration with pricing filters
- 📊 **Analyze**: Use Grafana dashboards for insights
- 🔍 **Query**: Write KQL queries in ADX for custom analysis
- 📋 **Monitor**: Check function logs for execution status
- 🔧 **Troubleshoot**: Verify managed identity permissions if issues occur
