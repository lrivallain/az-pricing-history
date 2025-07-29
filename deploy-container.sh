#!/bin/bash

# Azure Pricing Collection - Container Apps Deployment Script (Bash)
# ===================================================================

set -e  # Exit on any error

# Script parameters
RESOURCE_GROUP_NAME=""
CONTAINER_REGISTRY_NAME=""
IMAGE_TAG="latest"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
GRAY='\033[0;37m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}✓${NC} $1"
}

print_info() {
    echo -e "${CYAN}$1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_header() {
    echo -e "${GREEN}$1${NC}"
    echo -e "${GREEN}$(printf '=%.0s' $(seq 1 ${#1}))${NC}"
}

# Function to show usage
show_usage() {
    echo "Usage: $0 -g <resource-group> -r <registry-name> [-t <image-tag>]"
    echo ""
    echo "Options:"
    echo "  -g, --resource-group    Azure resource group name (required)"
    echo "  -r, --registry          Azure Container Registry name (required)"
    echo "  -t, --tag              Container image tag (default: latest)"
    echo "  -h, --help             Show this help message"
    echo ""
    echo "Example:"
    echo "  $0 -g azure-pricing-RG -r azpricingtoolacr"
    echo "  $0 --resource-group azure-pricing-RG --registry azpricingtoolacr --tag v1.0.0"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -g|--resource-group)
            RESOURCE_GROUP_NAME="$2"
            shift 2
            ;;
        -r|--registry)
            CONTAINER_REGISTRY_NAME="$2"
            shift 2
            ;;
        -t|--tag)
            IMAGE_TAG="$2"
            shift 2
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Validate required parameters
if [[ -z "$RESOURCE_GROUP_NAME" ]]; then
    print_error "Resource group name is required"
    show_usage
    exit 1
fi

if [[ -z "$CONTAINER_REGISTRY_NAME" ]]; then
    print_error "Container registry name is required"
    show_usage
    exit 1
fi

# Variables
APP_PATH="app"
IMAGE_NAME="pricing-collector"
FULL_IMAGE_NAME="${CONTAINER_REGISTRY_NAME}.azurecr.io/${IMAGE_NAME}:${IMAGE_TAG}"

print_header "Azure Pricing Collection - Container Apps Deployment"
echo ""

# Check if logged into Azure
print_info "Checking Azure authentication..."
if ! az account show >/dev/null 2>&1; then
    print_error "Please log in to Azure first: az login"
    exit 1
fi

ACCOUNT_INFO=$(az account show --query "user.name" -o tsv)
print_status "Authenticated as: $ACCOUNT_INFO"

# Check if Docker is available
print_info "Checking Docker availability..."
if ! command -v docker >/dev/null 2>&1; then
    print_error "Docker is not available. Please install Docker."
    exit 1
fi

DOCKER_VERSION=$(docker --version)
print_status "Docker is available: $DOCKER_VERSION"

# Login to Azure Container Registry
print_info "Logging into Azure Container Registry..."
if ! az acr login --name "$CONTAINER_REGISTRY_NAME" >/dev/null 2>&1; then
    print_error "Failed to login to Azure Container Registry"
    exit 1
fi
print_status "Logged into ACR: $CONTAINER_REGISTRY_NAME"

# Build Docker image
print_info "Building Docker image..."
print_info "Image: $FULL_IMAGE_NAME"

if [[ ! -d "$APP_PATH" ]]; then
    print_error "Application directory '$APP_PATH' not found"
    exit 1
fi

pushd "$APP_PATH" >/dev/null

if ! docker build -t "$FULL_IMAGE_NAME" . >/dev/null 2>&1; then
    print_error "Failed to build Docker image"
    popd >/dev/null
    exit 1
fi

popd >/dev/null
print_status "Docker image built successfully"

# Push Docker image to ACR
print_info "Pushing Docker image to Azure Container Registry..."
if ! docker push "$FULL_IMAGE_NAME" >/dev/null 2>&1; then
    print_error "Failed to push Docker image to ACR"
    exit 1
fi
print_status "Docker image pushed successfully"

# Get Container Apps Jobs information
print_info "Getting Container Apps Jobs information..."

SCHEDULED_JOB=$(az containerapp job list \
    --resource-group "$RESOURCE_GROUP_NAME" \
    --query "[?contains(name, 'scheduler')].name" -o tsv 2>/dev/null | head -n 1)

MANUAL_JOB=$(az containerapp job list \
    --resource-group "$RESOURCE_GROUP_NAME" \
    --query "[?contains(name, 'manual')].name" -o tsv 2>/dev/null | head -n 1)

if [[ -n "$SCHEDULED_JOB" ]]; then
    print_status "Scheduled Job found: $SCHEDULED_JOB"
    print_info "Updating the image for this job"
    az containerapp job update --resource-group "$RESOURCE_GROUP_NAME" --name "$SCHEDULED_JOB" --image "$FULL_IMAGE_NAME" > /dev/null && \
    print_status "Scheduled Job updated with new image: $FULL_IMAGE_NAME" || \
    print_error "Failed to update Scheduled Job with new image"
fi

if [[ -n "$MANUAL_JOB" ]]; then
    print_status "Manual Job found: $MANUAL_JOB"
    print_info "Updating the image for this job"
    az containerapp job update --resource-group "$RESOURCE_GROUP_NAME" --name "$MANUAL_JOB" --image "$FULL_IMAGE_NAME" > /dev/null && \
    print_status "Manual Job updated with new image: $FULL_IMAGE_NAME" || \
    print_error "Failed to update Manual Job with new image"
fi

echo ""
print_header "Deployment completed successfully!"
echo ""

print_info "Image Details:"
echo -e "  ${WHITE}Registry:${NC} ${CONTAINER_REGISTRY_NAME}.azurecr.io"
echo -e "  ${WHITE}Image:${NC} $IMAGE_NAME"
echo -e "  ${WHITE}Tag:${NC} $IMAGE_TAG"
echo -e "  ${WHITE}Full Name:${NC} $FULL_IMAGE_NAME"
echo ""

if [[ -n "$SCHEDULED_JOB" ]] || [[ -n "$MANUAL_JOB" ]]; then
    print_info "Next Steps:"

    if [[ -n "$MANUAL_JOB" ]]; then
        echo -e "  ${WHITE}1. To trigger manual job execution:${NC}"
        echo -e "     ${GRAY}az containerapp job start --resource-group \"$RESOURCE_GROUP_NAME\" --name \"$MANUAL_JOB\"${NC}"
        echo ""

        echo -e "  ${WHITE}2. To trigger with filters (for testing):${NC}"
        echo -e "     ${GRAY}az containerapp job start --resource-group \"$RESOURCE_GROUP_NAME\" --name \"$MANUAL_JOB\" \\${NC}"
        echo -e "     ${GRAY} AZURE_PRICING_MAX_ITEMS=\"10\"${NC}"
        echo ""
    fi

    echo -e "  ${WHITE}3. To list recent executions:${NC}"
    echo -e "     ${GRAY}az containerapp job execution list --resource-group \"$RESOURCE_GROUP_NAME\" \\${NC}"
    echo -e "     ${GRAY}  --name <job-name> --output table${NC}"
fi

echo ""
print_status "Ready to collect Azure pricing data! 🚀"
