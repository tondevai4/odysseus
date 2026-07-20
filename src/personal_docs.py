# src/personal_docs.py — backward-compatibility shim.
# Canonical location: src/documents/personal_docs.py
import sys
import src.documents.personal_docs
sys.modules[__name__] = src.documents.personal_docs
