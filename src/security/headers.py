from starlette.datastructures import MutableHeaders

from config.models import SecurityHeadersConfig


def apply_security_headers(
    headers: MutableHeaders,
    *,
    headers_config: SecurityHeadersConfig,
    hsts_enabled: bool = False,
) -> None:
    if not headers_config.enabled:
        return

    _set_header_if_absent(headers, "X-Content-Type-Options", headers_config.content_type_options)
    _set_header_if_absent(headers, "X-Frame-Options", headers_config.frame_options)
    _set_header_if_absent(headers, "Referrer-Policy", headers_config.referrer_policy)
    _set_header_if_absent(headers, "Permissions-Policy", headers_config.permissions_policy)
    _set_header_if_absent(headers, "Content-Security-Policy", headers_config.content_security_policy)
    if hsts_enabled:
        hsts = f"max-age={headers_config.hsts_max_age_seconds}; includeSubDomains"
        _set_header_if_absent(headers, "Strict-Transport-Security", hsts)


def _set_header_if_absent(headers: MutableHeaders, name: str, value: str) -> None:
    if value and name not in headers:
        headers[name] = value
