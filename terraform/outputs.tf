output "adx_cluster_uri" {
  description = "URI of the Azure Data Explorer cluster"
  value       = azurerm_kusto_cluster.main.uri
}

output "adx_database_name" {
  description = "Name of the Azure Data Explorer database"
  value       = azurerm_kusto_database.pricing_metrics.name
}

output "container_apps_environment_name" {
  description = "Name of the Container Apps Environment"
  value       = azurerm_container_app_environment.main.name
}

output "container_registry_login_server" {
  description = "Login server for Azure Container Registry"
  value       = azurerm_container_registry.main.login_server
}

output "pricing_scheduler_job_name" {
  description = "Name of the scheduled pricing collection job"
  value       = azurerm_container_app_job.pricing_scheduler.name
}

output "pricing_manual_job_name" {
  description = "Name of the manual pricing collection job"
  value       = azurerm_container_app_job.pricing_manual.name
}

output "managed_identity_client_id" {
  description = "Client ID of the managed identity for Container Apps jobs"
  value       = azurerm_user_assigned_identity.pricing_jobs.client_id
}

output "log_analytics_workspace_id" {
  description = "ID of the Log Analytics workspace"
  value       = azurerm_log_analytics_workspace.main.id
}

output "resource_group_name" {
  description = "Resource group name"
  value       = azurerm_resource_group.main.name
}

output "managed_grafana_url" {
  description = "URL of Azure Managed Grafana"
  value       = azurerm_dashboard_grafana.main.endpoint
}

output "managed_grafana_id" {
  description = "Resource ID of Azure Managed Grafana"
  value       = azurerm_dashboard_grafana.main.id
}
