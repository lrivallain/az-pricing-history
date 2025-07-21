# Azure Pricing Data Collector Function - Deployment Script (PowerShell)
# This script deploys the simplified Azure Function-based pricing data collector

param(
    [switch]$SkipTerraform = $false
)

# Function to print colored output
function Write-Status {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Blue
}

function Write-Success {
    param([string]$Message)
    Write-Host "[SUCCESS] $Message" -ForegroundColor Green
}

function Write-Warning {
    param([string]$Message)
    Write-Host "[WARNING] $Message" -ForegroundColor Yellow
}

function Write-Error {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

# Check if we're in the right directory
if (-not (Test-Path "terraform\main.tf")) {
    Write-Error "terraform\main.tf not found. Please run this script from the project root directory."
    exit 1
}

if (-not (Test-Path "function_app\function_app.py")) {
    Write-Error "function_app\function_app.py not found. Please run this script from the project root directory."
    exit 1
}

Write-Status "Starting Azure Pricing Data Collector Function deployment..."

# Check if user is logged into Azure
Write-Status "Checking Azure CLI login status..."
try {
    $null = az account show 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Not logged in"
    }
} catch {
    Write-Error "You are not logged into Azure CLI. Please run 'az login' first."
    exit 1
}

$subscriptionId = az account show --query id -o tsv
Write-Success "Logged into Azure subscription: $subscriptionId"

if (-not $SkipTerraform) {
    # Navigate to terraform directory
    Push-Location terraform

    try {
        # Check if terraform.tfvars exists
        if (-not (Test-Path "terraform.tfvars")) {
            Write-Warning "terraform.tfvars not found. Creating from example..."
            if (Test-Path "terraform.tfvars.example") {
                Copy-Item "terraform.tfvars.example" "terraform.tfvars"
                # Update subscription_id in terraform.tfvars
                $content = Get-Content "terraform.tfvars"
                $content = $content -replace 'subscription_id = ".*"', "subscription_id = `"$subscriptionId`""
                Set-Content "terraform.tfvars" $content
                Write-Success "Created terraform.tfvars with current subscription ID"
                Write-Warning "Please review and update terraform.tfvars if needed before continuing."
                Read-Host "Press Enter to continue or Ctrl+C to abort"
            } else {
                Write-Error "terraform.tfvars.example not found. Please create terraform.tfvars manually."
                exit 1
            }
        }

        # Initialize Terraform
        Write-Status "Initializing Terraform..."
        terraform init
        if ($LASTEXITCODE -ne 0) { throw "Terraform init failed" }

        # Validate Terraform configuration
        Write-Status "Validating Terraform configuration..."
        terraform validate
        if ($LASTEXITCODE -ne 0) { throw "Terraform validation failed" }

        # Plan Terraform deployment
        Write-Status "Planning Terraform deployment..."
        terraform plan -out=tfplan
        if ($LASTEXITCODE -ne 0) { throw "Terraform plan failed" }

        # Apply Terraform deployment
        Write-Status "Applying Terraform deployment..."
        terraform apply tfplan
        if ($LASTEXITCODE -ne 0) { throw "Terraform apply failed" }

        # Get outputs
        Write-Status "Retrieving deployment outputs..."
        $functionAppName = terraform output -raw function_app_name
        $resourceGroupName = terraform output -raw resource_group_name
        $functionHttpUrl = terraform output -raw function_http_trigger_url
        $appConfigEndpoint = terraform output -raw app_configuration_endpoint
        $adxClusterUri = terraform output -raw adx_cluster_uri
        $grafanaUrl = terraform output -raw managed_grafana_url

        Write-Success "Infrastructure deployed successfully!"
    } catch {
        Write-Error "Terraform deployment failed: $_"
        exit 1
    } finally {
        # Navigate back to project root
        Pop-Location
    }
} else {
    Write-Status "Skipping Terraform deployment (using existing infrastructure)..."
    # Get outputs from existing Terraform state
    Push-Location terraform
    try {
        $functionAppName = terraform output -raw function_app_name
        $resourceGroupName = terraform output -raw resource_group_name
        $functionHttpUrl = terraform output -raw function_http_trigger_url
        $appConfigEndpoint = terraform output -raw app_configuration_endpoint
        $adxClusterUri = terraform output -raw adx_cluster_uri
        $grafanaUrl = terraform output -raw managed_grafana_url
    } catch {
        Write-Error "Failed to get Terraform outputs. Make sure infrastructure is deployed first."
        exit 1
    } finally {
        Pop-Location
    }
}

# Deploy Function App code
Write-Status "Deploying Function App code..."
Push-Location function_app

try {
    # Create a zip file for deployment
    Write-Status "Creating deployment package..."
    $zipPath = "function_app.zip"
    if (Test-Path $zipPath) {
        Remove-Item $zipPath
    }

    # Get all files except certain patterns
    $files = Get-ChildItem -Recurse | Where-Object {
        $_.Name -notmatch "\.pyc$|__pycache__|\.git" -and -not $_.PSIsContainer
    }

    Compress-Archive -Path $files -DestinationPath $zipPath

    # Deploy the function app
    Write-Status "Deploying to Azure Function App: $functionAppName"
    az functionapp deployment source config-zip --resource-group $resourceGroupName --name $functionAppName --src $zipPath
    if ($LASTEXITCODE -ne 0) { throw "Function app deployment failed" }

    # Clean up
    Remove-Item $zipPath

    Write-Success "Function App code deployed successfully!"
} catch {
    Write-Error "Function deployment failed: $_"
    exit 1
} finally {
    # Go back to project root
    Pop-Location
}

Write-Host ""
Write-Success "=== Deployment Complete! ==="
Write-Host ""
Write-Status "📍 Resource Group: $resourceGroupName"
Write-Status "⚡ Function App: $functionAppName"
Write-Status "🌐 HTTP Trigger URL: $functionHttpUrl"
Write-Status "⚙️  App Configuration: $appConfigEndpoint"
Write-Status "📊 ADX Cluster: $adxClusterUri"
Write-Status "📈 Grafana Dashboard: $grafanaUrl"
Write-Host ""
Write-Status "🔧 Next Steps:"
$appConfigName = ($appConfigEndpoint -split '\.')[0] -replace 'https://', ''
Write-Host "  1. Configure pricing filters in App Configuration:"
Write-Host "     az appconfig kv set --name $appConfigName --key pricing-filters --value '{`"serviceName`":`"Virtual Machines`"}'"
Write-Host ""
Write-Host "  2. Test manual execution:"
Write-Host "     Invoke-RestMethod -Uri '$functionHttpUrl' -Method Post -ContentType 'application/json' -Body '{`"filters`":{`"serviceName`":`"Virtual Machines`"}}'"
Write-Host ""
Write-Host "  3. Monitor function execution in Azure Portal or view logs:"
Write-Host "     az functionapp logs tail --name $functionAppName --resource-group $resourceGroupName"
Write-Host ""
Write-Host "  4. Access Grafana dashboard for analytics:"
Write-Host "     $grafanaUrl"
Write-Host ""
Write-Success "The function will run automatically daily at 2 AM UTC based on the timer trigger."

# Provide Azure Portal link
$azurePortalUrl = "https://portal.azure.com/#@/resource/subscriptions/$subscriptionId/resourceGroups/$resourceGroupName/overview"
Write-Status "🌐 View resources in Azure Portal: $azurePortalUrl"
