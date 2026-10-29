"""Flask extension singletons.

They live in their own module so that models can import `db` without importing
the application package, which would import the models — the usual circular
import that makes people reach for deferred imports inside functions.
"""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

__all__ = ["db"]
