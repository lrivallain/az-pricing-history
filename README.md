# Azure Pricing Data Collector

A production-ready solution for collecting Azure pricing data using **Azure Container Apps Jobs** with real-time ingestion to **Azure Data Explorer (ADX)**.

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Azure Container Apps Jobs                    │
├─────────────────┬───────────────────────────────────────────────┤
│ Scheduled Job   │ Manual Job                                    │
│ (Daily 2AM UTC) │ (On-demand with custom env vars)              │
└─────────────────┴───────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              Azure Pricing API Integration                      │
│ • Synchronous requests with retry logic                         │
│ • Real-time batch ingestion (no memory accumulation)            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│           Azure Data Explorer (ADX) Database                    │
│ • pricing_metrics table (pricing data)                          │
│ • job_logs table (application error logs)                       │
│ • Real-time ingestion with automatic table creation             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Azure Managed Grafana                          │
│ • Pre-configured ADX data source                                │
│ • KQL-based dashboards for pricing analysis                     │
│ • Admin access via Azure RBAC                                   │
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

# 4. Run locally with Docker
./run-docker-local.sh
```

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
SCHEDULER_JOB=$(terraform output -raw pricing_scheduler_job_name)
MANUAL_JOB=$(terraform output -raw pricing_manual_job_name)
REGISTRY=$(terraform output -raw container_registry_login_server)

cd ..
# Build and push image: this will also update jobs to use the pushed image
./deploy-container.sh -g "$RESOURCE_GROUP" -r "$REGISTRY_NAME"
```

## 📋 Usage Guide

### Scheduled Execution

The scheduled job runs automatically **daily at 2:00 AM UTC**. No manual intervention required.

**Monitor scheduled jobs:**

```bash
# Check recent scheduled executions
az containerapp job execution list \
  --resource-group "$RESOURCE_GROUP" \
  --name "$SCHEDULER_JOB" \
  --query "[].{Name:name, Status:properties.status, StartTime:properties.startTime}"
```

### Manual Execution

**Basic execution:**

```bash
az containerapp job start \
  --resource-group "$RESOURCE_GROUP" \
  --name "$MANUAL_JOB"
```

**With item limit (testing):**

```bash
az containerapp job start \
  --resource-group "$RESOURCE_GROUP" \
  --name "$MANUAL_JOB" \
  --env-vars MAX_PRICING_ITEMS=5000
```

### Grafana Dashboards

Access your Grafana instance:

```bash
# Get Grafana URL from Terraform
terraform output managed_grafana_url
```

The Grafana instance includes:

- **Pre-configured ADX data source** connected to your pricing_metrics database
- **Admin access** for your Azure account via RBAC

## ⚙️ Configuration Reference

### Environment Variables

| Variable | Description | Required | Default | Example |
|----------|-------------|----------|---------|---------|
| `ADX_CLUSTER_URI` | Azure Data Explorer cluster URI | ✅ Yes | - | `https://mycluster.region.kusto.windows.net` |
| `ADX_DATABASE_NAME` | ADX database name | ✅ Yes | - | `pricing-metrics` |
| `MAX_PRICING_ITEMS` | Maximum items per execution | ❌ No | `5000` | `10000` or `-1` (unlimited) |
| `JOB_TYPE` | Job execution type identifier | ❌ No | `manual` | `scheduled`, `local-dev` |
| `API_RETRY_ATTEMPTS` | Number of retry attempts | ❌ No | `3` | `5` |
| `API_RETRY_DELAY` | Seconds between retries | ❌ No | `2.0` | `1.5` |
| `LOG_LEVEL` | Logging level | ❌ No | `INFO` | `DEBUG`, `WARNING`, `ERROR` |
