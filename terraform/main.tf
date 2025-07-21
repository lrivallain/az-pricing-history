# Azure Pricing Tool Infrastructure with Terraform
# Stack: Azure Functions + App Configuration + Azure Data Explorer + Grafana

terraform {
  required_version = ">= 1.0"
  required_providers {
    azurerm = {
      source = "hashicorp/azurerm"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

# Resource Group
resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = var.location

  tags = {
    Environment = var.environment
    Project     = "azure-pricing-tool"
  }
}

# Storage Account for Azure Function
resource "azurerm_storage_account" "function" {
  name                     = "${replace(var.prefix, "-", "")}funcsto"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"

  # Security settings
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false

  tags = {
    Environment = var.environment
    Project     = "azure-pricing-tool"
  }
}

# App Service Plan for Azure Function
resource "azurerm_service_plan" "function" {
  name                = "${var.prefix}-func-plan"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  os_type             = "Linux"
  sku_name            = "Y1"  # Consumption plan

  tags = {
    Environment = var.environment
    Project     = "azure-pricing-tool"
  }
}

# Application Insights for Function monitoring
resource "azurerm_application_insights" "function" {
  name                = "${var.prefix}-func-insights"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  application_type    = "other"

  tags = {
    Environment = var.environment
    Project     = "azure-pricing-tool"
  }
}

# Azure App Configuration for pricing settings
resource "azurerm_app_configuration" "main" {
  name                = "${var.prefix}-appconfig"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "free"

  tags = {
    Environment = var.environment
    Project     = "azure-pricing-tool"
  }
}

# Managed Identity for Azure Function
resource "azurerm_user_assigned_identity" "function" {
  name                = "${var.prefix}-func-identity"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  tags = {
    Environment = var.environment
    Project     = "azure-pricing-tool"
  }
}

# Azure Function App with GitHub source control
resource "azurerm_linux_function_app" "pricing_collector" {
  name                = "${var.prefix}-pricing-func"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  service_plan_id     = azurerm_service_plan.function.id
  storage_account_name       = azurerm_storage_account.function.name
  storage_account_access_key = azurerm_storage_account.function.primary_access_key

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.function.id]
  }

  app_settings = {
    "FUNCTIONS_WORKER_RUNTIME"       = "python"
    "PYTHON_VERSION"                 = "3.11"
    "APPLICATIONINSIGHTS_CONNECTION_STRING" = azurerm_application_insights.function.connection_string
    "AzureWebJobsFeatureFlags"       = "EnableWorkerIndexing"

    # Azure configuration
    "APP_CONFIG_ENDPOINT"   = azurerm_app_configuration.main.endpoint
    "ADX_CLUSTER_URI"       = azurerm_kusto_cluster.main.uri
    "ADX_DATABASE_NAME"     = azurerm_kusto_database.pricing_metrics.name
    "ADX_TABLE_NAME"        = "pricing_metrics"
    "AZURE_CLIENT_ID"       = azurerm_user_assigned_identity.function.client_id

    # Processing settings
    "MAX_PRICING_ITEMS"     = var.max_pricing_items
  }

  site_config {
    application_stack {
      python_version = "3.11"
    }

    # Enable CORS for development
    cors {
      allowed_origins = ["*"]
    }
  }

  tags = {
    Environment = var.environment
    Project     = "azure-pricing-tool"
  }
}

# Role assignments for Function Managed Identity

# App Configuration Data Reader for function to read configuration
resource "azurerm_role_assignment" "function_app_config_reader" {
  scope                = azurerm_app_configuration.main.id
  role_definition_name = "App Configuration Data Reader"
  principal_id         = azurerm_user_assigned_identity.function.principal_id
}


# Current Azure client configuration
data "azurerm_client_config" "current" {}

# Default pricing filters configuration in App Configuration
resource "azurerm_app_configuration_key" "pricing_filters" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "pricing-filters"
  value                  = jsonencode({
    # Default: all services (empty filter)
    # Add specific filters as needed, e.g.:
    # "serviceName": "Virtual Machines"
    # "armRegionName": "eastus"
  })
  type = "kv"

  depends_on = [azurerm_role_assignment.current_user_app_config_owner]
}

# Currency configuration
resource "azurerm_app_configuration_key" "currency_code" {
  configuration_store_id = azurerm_app_configuration.main.id
  key                    = "currency-code"
  value                  = "USD"
  type                   = "kv"

  depends_on = [azurerm_role_assignment.current_user_app_config_owner]
}

# Role assignment for current user to manage App Configuration (for deployment)
resource "azurerm_role_assignment" "current_user_app_config_owner" {
  scope                = azurerm_app_configuration.main.id
  role_definition_name = "App Configuration Data Owner"
  principal_id         = data.azurerm_client_config.current.object_id
}

# Azure Data Explorer (Kusto) Cluster for metrics storage
resource "azurerm_kusto_cluster" "main" {
  name                = "${var.prefix}-adx"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

  sku {
    name     = "Dev(No SLA)_Standard_D11_v2"
    capacity = 1
  }

  identity {
    type = "SystemAssigned"
  }

  tags = {
    Environment = var.environment
    Project     = "azure-pricing-tool"
    CostControl = "Ignore"
  }
}

# Azure Data Explorer Database for pricing metrics
resource "azurerm_kusto_database" "pricing_metrics" {
  name                = "pricing-metrics"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  cluster_name        = azurerm_kusto_cluster.main.name

  hot_cache_period   = "P7D"   # 7 days hot cache
  soft_delete_period = "P365D" # 1 year retention

  depends_on = [azurerm_kusto_cluster.main]
}

# Role assignment for Function Managed Identity to access ADX
resource "azurerm_role_assignment" "function_adx_contributor" {
  scope                = azurerm_kusto_cluster.main.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.function.principal_id
}

# Add database-level permissions for Function Managed Identity to access ADX database
resource "azurerm_kusto_database_principal_assignment" "function_db_admin" {
  name                = "function-admin"
  resource_group_name = azurerm_resource_group.main.name
  cluster_name        = azurerm_kusto_cluster.main.name
  database_name       = azurerm_kusto_database.pricing_metrics.name

  tenant_id      = data.azurerm_client_config.current.tenant_id
  principal_id   = azurerm_user_assigned_identity.function.principal_id
  principal_type = "App"
  role           = "Admin"
}

# Role assignment for current user to access ADX
resource "azurerm_role_assignment" "current_user_adx_contributor" {
  scope                = azurerm_kusto_cluster.main.id
  role_definition_name = "Contributor"
  principal_id         = data.azurerm_client_config.current.object_id
}

# Register Microsoft.Dashboard resource provider
resource "azurerm_resource_provider_registration" "dashboard" {
  name = "Microsoft.Dashboard"
}

# Azure Managed Grafana instance
resource "azurerm_dashboard_grafana" "main" {
  name                              = "${var.prefix}-grafana"
  resource_group_name               = azurerm_resource_group.main.name
  location                          = azurerm_resource_group.main.location
  api_key_enabled                   = true
  deterministic_outbound_ip_enabled = false
  public_network_access_enabled     = true
  grafana_major_version             = "11"

  identity {
    type = "SystemAssigned"
  }

  tags = {
    Environment = var.environment
    Project     = "azure-pricing-tool"
  }

  depends_on = [
    azurerm_resource_provider_registration.dashboard
  ]
}

# Role assignment for Managed Grafana to access ADX - using Contributor for full access
resource "azurerm_role_assignment" "grafana_adx_viewer" {
  scope                = azurerm_kusto_cluster.main.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_dashboard_grafana.main.identity[0].principal_id
}

# Add database-level permissions for Grafana to access ADX database
resource "azurerm_kusto_database_principal_assignment" "grafana_db_viewer" {
  name                = "grafana-viewer"
  resource_group_name = azurerm_resource_group.main.name
  cluster_name        = azurerm_kusto_cluster.main.name
  database_name       = azurerm_kusto_database.pricing_metrics.name

  tenant_id      = data.azurerm_client_config.current.tenant_id
  principal_id   = azurerm_dashboard_grafana.main.identity[0].principal_id
  principal_type = "App"
  role           = "Viewer"
}

# Role assignment for current user to have Grafana Admin access
resource "azurerm_role_assignment" "current_user_grafana_admin" {
  scope                = azurerm_dashboard_grafana.main.id
  role_definition_name = "Grafana Admin"
  principal_id         = data.azurerm_client_config.current.object_id
}