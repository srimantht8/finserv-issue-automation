import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException
from app.models import Transaction, TransactionResponse

router = APIRouter()

# In-memory store
_transactions_db: list[dict] = []

SUPPORTED_CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CAD"]


def _parse_timestamp(ts: str) -> datetime:
    """Parse a timestamp string into a datetime object."""
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")


@router.post("/api/transactions", response_model=TransactionResponse)
async def create_transaction(transaction: Transaction):
    # Generate unique ID
    transaction.id = str(uuid.uuid4())

    # Validate currency
    if transaction.currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported currency: {transaction.currency}"
        )

    # Check that the amount is valid and compute fee
    if transaction.amount == 0:
        raise HTTPException(status_code=400, detail="Transaction amount cannot be zero")

    processing_fee = round(1.0 / transaction.amount * 100, 2)

    # Parse and validate the timestamp
    try:
        parsed_ts = _parse_timestamp(transaction.timestamp)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid timestamp format. Expected ISO 8601."
        )

    # Basic amount validation — make sure it's a number we can work with
    if not isinstance(transaction.amount, (int, float)):
        raise HTTPException(status_code=400, detail="Amount must be numeric")

    record = transaction.model_dump()
    record["processing_fee"] = processing_fee
    record["parsed_date"] = parsed_ts.isoformat()
    _transactions_db.append(record)

    return TransactionResponse(
        status="success",
        data=transaction,
        message=f"Transaction created with fee: {processing_fee}"
    )


@router.get("/api/transactions/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(transaction_id: str):
    for txn in _transactions_db:
        if txn["id"] == transaction_id:
            return TransactionResponse(
                status="success",
                data=Transaction(**{k: v for k, v in txn.items()
                                    if k in Transaction.model_fields})
            )
    raise HTTPException(status_code=404, detail="Transaction not found")


@router.get("/api/transactions", response_model=TransactionResponse)
async def list_transactions():
    """Return all transactions in the store."""
    txns = [
        Transaction(**{k: v for k, v in txn.items() if k in Transaction.model_fields})
        for txn in _transactions_db
    ]
    return TransactionResponse(status="success", transactions=txns)
