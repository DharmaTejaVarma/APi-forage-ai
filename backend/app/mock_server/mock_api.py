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
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

mock_router = APIRouter(prefix="/mock/api/v1", tags=["Mock Store API"])

# Sample Mock Database State
INITIAL_PRODUCTS = {
    1: {"id": 1, "name": "Wireless Mouse", "category": "Electronics", "price": 250.0, "stock": 120},
    2: {"id": 2, "name": "USB-C Hub", "category": "Accessories", "price": 450.0, "stock": 80},
    3: {"id": 3, "name": "HD Webcam", "category": "Electronics", "price": 800.0, "stock": 25},
    4: {"id": 4, "name": "Ergonomic Desk Mat", "category": "Office", "price": 150.0, "stock": 200},
    5: {"id": 5, "name": "Mechanical Gaming Keyboard", "category": "Electronics", "price": 1000.0, "stock": 45},
}

products_db: Dict[int, Dict[str, Any]] = INITIAL_PRODUCTS.copy()
orders_db: Dict[str, Dict[str, Any]] = {}
order_counter = 5000


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


@mock_router.get("/openapi.json", summary="Get Mock API OpenAPI specification")
def get_mock_openapi():
    """Return the raw OpenAPI 3.0 specification file for this mock server."""
    spec_path = Path(__file__).resolve().parent.parent.parent / "samples" / "mock_openapi.json"
    if not spec_path.exists():
        raise HTTPException(status_code=500, detail="mock_openapi.json sample not found")
    with open(spec_path, "r", encoding="utf-8") as f:
        return json.load(f)


@mock_router.post("/reset", summary="Reset mock database to initial state")
def reset_mock_data():
    """Reset mock product catalog and clear orders."""
    global products_db, orders_db, order_counter
    products_db = INITIAL_PRODUCTS.copy()
    orders_db.clear()
    order_counter = 5000
    return {"message": "Mock store data reset successfully"}
