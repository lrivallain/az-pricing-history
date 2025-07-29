#!/usr/bin/env python3
"""
History Data Collection - Main Entry Point
==========================================

This is the main entry point for the modular history data collection system.
It uses the Job Orchestrator to coordinate multiple data collectors.

Key Features:
- Modular collector architecture
- Shared ADX client and configuration management
- Centralized error handling and logging
- Extensible design for new data sources
"""

import sys
import os

# Add the app directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.orchestrator import main

if __name__ == "__main__":
    main()
