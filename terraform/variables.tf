variable "subscription_id" {
  description = "Azure subscription ID"
  type        = string
}

variable "resource_group_name" {
  description = "Name of the Azure resource group"
  type        = string
  default     = "azure-pricing-RG"
}

variable "location" {
  description = "Azure region for resources"
  type        = string
  default     = "East US"
}

variable "prefix" {
  description = "Prefix for resource names"
  type        = string
  default     = "az-pricing-tool"
}

variable "environment" {
  description = "Environment tag"
  type        = string
  default     = "production"
}

variable "max_pricing_items" {
  description = "Maximum pricing items to process per job"
  type        = string
  default     = "1000"
}