#!/usr/bin/env python3
"""
Shared ADX Client Management
===========================

This module provides centralized Azure Data Explorer (ADX) client management
for all collectors in the history data collection system.

Key Features:
- Multi-method authentication (CLI token, DefaultAzureCredential, Managed Identity)
- Connection retry logic with fallback methods
- Shared client instance for efficiency
- Environment-aware authentication selection
"""

import os
import time
import logging
from typing import Optional

from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder


AUTH_METHODS_RETRIES = 1

class ADXClientManager:
    """Manages ADX client creation and authentication."""

    def __init__(self, cluster_uri: str, is_local: bool = False):
        """
        Initialize the ADX client manager.

        Args:
            cluster_uri: ADX cluster URI
            is_local: Whether running in local development mode
        """
        self.cluster_uri = cluster_uri
        self.is_local = is_local
        self.logger = logging.getLogger(__name__)
        self._client = None

    def get_client(self) -> KustoClient:
        """
        Get or create ADX client with retry logic and multiple auth methods.

        Returns:
            Authenticated KustoClient instance

        Raises:
            Exception: If all authentication methods fail
        """
        if self._client:
            return self._client

        auth_methods = []

        # In production Container Apps, try Managed Identity first
        if not self.is_local:
            client_id = os.getenv('AZURE_CLIENT_ID')
            if client_id:
                # Container Apps uses user-assigned managed identity
                auth_methods.append(('User-assigned Managed Identity (Token)', lambda: self._create_with_default_credential()))
                auth_methods.append(('User-assigned Managed Identity (Direct)', lambda: self._create_with_managed_identity(client_id)))
            else:
                # Fallback to system-assigned if no client_id
                auth_methods.append(('System-assigned Managed Identity', lambda: self._create_with_managed_identity(None)))
                auth_methods.append(('DefaultAzureCredential', lambda: self._create_with_default_credential()))
        else:
            # Local development - try different methods
            auth_methods.append(('Azure CLI Token', lambda: self._create_with_cli_token()))
            auth_methods.append(('DefaultAzureCredential', lambda: self._create_with_default_credential()))

        last_exception = None

        for auth_name, auth_method in auth_methods:
            for attempt in range(AUTH_METHODS_RETRIES):  # attempts per auth method
                try:
                    self.logger.info(f"Trying {auth_name} (attempt {attempt + 1})...")

                    self._client = auth_method()

                    # Test the connection
                    test_query = ".show version"
                    self._client.execute_mgmt("", test_query)

                    self.logger.info(f"ADX client created successfully with {auth_name}")
                    return self._client

                except Exception as e:
                    last_exception = e
                    self.logger.warning(f"{auth_name} attempt {attempt + 1} failed: {e}")

                    if attempt < 2:  # Wait before retry
                        wait_time = (attempt + 1) * 5
                        self.logger.info(f"Waiting {wait_time} seconds before retry...")
                        time.sleep(wait_time)

        # All auth methods failed
        error_msg = f"Failed to create ADX client with all authentication methods. Last error: {last_exception}"
        self.logger.error(error_msg)
        raise Exception(error_msg)

    def _create_with_managed_identity(self, client_id: Optional[str] = None) -> KustoClient:
        """Create Kusto client with Managed Identity."""
        # In Container Apps, we need to use the client_id for user-assigned managed identity
        if client_id:
            self.logger.info(f"Using User-assigned Managed Identity with client_id: {client_id}")
            kcsb = KustoConnectionStringBuilder.with_aad_managed_service_identity_authentication(
                self.cluster_uri, client_id
            )
        else:
            self.logger.info("Using System-assigned Managed Identity")
            kcsb = KustoConnectionStringBuilder.with_aad_managed_service_identity_authentication(
                self.cluster_uri
            )
        return KustoClient(kcsb)

    def _create_with_default_credential(self) -> KustoClient:
        """Create Kusto client with DefaultAzureCredential."""
        if self.is_local:
            # Local development - exclude managed identity
            credential = DefaultAzureCredential(exclude_managed_identity_credential=True)
            self.logger.info("Using DefaultAzureCredential (excluding managed identity)")
        else:
            # Container Apps environment - prioritize managed identity
            client_id = os.getenv('AZURE_CLIENT_ID')
            if client_id:
                self.logger.info(f"Using ManagedIdentityCredential with client_id: {client_id}")
                credential = ManagedIdentityCredential(client_id=client_id)
            else:
                self.logger.info("Using DefaultAzureCredential with managed identity")
                credential = DefaultAzureCredential()

        token = credential.get_token("https://help.kusto.windows.net/.default")
        kcsb = KustoConnectionStringBuilder.with_aad_user_token_authentication(
            self.cluster_uri, token.token
        )
        return KustoClient(kcsb)

    def _create_with_cli_token(self) -> KustoClient:
        """Create Kusto client with Azure CLI token (local development)."""
        adx_token = os.getenv('AZURE_ADX_TOKEN')
        if adx_token:
            kcsb = KustoConnectionStringBuilder.with_aad_user_token_authentication(
                self.cluster_uri, adx_token
            )
            return KustoClient(kcsb)
        else:
            raise Exception("AZURE_ADX_TOKEN not available")

    def close(self):
        """Close the ADX client."""
        if self._client:
            self._client = None
            self.logger.info("ADX client closed")
