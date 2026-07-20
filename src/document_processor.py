# src/document_processor.py — backward-compatibility shim.
# Canonical location: src/documents/processor.py
import sys
import src.documents.processor
sys.modules[__name__] = src.documents.processor
