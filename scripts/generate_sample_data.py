"""Generate deterministic sample order/settlement files.

Run with::

    uv run python scripts/generate_sample_data.py

Writes ``orders_sample`` and ``settlements_sample`` as both ``.xlsx`` and
``.csv`` into ``data/samples/``. The dataset is hand-crafted (no randomness) so
that every reconciliation outcome is represented and tests can assert exact
results. All cells are written as text for lossless round-tripping.

Scenario coverage (as-of date 2026-06-08, see SLA grace in config/settings.yaml):

* O1001 CARD  -> MATCHED (online, exact)
* O1002 CASH  -> MATCHED (cash deposited to bank)
* O1003 CASH  -> CASH_MISSING (no settlement)            -> Store Manager
* O1004 UPI   -> ONLINE_MISSING (SLA breached)           -> Payment Gateway
* O1005 CARD  -> AMOUNT_SHORT (settled 1500 of 2000)     -> PG + Store Manager
* O1006 CARD  -> AMOUNT_EXCESS (settled 900 of 800)      -> PG + Store Manager
* O1007 UPI   -> DUPLICATE_SETTLEMENT (settled twice)    -> PG + Bank
* O1008 CARD+CASH -> ORDER_SUM_MISMATCH (600+300 != 1000) -> Store Manager
                 (both obligations themselves MATCHED)
* O1009 CARD+CASH -> MATCHED split payment (700+300 == 1000)
* O1010 CARD  -> CANCELLED (ignored entirely)
* O1011 UPI   -> fuzzy candidate (pairs with S2011 by amount/date/source)
* O1012 CARD  -> LATE_SETTLEMENT (within grace; planner may WAIT)
* S2099       -> UNMATCHED_SETTLEMENT (no matching order)  -> Bank + PG
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLES_DIR = REPO_ROOT / "data" / "samples"

ORDER_COLUMNS = [
    "order_id",
    "order_date",
    "store_id",
    "customer_name",
    "customer_email",
    "amount",
    "payment_type",
    "payment_amount",
    "payment_gateway",
    "gateway_txn_id",
    "responsible_party",
    "status",
]

SETTLEMENT_COLUMNS = [
    "settlement_id",
    "settlement_date",
    "order_id",
    "gateway_txn_id",
    "reference_id",
    "payment_type",
    "amount",
    "fee",
    "net_amount",
    "source",
]


def _order(
    order_id: str,
    order_date: str,
    store_id: str,
    customer_name: str,
    customer_email: str,
    amount: str,
    payment_type: str,
    payment_amount: str,
    payment_gateway: str = "",
    gateway_txn_id: str = "",
    responsible_party: str = "",
    status: str = "PLACED",
) -> dict[str, str]:
    return {
        "order_id": order_id,
        "order_date": order_date,
        "store_id": store_id,
        "customer_name": customer_name,
        "customer_email": customer_email,
        "amount": amount,
        "payment_type": payment_type,
        "payment_amount": payment_amount,
        "payment_gateway": payment_gateway,
        "gateway_txn_id": gateway_txn_id,
        "responsible_party": responsible_party,
        "status": status,
    }


def _settlement(
    settlement_id: str,
    settlement_date: str,
    payment_type: str,
    amount: str,
    fee: str,
    net_amount: str,
    source: str,
    order_id: str = "",
    gateway_txn_id: str = "",
    reference_id: str = "",
) -> dict[str, str]:
    return {
        "settlement_id": settlement_id,
        "settlement_date": settlement_date,
        "order_id": order_id,
        "gateway_txn_id": gateway_txn_id,
        "reference_id": reference_id,
        "payment_type": payment_type,
        "amount": amount,
        "fee": fee,
        "net_amount": net_amount,
        "source": source,
    }


def build_orders() -> list[dict[str, str]]:
    return [
        _order(
            "O1001",
            "2026-06-06",
            "S1",
            "Asha",
            "asha@example.com",
            "1000.00",
            "CARD",
            "1000.00",
            "RAZORPAY",
            "TXN1001",
        ),
        _order("O1002", "2026-06-06", "S1", "Ben", "ben@example.com", "500.00", "CASH", "500.00"),
        _order("O1003", "2026-06-06", "S2", "Chitra", "", "700.00", "CASH", "700.00"),
        _order(
            "O1004",
            "2026-06-05",
            "S2",
            "Dev",
            "dev@example.com",
            "1200.00",
            "UPI",
            "1200.00",
            "PAYU",
            "TXN1004",
        ),
        _order(
            "O1005",
            "2026-06-06",
            "S1",
            "Esha",
            "",
            "2000.00",
            "CARD",
            "2000.00",
            "RAZORPAY",
            "TXN1005",
        ),
        _order(
            "O1006",
            "2026-06-06",
            "S3",
            "Farid",
            "",
            "800.00",
            "CARD",
            "800.00",
            "CASHFREE",
            "TXN1006",
        ),
        _order(
            "O1007",
            "2026-06-06",
            "S3",
            "Gita",
            "",
            "600.00",
            "UPI",
            "600.00",
            "RAZORPAY",
            "TXN1007",
        ),
        # O1008: split payment whose parts (600 + 300) do not sum to the total (1000).
        _order(
            "O1008",
            "2026-06-06",
            "S1",
            "Hari",
            "",
            "1000.00",
            "CARD",
            "600.00",
            "RAZORPAY",
            "TXN1008",
        ),
        _order("O1008", "2026-06-06", "S1", "Hari", "", "1000.00", "CASH", "300.00"),
        # O1009: split payment that sums correctly (700 + 300 == 1000).
        _order(
            "O1009", "2026-06-06", "S2", "Iqbal", "", "1000.00", "CARD", "700.00", "PAYU", "TXN1009"
        ),
        _order("O1009", "2026-06-06", "S2", "Iqbal", "", "1000.00", "CASH", "300.00"),
        _order(
            "O1010",
            "2026-06-06",
            "S2",
            "Juhi",
            "",
            "5000.00",
            "CARD",
            "5000.00",
            "RAZORPAY",
            "TXN1010",
            "",
            "CANCELLED",
        ),
        _order(
            "O1011",
            "2026-06-06",
            "S3",
            "Kiran",
            "",
            "1500.00",
            "UPI",
            "1500.00",
            "RAZORPAY",
            "TXN1011",
        ),
        _order(
            "O1012",
            "2026-06-08",
            "S1",
            "Latha",
            "",
            "900.00",
            "CARD",
            "900.00",
            "RAZORPAY",
            "TXN1012",
        ),
    ]


def build_settlements() -> list[dict[str, str]]:
    return [
        _settlement(
            "S2001",
            "2026-06-07",
            "CARD",
            "1000.00",
            "20.00",
            "980.00",
            "RAZORPAY",
            "O1001",
            "TXN1001",
            "UTR1001",
        ),
        _settlement(
            "S2002",
            "2026-06-07",
            "CASH",
            "500.00",
            "0.00",
            "500.00",
            "BANK",
            "O1002",
            "",
            "UTR1002",
        ),
        _settlement(
            "S2005",
            "2026-06-07",
            "CARD",
            "1500.00",
            "30.00",
            "1470.00",
            "RAZORPAY",
            "O1005",
            "TXN1005",
            "UTR1005",
        ),
        _settlement(
            "S2006",
            "2026-06-07",
            "CARD",
            "900.00",
            "18.00",
            "882.00",
            "CASHFREE",
            "O1006",
            "TXN1006",
            "UTR1006",
        ),
        _settlement(
            "S2007A",
            "2026-06-07",
            "UPI",
            "600.00",
            "6.00",
            "594.00",
            "RAZORPAY",
            "O1007",
            "TXN1007",
            "UTR1007A",
        ),
        _settlement(
            "S2007B",
            "2026-06-08",
            "UPI",
            "600.00",
            "6.00",
            "594.00",
            "RAZORPAY",
            "O1007",
            "TXN1007",
            "UTR1007B",
        ),
        _settlement(
            "S2008C",
            "2026-06-07",
            "CASH",
            "300.00",
            "0.00",
            "300.00",
            "BANK",
            "O1008",
            "",
            "UTR1008C",
        ),
        _settlement(
            "S2008D",
            "2026-06-07",
            "CARD",
            "600.00",
            "12.00",
            "588.00",
            "RAZORPAY",
            "O1008",
            "TXN1008",
            "UTR1008D",
        ),
        _settlement(
            "S2009C",
            "2026-06-07",
            "CASH",
            "300.00",
            "0.00",
            "300.00",
            "BANK",
            "O1009",
            "",
            "UTR1009C",
        ),
        _settlement(
            "S2009D",
            "2026-06-07",
            "CARD",
            "700.00",
            "14.00",
            "686.00",
            "PAYU",
            "O1009",
            "TXN1009",
            "UTR1009D",
        ),
        # Fuzzy candidate: same amount/source/near date as O1011 but no ids to match on.
        _settlement(
            "S2011",
            "2026-06-07",
            "UPI",
            "1500.00",
            "15.00",
            "1485.00",
            "RAZORPAY",
            "",
            "",
            "UTR1011",
        ),
        # Clearly unmatched settlement (no related order).
        _settlement(
            "S2099",
            "2026-06-07",
            "CARD",
            "4321.00",
            "40.00",
            "4281.00",
            "CASHFREE",
            "",
            "",
            "UTR9099",
        ),
    ]


def write_samples(out_dir: Path = SAMPLES_DIR) -> list[Path]:
    """Write the four sample files and return their paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    orders = pd.DataFrame(build_orders(), columns=ORDER_COLUMNS)
    settlements = pd.DataFrame(build_settlements(), columns=SETTLEMENT_COLUMNS)

    paths: list[Path] = []
    targets = [
        (orders, out_dir / "orders_sample.csv", out_dir / "orders_sample.xlsx"),
        (settlements, out_dir / "settlements_sample.csv", out_dir / "settlements_sample.xlsx"),
    ]
    for frame, csv_path, xlsx_path in targets:
        frame.to_csv(csv_path, index=False)
        frame.to_excel(xlsx_path, index=False, engine="openpyxl")
        paths.extend([csv_path, xlsx_path])
    return paths


def main() -> None:
    paths = write_samples()
    for path in paths:
        print(f"wrote {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
