"""
APIForge AI Error Diagnosis & Recovery Agent
Uses Ollama (qwen2.5:7b-instruct) to analyze step failures and propose candidate fixes.
NON-NEGOTIABLE RULE 9: Never apply fixes automatically.
Candidate fixes are proposals requiring explicit user confirmation before applying.
"""
import json
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from app.services.ollama_client import ollama_client
from app.services.validator import classify_error, ErrorCategory

logger = logging.getLogger(__name__)


class CandidateFix(BaseModel):
    fix_id: str = Field(..., description="Unique identifier for candidate fix")
    title: str = Field(..., description="Short summary of the proposed remediation")
    description: str = Field(..., description="Detailed explanation of why this fix resolves the issue")
    target_node_id: str = Field(..., description="The workflow node ID to modify")
    change_type: str = Field(..., description="Type of change: update_parameters | update_body | update_formula | update_path")
    patch: Dict[str, Any] = Field(..., description="Dictionary of fields to merge into node.data")


class ErrorDiagnosis(BaseModel):
    step_id: str
    error_category: str
    root_cause: str
    explanation: str
    candidate_fixes: List[CandidateFix]
    requires_user_approval: bool = True  # Non-negotiable Rule 9


DIAGNOSIS_SYSTEM_PROMPT = """You are an expert API debugging and error recovery agent in APIForge AI.
Your job is to diagnose why a workflow step failed and propose precise, actionable candidate fixes.

CRITICAL RULES:
1. NEVER apply or execute fixes automatically. You only generate recommendations.
2. Return ONLY a valid JSON object matching the exact schema below:
{
  "step_id": "<failing step ID>",
  "error_category": "<error category string>",
  "root_cause": "<concise 1-sentence root cause>",
  "explanation": "<detailed explanation of what went wrong>",
  "candidate_fixes": [
    {
      "fix_id": "fix_1",
      "title": "<short descriptive title>",
      "description": "<why this fix resolves the issue>",
      "target_node_id": "<node ID to update>",
      "change_type": "<update_parameters | update_body | update_formula | update_path>",
      "patch": { "<key>": "<new value>" }
    }
  ],
  "requires_user_approval": true
}
"""


async def diagnose_step_failure(
    step_id: str,
    node: Dict[str, Any],
    error_details: Dict[str, Any],
    execution_context: Dict[str, Any],
    endpoint_schema: Optional[Dict[str, Any]] = None,
) -> ErrorDiagnosis:
    """
    Diagnose a failed workflow step with Ollama and generate candidate fixes.
    """
    node_data = node.get("data", {})
    category = error_details.get("category") or ErrorCategory.UNKNOWN_ERROR
    error_msg = error_details.get("message") or error_details.get("error_message") or ""

    user_prompt = f"""Workflow Step Failed:
- Step ID: {step_id}
- Label: {node_data.get('label')}
- Type: {node.get('type') or node_data.get('step_type')}
- Method: {node_data.get('method')}
- Path: {node_data.get('path')}
- Parameters: {json.dumps(node_data.get('parameters') or {})}
- Request Body: {json.dumps(node_data.get('request_body') or {})}
- Formula (if transform): {(node_data.get('transformation') or {}).get('formula')}

Error Information:
- Category: {category}
- Error Message: {error_msg}
- Status Code: {error_details.get('status_code')}
- Response Body: {json.dumps(error_details.get('response_body') or {})}

Previous Step Outputs (Execution Context):
{json.dumps(execution_context, indent=2)}

Expected Endpoint Schema (if any):
{json.dumps(endpoint_schema or {}, indent=2)}

Diagnose the failure and return the JSON candidate fixes."""

    messages = [
        {"role": "system", "content": DIAGNOSIS_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        raw_response = await ollama_client.chat(
            messages=messages,
            format="json",
            temperature=0.1,
        )

        # Parse JSON
        start_idx = raw_response.find("{")
        end_idx = raw_response.rfind("}")
        if start_idx != -1 and end_idx != -1:
            clean_json = raw_response[start_idx : end_idx + 1]
            parsed = json.loads(clean_json)
            # Ensure required fields
            parsed["step_id"] = step_id
            parsed["requires_user_approval"] = True
            if "candidate_fixes" not in parsed or not isinstance(parsed["candidate_fixes"], list):
                parsed["candidate_fixes"] = []
            return ErrorDiagnosis(**parsed)
    except Exception as e:
        logger.warning(f"Ollama diagnosis generation fallback: {str(e)}")

    # Deterministic fallback candidate fix
    fallback_fixes = _generate_fallback_fixes(step_id, node_data, error_details)
    return ErrorDiagnosis(
        step_id=step_id,
        error_category=category,
        root_cause=f"Step '{step_id}' failed: {error_msg}",
        explanation=f"Error encountered during step execution: {error_msg}. Review the proposed candidate fixes below.",
        candidate_fixes=fallback_fixes,
        requires_user_approval=True,
    )


def _generate_fallback_fixes(
    step_id: str,
    node_data: Dict[str, Any],
    error_details: Dict[str, Any],
) -> List[CandidateFix]:
    """Generate safe, rule-based fallback candidate fixes when LLM is unavailable."""
    category = error_details.get("category", "")
    status_code = error_details.get("status_code")
    fixes: List[CandidateFix] = []

    if category == ErrorCategory.NOT_FOUND or (category == ErrorCategory.CLIENT_ERROR_4XX and status_code == 404):
        fixes.append(
            CandidateFix(
                fix_id="fix_verify_resource_id",
                title="Verify Resource Identifier or Path",
                description="The target resource was not found (HTTP 404). Update path or ID parameter to a valid resource.",
                target_node_id=step_id,
                change_type="update_parameters",
                patch={"parameters": {"id": 1}},
            )
        )
    elif category == ErrorCategory.AUTH_FAILURE or status_code in (401, 403):
        fixes.append(
            CandidateFix(
                fix_id="fix_check_auth_credentials",
                title="Check Connection Credentials & Auth Headers",
                description="Authentication failed (HTTP 401/403). Verify Bearer token or API Key on the API connection.",
                target_node_id=step_id,
                change_type="update_parameters",
                patch={"headers": dict(node_data.get("headers") or {})},
            )
        )
    elif category == ErrorCategory.INVALID_PARAMETERS or (category == ErrorCategory.CLIENT_ERROR_4XX and status_code in (400, 422)):
        fixes.append(
            CandidateFix(
                fix_id="fix_payload_validation",
                title="Adjust Request Parameters & Body",
                description="The target API rejected parameters or JSON body fields. Review required fields against schema.",
                target_node_id=step_id,
                change_type="update_body",
                patch={"request_body": node_data.get("request_body") or {}},
            )
        )
    elif category == ErrorCategory.DATA_MAPPING_FAILURE:
        fixes.append(
            CandidateFix(
                fix_id="fix_template_mapping",
                title="Correct Upstream Step Output Reference",
                description="A {{steps.<id>.output.<field>}} reference could not resolve. Verify the field path against upstream step output.",
                target_node_id=step_id,
                change_type="update_parameters",
                patch={"parameters": node_data.get("parameters") or {}},
            )
        )
    elif category == ErrorCategory.TRANSFORM_ERROR:
        fixes.append(
            CandidateFix(
                fix_id="fix_formula_syntax",
                title="Review Transformation Formula",
                description="The SimpleEval formula encountered an evaluation error. Check variable names and operators.",
                target_node_id=step_id,
                change_type="update_formula",
                patch={"transformation": {"operation": "calculate", "formula": "price * 1.0", "inputs": {"price": 100}}},
            )
        )
    elif category in (ErrorCategory.CONNECTION_FAILURE, ErrorCategory.NETWORK_TIMEOUT):
        fixes.append(
            CandidateFix(
                fix_id="fix_connection_endpoint",
                title="Inspect Target Service URL & Timeout",
                description="Target service is unreachable or timed out. Verify base URL, port, and service health.",
                target_node_id=step_id,
                change_type="update_path",
                patch={"path": node_data.get("path") or "/"},
            )
        )
    elif category in (ErrorCategory.MISSING_RESPONSE_FIELDS, ErrorCategory.SCHEMA_MISMATCH):
        fixes.append(
            CandidateFix(
                fix_id="fix_response_schema_alignment",
                title="Align Expected Response Schema or Downstream Mappings",
                description="Response structure diverged from expected JSONSchema or omitted required properties.",
                target_node_id=step_id,
                change_type="update_parameters",
                patch={"parameters": node_data.get("parameters") or {}},
            )
        )

    if not fixes:
        fixes.append(
            CandidateFix(
                fix_id="fix_general_inspection",
                title="Review Step Configuration",
                description="Inspect parameters, headers, and endpoint credentials.",
                target_node_id=step_id,
                change_type="update_parameters",
                patch={},
            )
        )

    return fixes
