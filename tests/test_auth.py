from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import server


async def identity(_request):
    return JSONResponse({"agent": server.current_agent.get()})


def client():
    app = Starlette(
        routes=[Route("/private", identity)],
        middleware=[Middleware(server.AuthMiddleware, tokens={"alpha": "agent-a"})],
    )
    return TestClient(app)


def test_missing_bearer_has_exact_static_challenge():
    response = client().get("/private")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer realm="devops-mcp"'


def test_invalid_bearer_is_401_and_not_policy_denial():
    response = client().get(
        "/private", headers={"Authorization": "Bearer wrong"}
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == (
        'Bearer realm="devops-mcp", error="invalid_token"'
    )


def test_token_identity_is_request_scoped_and_does_not_leak():
    with client() as test_client:
        accepted = test_client.get(
            "/private", headers={"Authorization": "Bearer alpha"}
        )
        rejected = test_client.get(
            "/private", headers={"Authorization": "Bearer wrong"}
        )
    assert accepted.json() == {"agent": "agent-a"}
    assert rejected.status_code == 401
    assert server.current_agent.get() == "unknown"


def test_query_token_is_documented_legacy_behavior_until_step_7():
    response = client().get("/private?token=alpha")
    assert response.status_code == 200
    assert response.json() == {"agent": "agent-a"}
