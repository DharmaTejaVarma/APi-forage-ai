"""
APIForge AI Secure Outgoing HTTP Client & URL Engine
Implements centralized URL construction (prefix deduplication, slash normalization,
query/path params), SSRF protection across all resolved DNS IPs, domain allowlisting,
credential attachment & log masking, response size caps, redirect destination
checks, and safe idempotent retries.
"""
import asyncio
import base64
import ipaddress
import re
import socket
import time
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from typing import Dict, Any, Optional, Tuple
import httpx

from app.config import get_settings
from app.security import mask_secret

settings = get_settings()

BLOCKED_METADATA_HOSTS = {
    "169.254.169.254",          # AWS / OpenStack / Azure instance metadata
    "metadata.google.internal",  # GCP metadata
    "metadata.packet.net",
    "100.100.100.200",          # Alibaba Cloud metadata
}

SENSITIVE_HEADER_KEYS = {"authorization", "x-api-key", "api-key", "apikey", "x-auth-token", "proxy-authorization"}
SENSITIVE_PARAM_KEYS = {"api_key", "apikey", "token", "access_token", "secret", "password", "key"}
IDEMPOTENT_METHODS = {"GET", "HEAD", "OPTIONS"}
RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
DEFAULT_MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB


class SSRFProtectionError(Exception):
    """Raised when an outgoing request violates SSRF security boundaries."""
    pass


class ResponseSizeLimitError(RuntimeError):
    """Raised when an external API response exceeds maximum permitted size."""
    pass


class ConnectionFailureError(RuntimeError):
    """Raised when TCP/HTTP connection to target service fails."""
    pass


def _is_domain_allowed(hostname_lower: str) -> bool:
    """Verify host against ALLOWED_DOMAINS when explicitly configured."""
    allowed = settings.allowed_domains_list
    if not allowed:
        return True
    for pattern in allowed:
        p = pattern.lower()
        if p.startswith("*."):
            suffix = p[1:]  # '.example.com'
            if hostname_lower.endswith(suffix) or hostname_lower == p[2:]:
                return True
        elif hostname_lower == p:
            return True
    return False


def validate_target_url(url: str) -> Tuple[str, str, int]:
    """
    Validate target URL against SSRF vulnerabilities:
    1. Enforce http/https schemes only.
    2. Block cloud metadata endpoints.
    3. Enforce ALLOWED_DOMAINS allowlist when configured (unless dev host in DEBUG).
    4. Validate ALL resolved IP addresses against private, loopback, link-local,
       reserved, multicast, and unspecified IP ranges unless in DEV allowlist during DEBUG.
    Returns (primary_resolved_ip, hostname, port).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ["http", "https"]:
        raise SSRFProtectionError(f"Unsupported protocol scheme '{parsed.scheme}'. Only http and https are permitted.")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFProtectionError("Target URL does not contain a valid hostname.")

    hostname_lower = hostname.lower()
    if hostname_lower in BLOCKED_METADATA_HOSTS:
        raise SSRFProtectionError(f"Access to cloud metadata host '{hostname}' is strictly prohibited.")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    # Resolve ALL IP addresses
    try:
        addr_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise SSRFProtectionError(f"Failed to resolve hostname '{hostname}': {str(e)}") from e

    if not addr_info:
        raise SSRFProtectionError(f"Could not resolve any IP address for host '{hostname}'.")

    dev_allowed = {h.lower() for h in settings.dev_allowed_hosts_list}
    resolved_ips = []
    for entry in addr_info:
        ip_str = entry[4][0]
        resolved_ips.append(ip_str)
        ip_obj = ipaddress.ip_address(ip_str)
        is_private_or_loopback = (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_reserved
            or ip_obj.is_multicast
            or ip_obj.is_unspecified
        )
        if is_private_or_loopback:
            is_dev_host = hostname_lower in dev_allowed or ip_str.lower() in dev_allowed
            if not (settings.DEBUG and is_dev_host):
                raise SSRFProtectionError(
                    f"Security violation: Request to internal/private IP '{ip_str}' ({hostname}) is forbidden."
                )

    is_dev_host_any = hostname_lower in dev_allowed or any(ip.lower() in dev_allowed for ip in resolved_ips)
    if settings.allowed_domains_list and not (settings.DEBUG and is_dev_host_any):
        if not _is_domain_allowed(hostname_lower):
            raise SSRFProtectionError(
                f"Security violation: Host '{hostname}' is not in ALLOWED_DOMAINS allowlist."
            )

    return resolved_ips[0], hostname, port


def build_target_url(
    base_url: str,
    endpoint_path: str,
    parameters: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Centralized URL builder:
    - Normalizes leading/trailing slashes between base_url and endpoint_path.
    - Deduplicates overlapping path prefixes (e.g. base ending '/mock/api/v1' + path '/mock/api/v1/products').
    - Substitutes path template params '{id}' and extracts remaining fields as query params.
    - Preserves inline query strings already present on endpoint_path or base_url.
    Returns (final_url_without_query_dict_merged, remaining_query_params_dict).
    """
    raw_base = (base_url or "").strip()
    raw_path = (endpoint_path or "").strip()

    # If endpoint_path is already an absolute http(s) URL, parse and extract cleanly
    if raw_path.startswith("http://") or raw_path.startswith("https://"):
        parsed_full = urlparse(raw_path)
        query_items = dict(parse_qsl(parsed_full.query))
        resolved_path = parsed_full.path or "/"
        base_scheme_host = f"{parsed_full.scheme}://{parsed_full.netloc}"
        base_prefix_path = ""
    else:
        parsed_base = urlparse(raw_base)
        base_scheme_host = f"{parsed_base.scheme}://{parsed_base.netloc}"
        base_prefix_path = parsed_base.path.rstrip("/")
        parsed_ep = urlparse(raw_path)
        query_items = dict(parse_qsl(parsed_base.query))
        query_items.update(dict(parse_qsl(parsed_ep.query)))
        resolved_path = parsed_ep.path or ""

    # Deduplicate overlapping base path prefix cleanly
    norm_ep_path = "/" + resolved_path.lstrip("/") if resolved_path else ""
    if base_prefix_path and norm_ep_path:
        if norm_ep_path == base_prefix_path:
            norm_ep_path = ""
        elif norm_ep_path.startswith(base_prefix_path + "/"):
            norm_ep_path = norm_ep_path[len(base_prefix_path):]

    combined_path = (base_prefix_path + norm_ep_path) or "/"

    # Apply path parameters and split query parameters
    query_params: Dict[str, Any] = dict(query_items)
    if parameters:
        for p_name, p_val in parameters.items():
            token = f"{{{p_name}}}"
            if token in combined_path:
                combined_path = combined_path.replace(token, str(p_val))
            else:
                query_params[p_name] = p_val

    # Detect unresolved path placeholders like '{id}'
    leftover_path_vars = re.findall(r"\{([a-zA-Z0-9_]+)\}", combined_path)
    if leftover_path_vars:
        raise ValueError(
            f"Missing required path parameter(s) {leftover_path_vars} for URL path '{combined_path}'"
        )

    final_url = base_scheme_host.rstrip("/") + "/" + combined_path.lstrip("/")
    return final_url, query_params


def mask_headers_for_log(headers: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Mask sensitive tokens/keys in headers before persistence or logging."""
    if not headers:
        return {}
    masked: Dict[str, str] = {}
    for k, v in headers.items():
        k_lower = k.lower()
        if k_lower in SENSITIVE_HEADER_KEYS or any(w in k_lower for w in ("token", "secret", "key", "auth", "password")):
            val_str = str(v)
            if " " in val_str and val_str.split(" ", 1)[0].lower() in {"bearer", "basic", "token"}:
                scheme, secret_part = val_str.split(" ", 1)
                masked[k] = f"{scheme} {mask_secret(secret_part)}"
            else:
                masked[k] = mask_secret(val_str)
        else:
            masked[k] = str(v)
    return masked


def mask_params_for_log(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Mask sensitive query parameter values before logging."""
    if not params:
        return {}
    masked: Dict[str, Any] = {}
    for k, v in params.items():
        if k.lower() in SENSITIVE_PARAM_KEYS or any(w in k.lower() for w in ("token", "secret", "password")):
            masked[k] = mask_secret(str(v))
        else:
            masked[k] = v
    return masked


class SecureHttpClient:
    """Secure client for executing validated external and internal API requests."""

    def __init__(
        self,
        default_timeout: float = 30.0,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_safe_retries: int = 2,
    ):
        self.default_timeout = default_timeout
        self.max_response_bytes = max_response_bytes
        self.max_safe_retries = max_safe_retries

    async def execute_request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        auth_type: str = "none",
        credentials: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        allow_redirects: bool = False,
        allow_unsafe_retry: bool = False,
        max_response_bytes: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute an outgoing HTTP request with SSRF validation, credential injection,
        response size bounds, redirect protection, safe idempotent retries, and latency measurement.
        """
        http_method = method.upper()
        validate_target_url(url)

        req_headers = dict(headers or {})
        req_params = dict(params or {})

        # Attach encrypted/decrypted credentials
        if credentials:
            if auth_type == "bearer":
                token = credentials.get("token") or credentials.get("access_token") or credentials.get("api_key")
                if token:
                    req_headers["Authorization"] = f"Bearer {token}"
            elif auth_type == "api_key":
                key_name = credentials.get("header_name") or credentials.get("key_name") or "X-API-Key"
                key_val = credentials.get("key") or credentials.get("api_key") or credentials.get("value")
                key_in = credentials.get("in", "header")
                if key_val:
                    if key_in == "query":
                        req_params[key_name] = key_val
                    else:
                        req_headers[key_name] = key_val
            elif auth_type == "basic":
                user = credentials.get("username", "")
                pwd = credentials.get("password", "")
                encoded = base64.b64encode(f"{user}:{pwd}".encode()).decode()
                req_headers["Authorization"] = f"Basic {encoded}"

        req_timeout = timeout or self.default_timeout
        size_limit = max_response_bytes if max_response_bytes is not None else self.max_response_bytes

        # Only retry safe idempotent operations unless explicitly allowed
        can_retry = (http_method in IDEMPOTENT_METHODS) or allow_unsafe_retry
        total_attempts = 1 + (self.max_safe_retries if can_retry else 0)

        start_time = time.perf_counter()
        last_error: Optional[Exception] = None
        response: Optional[httpx.Response] = None
        attempts_made = 0

        for attempt in range(1, total_attempts + 1):
            attempts_made = attempt
            try:
                response = await self._send_once(
                    method=http_method,
                    url=url,
                    headers=req_headers,
                    params=req_params,
                    json_data=json_data,
                    timeout=req_timeout,
                    allow_redirects=allow_redirects,
                )
                if response.status_code in RETRYABLE_STATUS_CODES and attempt < total_attempts:
                    await asyncio.sleep(0.05 * attempt)
                    continue
                break
            except (TimeoutError, ConnectionFailureError) as exc:
                last_error = exc
                if attempt < total_attempts:
                    await asyncio.sleep(0.05 * attempt)
                    continue
                raise

        if response is None:
            raise last_error or ConnectionFailureError(f"Failed to execute HTTP {http_method} to '{url}'")

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Enforce response size limit via Content-Length and actual content length
        content_len_hdr = response.headers.get("content-length")
        if content_len_hdr and content_len_hdr.isdigit() and int(content_len_hdr) > size_limit:
            raise ResponseSizeLimitError(
                f"Response Content-Length ({content_len_hdr} bytes) exceeds limit ({size_limit} bytes)"
            )
        raw_bytes = response.content or b""
        if len(raw_bytes) > size_limit:
            raise ResponseSizeLimitError(
                f"Response payload size ({len(raw_bytes)} bytes) exceeds limit ({size_limit} bytes)"
            )

        try:
            body = response.json()
        except Exception:
            body = response.text

        return {
            "status_code": response.status_code,
            "success": 200 <= response.status_code < 300,
            "data": body,
            "headers": mask_headers_for_log(dict(response.headers)),
            "elapsed_ms": elapsed_ms,
            "attempts": attempts_made,
            "request_masked": {
                "method": http_method,
                "url": url,
                "headers": mask_headers_for_log(req_headers),
                "params": mask_params_for_log(req_params),
            },
        }

    async def _send_once(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        params: Dict[str, Any],
        json_data: Optional[Dict[str, Any]],
        timeout: float,
        allow_redirects: bool,
    ) -> httpx.Response:
        """Perform a single HTTP roundtrip with disabled implicit redirects & local ASGI fallback."""
        current_url = url
        current_headers = dict(headers)
        max_hops = 3 if allow_redirects else 0

        for hop in range(max_hops + 1):
            validate_target_url(current_url)
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                try:
                    response = await client.request(
                        method=method,
                        url=current_url,
                        headers=current_headers,
                        params=params if hop == 0 else None,
                        json=json_data,
                    )
                except httpx.TimeoutException as e:
                    raise TimeoutError(f"HTTP request to '{current_url}' timed out after {timeout}s") from e
                except httpx.ConnectError as e:
                    if "127.0.0.1:8000" in current_url or "localhost:8000" in current_url:
                        from app.main import app as fastapi_app
                        transport = httpx.ASGITransport(app=fastapi_app)
                        async with httpx.AsyncClient(
                            transport=transport, base_url="http://127.0.0.1:8000", follow_redirects=False
                        ) as local_client:
                            parsed_local = urlparse(current_url)
                            local_target = parsed_local.path + (f"?{parsed_local.query}" if parsed_local.query else "")
                            response = await local_client.request(
                                method=method,
                                url=local_target,
                                headers=current_headers,
                                params=params if hop == 0 else None,
                                json=json_data,
                            )
                    else:
                        raise ConnectionFailureError(f"HTTP connection failed for '{current_url}': {str(e)}") from e
                except httpx.RequestError as e:
                    raise ConnectionFailureError(f"HTTP request failed: {str(e)}") from e

            # Handle 3xx redirects safely
            if 300 <= response.status_code < 400 and "location" in response.headers:
                if not allow_redirects:
                    raise SSRFProtectionError(
                        f"Redirects are disabled for security (received HTTP {response.status_code} redirect)"
                    )
                next_url = response.headers["location"]
                if next_url.startswith("/"):
                    p_cur = urlparse(current_url)
                    next_url = f"{p_cur.scheme}://{p_cur.netloc}{next_url}"
                validate_target_url(next_url)
                # Strip credentials when redirecting across origins
                if urlparse(next_url).netloc != urlparse(current_url).netloc:
                    for hk in list(current_headers.keys()):
                        if hk.lower() in SENSITIVE_HEADER_KEYS:
                            current_headers.pop(hk, None)
                current_url = next_url
                continue

            return response

        raise SSRFProtectionError("Exceeded maximum validated redirect hops")


# Global secure HTTP client instance
secure_http_client = SecureHttpClient()
