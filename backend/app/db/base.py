"""Declarative base for all GrowthLoop ORM models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base; keeps model metadata in one registry."""
