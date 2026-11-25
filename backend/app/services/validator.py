"""
APIForge AI Response Validator & Error Classifier
Validates API response status codes and JSONSchema schemas against endpoint response_schema.
Classifies failures into all 12 standard diagnostic categories for AI recovery and telemetry.
"""
from typing import Dict, Any, Optional, Tuple
import jsonschema
from jsonschema.exceptions import ValidationError, SchemaError


class ErrorCategory:
    CONNECTION_FAILURE = "CONNECTION_FAILURE"
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    AUTH_FAILURE = "AUTH_FAILURE"
    NOT_FOUND = "NOT_FOUND"
    INVALID_PARAMETERS = "INVALID_PARAMETERS"
    RATE_LIMIT_429 = "RATE_LIMIT_429"
    SERVER_ERROR_5XX = "SERVER_ERROR_5XX"
    MISSING_RESPONSE_FIELDS = "MISSING_RESPONSE_FIELDS"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    DATA_MAPPING_FAILURE = "DATA_MAPPING_FAILURE"
    TRANSFORM_ERROR = "TRANSFORM_ERROR"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    SSRF_VIOLATION = "SSRF_VIOLATION"
    CLIENT_ERROR_4XX = "CLIENT_ERROR_4XX"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


def _sanitize_openapi_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize OpenAPI 3.0 schemas to be compatible with jsonschema Draft 7.
    Converts 'nullable: true' to type union e.g. ['string', 'null'].
    """
    if not isinstance(schema, dict):
        return schema

    clean = dict(schema)

    if clean.get("nullable") is True:
        current_type = clean.get("type")
        if isinstance(current_type, str):
            clean["type"] = [current_type, "null"]
        elif isinstance(current_type, list) and "null" not in current_type:
            clean["type"] = current_type + ["null"]
        clean.pop("nullable", None)

    if "properties" in clean and isinstance(clean["properties"], dict):
        clean["properties"] = {k: _sanitize_openapi_schema(v) for k, v in clean["properties"].items()}
    if "items" in clean and isinstance(clean["items"], dict):
        clean["items"] = _sanitize_openapi_schema(clean["items"])

    return clean


def validate_response_schema(data: Any, schema: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate data against JSONSchema.
    Returns (is_valid, error_message).
    """
    if not schema:
        return True, None

    sanitized = _sanitize_openapi_schema(schema)
    try:
        jsonschema.validate(instance=data, schema=sanitized)
        return True, None
    except ValidationError as e:
        field = ".".join(str(p) for p in e.path) if e.path else "root"
        return False, f"Schema validation error at '{field}': {e.message}"
    except SchemaError as e:
        return False, f"Invalid JSON schema specification: {e.message}"
    except Exception as e:
        return False, f"Schema validation failed: {str(e)}"


def classify_error(
    status_code: Optional[int] = None,
    response_body: Any = None,
    exception: Optional[Exception] = None,
    error_message: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Classify an execution error into standardized diagnostic categories:
    Connection failure, Timeout, Authentication failure, Not found, Invalid parameters,
    Rate limiting, Server error, Missing response fields, Schema mismatch,
    Data mapping failure, Transformation failure, Workflow validation failure.
    """
    exc_name = type(exception).__name__ if exception else ""
    msg = error_message or (str(exception) if exception else "")
    msg_lower = msg.lower()

    if "SSRFProtectionError" in exc_name or "ssrf" in msg_lower or "prohibited" in msg_lower or "allowed_domains" in msg_lower or "internal/private ip" in msg_lower:
        category = ErrorCategory.SSRF_VIOLATION
        summary = "Outgoing request violated SSRF security boundaries."

    elif "DataMappingError" in exc_name or "unresolved template" in msg_lower or "unresolved data reference" in msg_lower:
        category = ErrorCategory.DATA_MAPPING_FAILURE
        summary = f"Data mapping failed: {msg}"

    elif "ConnectionFailureError" in exc_name or "connection failed" in msg_lower or "connecterror" in msg_lower or "name or service not known" in msg_lower:
        category = ErrorCategory.CONNECTION_FAILURE
        summary = "Could not connect to the target API service."

    elif "Timeout" in exc_name or "timed out" in msg_lower:
        category = ErrorCategory.NETWORK_TIMEOUT
        summary = "HTTP request timed out before receiving a response."

    elif "SimpleEval" in exc_name or "formula" in msg_lower or "evaluation failed" in msg_lower or "transformation" in msg_lower:
        category = ErrorCategory.TRANSFORM_ERROR
        summary = f"Data transformation error: {msg}"

    elif "validation" in msg_lower and ("cyclic" in msg_lower or "workflow" in msg_lower or "unregistered endpoint" in msg_lower or "non-ancestor" in msg_lower):
        category = ErrorCategory.VALIDATION_FAILURE
        summary = f"Workflow validation failed: {msg}"

    elif status_code in (401, 403):
        category = ErrorCategory.AUTH_FAILURE
        summary = f"API authentication/authorization failed (HTTP {status_code})."

    elif status_code == 404:
        category = ErrorCategory.NOT_FOUND
        summary = "Target API resource or endpoint not found (HTTP 404)."

    elif status_code in (400, 422) or "missing required" in msg_lower:
        category = ErrorCategory.INVALID_PARAMETERS
        summary = f"Invalid or missing request parameters/payload (HTTP {status_code or 400})."

    elif status_code == 429:
        category = ErrorCategory.RATE_LIMIT_429
        summary = "Target API returned HTTP 429 Too Many Requests (rate limited)."

    elif status_code and 400 <= status_code < 500:
        category = ErrorCategory.CLIENT_ERROR_4XX
        summary = f"Target API returned client error HTTP {status_code}."

    elif status_code and 500 <= status_code < 600:
        category = ErrorCategory.SERVER_ERROR_5XX
        summary = f"Target API returned server error HTTP {status_code}."

    elif "is a required property" in msg_lower or "missing response field" in msg_lower:
        category = ErrorCategory.MISSING_RESPONSE_FIELDS
        summary = f"API response omitted required schema field(s): {msg}"

    elif "schema" in msg_lower or "validation error at" in msg_lower:
        category = ErrorCategory.SCHEMA_MISMATCH
        summary = f"Response schema validation mismatch: {msg}"

    else:
        category = ErrorCategory.UNKNOWN_ERROR
        summary = msg or "An unexpected execution error occurred."

    return {
        "category": category,
        "summary": summary,
        "status_code": status_code,
        "error_message": msg,
        "response_body": response_body,
    }


def validate_api_response(
    status_code: int,
    data: Any,
    expected_status: Optional[int] = None,
    expected_schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Validate status code and body schema for an API response.
    Distinguishes MISSING_RESPONSE_FIELDS vs general SCHEMA_MISMATCH.
    """
    if expected_status and status_code != expected_status:
        classification = classify_error(status_code=status_code, response_body=data)
        classification["valid"] = False
        classification["reason"] = f"Expected HTTP {expected_status}, received HTTP {status_code}."
        return classification

    if status_code >= 400:
        classification = classify_error(status_code=status_code, response_body=data)
        classification["valid"] = False
        classification["reason"] = f"API returned error status HTTP {status_code}."
        return classification

    if expected_schema:
        is_valid, err_msg = validate_response_schema(data, expected_schema)
        if not is_valid:
            classification = classify_error(
                status_code=status_code,
                response_body=data,
                error_message=err_msg,
            )
            classification["valid"] = False
            classification["reason"] = err_msg
            return classification

    return {
        "valid": True,
        "category": None,
        "summary": "Response passed status and schema validation.",
        "status_code": status_code,
        "response_body": data,
    }
