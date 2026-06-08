"""Reader for the orders file (``.xlsx`` or ``.csv``)."""

from __future__ import annotations

from reconcile.models.domain import Order
from reconcile.parsers.base import (
    Source,
    load_dataframe,
    require_columns,
    validate_rows,
)

_FILE_LABEL = "Orders file"

_REQUIRED_COLUMNS = {
    "order_id",
    "order_date",
    "store_id",
    "amount",
    "payment_type",
    "payment_amount",
    "status",
}

# Spreadsheet column -> model field. Optional columns may be absent entirely.
_FIELD_MAP = {
    "order_id": "order_id",
    "order_date": "order_date",
    "store_id": "store_id",
    "amount": "amount",
    "payment_type": "payment_type",
    "payment_amount": "payment_amount",
    "payment_gateway": "payment_gateway",
    "gateway_txn_id": "gateway_txn_id",
    "responsible_party": "responsible_party",
    "status": "status",
    "customer_name": "customer_name",
    "customer_email": "customer_email",
}


def read_orders(source: Source, filename: str | None = None) -> list[Order]:
    """Parse and validate the orders file into :class:`Order` rows.

    Raises :class:`~reconcile.parsers.base.ParseError` on unreadable files,
    missing required columns, or row-level validation failures (with row numbers).
    """
    frame = load_dataframe(source, filename)
    require_columns(frame, _REQUIRED_COLUMNS, _FILE_LABEL)
    return validate_rows(frame, Order, file_label=_FILE_LABEL, field_map=_FIELD_MAP)
