from fastapi import FastAPI
from app.routes import transactions, accounts

app = FastAPI(
    title="Trading Engine API",
    description="Internal trading engine for processing transactions and managing accounts",
    version="1.2.0",
)

# Include route modules
app.include_router(transactions.router)
app.include_router(accounts.router)
