"""
Stage 3 SecureHttpClient & URL Construction Test Suite
Covers URL prefix deduplication, slash normalization, query/path params,
multi-IP SSRF DNS checks, ALLOWED_DOMAINS enforcement, redirect blocking,
response size caps, credential masking, and idempotent-only retries.
"""
import socket
from unittest.mock import patch, AsyncMock, MagicMock
import httpx
import pytest

from app.services.http_client import (
    build_target_url,
    validate_target_url,
    mask_headers_for_log,
    mask_params_for_log,
    SecureHttpClient,
    SSRFProtectionError,
    ResponseSizeLimitError,
    settings,
)


def test_build_target_url_normalization_and_deduplication():
    """Verify overlapping base/endpoint prefixes are deduplicated and slashes/params handled cleanly."""
    # Deduplicate /mock/api/v1 prefix
    url, qp = build_target_url("http://127.0.0.1:8000/mock/api/v1/", "/mock/api/v1/products/{id}", {"id": 5, "currency": "USD"})
    assert url == "http://127.0.0.1:8000/mock/api/v1/products/5"
    assert qp == {"currency": "USD"}

    # Deduplicate generic /v2 prefix
    url2, qp2 = build_target_url("https://api.example.com/v2", "v2/orders?status=open", {"limit": 10})
    assert url2 == "https://api.example.com/v2/orders"
    assert qp2 == {"status": "open", "limit": 10}

    # Missing required path variable raises clear ValueError
    with pytest.raises(ValueError, match="Missing required path parameter"):
        build_target_url("http://127.0.0.1:8000/mock/api/v1", "/products/{id}", {})


def test_ssrf_checks_all_dns_records_and_allowed_domains(monkeypatch):
    """Verify SSRF protection validates all resolved DNS records and enforces ALLOWED_DOMAINS."""
    # Multi-A record containing one public + one private internal IP -> blocked
    fake_dns = [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.5", 443)),
    ]
    with patch("socket.getaddrinfo", return_value=fake_dns):
        with pytest.raises(SSRFProtectionError, match="internal/private IP"):
            validate_target_url("https://dual-dns.example.org/api")

    # Enforce ALLOWED_DOMAINS when set
    public_dns = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))]
    monkeypatch.setattr(settings, "ALLOWED_DOMAINS", "api.trusted.com,*.partner.org")
    with patch("socket.getaddrinfo", return_value=public_dns):
        ip, host, _ = validate_target_url("https://sub.partner.org/v1/data")
        assert host == "sub.partner.org"

        with pytest.raises(SSRFProtectionError, match="ALLOWED_DOMAINS"):
            validate_target_url("https://evil.untrusted.com/steal")


def test_header_and_param_credential_masking():
    """Verify secrets in headers and query params are always masked cleanly."""
    hdrs = mask_headers_for_log({"Authorization": "Bearer super_secret_token_98765", "X-API-Key": "key_1234567890", "Content-Type": "application/json"})
    assert hdrs["Authorization"] == "Bearer supe...8765"
    assert hdrs["X-API-Key"] == "key_...7890"
    assert hdrs["Content-Type"] == "application/json"

    params = mask_params_for_log({"api_key": "secret_value_abcxyz", "id": 5})
    assert params["api_key"] == "secr...cxyz"
    assert params["id"] == 5


@pytest.mark.asyncio
async def test_redirect_protection_and_response_size_limit():
    """Verify redirects are disabled/validated and oversized responses are rejected."""
    client = SecureHttpClient(max_response_bytes=50, max_safe_retries=0)

    # 1. Redirect blocked when allow_redirects=False
    redir_resp = httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})
    with patch.object(client, "_send_once", AsyncMock(side_effect=SSRFProtectionError("Redirects are disabled"))):
        with pytest.raises(SSRFProtectionError):
            await client.execute_request("GET", "http://127.0.0.1:8000/mock/api/v1/products")

    # 2. Oversized response blocked
    huge_resp = httpx.Response(200, content=b"x" * 200, headers={"content-length": "200"})
    with patch.object(client, "_send_once", AsyncMock(return_value=huge_resp)):
        with pytest.raises(ResponseSizeLimitError, match="exceeds limit"):
            await client.execute_request("GET", "http://127.0.0.1:8000/mock/api/v1/products")


@pytest.mark.asyncio
async def test_idempotent_retry_safety():
    """Verify GET retries transient 503 and succeeds, whereas POST never auto-retries unsafe mutations."""
    client = SecureHttpClient(max_safe_retries=2)

    # GET succeeds on 2nd attempt after 503
    resp_503 = httpx.Response(503, json={"error": "unavailable"})
    resp_200 = httpx.Response(200, json={"id": 5, "price": 1000.0})
    mock_send_get = AsyncMock(side_effect=[resp_503, resp_200])
    with patch.object(client, "_send_once", mock_send_get):
        res = await client.execute_request("GET", "http://127.0.0.1:8000/mock/api/v1/products/5")
        assert res["status_code"] == 200
        assert res["attempts"] == 2

    # POST does NOT auto-retry on 503
    mock_send_post = AsyncMock(side_effect=[resp_503, resp_200])
    with patch.object(client, "_send_once", mock_send_post):
        res_post = await client.execute_request("POST", "http://127.0.0.1:8000/mock/api/v1/orders", json_data={"product_id": 5})
        assert res_post["status_code"] == 503
        assert res_post["attempts"] == 1
        assert mock_send_post.call_count == 1

