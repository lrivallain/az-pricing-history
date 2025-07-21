output "function_app_name" {
  description = "Name of the Azure Function App"
  value       = azurerm_linux_function_app.pricing_collector.name
}

output "function_app_url" {
  description = "URL of the Azure Function App"
  value       = "https://${azurerm_linux_function_app.pricing_collector.default_hostname}"
}

output "function_http_trigger_url" {
  description = "HTTP trigger URL for manual pricing collection"
  value       = "https://${azurerm_linux_function_app.pricing_collector.default_hostname}/api/collect"
}

output "app_configuration_endpoint" {
  description = "Endpoint of Azure App Configuration"
  value       = azurerm_app_configuration.main.endpoint
}

output "adx_cluster_uri" {
  description = "URI of the Azure Data Explorer cluster"
  value       = azurerm_kusto_cluster.main.uri
}

output "adx_database_name" {
  description = "Name of the Azure Data Explorer database"
  value       = azurerm_kusto_database.pricing_metrics.name
}

output "managed_grafana_url" {
  description = "URL of Azure Managed Grafana"
  value       = azurerm_dashboard_grafana.main.endpoint
}

output "managed_grafana_id" {
  description = "Resource ID of Azure Managed Grafana"
  value       = azurerm_dashboard_grafana.main.id
}

output "resource_group_name" {
  description = "Resource group name"
  value       = azurerm_resource_group.main.name
}

output "storage_account_name" {
  description = "Name of the function storage account"
  value       = azurerm_storage_account.function.name
}
