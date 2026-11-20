"""HTTP integration checks for the real-data web workspace."""

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from ui.server import Handler, UI_VERSION, run_policy


@pytest.fixture(scope="module")
def web():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    worker.join(timeout=5)


def request(web, route, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(web + route, data=data, headers=headers or {})
    with urlopen(req, timeout=30) as response:
        return response.status, response.read()


@pytest.mark.parametrize("route", ["/", "/prototype.html", "/workspace.js", "/explorer.html"])
def test_web_assets(web, route):
    status, content = request(web, route)
    assert status == 200 and len(content) > 100
    if route in ("/", "/prototype.html"):
        assert b'/workspace.js' in content
        assert b'connect-src blob: data:' not in content
        assert b'body:has(> #audit-prototype){margin:0}' in content


def test_health_version(web):
    _, content = request(web, "/healthz")
    assert json.loads(content)["ui_version"] == UI_VERSION


@pytest.mark.parametrize("policy", ["Oracle", "FlagAll", "RandomExplorer", "Reconciler"])
def test_native_policy_http(web, policy):
    _, content = request(web, "/api/run", {
        "source": {"split": "sample", "name": "sample_00"}, "policy": policy, "seed": 42,
    })
    result = json.loads(content)
    assert result["metrics"]["policy"] == policy
    assert result["metrics"]["scored"] is True
    assert result["metrics"]["grader_version"] == "1.0.0"
    assert 1 <= result["metrics"]["steps"] <= 100
    assert len(result["findings"]) <= 30
    assert len(result["trajectory"]) == result["metrics"]["steps"]
    assert '"issue_id"' not in json.dumps(result["trajectory"])
    if policy in ("Oracle", "Reconciler"):
        assert result["metrics"]["f1"] == 1.0


def test_generated_policy_matches_seed():
    source = {"preset": "mixed_small", "seed": 42}
    one = run_policy(source, "Reconciler", 42)
    two = run_policy(source, "Reconciler", 42)
    assert one["findings"] == two["findings"]
    assert one["metrics"]["episode_id"] == two["metrics"]["episode_id"]
    assert one["metrics"]["f1"] == two["metrics"]["f1"] == 1.0


@pytest.mark.parametrize("body", [
    {"source": {"split": "private_test", "name": "sample_00"}},
    {"source": {"split": "sample", "name": "../../private/truth.json"}},
    {"source": {"preset": "mixed_small", "seed": -1}},
    {"source": {"preset": "mixed_small", "seed": True}},
    {"source": {"preset": "unknown", "seed": 42}},
    {"source": {"split": "sample", "name": "sample_00"}, "policy": "unknown"},
    {"source": {"split": "sample", "name": "sample_00"}, "seed": 1.5},
    {"source": {"path": "/etc/passwd"}},
    {"source": None},
    [],
])
def test_invalid_run_rejected(web, body):
    with pytest.raises(HTTPError) as error:
        request(web, "/api/run", body)
    assert error.value.code == 400


def test_cross_origin_rejected(web):
    with pytest.raises(HTTPError) as error:
        request(web, "/api/run", {}, {"Origin": "https://other.example"})
    assert error.value.code == 403


def test_run_payload_limit(web):
    with pytest.raises(HTTPError) as error:
        request(web, "/api/run", {"padding": "x" * 9000})
    assert error.value.code == 413


@pytest.mark.parametrize("valid", [True, False])
def test_codespaces_forwarded_origin(web, monkeypatch, valid):
    monkeypatch.setenv("CODESPACE_NAME", "auditgym-test")
    monkeypatch.setenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev")
    port = web.rsplit(":", 1)[1]
    host = f"auditgym-test-{port}.app.github.dev" if valid else "other-space.app.github.dev"
    body = {"source": {"split": "sample", "name": "sample_00"}, "policy": "FlagAll"}
    if valid:
        status, _ = request(web, "/api/run", body, {"Origin": "https://" + host})
        assert status == 200
    else:
        with pytest.raises(HTTPError) as error:
            request(web, "/api/run", body, {"Origin": "https://" + host})
        assert error.value.code == 403
