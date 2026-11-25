"""
APIForge AI OpenAPI Specification Parser
Parses OpenAPI 3.0 / 3.1 and Swagger 2.0 specifications (JSON or YAML).
Resolves local schema references ($ref), extracts endpoint metadata,
security schemes, path/query parameters, request body schemas, and response definitions.
"""
import json
from copy import deepcopy
from typing import Dict, Any, List, Optional, Union
from pydantic import BaseModel, Field

try:
    import yaml
except ImportError:
    yaml = None


class ParsedEndpoint(BaseModel):
    path: str
    method: str
    summary: Optional[str] = None
    description: Optional[str] = None
    operation_id: Optional[str] = None
    parameters: List[Dict[str, Any]] = Field(default_factory=list)
    request_body_schema: Optional[Dict[str, Any]] = None
    response_schema: Optional[Dict[str, Any]] = None
    security: Optional[List[Dict[str, Any]]] = None


class ParsedOpenAPISpec(BaseModel):
    title: str
    version: str
    description: Optional[str] = None
    base_url: Optional[str] = None
    security_schemes: Dict[str, Any] = Field(default_factory=dict)
    endpoints: List[ParsedEndpoint] = Field(default_factory=list)


class OpenAPIParser:
    """Parser that ingests OpenAPI/Swagger specifications and resolves references."""

    SUPPORTED_METHODS = ["get", "post", "put", "delete", "patch", "options", "head"]

    def __init__(self, raw_spec: Union[Dict[str, Any], str]):
        if isinstance(raw_spec, str):
            try:
                self.raw_spec = json.loads(raw_spec)
            except json.JSONDecodeError as json_err:
                if yaml is not None:
                    try:
                        loaded = yaml.safe_load(raw_spec)
                        if isinstance(loaded, dict):
                            self.raw_spec = loaded
                        else:
                            raise ValueError("OpenAPI YAML specification did not parse to an object")
                    except Exception as yaml_err:
                        raise ValueError(
                            f"Invalid JSON/YAML OpenAPI spec: {json_err}; {yaml_err}"
                        ) from yaml_err
                else:
                    raise ValueError(f"Invalid JSON string provided for OpenAPI spec: {json_err}") from json_err
        elif isinstance(raw_spec, dict):
            self.raw_spec = deepcopy(raw_spec)
        else:
            raise TypeError("Specification must be a JSON/YAML string or dict")

        if "paths" not in self.raw_spec or not isinstance(self.raw_spec.get("paths"), dict):
            raise ValueError("Invalid OpenAPI specification: missing required 'paths' object")

        self.resolved_spec = deepcopy(self.raw_spec)
        self._resolve_all_references()

    def _get_ref_target(self, ref: str) -> Optional[Any]:
        """Resolve a local JSON Pointer ref (e.g. #/components/schemas/Product)."""
        if not ref.startswith("#/"):
            return None
        parts = ref.lstrip("#/").split("/")
        current = self.raw_spec
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return deepcopy(current)

    def _resolve_schema_refs(self, obj: Any, visited: Optional[set] = None) -> Any:
        """Recursively resolve $ref pointers within dictionary structures."""
        if visited is None:
            visited = set()

        if isinstance(obj, dict):
            if "$ref" in obj:
                ref = obj["$ref"]
                if ref in visited:
                    # Circular reference guard: return stub
                    return {"type": "object", "title": ref.split("/")[-1]}
                target = self._get_ref_target(ref)
                if target is not None:
                    visited.add(ref)
                    resolved = self._resolve_schema_refs(target, visited)
                    visited.remove(ref)
                    # Merge any sibling keys (like description or example)
                    for k, v in obj.items():
                        if k != "$ref" and isinstance(resolved, dict):
                            resolved[k] = v
                    return resolved
                return obj

            return {k: self._resolve_schema_refs(v, visited) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._resolve_schema_refs(item, visited) for item in obj]
        return obj

    def _resolve_all_references(self):
        """Pre-resolve references throughout paths and schemas."""
        if "paths" in self.resolved_spec:
            self.resolved_spec["paths"] = self._resolve_schema_refs(self.resolved_spec["paths"])

    def parse(self) -> ParsedOpenAPISpec:
        """Extract all endpoints, parameters, request body and response schemas."""
        info = self.resolved_spec.get("info", {})
        title = info.get("title", "Imported API")
        version = info.get("version", "1.0.0")
        description = info.get("description", "")

        # Extract security schemes (OpenAPI 3.x & Swagger 2.0)
        components = self.resolved_spec.get("components", {})
        security_schemes = components.get("securitySchemes") or self.resolved_spec.get("securityDefinitions") or {}
        global_security = self.resolved_spec.get("security")

        # Extract base_url from servers (OpenAPI 3.x) or host+basePath (Swagger 2.0)
        base_url = None
        servers = self.resolved_spec.get("servers", [])
        if servers and isinstance(servers, list) and len(servers) > 0:
            base_url = servers[0].get("url")
        elif "host" in self.resolved_spec:
            schemes = self.resolved_spec.get("schemes", ["http"])
            scheme = schemes[0] if schemes else "http"
            host = self.resolved_spec.get("host", "localhost")
            base_path = self.resolved_spec.get("basePath", "")
            base_url = f"{scheme}://{host}{base_path}".rstrip("/")

        parsed_endpoints: List[ParsedEndpoint] = []
        paths = self.resolved_spec.get("paths", {})

        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue

            path_params = path_item.get("parameters", [])

            for method_key in self.SUPPORTED_METHODS:
                if method_key not in path_item:
                    continue

                op = path_item[method_key]
                if not isinstance(op, dict):
                    continue

                method = method_key.upper()
                summary = op.get("summary")
                op_desc = op.get("description")
                operation_id = op.get("operationId") or f"{method.lower()}_{path.replace('/', '_').replace('{', '').replace('}', '')}"
                op_security = op.get("security", global_security)

                # Merge path-level and operation-level parameters
                combined_params: List[Dict[str, Any]] = []
                seen_params = set()

                for param in (path_params + op.get("parameters", [])):
                    if not isinstance(param, dict):
                        continue
                    # Check for Swagger 2.0 body param
                    if param.get("in") == "body":
                        continue
                    p_key = (param.get("name"), param.get("in"))
                    if p_key not in seen_params:
                        seen_params.add(p_key)
                        combined_params.append({
                            "name": param.get("name", ""),
                            "in": param.get("in", "query"),
                            "required": param.get("required", False),
                            "description": param.get("description", ""),
                            "schema": param.get("schema", {"type": param.get("type", "string")}),
                        })

                # Extract Request Body Schema
                request_body_schema = None
                if "requestBody" in op:
                    content = op["requestBody"].get("content", {})
                    if "application/json" in content:
                        request_body_schema = content["application/json"].get("schema")
                    elif content:
                        first_content = next(iter(content.values()))
                        request_body_schema = first_content.get("schema")
                else:
                    # Swagger 2.0 body param fallback
                    for param in op.get("parameters", []):
                        if isinstance(param, dict) and param.get("in") == "body":
                            request_body_schema = param.get("schema")
                            break

                # Extract Response Schema (prefer 200, 201, 204, or default)
                response_schema = None
                responses = op.get("responses", {})
                target_resp = None
                for status_code in ["200", "201", "204", "default"]:
                    if status_code in responses:
                        target_resp = responses[status_code]
                        break
                if target_resp is None and responses:
                    target_resp = next(iter(responses.values()))

                if isinstance(target_resp, dict):
                    if "content" in target_resp:
                        content = target_resp.get("content", {})
                        if "application/json" in content:
                            response_schema = content["application/json"].get("schema")
                        elif content:
                            first_content = next(iter(content.values()))
                            response_schema = first_content.get("schema")
                    elif "schema" in target_resp:
                        response_schema = target_resp.get("schema")

                # Synthesize helpful description/summary when sparse
                if not summary:
                    summary = f"{method} {path}".replace("{", "").replace("}", "")
                if not op_desc:
                    desc_parts = [f"Executes {method} request on {path}."]
                    if combined_params:
                        desc_parts.append(f"Parameters: {', '.join(p['name'] for p in combined_params)}.")
                    if request_body_schema and isinstance(request_body_schema, dict):
                        props = request_body_schema.get("properties", {})
                        if props:
                            desc_parts.append(f"Accepts JSON fields: {', '.join(props.keys())}.")
                    op_desc = " ".join(desc_parts)

                # Attach resolved security scheme definitions if declared
                resolved_security = None
                if op_security and isinstance(op_security, list):
                    resolved_security = []
                    for sec_req in op_security:
                        if isinstance(sec_req, dict):
                            for scheme_name, scopes in sec_req.items():
                                scheme_def = security_schemes.get(scheme_name, {})
                                resolved_security.append({
                                    "scheme": scheme_name,
                                    "type": scheme_def.get("type", "http"),
                                    "in": scheme_def.get("in", "header"),
                                    "name": scheme_def.get("name", "Authorization"),
                                    "scopes": scopes,
                                })

                parsed_endpoints.append(ParsedEndpoint(
                    path=path,
                    method=method,
                    summary=summary,
                    description=op_desc,
                    operation_id=operation_id,
                    parameters=combined_params,
                    request_body_schema=request_body_schema,
                    response_schema=response_schema,
                    security=resolved_security,
                ))

        return ParsedOpenAPISpec(
            title=title,
            version=version,
            description=description,
            base_url=base_url,
            security_schemes=security_schemes,
            endpoints=parsed_endpoints,
        )


def parse_openapi_spec(spec_data: Union[Dict[str, Any], str]) -> ParsedOpenAPISpec:
    """Convenience functional wrapper to parse OpenAPI specification."""
    parser = OpenAPIParser(spec_data)
    return parser.parse()
