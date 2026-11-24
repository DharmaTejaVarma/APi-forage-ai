"""
APIForge AI Response Validation & Error Classification Tests
Verifies JSONSchema validation, type mismatch detection, and error categorization.
"""
import pytest
from app.services.validator import (
    ErrorCategory,
    classify_error,
    validate_response_schema,
    validate_api_response,
)
from app.services.http_client import SSRFProtectionError


def test_jsonschema_valid_response():
    """Verify conforming response data passes schema validation."""
    schema = {
        "type": "object",
        "required": ["id", "name", "price"],
        "properties": {
            "id": {"type": "integer"},
            "name": {"type": "string"},
            "price": {"type": "number"},
            "stock": {"type": "integer", "nullable": True},
        },
    }
    data = {"id": 1, "name": "Wireless Mouse", "price": 250.0, "stock": 100}
    is_valid, err = validate_response_schema(data, schema)
    assert is_valid is True
    assert err is None


def test_jsonschema_invalid_type_mismatch():
    """Verify type mismatches are caught and descriptive error returned."""
    schema = {
        "type": "object",
        "required": ["price"],
        "properties": {
            "price": {"type": "number"},
        },
    }
    data = {"price": "not-a-number"}
    is_valid, err = validate_response_schema(data, schema)
    assert is_valid is False
    assert "Schema validation error" in err
    assert "price" in err


def test_jsonschema_missing_required_property():
    """Verify missing required fields fail schema validation."""
    schema = {
        "type": "object",
        "required": ["order_id", "status"],
        "properties": {
            "order_id": {"type": "string"},
            "status": {"type": "string"},
        },
    }
    data = {"order_id": "ORD-1234"}
    is_valid, err = validate_response_schema(data, schema)
    assert is_valid is False
    assert "status" in err


def test_error_classification_categories():
    """Verify diverse error types are classified into distinct ErrorCategory values."""
    # SSRF Violation
    c1 = classify_error(exception=SSRFProtectionError("Access forbidden to internal host"))
    assert c1["category"] == ErrorCategory.SSRF_VIOLATION

    # Rate Limiting 429
    c2 = classify_error(status_code=429, response_body={"error": "Too Many Requests"})
    assert c2["category"] == ErrorCategory.RATE_LIMIT_429

    # Client Error 404
    c3 = classify_error(status_code=404, response_body={"detail": "Product not found"})
    assert c3["category"] == ErrorCategory.CLIENT_ERROR_4XX

    # Server Error 500
    c4 = classify_error(status_code=500, response_body={"error": "Internal Server Error"})
    assert c4["category"] == ErrorCategory.SERVER_ERROR_5XX

    # Transform SimpleEval Error
    c5 = classify_error(error_message="SimpleEval formula evaluation failed: name 'xyz' is not defined")
    assert c5["category"] == ErrorCategory.TRANSFORM_ERROR

    # Schema Mismatch
    c6 = classify_error(error_message="Schema validation error at 'price': 'abc' is not of type 'number'")
    assert c6["category"] == ErrorCategory.SCHEMA_MISMATCH


def test_validate_api_response_wrapper():
    """Verify high-level validate_api_response assesses both status and schema."""
    schema = {
        "type": "object",
        "required": ["id"],
        "properties": {"id": {"type": "integer"}},
    }

    # Success case
    res1 = validate_api_response(200, {"id": 10}, expected_schema=schema)
    assert res1["valid"] is True
    assert res1["category"] is None

    # Error status code
    res2 = validate_api_response(400, {"message": "Bad request"})
    assert res2["valid"] is False
    assert res2["category"] == ErrorCategory.CLIENT_ERROR_4XX

    # Schema mismatch
    res3 = validate_api_response(200, {"id": "invalid_string"}, expected_schema=schema)
    assert res3["valid"] is False
    assert res3["category"] == ErrorCategory.SCHEMA_MISMATCH
