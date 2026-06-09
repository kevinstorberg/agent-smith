import re

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SANITIZE_RE = re.compile(r"[\"';\\]")

MAX_NAME_LENGTH = 40


def validate_name(name: str) -> str:
    if not name:
        raise ValueError("Name must not be empty")
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"Name too long (max {MAX_NAME_LENGTH} characters)")
    if not _NAME_RE.match(name):
        raise ValueError(
            "Name must start with a lowercase letter and contain only lowercase letters, digits, and underscores"
        )
    return name


def sanitize_query(query: str) -> str:
    cleaned = _SANITIZE_RE.sub("", query)
    return cleaned.strip()


def validate_uuid(value: str) -> str:
    if not _UUID_RE.match(value):
        raise ValueError(f"Invalid UUID format: {value!r}")
    return value


def validate_email(email: str) -> str:
    if not _EMAIL_RE.match(email):
        raise ValueError(f"Invalid email format: {email!r}")
    return email
