"""
APIForge AI Dashboard & Admin Metrics Tests
Verifies dashboard aggregation queries and RBAC admin protection.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import SessionLocal
from app.models import User, Workflow, APIConnection
from app.security import get_password_hash, create_access_token

client = TestClient(app)


def _get_user_token(email: str, role: str = "user"):
    with SessionLocal() as db:
        u = db.query(User).filter_by(email=email).first()
        if not u:
            u = User(
                email=email,
                hashed_password=get_password_hash("Pass123456!"),
                role=role,
                is_active=True,
            )
            db.add(u)
            db.commit()
            db.refresh(u)
        user_id = u.id
    token = create_access_token(data={"sub": str(user_id), "email": email, "role": role})
    return user_id, token


def test_dashboard_summary_metrics():
    """Verify GET /dashboard/summary returns accurate counters and structure."""
    user_id, token = _get_user_token("dash_user@apiforge.ai", role="user")
    headers = {"Authorization": f"Bearer {token}"}

    # Create dummy workflow
    with SessionLocal() as db:
        wf = Workflow(user_id=user_id, title="Dash WF", nodes=[], edges=[])
        db.add(wf)
        db.commit()

    r = client.get("/dashboard/summary", headers=headers)
    assert r.status_code == 200
    data = r.json()

    assert "total_workflows" in data
    assert data["total_workflows"] >= 1
    assert "total_executions" in data
    assert "success_rate" in data
    assert "recent_executions" in data
    assert isinstance(data["recent_executions"], list)


def test_admin_stats_rbac_restriction():
    """Verify regular user receives HTTP 403 Forbidden while admin receives 200."""
    _, user_token = _get_user_token("regular_employee@apiforge.ai", role="user")
    _, admin_token = _get_user_token("system_director@apiforge.ai", role="admin")

    # Regular user denied
    r_forbidden = client.get("/admin/stats", headers={"Authorization": f"Bearer {user_token}"})
    assert r_forbidden.status_code == 403

    # Admin allowed
    r_allowed = client.get("/admin/stats", headers={"Authorization": f"Bearer {admin_token}"})
    assert r_allowed.status_code == 200
    stats = r_allowed.json()
    assert "total_users" in stats
    assert "total_workflows" in stats
    assert stats["admin_email"] == "system_director@apiforge.ai"


def test_admin_audit_logs_and_user_management():
    """Verify admin can query audit logs and toggle user active state."""
    target_id, _ = _get_user_token("target_toggle@apiforge.ai", role="user")
    _, admin_token = _get_user_token("super_audit_admin@apiforge.ai", role="admin")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Query audit logs
    r_logs = client.get("/admin/audit-logs?limit=10", headers=admin_headers)
    assert r_logs.status_code == 200
    assert isinstance(r_logs.json(), list)

    # Toggle user active state
    r_toggle = client.post(f"/admin/users/{target_id}/toggle-active", headers=admin_headers)
    assert r_toggle.status_code == 200
    assert r_toggle.json()["is_active"] is False

    # Toggle back
    r_toggle_back = client.post(f"/admin/users/{target_id}/toggle-active", headers=admin_headers)
    assert r_toggle_back.status_code == 200
    assert r_toggle_back.json()["is_active"] is True
