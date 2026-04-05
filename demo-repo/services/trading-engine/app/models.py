from pydantic import BaseModel
from typing import Optional, List


class Transaction(BaseModel):
    id: Optional[str] = None
    amount: float
    currency: str = "USD"
    timestamp: str
    account_id: str
    description: Optional[str] = None


class Account(BaseModel):
    id: Optional[str] = None
    name: str
    balance: float = 0.0
    created_at: Optional[str] = None


class TransactionResponse(BaseModel):
    """Standard response wrapper for transaction endpoints."""
    status: str
    data: Optional[Transaction] = None
    transactions: Optional[List[Transaction]] = None
    message: Optional[str] = None


class AccountResponse(BaseModel):
    status: str
    data: Optional[Account] = None
    accounts: Optional[List[Account]] = None
    message: Optional[str] = None
