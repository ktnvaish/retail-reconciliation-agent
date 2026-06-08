"""Reader for the settlements file (``.xlsx`` or ``.csv``)."""

from __future__ import annotations

from reconcile.models.domain import Settlement
from reconcile.parsers.base import (
    Source,
    load_dataframe,
    require_columns,
    validate_rows,
)

_FILE_LABEL = "Settlements file"

_REQUIRED_COLUMNS = {
    "settlement_id",
    "settlement_date",
    "payment_type",
    "amount",
    "source",
}

# Spreadsheet column -> model field. Optional columns may be absent entirely.
_FIELD_MAP = {
    "settlement_id": "settlement_id",
    "settlement_date": "settlement_date",
    "payment_type": "payment_type",
    "amount": "amount",
    "fee": "fee",
    "net_amount": "net_amount",
    "source": "source",
    "order_id": "order_id",
    "gateway_txn_id": "gateway_txn_id",
    "reference_id": "reference_id",
}


def read_settlements(source: Source, filename: str | None = None) -> list[Settlement]:
    """Parse and validate the settlements file into :class:`Settlement` rows.

    Raises :class:`~reconcile.parsers.base.ParseError` on unreadable files,
    missing required columns, or row-level validation failures (with row numbers).
    """
    frame = load_dataframe(source, filename)
    require_columns(frame, _REQUIRED_COLUMNS, _FILE_LABEL)
    return validate_rows(frame, Settlement, file_label=_FILE_LABEL, field_map=_FIELD_MAP)
