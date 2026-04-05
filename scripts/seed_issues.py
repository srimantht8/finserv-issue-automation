#!/usr/bin/env python3
"""Seed realistic GitHub issues on the demo FinServ monorepo.

Usage:
    python -m scripts.seed_issues

The script is idempotent: it skips issues whose title already exists
as an open issue on the target repository.  It also ensures all
required labels exist before creating any issues.

Environment variables (read via orchestrator.config):
    GITHUB_TOKEN, REPO_OWNER, REPO_NAME
"""

from __future__ import annotations

from github import GithubException

from orchestrator.github_client import GitHubClient

# ── Custom labels that may not exist on a fresh repo ────────────────
REQUIRED_LABELS: dict[str, str] = {
    "bug": "d73a4a",
    "enhancement": "a2eeef",
    "documentation": "0075ca",
    "refactoring": "e4e669",
    "trading-engine": "1d76db",
    "api-gateway": "5319e7",
    "tech-debt": "fbca04",
    "high-priority": "b60205",
    "security": "ee0701",
}

# ── Issue definitions ───────────────────────────────────────────────

ISSUES: list[dict] = [
    # ----------------------------------------------------------------
    # 1. Trading Engine — /api/transactions 500 on negative amount
    # ----------------------------------------------------------------
    {
        "title": "/api/transactions returns 500 when amount is negative",
        "labels": ["bug", "trading-engine", "high-priority"],
        "body": """\
## Description

Sending a `POST /api/transactions` with a negative `amount` crashes the server
with a 500 Internal Server Error instead of returning a 422 validation error.

## Steps to Reproduce

```bash
curl -X POST http://localhost:8000/api/transactions \\
  -H "Content-Type: application/json" \\
  -d '{"account_id": "acct_8872", "amount": -150.00, "currency": "USD", "type": "withdrawal"}'
```

## Expected Behavior

The API should return a **422 Unprocessable Entity** with a clear message:

```json
{
  "detail": "amount must be a positive number"
}
```

## Actual Behavior

The server returns **500 Internal Server Error** and the following traceback
appears in the application logs:

```
Traceback (most recent call last):
  File "/app/trading_engine/routes/transactions.py", line 47, in create_transaction
    fee = calculate_fee(payload.amount, payload.currency)
  File "/app/trading_engine/services/fee_calculator.py", line 23, in calculate_fee
    basis_points = FEE_SCHEDULE[currency] / amount
ZeroDivisionError: float division by zero
```

The root cause is that `calculate_fee` divides by `amount` without first
validating that it is positive.  When the value happens to be exactly `0`
we get a `ZeroDivisionError`; for other negative values the fee comes out
negative, which later causes an `IntegrityError` on the database insert.

## Environment

- Python 3.11.6
- FastAPI 0.104.1
- uvicorn 0.24.0
- macOS 14.2 / Docker linux/amd64
""",
    },
    # ----------------------------------------------------------------
    # 2. Trading Engine — Date parsing fails for ISO 8601 with tz
    # ----------------------------------------------------------------
    {
        "title": "Date parsing fails for ISO 8601 with timezone offset",
        "labels": ["bug", "trading-engine"],
        "body": """\
## Description

The `parse_date` helper in `trading_engine/utils/date_helpers.py` uses
`datetime.strptime` with the format `"%Y-%m-%dT%H:%M:%S"`, which does
not handle timezone offsets.  Any client that sends an ISO 8601 timestamp
with an offset (e.g. `+05:30`, `-04:00`, `Z`) gets a 400 error.

## Steps to Reproduce

```bash
curl -X GET "http://localhost:8000/api/transactions?from_date=2024-01-15T10:30:00%2B05:00"
```

Returns:

```json
{
  "detail": "Invalid date format: 2024-01-15T10:30:00+05:00"
}
```

The same request **works** if you strip the offset:

```bash
curl -X GET "http://localhost:8000/api/transactions?from_date=2024-01-15T10:30:00"
# 200 OK
```

## Stack Trace

```
Traceback (most recent call last):
  File "/app/trading_engine/utils/date_helpers.py", line 12, in parse_date
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
ValueError: time data '2024-01-15T10:30:00+05:00' does not match format '%Y-%m-%dT%H:%M:%S'
```

## Suggested Fix

Replace `strptime` with `datetime.fromisoformat()` (available since
Python 3.7+) which handles offsets and the `Z` suffix natively:

```python
from datetime import datetime

def parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
```

## Impact

Several API consumers — including the React dashboard — send timestamps
with `Z` suffixes.  This is currently papered over in the frontend by
stripping the suffix before every request, which is fragile.
""",
    },
    # ----------------------------------------------------------------
    # 3. Trading Engine — Pagination for /api/accounts
    # ----------------------------------------------------------------
    {
        "title": "Add pagination to /api/accounts endpoint",
        "labels": ["enhancement", "trading-engine"],
        "body": """\
## Problem

`GET /api/accounts` returns the full list of accounts in a single
response with no pagination support.  In staging we already have ~12,000
accounts and the response payload is over 4 MB.  The endpoint takes
~1.8 s to serialize and the React dashboard frequently times out.

## Proposal

Add **offset/limit** query parameters with sensible defaults:

```
GET /api/accounts?limit=50&offset=0
```

Response:

```json
{
  "items": [ ... ],
  "total": 12340,
  "limit": 50,
  "offset": 0,
  "has_more": true
}
```

### Alternatives Considered

| Approach | Pros | Cons |
|----------|------|------|
| Offset / Limit | Simple, widely understood | Poor perf on deep offsets |
| Cursor-based | Stable under inserts/deletes | More complex client logic |
| Keyset | Best DB perf | Requires monotonic sort key |

For our current scale, offset/limit is fine.  We can revisit cursor-based
pagination when we exceed ~100 k accounts.

## Acceptance Criteria

- [ ] `limit` defaults to 50, max 200
- [ ] `offset` defaults to 0
- [ ] Response includes `total`, `has_more`
- [ ] Existing clients that don't pass params still work (backward compat)
- [ ] Unit tests cover edge cases (offset > total, limit = 0, etc.)
""",
    },
    # ----------------------------------------------------------------
    # 4. Trading Engine — Rate limiting middleware
    # ----------------------------------------------------------------
    {
        "title": "Add rate limiting middleware",
        "labels": ["enhancement", "trading-engine"],
        "body": """\
## Problem

There is currently **no rate limiting** on any Trading Engine endpoint.
During a recent load test we saw a single misconfigured client send
~14,000 requests/minute to `/api/transactions`, which saturated the DB
connection pool and caused cascading 503s for all other consumers.

## Proposal

Add per-client rate limiting via the `slowapi` library (a Starlette/
FastAPI port of `flask-limiter`).

### Suggested Limits

| Endpoint Group | Rate | Window |
|----------------|------|--------|
| `GET  /api/*` | 300 req | 1 min |
| `POST /api/transactions` | 60 req | 1 min |
| `POST /api/accounts` | 30 req | 1 min |
| `*` (catch-all) | 600 req | 1 min |

Rate-limit state should use an in-memory store for local dev and Redis
for staging/prod.

### Response on Throttle

```
HTTP/1.1 429 Too Many Requests
Retry-After: 12
Content-Type: application/json

{
  "detail": "Rate limit exceeded. Try again in 12 seconds."
}
```

## References

- https://github.com/laurentS/slowapi
- RFC 6585 (429 status code)
""",
    },
    # ----------------------------------------------------------------
    # 5. Trading Engine — Extract duplicate validation logic
    # ----------------------------------------------------------------
    {
        "title": "Extract duplicate validation logic in handlers",
        "labels": ["refactoring", "trading-engine", "tech-debt"],
        "body": """\
## Problem

`trading_engine/validation.py` already defines helper functions like
`validate_account_id()`, `validate_amount()`, and `validate_currency()`,
but most route handlers **do not use them**.  Instead, each handler
reimplements the checks inline with slightly different rules.

### Example: Amount validation in three places

**validation.py** (canonical, unused):
```python
def validate_amount(value: float) -> None:
    if value <= 0:
        raise ValueError("amount must be positive")
    if value > 1_000_000:
        raise ValueError("amount exceeds maximum")
```

**routes/transactions.py** (inline):
```python
if payload.amount < 0:          # allows zero — bug!
    raise HTTPException(422, "Invalid amount")
```

**routes/transfers.py** (inline):
```python
if not isinstance(body["amount"], (int, float)) or body["amount"] <= 0:
    return JSONResponse({"error": "bad amount"}, status_code=400)
    # uses 400, not 422 — inconsistent
```

Three different validation rules, three different error formats, two
different HTTP status codes.

## Proposed Changes

1. Delete inline validation from every route handler.
2. Import and call the helpers from `validation.py`.
3. Add a FastAPI dependency (`Depends`) that runs the validators
   automatically so route functions stay clean.
4. Ensure every validation failure returns a **422** with the standard
   error schema.

## Acceptance Criteria

- [ ] No inline validation logic remains in route files
- [ ] All validation goes through `validation.py`
- [ ] Consistent 422 responses for all validation errors
- [ ] Existing tests still pass
""",
    },
    # ----------------------------------------------------------------
    # 6. Trading Engine — Docstrings for utility functions
    # ----------------------------------------------------------------
    {
        "title": "Add docstrings to core utility functions",
        "labels": ["documentation", "trading-engine"],
        "body": """\
## Problem

Most functions in the `trading_engine/utils/` package have no
docstrings.  New team members (we onboarded two people last sprint)
repeatedly ask the same questions about:

- What formats does `parse_date()` accept?
- Does `validate_account_id()` check the database or just the format?
- What does `calculate_fee()` return when the currency is unknown?
- Is `mask_pii()` safe for production logging, or does it only redact
  the first match?

## Scope

Files that need docstrings:

| File | Functions w/o docstrings |
|------|--------------------------|
| `utils/date_helpers.py` | `parse_date`, `format_date`, `to_utc` |
| `utils/validation.py` | `validate_account_id`, `validate_amount`, `validate_currency` |
| `utils/formatting.py` | `mask_pii`, `truncate`, `format_currency` |
| `utils/crypto.py` | `hash_payload`, `verify_signature` |

## Guidelines

- Follow [Google-style docstrings](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings).
- Include `Args`, `Returns`, `Raises` sections.
- Add at least one usage example per function.
- Mention edge cases and gotchas inline.

## Example

```python
def validate_account_id(account_id: str) -> bool:
    \"\"\"Check whether *account_id* matches the expected format.

    The expected format is ``acct_`` followed by exactly 4 digits
    (e.g. ``acct_0042``).  This is a **format-only** check; it does
    not verify that the account exists in the database.

    Args:
        account_id: The raw account identifier string.

    Returns:
        ``True`` if the format is valid, ``False`` otherwise.

    Raises:
        TypeError: If *account_id* is not a string.

    Example::

        >>> validate_account_id("acct_1234")
        True
        >>> validate_account_id("1234")
        False
    \"\"\"
```
""",
    },
    # ----------------------------------------------------------------
    # 7. Trading Engine — CORS headers missing
    # ----------------------------------------------------------------
    {
        "title": "CORS headers missing for frontend requests",
        "labels": ["bug", "trading-engine"],
        "body": """\
## Description

The React dashboard at `https://dashboard.finserv-internal.dev` cannot
reach the Trading Engine API because no CORS headers are returned.  The
browser blocks every preflight request.

## Browser Console Error

```
Access to XMLHttpRequest at 'http://localhost:8000/api/accounts'
from origin 'http://localhost:3000' has been blocked by CORS policy:
No 'Access-Control-Allow-Origin' header is present on the requested
resource.
```

## Root Cause

`main.py` creates the FastAPI application but never adds
`CORSMiddleware`:

```python
# main.py (current)
from fastapi import FastAPI

app = FastAPI(title="Trading Engine")

# ... route includes ...
# NOTE: no CORSMiddleware — frontend requests will fail
```

## Suggested Fix

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://dashboard.finserv-internal.dev",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

For production we should read allowed origins from an environment
variable rather than hard-coding them.

## Impact

This blocks all frontend development.  The team has been working around
it by running a local nginx reverse-proxy, but that adds friction to
every new developer's setup.
""",
    },
    # ----------------------------------------------------------------
    # 8. Trading Engine — Health check endpoint
    # ----------------------------------------------------------------
    {
        "title": "Add health check endpoint",
        "labels": ["enhancement", "trading-engine"],
        "body": """\
## Problem

The Trading Engine has no health check endpoint.  Our Kubernetes
deployment currently uses a TCP socket probe on port 8000, which only
tells us that uvicorn is listening — not that the application is
actually healthy (e.g., database reachable, config loaded).

Last week the pod was "healthy" according to k8s but returning 500 on
every request because the DB connection pool was exhausted.

## Proposal

Add two endpoints:

### `GET /healthz` (liveness)

Returns `200 OK` as long as the process is alive.  Used by k8s liveness
probe.

```json
{
  "status": "ok"
}
```

### `GET /readyz` (readiness)

Checks downstream dependencies and returns `200` only when everything
is reachable.  Used by k8s readiness probe.

```json
{
  "status": "ok",
  "checks": {
    "database": "ok",
    "cache": "ok"
  },
  "version": "1.4.2",
  "uptime_seconds": 84321
}
```

If any check fails, return `503 Service Unavailable`:

```json
{
  "status": "degraded",
  "checks": {
    "database": "ok",
    "cache": "error: connection refused"
  }
}
```

## Acceptance Criteria

- [ ] `GET /healthz` returns 200 with no side effects
- [ ] `GET /readyz` checks DB connectivity
- [ ] Probes do not require authentication
- [ ] Response time < 500 ms
- [ ] Update k8s manifests to use HTTP probes
""",
    },
    # ----------------------------------------------------------------
    # 9. API Gateway — Session not invalidated on password change
    # ----------------------------------------------------------------
    {
        "title": "User session not invalidated on password change",
        "labels": ["bug", "api-gateway", "security"],
        "body": """\
## Description

When a user changes their password via `POST /auth/change-password`,
existing sessions (including those on other devices) remain valid.  An
attacker who has stolen a session token can continue using it
indefinitely even after the victim changes their password.

## Steps to Reproduce

1. Log in on **Browser A** and note the session cookie.
2. Log in on **Browser B** (same account).
3. On **Browser A**, call `POST /auth/change-password` with a new
   password.
4. On **Browser B**, call `GET /api/me` using the old session cookie.
5. **Actual:** Request succeeds with 200.
   **Expected:** Request fails with 401 Unauthorized.

## Root Cause

`auth.js` updates the password hash in the database but does not
invalidate existing sessions:

```javascript
// api-gateway/routes/auth.js  (line ~87)
router.post('/change-password', authenticate, async (req, res) => {
  const { currentPassword, newPassword } = req.body;
  const user = await User.findById(req.user.id);
  const valid = await bcrypt.compare(currentPassword, user.passwordHash);
  if (!valid) return res.status(401).json({ error: 'Wrong password' });

  user.passwordHash = await bcrypt.hash(newPassword, 12);
  await user.save();

  // BUG: should invalidate all sessions for this user here
  res.json({ message: 'Password updated' });
});
```

## Suggested Fix

After saving the new hash, delete every session record for the user:

```javascript
await Session.deleteMany({ userId: req.user.id });
```

Then re-create a fresh session for the current request so the user
who changed the password does not get logged out.

## Security Impact

**High.** This violates OWASP Session Management guidelines (section
3.3) and means a compromised session cannot be revoked by the
legitimate user.
""",
    },
    # ----------------------------------------------------------------
    # 10. API Gateway — Inconsistent error response format
    # ----------------------------------------------------------------
    {
        "title": "Error responses don't follow consistent format",
        "labels": ["bug", "api-gateway"],
        "body": """\
## Description

Different endpoints in the API Gateway return errors in at least three
incompatible formats.  This makes client-side error handling unreliable
and forces the React dashboard to use fragile heuristics to extract
error messages.

## Examples

### Format 1 — `routes/auth.js`

```json
{
  "error": "Invalid credentials"
}
```

### Format 2 — `routes/accounts.js`

```json
{
  "message": "Account not found",
  "statusCode": 404
}
```

### Format 3 — Express default (uncaught errors)

```json
{
  "stack": "TypeError: Cannot read property 'id' of undefined\\n    at ...",
  "message": "Cannot read property 'id' of undefined"
}
```

The frontend currently does:

```javascript
const msg = err.response?.data?.error
  || err.response?.data?.message
  || err.response?.data?.detail
  || 'Unknown error';
```

This is brittle and has already caused user-visible bugs where the
dashboard shows "Unknown error" instead of the actual message.

## Proposed Standard Format

```json
{
  "error": {
    "code": "ACCOUNT_NOT_FOUND",
    "message": "Account with ID acct_9999 was not found.",
    "status": 404
  }
}
```

## Acceptance Criteria

- [ ] All error responses follow the standard format above
- [ ] Create a shared `sendError(res, status, code, message)` helper
- [ ] Add a global Express error handler for uncaught exceptions
- [ ] Stack traces are never exposed in production (`NODE_ENV=production`)
- [ ] Update API documentation with the new error schema
""",
    },
    # ----------------------------------------------------------------
    # 11. API Gateway — Request logging middleware
    # ----------------------------------------------------------------
    {
        "title": "Add request logging middleware",
        "labels": ["enhancement", "api-gateway"],
        "body": """\
## Problem

`api-gateway/middleware/logging.js` exists but is essentially a stub:

```javascript
// logging.js (current)
module.exports = (req, res, next) => {
  // TODO: implement logging
  next();
};
```

When something goes wrong in production we have **zero visibility** into
what requests were made, what status codes were returned, or how long
they took.  Last week we spent two hours debugging a 502 that turned out
to be a single malformed request — time that would have been saved by
proper request logs.

## Requirements

Each request should produce a structured JSON log line:

```json
{
  "timestamp": "2024-02-10T14:32:01.445Z",
  "method": "POST",
  "path": "/api/transactions",
  "status": 201,
  "duration_ms": 47,
  "ip": "10.0.1.42",
  "user_id": "usr_331",
  "request_id": "req_a8f3c"
}
```

### Details

- Log **after** the response is sent (use `res.on('finish', ...)`) so
  that `status` and `duration_ms` are accurate.
- Generate a unique `request_id` (uuid v4) and attach it to the request
  object so downstream handlers can include it in their own logs.
- Set the `X-Request-Id` response header.
- Mask sensitive fields (`Authorization`, `Cookie`) in the log.
- In development, pretty-print; in production, use single-line JSON for
  log aggregators.

## Suggested Libraries

- `morgan` (popular, simpler) or `pino-http` (structured JSON, faster).
""",
    },
    # ----------------------------------------------------------------
    # 12. API Gateway — Input sanitization
    # ----------------------------------------------------------------
    {
        "title": "Add input sanitization for user-facing endpoints",
        "labels": ["enhancement", "api-gateway", "security"],
        "body": """\
## Problem

Request bodies are used directly throughout the API Gateway without any
validation or sanitization.  For example:

```javascript
// routes/accounts.js
router.post('/', authenticate, async (req, res) => {
  const account = new Account(req.body);   // raw body → DB
  await account.save();
  res.status(201).json(account);
});
```

This pattern is vulnerable to:

1. **Stored XSS** — a user can set their `displayName` to
   `<script>alert(1)</script>` and it will be rendered unescaped in
   the admin panel.
2. **NoSQL Injection** — passing `{"email": {"$gt": ""}}` bypasses
   email lookups.
3. **Mass Assignment** — a user can set `role: "admin"` in the request
   body and elevate their privileges, since there is no allowlist of
   accepted fields.

## Proof of Concept (XSS)

```bash
curl -X POST http://localhost:4000/api/accounts \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer <token>" \\
  -d '{"displayName": "<img src=x onerror=alert(document.cookie)>", "email": "test@example.com"}'
```

The `displayName` is stored as-is and rendered in the admin panel HTML
without escaping.

## Proposed Solution

1. Add `express-validator` (or `joi` / `zod`) to validate and sanitize
   every user-facing endpoint.
2. Define explicit schemas for each route's expected input.
3. Reject requests that don't conform — return 422 with details.
4. Strip or escape HTML entities in all string inputs.
5. Use Mongoose `select` or explicit field picks to prevent mass
   assignment.

## Acceptance Criteria

- [ ] Every `POST` / `PUT` / `PATCH` route validates its input
- [ ] HTML entities are escaped in string fields
- [ ] NoSQL injection payloads are rejected
- [ ] Mass assignment is prevented
- [ ] Tests cover each attack vector above
""",
    },
    # ----------------------------------------------------------------
    # 13. API Gateway — Replace callbacks with async/await
    # ----------------------------------------------------------------
    {
        "title": "Replace callback-based code with async/await",
        "labels": ["refactoring", "api-gateway", "tech-debt"],
        "body": """\
## Problem

`api-gateway/routes/auth.js` still uses the callback API for `bcrypt`
operations.  The result is deeply nested code that is hard to read,
hard to test, and easy to get wrong (missing error propagation).

### Current Code (simplified)

```javascript
router.post('/register', (req, res) => {
  const { email, password } = req.body;
  bcrypt.genSalt(12, (err, salt) => {
    if (err) return res.status(500).json({ error: 'Internal error' });
    bcrypt.hash(password, salt, (err, hash) => {
      if (err) return res.status(500).json({ error: 'Internal error' });
      User.create({ email, passwordHash: hash }, (err, user) => {
        if (err) {
          if (err.code === 11000) {
            return res.status(409).json({ error: 'Email taken' });
          }
          return res.status(500).json({ error: 'Internal error' });
        }
        req.session.userId = user._id;
        res.status(201).json({ id: user._id, email: user.email });
      });
    });
  });
});
```

That is **four levels** of nesting.  A try/catch with `await` reduces
it to flat, linear code.

### Proposed Refactor

```javascript
router.post('/register', async (req, res, next) => {
  try {
    const { email, password } = req.body;
    const hash = await bcrypt.hash(password, 12);
    const user = await User.create({ email, passwordHash: hash });
    req.session.userId = user._id;
    res.status(201).json({ id: user._id, email: user.email });
  } catch (err) {
    if (err.code === 11000) {
      return res.status(409).json({ error: 'Email already registered' });
    }
    next(err);
  }
});
```

## Scope

- `routes/auth.js` — `register`, `login`, `change-password`
- Any other file still using callback-based bcrypt or Mongoose calls

## Acceptance Criteria

- [ ] No callback-style bcrypt calls remain
- [ ] All async route handlers pass errors to `next()` (or use
      `express-async-errors`)
- [ ] Existing tests pass without changes
- [ ] No change in external API behavior
""",
    },
    # ----------------------------------------------------------------
    # 14. API Gateway — Update auth endpoint docs
    # ----------------------------------------------------------------
    {
        "title": "Update API docs for authentication endpoints",
        "labels": ["documentation", "api-gateway"],
        "body": """\
## Problem

The API documentation for authentication endpoints is outdated.  The
`/auth/register` and `/auth/login` routes were reworked two sprints ago
(PR #34) but the docs were never updated.  As a result:

- New hires keep asking in Slack how login and registration work.
- The Postman collection in `docs/postman/` still references the old
  `/users/signup` path.
- There is no documentation at all for `/auth/change-password` or
  `/auth/logout`.

## Scope

Document the following endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/auth/register` | Create a new user account |
| `POST` | `/auth/login` | Authenticate and receive a session |
| `POST` | `/auth/logout` | Destroy the current session |
| `POST` | `/auth/change-password` | Update password (requires auth) |
| `GET`  | `/auth/me` | Return the authenticated user profile |

For each endpoint, document:

1. Request headers (Content-Type, Authorization if required)
2. Request body schema with types and constraints
3. Success response (status code + body)
4. Error responses (all possible status codes + bodies)
5. Example `curl` command
6. Rate limits (once implemented)

## Where to Put It

- Update `docs/api/auth.md` (main reference).
- Update the Postman collection `docs/postman/finserv.postman_collection.json`.
- Add JSDoc comments to each route handler in `routes/auth.js` so the
  docs stay close to the code.

## Acceptance Criteria

- [ ] All five auth endpoints are documented
- [ ] Examples are copy-pastable and work against local dev
- [ ] Postman collection is importable and tests pass
- [ ] At least one reviewer who is new to the codebase confirms the
      docs are sufficient to onboard without Slack questions
""",
    },
    # ----------------------------------------------------------------
    # 15. API Gateway — Race condition in balance updates
    # ----------------------------------------------------------------
    {
        "title": "Race condition in concurrent balance updates",
        "labels": ["bug", "api-gateway", "high-priority"],
        "body": """\
## Description

The `updateBalance` function in `api-gateway/services/accounts.js`
follows a **read-modify-write** pattern without any form of locking or
atomic operation.  Under concurrent requests this causes lost updates.

## Reproduction Scenario

Starting balance: **$1,000.00**

| Time | Request A (withdraw $200) | Request B (withdraw $300) |
|------|--------------------------|--------------------------|
| t0 | `balance = getBalance()` -> $1,000 | |
| t1 | | `balance = getBalance()` -> $1,000 |
| t2 | `setBalance(1000 - 200)` -> $800 | |
| t3 | | `setBalance(1000 - 300)` -> $700 |

**Expected final balance:** $500 ($1,000 - $200 - $300)
**Actual final balance:** $700 (Request A's write is lost)

## Code

```javascript
// api-gateway/services/accounts.js  (line ~42)
async function updateBalance(accountId, amount) {
  const account = await Account.findById(accountId);  // READ
  account.balance += amount;                           // MODIFY
  await account.save();                                // WRITE
  // Works fine for now — single server, low traffic
  return account.balance;
}
```

Note the comment "Works fine for now" — this was fine when we had a
single server, but we now run three replicas behind a load balancer.

## Suggested Fix

Use MongoDB's `$inc` operator for atomic updates:

```javascript
async function updateBalance(accountId, amount) {
  const result = await Account.findByIdAndUpdate(
    accountId,
    { $inc: { balance: amount } },
    { new: true }
  );
  if (!result) throw new NotFoundError(`Account ${accountId} not found`);
  return result.balance;
}
```

For transfers (debit one account, credit another), wrap the operation in
a MongoDB transaction:

```javascript
const session = await mongoose.startSession();
try {
  await session.withTransaction(async () => {
    await Account.findByIdAndUpdate(fromId, { $inc: { balance: -amount } }, { session });
    await Account.findByIdAndUpdate(toId,   { $inc: { balance:  amount } }, { session });
  });
} finally {
  session.endSession();
}
```

## Impact

**High.**  In production we have already seen two cases where a
customer's balance was higher than it should be after concurrent
withdrawals.  This is a **financial correctness** issue.
""",
    },
]


def _ensure_labels(client: GitHubClient) -> None:
    """Create any missing labels on the repository.

    Uses the internal ``_repo`` attribute of GitHubClient to check and
    create labels directly via PyGithub.
    """
    repo = client._repo  # noqa: SLF001 — private access is intentional
    existing: set[str] = set()
    try:
        for label in repo.get_labels():
            existing.add(label.name)
    except GithubException as exc:
        print(f"[warning] Could not fetch existing labels: {exc}")
        existing = set()

    for name, color in REQUIRED_LABELS.items():
        if name in existing:
            print(f"  Label '{name}' already exists — skipping")
            continue
        try:
            repo.create_label(name=name, color=color)
            print(f"  Created label '{name}' (#{color})")
        except GithubException as exc:
            # 422 means the label already exists (race or pagination miss).
            if exc.status == 422:
                print(f"  Label '{name}' already exists (422) — skipping")
            else:
                print(f"  [error] Failed to create label '{name}': {exc}")


def main() -> None:
    """Seed all issues, skipping any that already exist by title."""
    client = GitHubClient()

    # 1. Ensure required labels exist.
    print("\n=== Ensuring labels exist ===\n")
    _ensure_labels(client)

    # 2. Fetch existing open issue titles for idempotency.
    print("\n=== Checking existing issues ===\n")
    existing_issues = client.fetch_open_issues()
    existing_titles: set[str] = {issue["title"] for issue in existing_issues}
    print(f"  Found {len(existing_titles)} existing open issues")

    # 3. Create issues.
    print("\n=== Creating issues ===\n")
    created = 0
    skipped = 0

    for idx, issue in enumerate(ISSUES, start=1):
        title = issue["title"]

        if title in existing_titles:
            print(f"  [{idx:>2}/{len(ISSUES)}] SKIP (already exists): {title}")
            skipped += 1
            continue

        issue_number = client.create_issue(
            title=title,
            body=issue["body"],
            labels=issue["labels"],
        )
        print(f"  [{idx:>2}/{len(ISSUES)}] CREATED #{issue_number}: {title}")
        created += 1

    # 4. Summary.
    print(f"\n=== Done: {created} created, {skipped} skipped ===\n")


if __name__ == "__main__":
    main()
