"""
Phase 1 Database and SQLAlchemy Models Test Suite
Validates table creation, schema integrity, SQLite WAL mode, foreign key enforcement,
CASCADE deletions, JSON field serialization, and CRUD operations across all models.
"""
import pytest
from sqlalchemy import text, inspect
from sqlalchemy.exc import IntegrityError
from app.db import engine, SessionLocal, get_db, check_db_connectivity, init_db
from app.models import (
    User,
    APIConnection,
    Endpoint,
    Workflow,
    WorkflowExecution,
    AuditLog,
)


@pytest.fixture(autouse=True)
def setup_database():
    """Ensure all tables exist before each test."""
    init_db()
    yield


def test_db_connectivity_helper():
    """Verify check_db_connectivity returns True for SELECT 1."""
    assert check_db_connectivity() is True


def test_sqlite_pragmas():
    """Verify that SQLite foreign_keys is ON and journal_mode is WAL."""
    with engine.connect() as conn:
        fk_result = conn.execute(text("PRAGMA foreign_keys")).scalar()
        assert fk_result == 1, f"Expected foreign_keys=1, got {fk_result}"

        wal_result = conn.execute(text("PRAGMA journal_mode")).scalar()
        assert str(wal_result).lower() == "wal", f"Expected journal_mode=wal, got {wal_result}"


def test_tables_created():
    """Verify that all expected tables are registered and created in SQLite."""
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    expected_tables = [
        "users",
        "api_connections",
        "endpoints",
        "workflows",
        "workflow_executions",
        "audit_logs",
    ]
    for table in expected_tables:
        assert table in table_names, f"Table '{table}' was not created in the database."


def test_user_crud():
    """Verify User model creation, retrieval, and fields."""
    with SessionLocal() as db:
        user = User(
            email="developer@apiforge.ai",
            hashed_password="hashed_pw_test_123",
            role="admin",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        assert user.id is not None
        assert user.email == "developer@apiforge.ai"
        assert user.role == "admin"
        assert user.is_active is True
        assert user.created_at is not None
        assert user.updated_at is not None

        # Clean up
        db.delete(user)
        db.commit()


def test_connection_and_endpoints_crud():
    """Verify APIConnection and Endpoint models with JSON schemas and vector embeddings."""
    with SessionLocal() as db:
        # Create user
        user = User(
            email="conn_test@apiforge.ai",
            hashed_password="hashed_pw_test_123",
            role="user",
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        # Create connection
        connection = APIConnection(
            user_id=user.id,
            name="Mock Store API",
            description="Testing Store Service",
            base_url="http://localhost:8080/api/v1",
            auth_type="api_key",
            encrypted_credentials="fernet_encrypted_token_here",
            default_headers={"X-API-Key": "secret-key", "Content-Type": "application/json"},
        )
        db.add(connection)
        db.commit()
        db.refresh(connection)

        assert connection.id is not None
        assert connection.default_headers["X-API-Key"] == "secret-key"

        # Create endpoint
        dummy_embedding = [0.0123, -0.0456, 0.0789, 0.1122]
        endpoint = Endpoint(
            connection_id=connection.id,
            path="/products/{id}",
            method="GET",
            summary="Retrieve single product",
            description="Returns details for a product by ID",
            operation_id="getProductById",
            parameters=[{"name": "id", "in": "path", "required": True, "type": "integer"}],
            response_schema={"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}}},
            embedding=dummy_embedding,
        )
        db.add(endpoint)
        db.commit()
        db.refresh(endpoint)

        assert endpoint.id is not None
        assert endpoint.method == "GET"
        assert len(endpoint.embedding) == 4
        assert endpoint.parameters[0]["name"] == "id"

        # Clean up
        db.delete(user)
        db.commit()


def test_workflow_and_execution_crud():
    """Verify Workflow and WorkflowExecution models with nodes, edges, and step results."""
    with SessionLocal() as db:
        user = User(email="wf_test@apiforge.ai", hashed_password="pw")
        db.add(user)
        db.commit()
        db.refresh(user)

        sample_nodes = [
            {"id": "node_1", "type": "api", "data": {"label": "Fetch Product", "method": "GET"}},
            {"id": "node_2", "type": "transform", "data": {"label": "Apply Discount", "formula": "price * 0.9"}},
        ]
        sample_edges = [{"id": "e1-2", "source": "node_1", "target": "node_2"}]

        workflow = Workflow(
            user_id=user.id,
            title="Product Discount Flow",
            description="Fetches product and applies discount",
            raw_prompt="Fetch product and apply discount",
            nodes=sample_nodes,
            edges=sample_edges,
            status="draft",
        )
        db.add(workflow)
        db.commit()
        db.refresh(workflow)

        assert workflow.id is not None
        assert len(workflow.nodes) == 2
        assert workflow.edges[0]["source"] == "node_1"

        # Create Execution
        execution = WorkflowExecution(
            workflow_id=workflow.id,
            user_id=user.id,
            status="pending",
            requires_approval=True,
            pending_approval_step="node_2",
            approval_status="pending",
            step_results={"node_1": {"status_code": 200, "data": {"id": 5, "price": 1000}}},
            execution_logs=[{"step": "node_1", "status": "completed", "time_ms": 45}],
        )
        db.add(execution)
        db.commit()
        db.refresh(execution)

        assert execution.id is not None
        assert execution.requires_approval is True
        assert execution.step_results["node_1"]["data"]["price"] == 1000

        # Clean up
        db.delete(user)
        db.commit()


def test_cascade_delete():
    """Verify that deleting a User automatically cascades to all associated records."""
    with SessionLocal() as db:
        user = User(email="cascade_test@apiforge.ai", hashed_password="pw")
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

        connection = APIConnection(
            user_id=user_id,
            name="Cascade API",
            base_url="http://test.com",
        )
        db.add(connection)
        db.commit()
        db.refresh(connection)
        conn_id = connection.id

        endpoint = Endpoint(
            connection_id=conn_id,
            path="/test",
            method="GET",
        )
        db.add(endpoint)

        workflow = Workflow(
            user_id=user_id,
            title="Cascade Workflow",
        )
        db.add(workflow)
        db.commit()
        db.refresh(workflow)
        wf_id = workflow.id

        execution = WorkflowExecution(
            workflow_id=wf_id,
            user_id=user_id,
            status="completed",
        )
        db.add(execution)

        audit = AuditLog(
            user_id=user_id,
            action="login",
        )
        db.add(audit)
        db.commit()

        # Delete the user
        db.delete(user)
        db.commit()

        # Verify cascade deletions
        assert db.query(APIConnection).filter_by(id=conn_id).first() is None
        assert db.query(Endpoint).filter_by(connection_id=conn_id).first() is None
        assert db.query(Workflow).filter_by(id=wf_id).first() is None
        assert db.query(WorkflowExecution).filter_by(workflow_id=wf_id).first() is None


def test_foreign_key_violation():
    """Verify that SQLite foreign key enforcement raises IntegrityError on invalid parent ID."""
    with SessionLocal() as db:
        # Invalid user_id 999999
        invalid_connection = APIConnection(
            user_id=999999,
            name="Invalid Connection",
            base_url="http://invalid.com",
        )
        db.add(invalid_connection)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_audit_log_crud():
    """Verify AuditLog records system actions with JSON details and IP."""
    with SessionLocal() as db:
        audit = AuditLog(
            user_id=None,  # System event without user
            action="system_startup",
            resource_type="system",
            resource_id="backend_instance_1",
            details={"version": "1.0.0", "status": "initialized"},
            ip_address="127.0.0.1",
        )
        db.add(audit)
        db.commit()
        db.refresh(audit)

        assert audit.id is not None
        assert audit.action == "system_startup"
        assert audit.details["version"] == "1.0.0"
        assert audit.created_at is not None

        db.delete(audit)
        db.commit()
