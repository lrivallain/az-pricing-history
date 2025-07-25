#!/bin/bash

# Azure Pricing Collection - Local Docker Runner
# ==============================================

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
WHITE='\033[1;37m'
NC='\033[0m'

print_header() {
    echo -e "${GREEN}$1${NC}"
    echo -e "${GREEN}$(printf '=%.0s' $(seq 1 ${#1}))${NC}"
}

print_info() {
    echo -e "${CYAN}$1${NC}"
}

print_status() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# Configuration
CONFIG_FILE=".env.local"
IMAGE_NAME="azpricingtoolacr.azurecr.io/pricing-collector"
IMAGE_TAG="local-test"
CONTAINER_NAME="pricing-collector-local"

print_header "Azure Pricing Collection - Local Docker Run"
echo ""

# Check if Docker is available
if ! command -v docker >/dev/null 2>&1; then
    print_error "Docker not found. Please install Docker Desktop."
    exit 1
fi

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    print_error "Docker is not running. Please start Docker Desktop."
    exit 1
fi

print_status "Docker is available and running"

# Check if configuration file exists
if [[ ! -f "$CONFIG_FILE" ]]; then
    print_error "Configuration file '$CONFIG_FILE' not found."
    print_info "Create the .env.local file with your configuration settings."
    exit 1
fi

# Build Docker image
print_info "Building Docker image: $IMAGE_NAME:$IMAGE_TAG"

cd app/
if ! docker build -t "$IMAGE_NAME:$IMAGE_TAG" .; then
    print_error "Failed to build Docker image"
    exit 1
fi
cd ..
print_status "Docker image built successfully"

# Clean up any existing container
if docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
    print_info "Removing existing container: $CONTAINER_NAME"
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1
fi

# Check Azure authentication
print_info "Checking Azure authentication..."
if az account show >/dev/null 2>&1; then
    ACCOUNT_INFO=$(az account show --query "name" -o tsv)
    print_status "Authenticated as: $ACCOUNT_INFO"

    # Get Azure CLI token for ADX access
    print_info "Getting Azure CLI access token for ADX..."
    ADX_TOKEN=$(az account get-access-token --resource "https://help.kusto.windows.net" --query "accessToken" -o tsv)
    if [[ -z "$ADX_TOKEN" ]]; then
        print_error "Failed to get Azure CLI access token for ADX"
        exit 1
    fi
    print_status "Azure CLI access token obtained"

    # Get Azure CLI credentials for container
    AZURE_CONFIG_DIR="$HOME/.azure"
    if [[ ! -d "$AZURE_CONFIG_DIR" ]]; then
        print_error "Azure CLI configuration not found. Run 'az login' first."
        exit 1
    fi
else
    print_error "Not authenticated with Azure. Run 'az login' first."
    exit 1
fi

# Prepare environment variables from config file
print_info "Loading configuration from $CONFIG_FILE..."
ENV_VARS=""

# Read config file and convert to Docker env format
while IFS='=' read -r key value || [[ -n "$key" ]]; do
    # Skip comments and empty lines
    if [[ $key =~ ^[[:space:]]*# ]] || [[ -z "$key" ]]; then
        continue
    fi

    # Remove whitespace from key
    key=$(echo "$key" | xargs)

    # For value, only remove leading/trailing whitespace, preserve content
    value=$(echo "$value" | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*$//')

    # Remove outer quotes if present, but preserve inner content
    if [[ $value =~ ^\".*\"$ ]]; then
        value=$(echo "$value" | sed 's/^"\(.*\)"$/\1/')
    fi

    if [[ -n "$key" && -n "$value" ]]; then
        # Properly escape the value for Docker env vars
        ENV_VARS="$ENV_VARS -e $key=$(printf '%q' "$value")"
    fi
done < "$CONFIG_FILE"

# Set job type for local Docker execution
ENV_VARS="$ENV_VARS -e JOB_TYPE=$(printf '%q' 'local-docker')"

# Add Azure CLI token as environment variable for ADX access
ENV_VARS="$ENV_VARS -e AZURE_ADX_TOKEN=$(printf '%q' "$ADX_TOKEN")"

# Show configuration summary
echo ""
print_header "Run Configuration"
echo -e "  ${WHITE}Docker Image:${NC} $IMAGE_NAME:$IMAGE_TAG"
echo -e "  ${WHITE}Container:${NC} $CONTAINER_NAME"
echo -e "  ${WHITE}Config File:${NC} $CONFIG_FILE"
echo -e "  ${WHITE}Job Type:${NC} local-docker"

# Check for dry run mode in config
if grep -q "^DRY_RUN=true" "$CONFIG_FILE" 2>/dev/null; then
    echo -e "  ${WHITE}Mode:${NC} ${YELLOW}DRY RUN${NC}"
fi

echo ""

# Run the container
print_info "Starting Docker container..."
echo ""

# Docker run command with Azure CLI credentials mounted
DOCKER_CMD="docker run --rm --name $CONTAINER_NAME \
    -v \"$AZURE_CONFIG_DIR:/root/.azure:ro\" \
    $ENV_VARS \
    $IMAGE_NAME:$IMAGE_TAG"

print_info "Executing: docker run --rm --name $CONTAINER_NAME [env vars] $IMAGE_NAME:$IMAGE_TAG"
echo ""

if eval $DOCKER_CMD; then
    echo ""
    print_status "Docker container execution completed successfully!"

    # Check if dry run mode is enabled
    if ! grep -q "^DRY_RUN=true" "$CONFIG_FILE" 2>/dev/null; then
        echo ""
        print_info "You can query the data in ADX using:"
        echo -e "  ${CYAN}pricing_metrics${NC}"
        echo -e "  ${CYAN}| where job_datetime >= ago(1h)${NC}"
        echo -e "  ${CYAN}| where job_type == \"local-docker\"${NC}"
        echo -e "  ${CYAN}| summarize count() by armRegionName, serviceName${NC}"
    fi
else
    echo ""
    print_error "Docker container execution failed!"
    print_info "Check the logs above for details."

    # Show container logs if container still exists
    if docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
        print_info "Container logs:"
        docker logs "$CONTAINER_NAME"
    fi

    exit 1
fi
