"""
Stage 2 Data Mapping & Safe Transformations Test Suite
Covers canonical {{steps...}} and legacy syntax, array item predicate selection,
nested JSON lookup, calculate/extract/filter/rename/merge/format operations,
condition evaluation, unresolved template detection, and sandbox safety.
"""
import pytest
from app.services.transforms import (
    DataMappingError,
    resolve_templates,
    resolve_templates_strict,
    evaluate_transformation,
    evaluate_condition,
    prevalidate_expression,
)


def test_canonical_nested_json_and_array_selection():
    """Verify nested JSON dot-access and array item predicate lookup (not blindly [0])."""
    context = {
        "steps": {
            "step_1": {
                "output": [
                    {"id": 1, "name": "Wireless Mouse", "price": 250.0},
                    {"id": 5, "name": "Keyboard", "price": 1000.0},
                ]
            },
            "step_2": {
                "output": {
                    "id": 2,
                    "contact": {"email": "alice.morgan@example.com"},
                }
            },
        },
        "vars": {"cust": {"tier": "gold"}},
    }

    # Nested JSON
    assert resolve_templates_strict("{{steps.step_2.output.contact.email}}", context) == "alice.morgan@example.com"
    assert resolve_templates_strict("{{vars.cust.tier}}", context) == "gold"

    # Array predicate selects product id 5 (1000.0), NOT item 0 (250.0)
    assert resolve_templates_strict("{{steps.step_1.output[id=5].price}}", context) == 1000.0
    assert resolve_templates_strict("{{steps.step_1.output[id=5].name}}", context) == "Keyboard"
    assert resolve_templates_strict("{{steps.step_1.output[?(@.id==5)].name}}", context) == "Keyboard"


def test_unresolved_templates_raise_error_before_request():
    """Verify strict template resolution detects missing keys and unknown steps."""
    context = {"steps": {"step_1": {"output": {"id": 5, "price": 1000.0}}}}

    with pytest.raises(DataMappingError, match="Unresolved"):
        resolve_templates_strict("{{steps.step_1.output.nonexistent}}", context)

    with pytest.raises(DataMappingError, match="Unresolved"):
        resolve_templates_strict({"price": "{{steps.step_99.output.price}}"}, context)


def test_all_six_transformation_operations():
    """Verify calculate, extract, filter, rename, merge, and format operations without eval()."""
    context = {
        "steps": {
            "products": {
                "output": [
                    {"id": 1, "name": "Mouse", "price": 250.0, "stock": 10},
                    {"id": 5, "name": "Keyboard", "price": 1000.0, "stock": 45},
                    {"id": 9, "name": "Sold Out", "price": 1500.0, "stock": 0},
                ]
            },
            "customer": {
                "output": {"id": 2, "name": "Alice", "contact": {"email": "alice@example.com"}}
            },
        }
    }

    # 1. filter (select product ID 5 from array)
    filtered = evaluate_transformation(
        {"operation": "filter", "source": "{{steps.products.output}}", "field": "id", "op": "==", "value": 5, "single": True},
        context,
    )
    assert filtered["id"] == 5 and filtered["price"] == 1000.0

    # Filter empty match must fail cleanly rather than returning [0]
    with pytest.raises(DataMappingError):
        evaluate_transformation(
            {"operation": "filter", "source": "{{steps.products.output}}", "field": "id", "op": "==", "value": 999, "single": True},
            context,
        )

    # 2. extract
    extracted = evaluate_transformation(
        {
            "operation": "extract",
            "fields": {
                "email": "{{steps.customer.output.contact.email}}",
                "product_name": "{{steps.products.output[id=5].name}}",
                "price": "{{steps.products.output[id=5].price}}",
            },
        },
        context,
    )
    assert extracted == {"email": "alice@example.com", "product_name": "Keyboard", "price": 1000.0}

    # 3. calculate (10% discount)
    calc = evaluate_transformation(
        {"operation": "calculate", "formula": "price * 0.90", "inputs": {"price": "{{steps.products.output[id=5].price}}"}},
        context,
    )
    assert calc == 900.0

    # 4. rename
    renamed = evaluate_transformation(
        {"operation": "rename", "source": "{{steps.products.output[id=5]}}", "mapping": {"name": "title", "price": "unit_price"}},
        context,
    )
    assert renamed["title"] == "Keyboard" and renamed["unit_price"] == 1000.0
    assert "name" not in renamed

    # 5. merge
    merged = evaluate_transformation(
        {
            "operation": "merge",
            "sources": ["{{steps.products.output[id=5]}}"],
            "fields": {"customer_email": "{{steps.customer.output.contact.email}}"},
        },
        context,
    )
    assert merged["id"] == 5 and merged["customer_email"] == "alice@example.com"

    # 6. format
    formatted = evaluate_transformation(
        {
            "operation": "format",
            "template": "Product {{steps.products.output[id=5].name}} for {{steps.customer.output.contact.email}}",
        },
        context,
    )
    assert formatted == "Product Keyboard for alice@example.com"


def test_condition_evaluation_and_injection_blocking():
    """Verify safe condition evaluation and expression AST prevalidation."""
    context = {"steps": {"step_1": {"output": {"stock": 5, "price": 100.0}}}}

    assert evaluate_condition("{{steps.step_1.output.stock}} > 0", context) is True
    assert evaluate_condition({"left": "{{steps.step_1.output.stock}}", "op": "==", "right": 0}, context) is False

    # Prevalidation accepts valid math/condition syntax and blocks dunders
    prevalidate_expression("price * 0.90")
    prevalidate_expression("{{steps.step_1.output.stock}} > 0")
    with pytest.raises(ValueError):
        prevalidate_expression("__import__('os').system('ls')")

