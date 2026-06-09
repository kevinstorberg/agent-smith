import pytest

from src.security.validation import (
    MAX_NAME_LENGTH,
    sanitize_query,
    validate_email,
    validate_name,
    validate_uuid,
)


@pytest.mark.unit
class TestValidateName:
    def test_valid_name_accepted(self):
        assert validate_name("my_resource") == "my_resource"

    def test_single_char_accepted(self):
        assert validate_name("a") == "a"

    def test_name_with_digits_accepted(self):
        assert validate_name("item_2") == "item_2"

    def test_starts_with_digit_rejected(self):
        with pytest.raises(ValueError, match="must start with"):
            validate_name("123invalid")

    def test_uppercase_rejected(self):
        with pytest.raises(ValueError, match="must start with"):
            validate_name("MyResource")

    def test_special_chars_rejected(self):
        with pytest.raises(ValueError, match="must start with"):
            validate_name("my-resource")

    def test_empty_rejected(self):
        with pytest.raises(ValueError):
            validate_name("")

    def test_too_long_rejected(self):
        with pytest.raises(ValueError, match="too long"):
            validate_name("a" * (MAX_NAME_LENGTH + 1))


@pytest.mark.unit
class TestSanitizeQuery:
    def test_strips_double_quotes(self):
        assert sanitize_query('hello "world"') == "hello world"

    def test_strips_single_quotes(self):
        assert sanitize_query("hello 'world'") == "hello world"

    def test_strips_semicolons(self):
        assert sanitize_query("SELECT; DROP TABLE") == "SELECT DROP TABLE"

    def test_strips_backslashes(self):
        assert sanitize_query("path\\to\\file") == "pathtofile"

    def test_preserves_normal_text(self):
        assert sanitize_query("normal search query") == "normal search query"

    def test_strips_leading_trailing_whitespace(self):
        assert sanitize_query("  hello  ") == "hello"


@pytest.mark.unit
class TestValidateUuid:
    def test_valid_uuid_accepted(self):
        validate_uuid("12345678-1234-1234-1234-123456789abc")

    def test_uppercase_uuid_accepted(self):
        validate_uuid("12345678-1234-1234-1234-123456789ABC")

    def test_invalid_format_rejected(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            validate_uuid("not-a-uuid")

    def test_empty_rejected(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            validate_uuid("")

    def test_no_hyphens_rejected(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            validate_uuid("12345678123412341234123456789abc")


@pytest.mark.unit
class TestValidateEmail:
    def test_valid_email_accepted(self):
        assert validate_email("user@example.com") == "user@example.com"

    def test_missing_at_rejected(self):
        with pytest.raises(ValueError, match="Invalid email"):
            validate_email("userexample.com")

    def test_missing_domain_rejected(self):
        with pytest.raises(ValueError, match="Invalid email"):
            validate_email("user@")

    def test_empty_rejected(self):
        with pytest.raises(ValueError, match="Invalid email"):
            validate_email("")
