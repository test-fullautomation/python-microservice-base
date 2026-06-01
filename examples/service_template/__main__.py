"""Entry point for ``python -m <service_folder>`` execution."""
import os
import sys

# Ensure the service directory is on sys.path for local imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import main

if __name__ == '__main__':
   main()
