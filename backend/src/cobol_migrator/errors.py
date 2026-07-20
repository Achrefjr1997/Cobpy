from __future__ import annotations


class MigratorError(Exception):
    """Base exception for the COBOL migrator."""


class IngestionError(MigratorError):
    """Error during COBOL source ingestion."""


class SafetyError(MigratorError):
    """Generated code failed safety checks."""


class ValidationError(MigratorError):
    """Validation of generated code failed."""
