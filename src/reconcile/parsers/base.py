"""Shared parsing helpers for the orders and settlements readers.

Spreadsheets are read with everything as text (no implicit float/NaN coercion),
then validated row-by-row into typed Pydantic models. Validation errors are
aggregated with 1-based spreadsheet row numbers so users can find and fix the
offending cell quickly.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import TypeVar

import pandas as pd
from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)

# Source can be a filesystem path or raw bytes (e.g. an HTTP upload).
Source = str | Path | bytes


class ParseError(Exception):
    """Raised when an input file cannot be read or validated.

    Carries a human-readable message plus the structured list of per-row errors
    (when applicable) so callers can surface them in the UI/CLI or an incident.
    """

    def __init__(self, message: str, *, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.errors = errors or []


def _detect_is_csv(filename: str | None, source: Source) -> bool:
    """Decide whether the source is CSV (vs Excel) from its filename/path."""
    name = filename
    if name is None and isinstance(source, (str, Path)):
        name = str(source)
    if name is None:
        raise ParseError("Cannot determine file type: provide a .csv or .xlsx filename.")
    lowered = name.lower()
    if lowered.endswith(".csv"):
        return True
    if lowered.endswith((".xlsx", ".xlsm", ".xls")):
        return False
    raise ParseError(f"Unsupported file type: {name!r}. Use .csv or .xlsx.")


def load_dataframe(source: Source, filename: str | None = None) -> pd.DataFrame:
    """Read a CSV/Excel source into a string-typed DataFrame.

    Blank cells become empty strings (not NaN) so downstream cleaning can map
    them to ``None`` consistently.
    """
    is_csv = _detect_is_csv(filename, source)
    buffer: io.BytesIO | str | Path
    buffer = io.BytesIO(source) if isinstance(source, bytes) else source

    try:
        if is_csv:
            frame = pd.read_csv(buffer, dtype=str, keep_default_na=False, na_values=[])
        else:
            frame = pd.read_excel(
                buffer, dtype=str, keep_default_na=False, na_values=[], engine="openpyxl"
            )
    except ValueError as exc:
        raise ParseError(f"Could not read file: {exc}") from exc
    except OSError as exc:  # missing file, permission error, etc.
        raise ParseError(f"Could not open file: {exc}") from exc

    frame.columns = [str(col).strip() for col in frame.columns]
    return frame


def require_columns(frame: pd.DataFrame, required: set[str], file_label: str) -> None:
    """Raise :class:`ParseError` if any required column is missing."""
    present = set(frame.columns)
    missing = required - present
    if missing:
        raise ParseError(
            f"{file_label} is missing required column(s): {', '.join(sorted(missing))}.",
            errors=[f"missing column: {name}" for name in sorted(missing)],
        )


def clean_cell(value: object) -> str | None:
    """Strip whitespace; map empty strings to ``None``."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def validate_rows(
    frame: pd.DataFrame,
    model: type[ModelT],
    *,
    file_label: str,
    field_map: dict[str, str],
) -> list[ModelT]:
    """Validate every data row into ``model`` instances, aggregating errors.

    ``field_map`` maps spreadsheet column names to model field names. Empty
    files yield a :class:`ParseError` (there is nothing to reconcile).
    """
    if frame.empty:
        raise ParseError(f"{file_label} contains no data rows.")

    instances: list[ModelT] = []
    errors: list[str] = []

    for position, (_, row) in enumerate(frame.iterrows()):
        # Spreadsheet row number: +2 accounts for the header row and 0-based index.
        row_number = position + 2
        payload = {
            field: value
            for column, field in field_map.items()
            if (value := clean_cell(row.get(column))) is not None
        }
        try:
            instances.append(model.model_validate(payload))
        except ValidationError as exc:
            for err in exc.errors():
                location = ".".join(str(part) for part in err["loc"]) or "row"
                errors.append(f"row {row_number}: {location}: {err['msg']}")

    if errors:
        raise ParseError(
            f"{file_label} has {len(errors)} validation error(s).",
            errors=errors,
        )
    return instances
