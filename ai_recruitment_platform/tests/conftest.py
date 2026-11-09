import os
# Import config only after establishing a disposable, local test database.
os.environ["AI_MODE"] = "demo"
os.environ["DATABASE_URL"] = "sqlite:///./.test_talentatlas.db"
os.environ["UPLOAD_DIR"] = "./.test_uploads"
os.environ.pop("REDIS_URL", None)

import pytest
from fastapi.testclient import TestClient
from app.db import Base, engine
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        yield c


@pytest.fixture
def admin(client):
    result = client.post("/api/v1/auth/bootstrap", json={
        "company": "Northwind Talent", "name": "Admin One",
        "email": "admin@northwind.example", "password": "correct horse battery staple"})
    assert result.status_code == 201, result.text
    auth = result.json()
    return {"header": {"Authorization": "Bearer " + auth["access_token"]},
            "tenant_id": auth["tenant_id"], "user_id": auth["user_id"]}


def make_user(client, admin, name, email, role):
    response = client.post("/api/v1/users", json={
        "name": name, "email": email,
        "password": "complex-password-123", "role": role}, headers=admin["header"])
    assert response.status_code == 201, response.text
    login = client.post("/api/v1/auth/login", json={
        "email": email, "password": "complex-password-123"})
    assert login.status_code == 200
    return {"id": response.json()["id"],
            "header": {"Authorization": "Bearer " + login.json()["access_token"]}}
