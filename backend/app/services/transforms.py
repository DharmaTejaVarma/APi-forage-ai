"""
APIForge AI Safe Transformations & Centralized Data-Mapping Engine
Evaluates mathematical expressions, conditional guards, and structured data operations
safely without Python eval() or exec().
Uses SimpleEval for sandboxed evaluation and jsonpath-ng + typed selectors for
objects, nested JSON, and array filtering/selection.

Canonical reference syntax:
  {{steps.step_1.output.name}}
  {{steps.step_1.output.customer.email}}
  {{steps.step_1.output[id=5].price}}
  {{vars.custom_var.field}}
Also supports legacy {{step_1.output.field}} for backward compatibility.
"""
import re
import operator
from typing import Any, Dict, List, Optional, Tuple
from simpleeval import SimpleEval
from jsonpath_ng import parse as parse_jsonpath

SAFE_FUNCTIONS = {
    "round": round,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "min": min,
    "max": max,
    "abs": abs,
    "len": len,
    "sum": sum,
}

TEMPLATE_PATTERN = re.compile(r"\{\{([^}]+)\}\}")
BRACKET_SELECTOR_RE = re.compile(r"^([^\[]+)\[([^\]]+)\]$")
PREDICATE_EQ_RE = re.compile(r"^(?:\?\s*\(?\s*@\.)?([a-zA-Z_][a-zA-Z0-9_]*)\s*={1,2}\s*(.+?)\)?$")

_MISSING = object()

_COMPARATORS = {
    "==": operator.eq,
    "eq": operator.eq,
    "!=": operator.ne,
    "ne": operator.ne,
    ">": operator.gt,
    "gt": operator.gt,
    ">=": operator.ge,
    "ge": operator.ge,
    "<": operator.lt,
    "lt": operator.lt,
    "<=": operator.le,
    "le": operator.le,
    "in": lambda a, b: a in b if b is not None else False,
    "contains": lambda a, b: b in a if a is not None else False,
}


class DataMappingError(ValueError):
    """Raised when template references cannot be resolved or yield invalid data."""
    pass


def _parse_literal(raw: str) -> Any:
    raw = raw.strip()
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    if raw.lower() == "null" or raw.lower() == "none":
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def _select_from_array_predicate(arr: List[Any], predicate: str) -> Any:
    """Select an item from a list using numeric index or equality predicate e.g. 'id=5'."""
    pred = predicate.strip()
    if pred.isdigit() or (pred.startswith("-") and pred[1:].isdigit()):
        idx = int(pred)
        return arr[idx] if -len(arr) <= idx < len(arr) else _MISSING

    eq_match = PREDICATE_EQ_RE.match(pred)
    if eq_match:
        field_name = eq_match.group(1)
        expected_val = _parse_literal(eq_match.group(2))
        for item in arr:
            if isinstance(item, dict) and field_name in item:
                actual = item[field_name]
                if actual == expected_val or str(actual) == str(expected_val):
                    return item
        return _MISSING

    return _MISSING


def _traverse_parts(parts: List[str], root: Any) -> Any:
    """Traverse dot/bracket segments cleanly, returning _MISSING if any segment fails."""
    current = root
    for part in parts:
        # Check bracketed segment like items[0] or output[id=5] or standalone [id=5]
        if part.startswith("[") and part.endswith("]"):
            if not isinstance(current, list):
                return _MISSING
            current = _select_from_array_predicate(current, part[1:-1])
            if current is _MISSING:
                return _MISSING
            continue

        # Handle chained brackets e.g. matrix[0][1] or products[id=5]
        m = BRACKET_SELECTOR_RE.match(part)
        if m:
            head = m.group(1)
            bracket_inner = part[len(head):]
            if not isinstance(current, dict) or head not in current:
                return _MISSING
            current = current[head]
            for bracket_expr in re.findall(r"\[([^\]]+)\]", bracket_inner):
                if not isinstance(current, list):
                    return _MISSING
                current = _select_from_array_predicate(current, bracket_expr)
                if current is _MISSING:
                    return _MISSING
            continue

        if isinstance(current, dict):
            if part in current:
                current = current[part]
            else:
                return _MISSING
        elif isinstance(current, (list, tuple)) and part.isdigit():
            idx = int(part)
            current = current[idx] if 0 <= idx < len(current) else _MISSING
            if current is _MISSING:
                return _MISSING
        else:
            return _MISSING

    return current


def _split_path_parts(path_expr: str) -> List[str]:
    """Split dot path while preserving bracket expressions like [?(@.id==5)]."""
    parts: List[str] = []
    buf: List[str] = []
    bracket_depth = 0
    for ch in path_expr:
        if ch == "[":
            bracket_depth += 1
            buf.append(ch)
        elif ch == "]":
            bracket_depth = max(0, bracket_depth - 1)
            buf.append(ch)
        elif ch == "." and bracket_depth == 0:
            if buf:
                parts.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def resolve_value_from_context(path_expr: str, context: Dict[str, Any]) -> Tuple[bool, Any]:
    """
    Resolve a dotted/JSONPath reference against execution context.
    Returns (found: bool, value: Any).
    Supports:
      - '{{steps.step_1.output.name}}' / 'steps.step_1.output[id=5].price'
      - '{{vars.my_var.email}}'
      - Legacy '{{step_1.output.price}}'
      - JSONPath starting with '$'
    """
    expr = path_expr.strip()
    if not expr:
        return False, None

    # 1. JSONPath syntax starting with '$'
    if expr.startswith("$"):
        try:
            jp = parse_jsonpath(expr)
            matches = jp.find(context)
            if matches:
                return True, matches[0].value if len(matches) == 1 else [m.value for m in matches]
            # Try normalizing $.steps. -> $. if context has step_id at root
            if expr.startswith("$.steps.") and "steps" not in context:
                alt_jp = parse_jsonpath("$." + expr[len("$.steps."):])
                alt_matches = alt_jp.find(context)
                if alt_matches:
                    return True, alt_matches[0].value
        except Exception:
            pass
        return False, None

    parts = _split_path_parts(expr)
    if not parts:
        return False, None

    # 2. Direct traversal against context
    res = _traverse_parts(parts, context)
    if res is not _MISSING:
        return True, res

    # 3. Handle canonical 'steps.<id>...' when context is keyed cleanly or legacy root-keyed
    if parts[0] == "steps" and "steps" not in context and len(parts) > 1:
        res = _traverse_parts(parts[1:], context)
        if res is not _MISSING:
            return True, res

    if parts[0] != "steps" and "steps" in context and isinstance(context["steps"], dict):
        res = _traverse_parts(["steps"] + parts, context)
        if res is not _MISSING:
            return True, res

    # 4. Handle output_var shorthand if present under vars
    if parts[0] != "vars" and "vars" in context and isinstance(context["vars"], dict):
        res = _traverse_parts(["vars"] + parts, context)
        if res is not _MISSING:
            return True, res

    return False, None


def get_value_from_context(path_expr: str, context: Dict[str, Any]) -> Any:
    """Extract value from execution context, returning None if not found."""
    found, val = resolve_value_from_context(path_expr, context)
    return val if found else None


def find_unresolved_templates(value: Any) -> List[str]:
    """Recursively collect any raw '{{...}}' template strings remaining in a value."""
    unresolved: List[str] = []
    if isinstance(value, str):
        unresolved.extend(m.group(0) for m in TEMPLATE_PATTERN.finditer(value))
    elif isinstance(value, dict):
        for v in value.values():
            unresolved.extend(find_unresolved_templates(v))
    elif isinstance(value, list):
        for item in value:
            unresolved.extend(find_unresolved_templates(item))
    return unresolved


def resolve_templates(
    value: Any,
    context: Dict[str, Any],
    strict: bool = False,
    missing_refs: Optional[List[str]] = None,
) -> Any:
    """
    Recursively resolve '{{steps.step_id.output.field}}' (and legacy '{{step_id.output.field}}')
    placeholders within strings, dicts, and lists.
    Preserves native types when an entire string is a single template token.
    When strict=True, raises DataMappingError if any template token cannot be resolved.
    """
    collected = missing_refs if missing_refs is not None else []

    if isinstance(value, str):
        trimmed = value.strip()
        single_match = re.fullmatch(r"\{\{([^}]+)\}\}", trimmed)
        if single_match:
            expr = single_match.group(1).strip()
            found, resolved = resolve_value_from_context(expr, context)
            if not found:
                collected.append(value)
                if strict and missing_refs is None:
                    raise DataMappingError(f"Unresolved template reference: {value}")
                return value
            return resolved

        def replacer(match: re.Match) -> str:
            expr = match.group(1).strip()
            found, res = resolve_value_from_context(expr, context)
            if not found or res is None:
                collected.append(match.group(0))
                return match.group(0)
            return str(res)

        out = TEMPLATE_PATTERN.sub(replacer, value)
        if strict and missing_refs is None and collected:
            raise DataMappingError(f"Unresolved template reference(s): {', '.join(collected)}")
        return out

    elif isinstance(value, dict):
        out_dict = {k: resolve_templates(v, context, strict=False, missing_refs=collected) for k, v in value.items()}
        if strict and missing_refs is None and collected:
            raise DataMappingError(f"Unresolved template reference(s): {', '.join(collected)}")
        return out_dict

    elif isinstance(value, list):
        out_list = [resolve_templates(item, context, strict=False, missing_refs=collected) for item in value]
        if strict and missing_refs is None and collected:
            raise DataMappingError(f"Unresolved template reference(s): {', '.join(collected)}")
        return out_list

    return value


def resolve_templates_strict(value: Any, context: Dict[str, Any]) -> Any:
    """Resolve templates strictly and verify zero unresolved placeholders remain."""
    missing: List[str] = []
    resolved = resolve_templates(value, context, strict=False, missing_refs=missing)
    if missing:
        raise DataMappingError(f"Unresolved data reference(s): {', '.join(dict.fromkeys(missing))}")
    leftover = find_unresolved_templates(resolved)
    if leftover:
        raise DataMappingError(f"Unresolved data reference(s): {', '.join(dict.fromkeys(leftover))}")
    return resolved


def _safe_simple_eval(expr: str, names: Dict[str, Any]) -> Any:
    """Evaluate an expression cleanly via SimpleEval with strict security guards."""
    if not isinstance(expr, str) or not expr.strip():
        raise ValueError("Expression must be a non-empty string")
    if "__" in expr:
        raise ValueError("Forbidden dunder attribute access in expression")

    # Replace inline {{...}} tokens with bound parameter variables rather than string interpolation
    bound_names = dict(names)
    idx = 0

    def bind_template(match: re.Match) -> str:
        nonlocal idx
        path = match.group(1).strip()
        found, val = resolve_value_from_context(path, names)
        if not found:
            raise DataMappingError(f"Unresolved template reference in expression: {match.group(0)}")
        var_name = f"__tpl_{idx}"
        # Keep simple identifier without dunder by avoiding double underscore!
        var_name = f"tpl_var_{idx}"
        idx += 1
        bound_names[var_name] = val
        return var_name

    rewritten = TEMPLATE_PATTERN.sub(bind_template, expr)
    if "__" in rewritten:
        raise ValueError("Forbidden dunder identifier in expression")

    evaluator = SimpleEval(functions=SAFE_FUNCTIONS, names=bound_names)
    return evaluator.eval(rewritten)


def _eval_calculate(transformation: Dict[str, Any], context: Dict[str, Any]) -> Any:
    formula = transformation.get("formula") or transformation.get("expression")
    raw_inputs = transformation.get("inputs") or {}
    resolved_inputs = resolve_templates_strict(raw_inputs, context)

    merged_names: Dict[str, Any] = {}
    if isinstance(context, dict):
        merged_names.update(context)
    if isinstance(resolved_inputs, dict):
        merged_names.update(resolved_inputs)

    try:
        result = _safe_simple_eval(str(formula), merged_names)
        if isinstance(result, float):
            return round(result, 2)
        return result
    except DataMappingError:
        raise
    except Exception as e:
        raise ValueError(f"Safe transformation evaluation failed for formula '{formula}': {str(e)}") from e


def _eval_filter(transformation: Dict[str, Any], context: Dict[str, Any]) -> Any:
    """Filter an array of dicts by field comparison or predicate expression."""
    raw_source = transformation.get("source") or transformation.get("items") or transformation.get("input")
    if raw_source is None and isinstance(transformation.get("inputs"), dict):
        raw_source = transformation["inputs"].get("items") or transformation["inputs"].get("source")

    items = resolve_templates_strict(raw_source, context)
    if not isinstance(items, list):
        raise DataMappingError(f"Filter transformation expected array input, got {type(items).__name__}")

    where = transformation.get("where")
    field = transformation.get("field")
    op_name = transformation.get("op", "==")
    target_val = transformation.get("value")
    if isinstance(target_val, str) and "{{" in target_val:
        target_val = resolve_templates_strict(target_val, context)
    predicate_expr = transformation.get("predicate") or transformation.get("condition")
    single = bool(transformation.get("single", False) or transformation.get("select") == "first")

    matched: List[Any] = []
    for item in items:
        keep = True
        if where and isinstance(where, dict):
            if not isinstance(item, dict):
                keep = False
            else:
                keep = all(
                    k in item and (item[k] == v or str(item[k]) == str(v))
                    for k, v in where.items()
                )
        elif field:
            if not isinstance(item, dict) or field not in item:
                keep = False
            else:
                comp = _COMPARATORS.get(str(op_name), operator.eq)
                try:
                    keep = bool(comp(item[field], target_val))
                except Exception:
                    keep = str(item[field]) == str(target_val)
        elif predicate_expr:
            eval_names = dict(context)
            eval_names["item"] = item
            if isinstance(item, dict):
                eval_names.update(item)
            keep = bool(_safe_simple_eval(predicate_expr, eval_names))

        if keep:
            matched.append(item)

    if single:
        if not matched:
            raise DataMappingError("Filter selection matched zero items in array response")
        return matched[0]
    return matched


def _eval_extract(transformation: Dict[str, Any], context: Dict[str, Any]) -> Any:
    """Extract specific fields or nested objects cleanly (with optional array item selection)."""
    if transformation.get("where") or transformation.get("field") and (transformation.get("source") or transformation.get("items")):
        # Support array selection followed by field extraction
        item_or_items = _eval_filter({**transformation, "single": transformation.get("single", True)}, context)
        extract_fields = transformation.get("fields") or transformation.get("mapping")
        if isinstance(extract_fields, dict) and isinstance(item_or_items, dict):
            local_ctx = {**context, "item": item_or_items}
            return resolve_templates_strict(extract_fields, local_ctx)
        if isinstance(extract_fields, list) and isinstance(item_or_items, dict):
            return {f: item_or_items.get(f) for f in extract_fields}
        return item_or_items

    fields = transformation.get("fields") or transformation.get("mapping") or transformation.get("inputs")
    if isinstance(fields, dict):
        return resolve_templates_strict(fields, context)
    if isinstance(fields, str):
        return resolve_templates_strict(fields, context)
    if "source" in transformation:
        return resolve_templates_strict(transformation["source"], context)
    raise DataMappingError("Extract transformation missing 'fields', 'mapping', or 'source'")


def _eval_rename(transformation: Dict[str, Any], context: Dict[str, Any]) -> Any:
    """Rename keys on an object or list of objects according to mapping {old: new} or {new: old}."""
    raw_source = transformation.get("source") or transformation.get("input") or transformation.get("inputs")
    resolved_src = resolve_templates_strict(raw_source, context)
    key_map = transformation.get("mapping") or transformation.get("fields") or {}
    if not isinstance(key_map, dict):
        raise DataMappingError("Rename transformation requires dict 'mapping'")

    def rename_one(obj: Any) -> Any:
        if not isinstance(obj, dict):
            return obj
        # Preserve unmapped keys unless strict_keys set, applying old -> new
        out = dict(obj)
        for old_k, new_k in key_map.items():
            if old_k in out:
                val = out.pop(old_k)
                out[new_k] = val
        return out

    if isinstance(resolved_src, list):
        return [rename_one(item) for item in resolved_src]
    return rename_one(resolved_src)


def _eval_merge(transformation: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Merge multiple resolved objects/step outputs into a unified dictionary."""
    sources = transformation.get("sources") or []
    merged: Dict[str, Any] = {}
    for src in sources:
        resolved = resolve_templates_strict(src, context)
        if isinstance(resolved, dict):
            merged.update(resolved)

    extra_fields = transformation.get("fields") or transformation.get("inputs")
    if isinstance(extra_fields, dict):
        resolved_extra = resolve_templates_strict(extra_fields, context)
        if isinstance(resolved_extra, dict):
            merged.update(resolved_extra)

    return merged


def _eval_format(transformation: Dict[str, Any], context: Dict[str, Any]) -> Any:
    """Safely render formatted string templates or structured payloads."""
    template = transformation.get("template") or transformation.get("payload") or transformation.get("inputs")
    return resolve_templates_strict(template, context)


def evaluate_transformation(
    transformation: Dict[str, Any],
    context: Dict[str, Any],
) -> Any:
    """
    Safely execute a transformation step without Python eval() or exec().
    Supports operations: calculate, extract, filter, rename, merge, format,
    as well as shorthand formula/mapping specifications.
    """
    if not isinstance(transformation, dict) or not transformation:
        return None

    op = str(transformation.get("operation") or "").strip().lower()

    if op == "calculate" or (not op and ("formula" in transformation or "expression" in transformation)):
        return _eval_calculate(transformation, context)
    if op == "filter":
        return _eval_filter(transformation, context)
    if op == "extract":
        return _eval_extract(transformation, context)
    if op == "rename":
        return _eval_rename(transformation, context)
    if op == "merge":
        return _eval_merge(transformation, context)
    if op == "format":
        return _eval_format(transformation, context)

    # Backward-compatible dict mapping / input resolution
    mapping = transformation.get("mapping")
    if mapping and isinstance(mapping, dict):
        return resolve_templates_strict(mapping, context)

    inputs = transformation.get("inputs")
    if inputs is not None:
        return resolve_templates_strict(inputs, context)

    return None


def evaluate_condition(
    condition: Any,
    context: Dict[str, Any],
) -> bool:
    """
    Safely evaluate a conditional step/branch predicate via SimpleEval.
    Supports:
      - Bool literal
      - Dict predicate: {"left": "{{steps.step_1.output.stock}}", "op": ">", "right": 0}
      - String expression: "{{steps.step_1.output.stock}} > 0"
    """
    if isinstance(condition, bool):
        return condition
    if isinstance(condition, dict):
        if "expression" in condition or "formula" in condition:
            expr = condition.get("expression") or condition.get("formula")
            raw_inputs = condition.get("inputs") or {}
            resolved_inputs = resolve_templates_strict(raw_inputs, context)
            names = {**context, **(resolved_inputs if isinstance(resolved_inputs, dict) else {})}
            return bool(_safe_simple_eval(str(expr), names))

        left = resolve_templates_strict(condition.get("left"), context)
        right = resolve_templates_strict(condition.get("right"), context)
        op_name = str(condition.get("op", "=="))
        comp = _COMPARATORS.get(op_name)
        if not comp:
            raise ValueError(f"Unsupported condition operator: {op_name}")
        return bool(comp(left, right))

    if isinstance(condition, str) and condition.strip():
        return bool(_safe_simple_eval(condition.strip(), context))

    raise ValueError(f"Invalid condition specification: {condition}")


def prevalidate_expression(expr: str) -> None:
    """
    Statically check SimpleEval expression syntax without executing arbitrary inputs.
    Raises ValueError if syntax is invalid or contains forbidden dunders.
    """
    if not isinstance(expr, str) or not expr.strip():
        raise ValueError("Formula/condition expression cannot be empty")
    if "__" in expr:
        raise ValueError("Forbidden dunder reference in expression")

    # Replace template tokens cleanly with safe dummy variable names and parse AST via SimpleEval
    sanitized = TEMPLATE_PATTERN.sub("dummy_var", expr)
    try:
        evaluator = SimpleEval(functions=SAFE_FUNCTIONS)
        evaluator.parse(sanitized)
    except Exception as e:
        raise ValueError(f"Invalid transformation/condition syntax '{expr}': {str(e)}") from e
