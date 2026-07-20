# src/document_actions.py — backward-compatibility shim.
# Canonical location: src/documents/actions.py
import sys
import src.documents.actions
sys.modules[__name__] = src.documents.actions
