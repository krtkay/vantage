"""Data access: a pluggable SQLAlchemy engine, runtime schema introspection, and
an optional human-authored data dictionary. Point DATABASE_URL at any
SQLite/Postgres/MySQL database and the agent adapts automatically."""

from .db import dialect_of, make_engine, run_query
from .dictionary import format_dictionary, load_dictionary
from .schema import SchemaInfo, introspect

__all__ = [
    "make_engine",
    "run_query",
    "dialect_of",
    "introspect",
    "SchemaInfo",
    "load_dictionary",
    "format_dictionary",
]
