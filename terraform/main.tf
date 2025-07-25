# Azure Pricing Tool Infrastructure with Terraform
# Stack: Azure Container Apps Jobs + Azure Data Explorer + Grafana

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
  storage_use_azuread = true
}

# Data source for current Azure client configuration
data "azurerm_client_config" "current" {}

# Resource Group
resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = var.location

  tags = {
    Environment = var.environment
    Project     = "azure-pricing-tool"
  }
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

  depends_on = [
    azurerm_kusto_cluster.main
  ]
}

# Role assignment for Container Apps jobs Managed Identity to access ADX
resource "azurerm_role_assignment" "container_apps_adx_contributor" {
  scope                = azurerm_kusto_cluster.main.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.pricing_jobs.principal_id
}

# Add database-level permissions for Container Apps jobs Managed Identity to access ADX database
resource "azurerm_kusto_database_principal_assignment" "container_apps_db_admin" {
  name                = "container-apps-admin"
  resource_group_name = azurerm_resource_group.main.name
  cluster_name        = azurerm_kusto_cluster.main.name
  database_name       = azurerm_kusto_database.pricing_metrics.name

  tenant_id      = data.azurerm_client_config.current.tenant_id
  principal_id   = azurerm_user_assigned_identity.pricing_jobs.principal_id
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