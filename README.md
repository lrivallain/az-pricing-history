# Modular History Data Collection System

A production-ready, modular solution for collecting historical data from multiple sources using **Azure Container Apps Jobs** with real-time ingestion to **Azure Data Explorer (ADX)**.

## 🏗️ Modular Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                Job Orchestrator (main.py)                       │
│ • Coordinates multiple collectors                                │
│ • Manages shared resources (ADX client, logging)                │
│ • Provides unified error handling and reporting                 │
└─────────────────┬───────────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Data Collectors                              │
├─────────────────┬─────────────────┬─────────────────────────────┤
│ Azure Pricing   │ Azure Cost      │ Future Collectors           │
│ Collector       │ Collector       │ (Database, APIs, Files)     │
│ (Active)        │ (Template)      │ (Extensible)                │
└─────────────────┴─────────────────┴─────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────────┐
│              Shared Components                                  │
│ • ADX Client Manager (multi-auth, connection pooling)           │
│ • Configuration Manager (.env.local + environment variables)   │
│ • ADX Logger (logging to ADX job_logs table)             │
└─────────────────────────────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────────┐
│           Azure Data Explorer (ADX) Database                    │
│ • pricing_metrics table (Azure pricing data)                    │
│ • cost_metrics table (Azure cost data - future)                │
│ • job_logs table (application logs)                       │
│ • Collector-specific tables (auto-created)                      │
└─────────────────────────────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Azure Managed Grafana                          │
│ • Pre-configured ADX data source                                │
│ • Multi-table KQL-based dashboards                             │
│ • Cross-collector analytics and monitoring                      │
└─────────────────────────────────────────────────────────────────┘
```

## 🚀 Quick Start

### Prerequisites

- **Azure CLI** installed and authenticated (`az login`)
- **Docker** (for local development)
- **Terraform >= 1.0** (for infrastructure deployment)
- **Azure subscription** with appropriate permissions

### Local Development Setup

```bash
# 1. Clone and navigate to the project
cd projects/pricing

# 2. Configure your environment
cp .env.local.example .env.local
# Edit .env.local with your ADX cluster details

# 3. Authenticate with Azure
az login

# 4. Run the modular system locally
cd app
python main.py
```

### Docker Development

```bash
# Run with Docker (automatically loads .env.local)
./run-docker-local.sh
```

## 📁 Project Structure

```
app/
├── main.py                     # Main entry point for the modular system
├── core/                       # Core orchestration framework
│   ├── __init__.py
│   ├── base_collector.py       # Abstract base class for all collectors
│   └── orchestrator.py         # Job orchestration and coordination
├── collectors/                 # Data collector implementations
│   ├── __init__.py
│   ├── azure_pricing_collector.py    # Azure Pricing API collector
│   └── azure_cost_collector.py       # Azure Cost Management template
├── shared/                     # Shared utilities and components
│   ├── __init__.py
│   ├── adx_client.py          # ADX client management
│   └── config.py              # Configuration management
├── adx_logger.py              # ADX logging module
├── Dockerfile                 # Multi-stage container build
└── MODULAR_ARCHITECTURE.md    # Detailed architecture documentation
```

## 🔧 Available Collectors

### Active Collectors

1. **[Azure Pricing Collector](app/collectors/AZURE_PRICING.md)** - Collects pricing data from Azure Pricing API
   - Table: `pricing_metrics`
   - Features: API retry logic, FILTERS_JSON support, real-time ingestion
   - Configuration: `API_RETRY_ATTEMPTS`, `FILTERS_JSON`, etc.

### Template Collectors

2. **[Azure Cost Collector](app/collectors/AZURE_COST.md)** - Template for Azure Cost Management data
   - Table: `cost_metrics`
   - Status: Template/Example implementation
   - Enable with: `ENABLE_COST_COLLECTOR=true`

## 🏗️ Infrastructure Deployment

### 1. Deploy Azure Resources

```bash
cd terraform

# Configure your deployment
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your subscription ID and preferences

# Deploy infrastructure
terraform init
terraform plan
terraform apply
```

### 2. Build and Deploy Container Image

```bash
# Get container registry name from Terraform output
REGISTRY_NAME=$(terraform output -raw container_registry_login_server | cut -d'.' -f1)
RESOURCE_GROUP=$(terraform output -raw resource_group_name)
REGISTRY=$(terraform output -raw container_registry_login_server)

cd ..
# Build and push image: this will also update jobs to use the pushed image
./deploy-container.sh -g "$RESOURCE_GROUP" -r "$REGISTRY_NAME"
```

## 📋 Usage Guide

### Scheduled Execution

The system runs automatically **daily at 2:00 AM UTC** with all enabled collectors.

**Monitor scheduled jobs:**

```bash
RESOURCE_GROUP=$(terraform output -raw resource_group_name)
SCHEDULER_JOB=$(terraform output -raw pricing_scheduler_job_name)

# Check recent scheduled executions
az containerapp job execution list \
  --resource-group "$RESOURCE_GROUP" \
  --name "$SCHEDULER_JOB" \
  --query "[].{Name:name, Status:properties.status, StartTime:properties.startTime}"
```

### Manual Execution

**Run all enabled collectors:**

```bash
MANUAL_JOB=$(terraform output -raw pricing_manual_job_name)

az containerapp job start \
  --resource-group "$RESOURCE_GROUP" \
  --name "$MANUAL_JOB"
```

**Run with specific collector configuration:**

```bash
# Run only Azure Pricing collector with limits
az containerapp job start \
  --resource-group "$RESOURCE_GROUP" \
  --name "$MANUAL_JOB" \
  --env-vars MAX_PRICING_ITEMS=5000 LOG_LEVEL=DEBUG

# Enable additional collectors
az containerapp job start \
  --resource-group "$RESOURCE_GROUP" \
  --name "$MANUAL_JOB" \
  --env-vars ENABLE_COST_COLLECTOR=true
```

## ⚙️ Configuration Reference

### Global Configuration

| Variable | Description | Required | Default | Example |
|----------|-------------|----------|---------|---------|
| `ADX_CLUSTER_URI` | Azure Data Explorer cluster URI | ✅ Yes | - | `https://mycluster.region.kusto.windows.net` |
| `ADX_DATABASE_NAME` | ADX database name | ✅ Yes | - | `pricing-metrics` |
| `JOB_TYPE` | Job execution type identifier | ❌ No | `manual` | `scheduled`, `local-test` |
| `LOG_LEVEL` | Application logging level | ❌ No | `INFO` | `DEBUG`, `WARNING`, `ERROR` |
| `ADX_LOG_LEVEL` | ADX error logging level | ❌ No | `WARNING` | `ERROR`, `CRITICAL` |

### Collector-Specific Configuration

#### Azure Pricing Collector
| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `ENABLE_AZURE_PRICING_COLLECTOR` | Enable Azure Pricing collector | `true` | `false` |
| `AZURE_PRICING_MAX_ITEMS` | Maximum items per execution | `5000` | `10000` or `-1` (unlimited) |
| `AZURE_PRICING_API_RETRY_ATTEMPTS` | Number of retry attempts | `3` | `5` |
| `AZURE_PRICING_API_RETRY_DELAY` | Seconds between retries | `2.0` | `1.5` |
| `AZURE_PRICING_FILTERS` | JSON filters for targeted collection | `{}` | `{"serviceName": "Virtual Machines"}` |

#### Azure Cost Collector (Template)
| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `ENABLE_COST_COLLECTOR` | Enable cost collector | `false` | `true` |
| `COST_TIMEFRAME` | Cost data timeframe | `MonthToDate` | `LastMonth` |
| `COST_GRANULARITY` | Data granularity | `Daily` | `Monthly` |

## 🔍 Monitoring and Troubleshooting

### Job Execution Monitoring

```bash
# View job execution details
az containerapp job execution show \
  --name "$MANUAL_JOB" \
  --resource-group "$RESOURCE_GROUP" \
  --job-execution-name <execution-name>

# Stream logs in real-time
az containerapp job execution logs show \
  --name "$MANUAL_JOB" \
  --resource-group "$RESOURCE_GROUP" \
  --job-execution-name <execution-name>
```

### ADX Monitoring Queries

```kql
// View recent job executions across all collectors
job_logs
| where TimeGenerated > ago(1d)
| where LogLevel in ("ERROR", "CRITICAL")
| summarize ErrorCount=count() by JobId, CollectorName=extract("([^.]+)$", 1, LoggerName)
| order by ErrorCount desc

// Monitor pricing data collection
pricing_metrics
| where jobDateTime > ago(1d)
| summarize ItemCount=count(),
           Collectors=dcount(collectorName),
           LastCollection=max(jobDateTime)
  by jobId
| order by LastCollection desc
```

### Grafana Dashboards

Access your Grafana instance for comprehensive monitoring:

```bash
# Get Grafana URL from Terraform
terraform output managed_grafana_url
```

## 🛠️ Extending the System

### Adding a New Collector

1. **Create collector class** extending `BaseCollector`
2. **Add configuration** in `shared/config.py`
3. **Register collector** in `core/orchestrator.py`
4. **Create documentation** in `collectors/YOUR_COLLECTOR.md`

### Example: Database Collector

```python
from core.base_collector import BaseCollector

class DatabaseCollector(BaseCollector):
    @property
    def collector_name(self) -> str:
        return "database_source"

    def collect_data(self, adx_client) -> int:
        # Implement your data collection logic
        pass
```

## 📚 Documentation

- **[Modular Architecture Guide](app/MODULAR_ARCHITECTURE.md)** - Detailed architecture and implementation guide
- **[Azure Pricing Collector](app/collectors/AZURE_PRICING.md)** - Azure Pricing API collector documentation
- **[Azure Cost Collector](app/collectors/AZURE_COST.md)** - Azure Cost Management template documentation

## 🔧 Development Tools

### Docker Development

```bash
# Edit configuration in .env.local

# Run the collector in Docker with local configuration
./run-docker-local.sh
```
