# FinServ Platform -- Monorepo

Internal platform services for FinServ Co. This repository contains the core backend services that power our trading and API infrastructure.

## Services

### api-gateway (Node.js / Express)

Public-facing REST gateway that handles authentication, rate limiting, and request routing to downstream services.

```bash
cd services/api-gateway
npm install
npm run dev        # starts on :3000
npm test
```

### trading-engine (Python / FastAPI)

Order management and trade execution engine. Connects to market data feeds and manages the order lifecycle.

```bash
cd services/trading-engine
pip install -r requirements.txt
uvicorn main:app --reload   # starts on :8000
pytest
```

## Development

1. Clone the repo and check out a feature branch.
2. Follow the setup instructions for the service you are working on.
3. Open a PR against `main` -- CI runs linting, tests, and type checks automatically.
