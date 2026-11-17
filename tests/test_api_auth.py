"""
Device REST routes (/api/*) must require a key and only ever touch the caller's
own family. They used to be wide open whenever POLLY_API_KEY was unset, and
/api/items read and deleted across every tenant.
"""
import hashlib
import importlib
import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from core.database import PollyDB

GLOBAL = "global-test-key-0123456789abcdef"
KEY_T1 = "device-key-tenant-one-0123456789"
KEY_T8 = "device-key-tenant-eight-01234567"


def _h(k):
    return hashlib.sha256(k.encode()).hexdigest()


def _app(db, monkeypatch, global_key):
    monkeypatch.setenv("POLLY_API_KEY", global_key)
    monkeypatch.delenv("POLLY_AUTH_DISABLED", raising=False)
    import core.auth as auth
    importlib.reload(auth)
    from api.commands import router as commands_router
    from api.devices import router as devices_router

    app = FastAPI()
    app.state.db = db
    app.add_middleware(auth.APIKeyMiddleware)
    app.include_router(commands_router, prefix="/api")
    app.include_router(devices_router, prefix="/api/devices")

    @app.post("/api/stripe/webhook")
    async def hook():
        return {"ok": True}

    return TestClient(app)


@pytest.fixture
def db(tmp_path):
    d = PollyDB(str(tmp_path / "auth.db"))
    d.register_device("dev-t1", 1, api_key=KEY_T1)
    d.register_device("dev-t8", 8, api_key=KEY_T8)
    d.store_item("keys", "kitchen drawer", tenant_id=1)
    d.store_item("passport", "safe", tenant_id=8)
    return d


@pytest.mark.parametrize("global_key", [GLOBAL, ""])
def test_no_key_is_rejected(db, monkeypatch, global_key):
    # An unset global key must lock the door, not open it.
    c = _app(db, monkeypatch, global_key)
    for method, path in (("get", "/api/items"), ("get", "/api/stats"),
                         ("get", "/api/devices/"), ("delete", "/api/items/1")):
        assert getattr(c, method)(path).status_code == 401, path
        assert getattr(c, method)(path, headers={"X-API-Key": "made-up"}).status_code == 401, path


def test_device_key_sees_only_its_tenant(db, monkeypatch):
    c = _app(db, monkeypatch, GLOBAL)
    r = c.get("/api/items", headers={"X-API-Key": KEY_T1})
    assert r.status_code == 200
    assert [i["item"] for i in r.json()["items"]] == ["keys"]
    r = c.get("/api/items?search=passport", headers={"X-API-Key": KEY_T1})
    assert r.json()["items"] == []
    assert c.get("/api/stats", headers={"X-API-Key": KEY_T8}).status_code == 200


def test_cannot_delete_another_familys_item(db, monkeypatch):
    c = _app(db, monkeypatch, GLOBAL)
    other = db.list_all(tenant_id=8)[0]["id"]
    assert c.delete(f"/api/items/{other}", headers={"X-API-Key": KEY_T1}).status_code == 404
    assert len(db.list_all(tenant_id=8)) == 1


def test_new_item_lands_in_callers_tenant(db, monkeypatch):
    c = _app(db, monkeypatch, GLOBAL)
    r = c.post("/api/items", json={"item": "glasses", "location": "nightstand"},
               headers={"X-API-Key": KEY_T8})
    assert r.status_code == 200
    assert "glasses" in [i["item"] for i in db.list_all(tenant_id=8)]
    assert "glasses" not in [i["item"] for i in db.list_all(tenant_id=1)]


def test_device_list_is_admin_only(db, monkeypatch):
    c = _app(db, monkeypatch, GLOBAL)
    assert c.get("/api/devices/", headers={"X-API-Key": KEY_T1}).status_code == 403
    assert c.get("/api/devices/", headers={"X-API-Key": GLOBAL}).status_code == 200


def test_stripe_webhook_stays_public(db, monkeypatch):
    c = _app(db, monkeypatch, GLOBAL)
    assert c.post("/api/stripe/webhook").status_code == 200
