"""
Phase 6 SSRF Protection Test Suite
Verifies that the SecureHttpClient strictly blocks requests to cloud metadata endpoints,
unsupported URL schemes, and unauthorized private/internal IP ranges.
Non-Negotiable Rule: Prevent SSRF, private IP access and unauthorized API calls.
"""
import pytest
from app.services.http_client import validate_target_url, SSRFProtectionError


def test_ssrf_blocks_cloud_metadata():
    """Verify requests to AWS/Azure/GCP metadata endpoints are blocked."""
    with pytest.raises(SSRFProtectionError, match="cloud metadata"):
        validate_target_url("http://169.254.169.254/latest/meta-data/")

    with pytest.raises(SSRFProtectionError, match="cloud metadata"):
        validate_target_url("http://metadata.google.internal/computeMetadata/v1/")


def test_ssrf_blocks_unsupported_protocols():
    """Verify non-HTTP protocols are rejected."""
    with pytest.raises(SSRFProtectionError, match="Unsupported protocol scheme"):
        validate_target_url("file:///etc/passwd")

    with pytest.raises(SSRFProtectionError, match="Unsupported protocol scheme"):
        validate_target_url("gopher://127.0.0.1:70/test")

    with pytest.raises(SSRFProtectionError, match="Unsupported protocol scheme"):
        validate_target_url("ftp://ftp.example.com/data")


def test_ssrf_allows_dev_hosts_in_debug():
    """Verify local development allowed hosts (localhost, 127.0.0.1) are permitted in dev mode."""
    ip, host, port = validate_target_url("http://127.0.0.1:8000/mock/api/v1/products")
    assert ip in ["127.0.0.1", "::1"]
    assert port == 8000

    ip2, host2, port2 = validate_target_url("http://localhost:8000/health")
    assert host2 == "localhost"


def test_ssrf_allows_public_urls():
    """Verify public internet hostnames pass validation."""
    ip, host, port = validate_target_url("https://httpbin.org/get")
    assert host == "httpbin.org"
    assert port == 443
    assert ip is not None
