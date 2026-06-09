from src.diagnostics.redaction import REDACTED, redact_mapping


def test_redaction_hides_sensitive_values_recursively():
    redacted = redact_mapping(
        {
            "DATABASE_URL": "postgres://secret",
            "nested": {"api_key": "key", "safe": "value"},
            "items": [{"password": "pw"}],
            "REDIS_URL": "redis://localhost",
            "DOCUMENTDB_URI": "mongodb://localhost",
        }
    )

    assert redacted["DATABASE_URL"] == REDACTED
    assert redacted["nested"]["api_key"] == REDACTED
    assert redacted["nested"]["safe"] == "value"
    assert redacted["items"][0]["password"] == REDACTED
    assert redacted["REDIS_URL"] == REDACTED
    assert redacted["DOCUMENTDB_URI"] == REDACTED


def test_redaction_does_not_hide_safe_words_containing_sensitive_substrings():
    redacted = redact_mapping({"security": {"enabled": True}, "max_tokens": 1000})

    assert redacted["security"] == {"enabled": True}
    assert redacted["max_tokens"] == 1000


def test_redaction_can_expose_values_for_local_debugging():
    value = {"SECRET_KEY": "secret"}

    assert redact_mapping(value, expose_values=True) == value
