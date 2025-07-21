#!/bin/bash

# Azure Pricing Data Collector Function - Deployment Script
# This script deploys the simplified Azure Function-based pricing data collector

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if we're in the right directory
if [ ! -f "terraform/main.tf" ]; then
    print_error "terraform/main.tf not found. Please run this script from the project root directory."
    exit 1
fi

if [ ! -f "function_app/function_app.py" ]; then
    print_error "function_app/function_app.py not found. Please run this script from the project root directory."
    exit 1
fi

print_status "Starting Azure Pricing Data Collector Function deployment..."

# Check if user is logged into Azure
print_status "Checking Azure CLI login status..."
if ! az account show > /dev/null 2>&1; then
    print_error "You are not logged into Azure CLI. Please run 'az login' first."
    exit 1
fi

SUBSCRIPTION_ID=$(az account show --query id -o tsv)
print_success "Logged into Azure subscription: $SUBSCRIPTION_ID"

# Navigate to terraform directory
cd terraform

# Check if terraform.tfvars exists
if [ ! -f "terraform.tfvars" ]; then
    print_warning "terraform.tfvars not found. Creating from example..."
    if [ -f "terraform.tfvars.example" ]; then
        cp terraform.tfvars.example terraform.tfvars
        # Update subscription_id in terraform.tfvars
        sed -i "s/subscription_id = \".*\"/subscription_id = \"$SUBSCRIPTION_ID\"/" terraform.tfvars
        print_success "Created terraform.tfvars with current subscription ID"
        print_warning "Please review and update terraform.tfvars if needed before continuing."
        read -p "Press Enter to continue or Ctrl+C to abort..."
    else
        print_error "terraform.tfvars.example not found. Please create terraform.tfvars manually."
        exit 1
    fi
fi

# Initialize Terraform
print_status "Initializing Terraform..."
terraform init

# Validate Terraform configuration
print_status "Validating Terraform configuration..."
terraform validate

# Plan Terraform deployment
print_status "Planning Terraform deployment..."
terraform plan -out=tfplan

# Apply Terraform deployment
print_status "Applying Terraform deployment..."
terraform apply tfplan

# Get outputs
print_status "Retrieving deployment outputs..."
FUNCTION_APP_NAME=$(terraform output -raw function_app_name)
RESOURCE_GROUP_NAME=$(terraform output -raw resource_group_name)
FUNCTION_HTTP_URL=$(terraform output -raw function_http_trigger_url)
APP_CONFIG_ENDPOINT=$(terraform output -raw app_configuration_endpoint)
ADX_CLUSTER_URI=$(terraform output -raw adx_cluster_uri)
GRAFANA_URL=$(terraform output -raw managed_grafana_url)

print_success "Infrastructure deployed successfully!"

# Navigate back to project root
cd ..

# Deploy Function App code
print_status "Deploying Function App code..."
cd function_app

# Create a zip file for deployment
print_status "Creating deployment package..."
zip -r function_app.zip . -x "*.pyc" "__pycache__/*" "*.git*"

# Deploy the function app
print_status "Deploying to Azure Function App: $FUNCTION_APP_NAME"
az functionapp deployment source config-zip \
    --resource-group "$RESOURCE_GROUP_NAME" \
    --name "$FUNCTION_APP_NAME" \
    --src function_app.zip

# Clean up
rm function_app.zip

print_success "Function App code deployed successfully!"

# Go back to project root
cd ..

echo ""
print_success "=== Deployment Complete! ==="
echo ""
print_status "📍 Resource Group: $RESOURCE_GROUP_NAME"
print_status "⚡ Function App: $FUNCTION_APP_NAME"
print_status "🌐 HTTP Trigger URL: $FUNCTION_HTTP_URL"
print_status "⚙️  App Configuration: $APP_CONFIG_ENDPOINT"
print_status "📊 ADX Cluster: $ADX_CLUSTER_URI"
print_status "📈 Grafana Dashboard: $GRAFANA_URL"
echo ""
print_status "🔧 Next Steps:"
echo "  1. Configure pricing filters in App Configuration:"
echo "     az appconfig kv set --name $(echo $APP_CONFIG_ENDPOINT | cut -d. -f1 | cut -d/ -f3) --key pricing-filters --value '{\"serviceName\":\"Virtual Machines\"}'"
echo ""
echo "  2. Test manual execution:"
echo "     curl -X POST \"$FUNCTION_HTTP_URL\" -H \"Content-Type: application/json\" -d '{\"filters\":{\"serviceName\":\"Virtual Machines\"}}'"
echo ""
echo "  3. Monitor function execution in Azure Portal or view logs:"
echo "     az functionapp logs tail --name $FUNCTION_APP_NAME --resource-group $RESOURCE_GROUP_NAME"
echo ""
echo "  4. Access Grafana dashboard for analytics:"
echo "     $GRAFANA_URL"
echo ""
print_success "The function will run automatically daily at 2 AM UTC based on the timer trigger."

# Provide Azure Portal link
AZURE_PORTAL_URL="https://portal.azure.com/#@/resource/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP_NAME/overview"
print_status "🌐 View resources in Azure Portal: $AZURE_PORTAL_URL"
