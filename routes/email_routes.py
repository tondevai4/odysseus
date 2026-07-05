"""Backward compatibility shim for email routes.

The monolithic email_routes.py has been refactored into the `routes.email` package.
This file is preserved so that existing imports across the project do not break.
"""

from routes.email import setup_email_routes

# If any specific functions were imported from here by other modules,
# they should be mapped here or the importing modules should be updated.
