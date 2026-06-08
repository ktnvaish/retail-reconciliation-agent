# Input file schema

The system defines its own input formats. Both `.xlsx` and `.csv` are accepted.
All values are read as text and validated into typed models; blank optional cells
fall back to defaults. Validation errors are reported with 1-based spreadsheet row
numbers.

Regenerate the bundled samples any time:

```bash
uv run python scripts/generate_sample_data.py
```

## Orders file

One **row per payment obligation**. An order (`order_id`) may span several rows
(e.g. part CARD + part CASH); each row reconciles independently, and the rows'
`payment_amount` values must sum to the order `amount`.

| Column | Type | Required | Notes |
|---|---|---|---|
| `order_id` | string | yes | Repeated across the order's rows; not unique |
| `order_date` | date `YYYY-MM-DD` | yes | Used for age / SLA |
| `store_id` | string | yes | |
| `amount` | decimal | yes | Order gross total; identical on every row of the order |
| `payment_type` | enum | yes | `CASH` \| `UPI` \| `CARD` \| `NETBANKING` \| `WALLET` |
| `payment_amount` | decimal | yes | This obligation's amount |
| `payment_gateway` | enum / null | conditional | Required when `payment_type != CASH`: `RAZORPAY` \| `PAYU` \| `CASHFREE` |
| `gateway_txn_id` | string / null | conditional | Required when `payment_type != CASH`; unique per online obligation |
| `responsible_party` | enum / null | no | Override role: `STORE_MANAGER` \| `PAYMENT_GATEWAY` \| `BANK` \| `ADMIN` |
| `status` | enum | yes | `PLACED` \| `CANCELLED` — only `PLACED` is reconciled |
| `customer_name` | string | no | |
| `customer_email` | string | no | |

Example (a split payment, `O1009`):

```csv
order_id,order_date,store_id,amount,payment_type,payment_amount,payment_gateway,gateway_txn_id,status
O1009,2026-06-06,S2,1000.00,CARD,700.00,PAYU,TXN1009,PLACED
O1009,2026-06-06,S2,1000.00,CASH,300.00,,,PLACED
```

## Settlements file

One **row per money-received entry** from a bank or payment gateway.

| Column | Type | Required | Notes |
|---|---|---|---|
| `settlement_id` | string | yes | Unique within the file |
| `settlement_date` | date `YYYY-MM-DD` | yes | |
| `payment_type` | enum | yes | Same enum as orders |
| `amount` | decimal | yes | Gross amount received |
| `fee` | decimal | no | Defaults to `0` |
| `net_amount` | decimal | no | Defaults to `amount - fee` |
| `source` | enum | yes | `BANK` \| `RAZORPAY` \| `PAYU` \| `CASHFREE` |
| `order_id` | string / null | no | Secondary join key |
| `gateway_txn_id` | string / null | no | Preferred join key |
| `reference_id` | string / null | no | Bank/PG reference (e.g. UTR) |

Example:

```csv
settlement_id,settlement_date,order_id,gateway_txn_id,reference_id,payment_type,amount,fee,net_amount,source
S2001,2026-06-07,O1001,TXN1001,UTR1001,CARD,1000.00,20.00,980.00,RAZORPAY
```

## Validation rules

- Unsupported extensions (anything but `.csv` / `.xlsx`) are rejected.
- Missing required columns are reported before any row is parsed.
- Empty files (header only) are rejected.
- Online obligations missing `gateway_txn_id` or `payment_gateway` fail with the
  offending row number.
- Amounts are parsed as exact `Decimal` (no floating-point drift).
