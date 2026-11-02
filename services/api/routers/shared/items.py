from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

from services.action_items import db


def call_item(operation: Callable, *args: Any) -> Any:
    try:
        return operation(*args)
    except db.NotFound as error:
        raise HTTPException(404, str(error)) from None
    except db.Conflict as error:
        raise HTTPException(409, str(error)) from None
    except db.StorageError as error:
        raise HTTPException(503, str(error)) from None
    except (ValueError, ValidationError) as error:
        raise HTTPException(422, str(error)) from None
