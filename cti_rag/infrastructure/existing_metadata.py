"""Explicit bridge to the repository's existing metadata connection management."""
from .canonical_store import CanonicalMetadataStore

def canonical_store_from_legacy_manager(manager,object_store=None):
    """Bind canonical tables to an already-configured legacy manager engine/pool.

    Callers construct KBDBManager/DBManager in the legacy composition root. This module
    intentionally does not import packages.manager, SQLAlchemy, or credentials itself.
    """
    exists=None if object_store is None else object_store.exists
    return CanonicalMetadataStore.from_existing_manager(manager,object_exists=exists)
