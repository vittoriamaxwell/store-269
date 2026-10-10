"""store-269: a time-ordered key-value store.

Public surface:
    Store      -- the store class.
    Entry      -- the record returned by queries (key, value, timestamp).
"""
from store_269.core import Entry, Store

__all__ = ["Store", "Entry"]
