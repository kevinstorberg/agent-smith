# API Errors

Cairn wraps API failures in one envelope:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed",
    "details": [],
    "request_id": "..."
  }
}
```

The source of truth is `src/api/errors.py`. It provides:

- `APIException` for app-owned errors with explicit codes and details.
- Global handlers for `HTTPException`, validation errors, and unhandled errors.
- Request ID middleware that reads or creates `X-Request-ID` and returns it on every response.

Use `APIException` in new route or service boundaries when the application knows
the stable error code. Existing FastAPI `HTTPException` call sites are still
wrapped by the global handlers.

Unhandled exceptions return a generic `internal_server_error` response by
default. Set `DEBUG_ERRORS=true` only in local development when the response
should include the exception type and message in `details`.
