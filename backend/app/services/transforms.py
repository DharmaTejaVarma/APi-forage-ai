"""
APIForge AI Safe Transformations & Template Engine
Evaluates mathematical expressions and data mappings safely without Python eval() or exec().
Uses SimpleEval for sandboxed math and jsonpath-ng for robust JSON field extraction.
Non-Negotiable Rule: Never use Python eval() or exec() for transformations.
"""
import re
from typing import Any, Dict, List, Optional, Union
from simpleeval import SimpleEval
from jsonpath_ng import parse as parse_jsonpath

SAFE_FUNCTIONS = {
    "round": round,
    "int": int,
    "float": float,
    "str": str,
    "min": min,
    "max": max,
    "abs": abs,
    "len": len,
}

TEMPLATE_PATTERN = re.compile(r"\{\{([^}]+)\}\}")


def get_value_from_context(path_expr: str, context: Dict[str, Any]) -> Any:
    """
    Extract a value from the execution context dictionary using dot-notation or JSONPath.
    Examples:
      'step_1.output.id'
      'step_1.output.price'
      '$.step_1.output.data.items[0]'
    """
    path_expr = path_expr.strip()

    # 1. Handle JSONPath syntax starting with '$'
    if path_expr.startswith("$"):
        try:
            jp = parse_jsonpath(path_expr)
            matches = jp.find(context)
            if matches:
                return matches[0].value
        except Exception:
            pass

    # 2. Handle dot-notation: e.g. 'step_1.output.price'
    parts = path_expr.split(".")
    current = context

    for part in parts:
        if isinstance(current, dict):
            if part in current:
                current = current[part]
            else:
                return None
        elif isinstance(current, (list, tuple)) and part.isdigit():
            idx = int(part)
            if 0 <= idx < len(current):
                current = current[idx]
            else:
                return None
        else:
            return None

    return current


def resolve_templates(value: Any, context: Dict[str, Any]) -> Any:
    """
    Recursively resolve '{{step_id.output.field}}' placeholders within strings, dicts, and lists.
    Preserves native data types (int, float, dict, list) if the entire string is a single template token.
    """
    if isinstance(value, str):
        trimmed = value.strip()
        # Check if value is a single complete template token, e.g. "{{step_1.output.id}}"
        single_match = re.fullmatch(r"\{\{([^}]+)\}\}", trimmed)
        if single_match:
            expr = single_match.group(1).strip()
            resolved = get_value_from_context(expr, context)
            return resolved if resolved is not None else value

        # Otherwise perform substring replacement for embedded strings
        def replacer(match):
            expr = match.group(1).strip()
            res = get_value_from_context(expr, context)
            return str(res) if res is not None else match.group(0)

        return TEMPLATE_PATTERN.sub(replacer, value)

    elif isinstance(value, dict):
        return {k: resolve_templates(v, context) for k, v in value.items()}
    elif isinstance(value, list):
        return [resolve_templates(item, context) for item in value]

    return value


def evaluate_transformation(
    transformation: Dict[str, Any],
    context: Dict[str, Any],
) -> Any:
    """
    Safely execute a mathematical formula or mapping expression using SimpleEval.
    Supports input variable substitution and built-in safe functions.
    Never uses eval() or exec().
    """
    formula = transformation.get("formula")
    mapping = transformation.get("mapping")

    # 1. If formula is specified (e.g. 'price * (1 - discount_pct / 100)')
    if formula:
        raw_inputs = transformation.get("inputs", {})
        # Resolve any context references inside inputs
        resolved_names = resolve_templates(raw_inputs, context)

        evaluator = SimpleEval(functions=SAFE_FUNCTIONS, names=resolved_names)
        try:
            result = evaluator.eval(formula)
            # Round float values for clean currency/price math
            if isinstance(result, float):
                return round(result, 2)
            return result
        except Exception as e:
            raise ValueError(f"Safe transformation evaluation failed for formula '{formula}': {str(e)}") from e

    # 2. If direct mapping dictionary is specified
    if mapping and isinstance(mapping, dict):
        return resolve_templates(mapping, context)

    # 3. Fallback: resolve inputs directly
    inputs = transformation.get("inputs")
    if inputs:
        return resolve_templates(inputs, context)

    return None
