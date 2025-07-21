variable "subscription_id" {
  description = "Azure subscription ID"
  type        = string
}

variable "resource_group_name" {
  description = "Name of the Azure resource group"
  type        = string
  default     = "rg-azure-pricing-tool"
}

variable "location" {
  description = "Azure region for resources"
  type        = string
  default     = "East US"
}

variable "prefix" {
  description = "Prefix for resource names"
  type        = string
  default     = "pricing-tool"
}

variable "environment" {
  description = "Environment tag"
  type        = string
  default     = "development"
}

variable "max_pricing_items" {
  description = "Maximum pricing items to process (-1 for unlimited)"
  type        = string
  default     = "-1"
}

variable "github_repo_url" {
  description = "GitHub repository URL for source control"
  type        = string
  default     = "https://github.com/lrivallain/az-pricing-history.git"
}

variable "github_branch" {
  description = "GitHub branch to deploy from"
  type        = string
  default     = "master"
}