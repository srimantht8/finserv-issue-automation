import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException
from app.models import Account, AccountResponse

router = APIRouter()

# In-memory account storage
_accounts_db: list[dict] = []

MIN_ACCOUNT_NAME_LENGTH = 2
MAX_ACCOUNT_NAME_LENGTH = 128


@router.post("/api/accounts", response_model=AccountResponse)
async def create_account(account: Account):
    account.id = str(uuid.uuid4())
    account.created_at = datetime.utcnow().isoformat()

    # Validate the account name inline
    name = account.name.strip()
    if len(name) < MIN_ACCOUNT_NAME_LENGTH:
        raise HTTPException(status_code=400, detail="Account name is too short")
    if len(name) > MAX_ACCOUNT_NAME_LENGTH:
        raise HTTPException(status_code=400, detail="Account name exceeds maximum length")
    if not name.replace(" ", "").replace("-", "").isalnum():
        raise HTTPException(
            status_code=400,
            detail="Account name contains invalid characters"
        )

    _accounts_db.append(account.model_dump())

    return AccountResponse(status="success", data=account, message="Account created")


@router.get("/api/accounts/{account_id}", response_model=AccountResponse)
async def get_account(account_id: str):
    for acct in _accounts_db:
        if acct["id"] == account_id:
            return AccountResponse(status="success", data=Account(**acct))

    raise HTTPException(status_code=404, detail="Account not found")


@router.get("/api/accounts", response_model=AccountResponse)
async def list_accounts():
    accounts = [Account(**acct) for acct in _accounts_db]
    return AccountResponse(status="success", accounts=accounts)
