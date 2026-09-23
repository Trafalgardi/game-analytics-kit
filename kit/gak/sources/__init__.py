"""Source registry: name -> Source class.

A new source is one module implementing base.Source plus its field list,
registered here. Core tables of every registered source are always created,
because the generic views in schema_core.sql select from them.
"""

from __future__ import annotations

from typing import Mapping

from .. import GakError
from .appmetrica import AppMetricaSource
from .base import Log, RequestRejected, Source, SourceError, Table

REGISTRY: dict[str, type[Source]] = {
    AppMetricaSource.name: AppMetricaSource,
}

__all__ = ["REGISTRY", "RequestRejected", "Source", "SourceError", "Table",
           "create", "schema_tables", "source_class"]


def source_class(name: str) -> type[Source]:
    try:
        return REGISTRY[name]
    except KeyError:
        raise GakError(f"unknown source '{name}'; known: {', '.join(REGISTRY)}") from None


def create(name: str, options: Mapping[str, object], token: str | None = None,
           token_origin: str = "", log: Log = print) -> Source:
    return source_class(name)(options, token, token_origin, log)


def schema_tables() -> list[Table]:
    """Tables of every registered source, for store.ensure_schema."""
    return [table for cls in REGISTRY.values() for table in cls().tables()]
