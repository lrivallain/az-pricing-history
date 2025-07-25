# Azure Container Apps Infrastructure for Pricing Collection Jobs
# This file contains Container Apps environment, jobs, and supporting resources

# User-assigned managed identity for Container Apps jobs
resource "azurerm_user_assigned_identity" "pricing_jobs" {
  name                = "${var.prefix}-jobs-id"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

  tags = {
    Environment = var.environment
    Project     = "azure-pricing-tool"
  }
}

# Log Analytics Workspace for Container Apps
resource "azurerm_log_analytics_workspace" "main" {
  name                = "${var.prefix}-law"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30

  tags = {
    Environment = var.environment
    Project     = "azure-pricing-tool"
  }
}

# Container Apps Environment
resource "azurerm_container_app_environment" "main" {
  name                       = "${var.prefix}-cae"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  tags = {
    Environment = var.environment
    Project     = "azure-pricing-tool"
  }
}

# Diagnostic settings for Container Apps Environment
resource "azurerm_monitor_diagnostic_setting" "container_app_environment" {
  name                       = "${var.prefix}-cae-diag"
  target_resource_id         = azurerm_container_app_environment.main.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  enabled_log {
    category = "ContainerAppConsoleLogs"
  }

  enabled_log {
    category = "ContainerAppSystemLogs"
  }

  metric {
    category = "AllMetrics"
    enabled  = true
  }
}

# Azure Container Registry for pricing collection images
resource "azurerm_container_registry" "main" {
  name                = "${replace(var.prefix, "-", "")}acr"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  admin_enabled       = false

  identity {
    type = "SystemAssigned"
  }

  tags = {
    Environment = var.environment
    Project     = "azure-pricing-tool"
  }
}

# Role assignment for managed identity to pull from ACR
resource "azurerm_role_assignment" "pricing_jobs_acr_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.pricing_jobs.principal_id
}

# Container Apps Job for scheduled pricing collection
resource "azurerm_container_app_job" "pricing_scheduler" {
  name                         = "${var.prefix}-sched"
  location                     = azurerm_resource_group.main.location
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.pricing_jobs.id]
  }

  replica_timeout_in_seconds = 3600  # 1 hour timeout for long-running jobs
  replica_retry_limit        = 3

  # Scheduled trigger - runs daily at 02:00 UTC
  schedule_trigger_config {
    cron_expression                = "0 2 * * *"  # Daily at 2 AM UTC
    parallelism                    = 1
    replica_completion_count       = 1
  }

  template {
    container {
      name   = "pricing-collector"
      image  = "${azurerm_container_registry.main.login_server}/pricing-collector:latest"
      cpu    = 1.0
      memory = "2Gi"

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.pricing_jobs.client_id
      }

      env {
        name  = "AZURE_TENANT_ID"
        value = data.azurerm_client_config.current.tenant_id
      }

      env {
        name  = "AZURE_SUBSCRIPTION_ID"
        value = data.azurerm_client_config.current.subscription_id
      }

      env {
        name  = "ADX_CLUSTER_URI"
        value = azurerm_kusto_cluster.main.uri
      }

      env {
        name  = "ADX_DATABASE_NAME"
        value = azurerm_kusto_database.pricing_metrics.name
      }

      env {
        name  = "MAX_PRICING_ITEMS"
        value = var.max_pricing_items
      }

      env {
        name  = "JOB_TYPE"
        value = "scheduled"
      }

      env {
        name  = "PYTHONUNBUFFERED"
        value = "1"
      }

      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }

      env {
        name  = "AZURE_LOG_LEVEL"
        value = "WARNING"
      }

      env {
        name  = "JOB_EXECUTION_ID"
        value = "$AZURE_CONTAINER_APP_JOB_EXECUTION_ID"
      }
    }
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.pricing_jobs.id
  }

  tags = {
    Environment = var.environment
    Project     = "azure-pricing-tool"
    JobType     = "scheduled"
  }
}

# Container Apps Job for manual/on-demand pricing collection
resource "azurerm_container_app_job" "pricing_manual" {
  name                         = "${var.prefix}-manual"
  location                     = azurerm_resource_group.main.location
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.pricing_jobs.id]
  }

  replica_timeout_in_seconds = 21600  # 6 hours timeout for manual jobs
  replica_retry_limit        = 0

  # Manual trigger for on-demand execution
  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name   = "pricing-collector"
      image  = "${azurerm_container_registry.main.login_server}/pricing-collector:latest"
      cpu    = 1.0
      memory = "2Gi"

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.pricing_jobs.client_id
      }

      env {
        name  = "AZURE_TENANT_ID"
        value = data.azurerm_client_config.current.tenant_id
      }

      env {
        name  = "AZURE_SUBSCRIPTION_ID"
        value = data.azurerm_client_config.current.subscription_id
      }

      env {
        name  = "ADX_CLUSTER_URI"
        value = azurerm_kusto_cluster.main.uri
      }

      env {
        name  = "ADX_DATABASE_NAME"
        value = azurerm_kusto_database.pricing_metrics.name
      }

      env {
        name  = "MAX_PRICING_ITEMS"
        value = var.max_pricing_items
      }

      env {
        name  = "JOB_TYPE"
        value = "manual"
      }

      env {
        name  = "PYTHONUNBUFFERED"
        value = "1"
      }

      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }

      env {
        name  = "AZURE_LOG_LEVEL"
        value = "WARNING"
      }

      env {
        name  = "JOB_EXECUTION_ID"
        value = "$AZURE_CONTAINER_APP_JOB_EXECUTION_ID"
      }
    }
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.pricing_jobs.id
  }

  tags = {
    Environment = var.environment
    Project     = "azure-pricing-tool"
    JobType     = "manual"
  }
}
