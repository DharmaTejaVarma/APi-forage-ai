"""
Phase 3 OpenAPI Parser and Mock Server Test Suite
Verifies OpenAPI 3.0 specification parsing, reference dereferencing ($ref),
schema extraction, and the mock e-commerce REST API.
"""
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.openapi_parser import parse_openapi_spec, OpenAPIParser

client = TestClient(app)

SAMPLE_PATH = Path(__file__).resolve().parent.parent / "samples" / "mock_openapi.json"


@pytest.fixture
def mock_spec_dict():
    with open(SAMPLE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================================
# OpenAPI Parser Tests
# ============================================================================

def test_parse_mock_openapi_spec(mock_spec_dict):
    """Verify that OpenAPIParser parses metadata and endpoints correctly."""
    parsed = parse_openapi_spec(mock_spec_dict)

    assert parsed.title == "APIForge Mock Store API"
    assert parsed.version == "1.0.0"
    assert parsed.base_url == "http://127.0.0.1:8000/mock/api/v1"
    assert len(parsed.endpoints) == 5

    # Check /products endpoint
    get_products = next(ep for ep in parsed.endpoints if ep.path == "/products" and ep.method == "GET")
    assert get_products.operation_id == "getProducts"
    assert get_products.response_schema is not None
    assert get_products.response_schema["type"] == "array"

    # Check /products/{id} endpoint
    get_product_id = next(ep for ep in parsed.endpoints if ep.path == "/products/{id}" and ep.method == "GET")
    assert len(get_product_id.parameters) == 1
    param = get_product_id.parameters[0]
    assert param["name"] == "id"
    assert param["in"] == "path"
    assert param["required"] is True

    # Check /discounts/calculate endpoint (requestBody resolution)
    calc_discount = next(ep for ep in parsed.endpoints if ep.path == "/discounts/calculate" and ep.method == "POST")
    assert calc_discount.request_body_schema is not None
    assert "price" in calc_discount.request_body_schema["properties"]
    assert "discount_percentage" in calc_discount.request_body_schema["properties"]

    # Check /orders endpoint
    create_order = next(ep for ep in parsed.endpoints if ep.path == "/orders" and ep.method == "POST")
    assert create_order.request_body_schema is not None
    assert "product_id" in create_order.request_body_schema["properties"]
    assert "final_price" in create_order.request_body_schema["properties"]


def test_dereference_local_components():
    """Verify that $ref pointers are deeply dereferenced into concrete schemas."""
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Ref Test", "version": "1.0"},
        "paths": {
            "/item": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Item"}
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                "schema": {"$ref": "#/components/schemas/Item"}
                            }
                        }
                    }
                }
            }
        }},
        "components": {
            "schemas": {
                "Item": {
                    "type": "object",
                    "properties": {
                        "sku": {"type": "string"},
                        "price": {"type": "number"}
                    }
                }
            }
        }
    }
    parsed = parse_openapi_spec(spec)
    ep = parsed.endpoints[0]
    assert ep.request_body_schema["type"] == "object"
    assert "sku" in ep.request_body_schema["properties"]
    assert ep.response_schema["type"] == "object"
    assert "price" in ep.response_schema["properties"]


# ============================================================================
# Mock API Server Endpoints Tests
# ============================================================================

def test_mock_api_get_products():
    """Verify GET /mock/api/v1/products returns product list."""
    response = client.get("/mock/api/v1/products")
    assert response.status_code == 200
    products = response.json()
    assert len(products) >= 5
    product_5 = next(p for p in products if p["id"] == 5)
    assert product_5["name"] == "Mechanical Gaming Keyboard"
    assert product_5["price"] == 1000.0


def test_mock_api_get_product_by_id():
    """Verify GET /mock/api/v1/products/5 retrieves specific product details."""
    response = client.get("/mock/api/v1/products/5")
    assert response.status_code == 200
    product = response.json()
    assert product["id"] == 5
    assert product["price"] == 1000.0

    # Non-existent product -> 404
    r_404 = client.get("/mock/api/v1/products/9999")
    assert r_404.status_code == 404


def test_mock_api_calculate_discount():
    """Verify POST /mock/api/v1/discounts/calculate applies 10% discount: 1000 -> 900."""
    payload = {"price": 1000.0, "discount_percentage": 10.0}
    response = client.post("/mock/api/v1/discounts/calculate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["original_price"] == 1000.0
    assert data["discount_percentage"] == 10.0
    assert data["discounted_price"] == 900.0
    assert data["saved_amount"] == 100.0


def test_mock_api_create_and_get_order():
    """Verify POST /mock/api/v1/orders and GET /mock/api/v1/orders/{id}."""
    order_payload = {
        "product_id": 5,
        "final_price": 900.0,
        "quantity": 1,
        "customer_email": "tester@apiforge.ai",
    }
    r_create = client.post("/mock/api/v1/orders", json=order_payload)
    assert r_create.status_code == 201
    order_data = r_create.json()
    assert order_data["product_id"] == 5
    assert order_data["final_price"] == 900.0
    assert order_data["status"] == "confirmed"
    order_id = order_data["order_id"]

    # Retrieve order by ID
    r_get = client.get(f"/mock/api/v1/orders/{order_id}")
    assert r_get.status_code == 200
    assert r_get.json()["order_id"] == order_id


def test_mock_api_openapi_json_endpoint():
    """Verify GET /mock/api/v1/openapi.json serves raw spec."""
    response = client.get("/mock/api/v1/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    assert spec["openapi"].startswith("3.")
    assert "/products" in spec["paths"]
