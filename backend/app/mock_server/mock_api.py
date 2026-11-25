"""
APIForge AI Mock Server API
Provides a fully functional e-commerce REST API for demonstration and DAG workflow execution.
Endpoints:
  GET  /api/v1/products
  GET  /api/v1/products/{id}
  POST /api/v1/discounts/calculate
  POST /api/v1/orders
  GET  /api/v1/orders/{id}
  GET  /api/v1/openapi.json
"""
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Header, status
from pydantic import BaseModel, Field

mock_router = APIRouter(prefix="/mock/api/v1", tags=["Mock Store API"])

VALID_MOCK_BEARER_TOKENS = {
    "apiforge-demo-bearer-token-2026",
    "valid-bearer-token-123",
    "sk_live_test_bearer_token",
}

# Sample Mock Database State
INITIAL_PRODUCTS = {
    1: {"id": 1, "name": "Wireless Mouse", "category": "Electronics", "price": 250.0, "stock": 120},
    2: {"id": 2, "name": "USB-C Hub", "category": "Accessories", "price": 450.0, "stock": 80},
    3: {"id": 3, "name": "HD Webcam", "category": "Electronics", "price": 800.0, "stock": 25},
    4: {"id": 4, "name": "Ergonomic Desk Mat", "category": "Office", "price": 150.0, "stock": 200},
    5: {"id": 5, "name": "Mechanical Gaming Keyboard", "category": "Electronics", "price": 1000.0, "stock": 45},
    9: {"id": 9, "name": "Limited Edition GPU", "category": "Hardware", "price": 1500.0, "stock": 0},
    10: {"id": 10, "name": "4K Studio Monitor", "category": "Electronics", "price": 500.0, "stock": 18},
}

INITIAL_CUSTOMERS = {
    1: {
        "id": 1,
        "name": "John Carter",
        "tier": "silver",
        "contact": {"email": "john.carter@example.com", "phone": "+1-555-0101"},
        "address": {"city": "Seattle", "country": "US"},
    },
    2: {
        "id": 2,
        "name": "Alice Morgan",
        "tier": "gold",
        "contact": {"email": "alice.morgan@example.com", "phone": "+1-555-0102"},
        "address": {"city": "Austin", "country": "US"},
    },
}

products_db: Dict[int, Dict[str, Any]] = INITIAL_PRODUCTS.copy()
customers_db: Dict[int, Dict[str, Any]] = INITIAL_CUSTOMERS.copy()
orders_db: Dict[str, Dict[str, Any]] = {}
emails_db: List[Dict[str, Any]] = []
order_counter = 5000
email_counter = 100


# ============================================================================
# Schemas for Mock Server
# ============================================================================

class ProductSchema(BaseModel):
    id: int
    name: str
    category: str
    price: float
    stock: int


class DiscountRequest(BaseModel):
    price: float = Field(..., ge=0, description="Original product price")
    discount_percentage: float = Field(..., ge=0, le=100, description="Percentage discount (0-100)")


class DiscountResponse(BaseModel):
    original_price: float
    discount_percentage: float
    discounted_price: float
    saved_amount: float


class OrderCreateRequest(BaseModel):
    product_id: int
    final_price: float
    quantity: int = 1
    customer_email: Optional[str] = "demo@apiforge.ai"


class OrderResponse(BaseModel):
    order_id: str
    product_id: int
    final_price: float
    quantity: int
    status: str
    created_at: str


# ============================================================================
# Mock Endpoints
# ============================================================================

@mock_router.get("/products", response_model=List[ProductSchema], summary="List all products")
def list_products():
    """Return all products in mock store catalog."""
    return list(products_db.values())


@mock_router.get("/products/{id}", response_model=ProductSchema, summary="Get product by ID")
@mock_router.get("/products/item/{id}", response_model=ProductSchema, include_in_schema=False)
def get_product(id: int):
    """Retrieve details for a single product by numeric ID."""
    product = products_db.get(id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {id} not found"
        )
    return product


@mock_router.post("/discounts/calculate", response_model=DiscountResponse, summary="Calculate discounted price")
def calculate_discount(payload: DiscountRequest):
    """Compute discounted price and total savings."""
    discount_fraction = payload.discount_percentage / 100.0
    saved = round(payload.price * discount_fraction, 2)
    discounted = round(payload.price - saved, 2)

    return DiscountResponse(
        original_price=payload.price,
        discount_percentage=payload.discount_percentage,
        discounted_price=discounted,
        saved_amount=saved,
    )


@mock_router.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED, summary="Create order")
def create_order(order_in: OrderCreateRequest):
    """Submit purchase order for a product."""
    global order_counter
    product = products_db.get(order_in.product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product {order_in.product_id} does not exist"
        )

    order_counter += 1
    order_id = f"ORD-{order_counter}"
    order_record = {
        "order_id": order_id,
        "product_id": order_in.product_id,
        "final_price": order_in.final_price,
        "quantity": order_in.quantity,
        "status": "confirmed",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    orders_db[order_id] = order_record
    return order_record


@mock_router.get("/orders/{order_id}", response_model=OrderResponse, summary="Get order by ID")
def get_order(order_id: str):
    """Retrieve status and order information by order ID."""
    order = orders_db.get(order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found"
        )
    return order


class EmailNotificationRequest(BaseModel):
    to: Optional[str] = None
    recipient: Optional[str] = None
    subject: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)


class EmailNotificationResponse(BaseModel):
    message_id: str
    recipient: str
    subject: str
    body: str
    status: str
    sent_at: str


@mock_router.get("/customers/{id}", summary="Get customer details by ID (with nested contact)")
def get_customer(id: int):
    """Retrieve customer record including nested contact email and address."""
    customer = customers_db.get(id)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Customer with ID {id} not found")
    return customer


@mock_router.post(
    "/notifications/email",
    response_model=EmailNotificationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send email notification",
)
def send_email_notification(payload: EmailNotificationRequest):
    """Simulate sending a notification email and record the message for verification."""
    global email_counter
    target_recipient = payload.to or payload.recipient
    if not target_recipient or "@" not in target_recipient:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A valid recipient email address ('to' or 'recipient') is required",
        )
    email_counter += 1
    record = {
        "message_id": f"MSG-{email_counter}",
        "recipient": target_recipient,
        "subject": payload.subject,
        "body": payload.body,
        "status": "sent",
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }
    emails_db.append(record)
    return record


@mock_router.get("/notifications/email", summary="List sent notification emails")
def list_sent_emails():
    """Return recorded notification emails sent through the mock API."""
    return emails_db


@mock_router.get("/secure/profile", summary="Protected profile endpoint requiring Bearer authentication")
def get_secure_profile(authorization: Optional[str] = Header(None)):
    """Validate Authorization Bearer token; return 401 when missing/invalid, 200 when authorized."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Bearer authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    if token not in VALID_MOCK_BEARER_TOKENS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {
        "service": "apiforge-secure-vault",
        "account_id": "ENT-2026",
        "clearance": "confidential",
        "authenticated": True,
    }


@mock_router.get("/openapi.json", summary="Get Mock API OpenAPI specification")
def get_mock_openapi():
    """Return the raw OpenAPI 3.0 specification file for this mock server."""
    spec_path = Path(__file__).resolve().parent.parent.parent / "samples" / "mock_openapi.json"
    if not spec_path.exists():
        raise HTTPException(status_code=500, detail="mock_openapi.json sample not found")
    with open(spec_path, "r", encoding="utf-8") as f:
        return json.load(f)


@mock_router.get("/extended-openapi.json", summary="Get Extended Mock API OpenAPI specification")
def get_extended_mock_openapi():
    """Return the extended OpenAPI 3.0 specification including Customers, Email, and Secure endpoints."""
    spec_path = Path(__file__).resolve().parent.parent.parent / "samples" / "extended_mock_openapi.json"
    if not spec_path.exists():
        raise HTTPException(status_code=500, detail="extended_mock_openapi.json sample not found")
    with open(spec_path, "r", encoding="utf-8") as f:
        return json.load(f)


@mock_router.post("/reset", summary="Reset mock database to initial state")
def reset_mock_data():
    """Reset mock product catalog, emails, and clear orders."""
    global products_db, customers_db, orders_db, emails_db, order_counter, email_counter
    products_db = INITIAL_PRODUCTS.copy()
    customers_db = INITIAL_CUSTOMERS.copy()
    orders_db.clear()
    emails_db.clear()
    order_counter = 5000
    email_counter = 100
    return {"message": "Mock store data reset successfully"}
