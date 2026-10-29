import pytest
from aiohttp.test_utils import TestClient, TestServer
from app import Foundry, channel_diagnostic, create_app, response_text
from microsoft_agents.activity import Activity, ConversationAccount


class NeverInvoke:
    async def invoke(self, text):
        raise AssertionError("Unauthenticated request reached backend")


@pytest.mark.asyncio
@pytest.mark.parametrize("header", [None, "Bearer invalid", "Basic invalid"])
async def test_sdk_rejects_unauthenticated(header):
    app = create_app("11111111-1111-4111-8111-111111111111",
                     "22222222-2222-4222-8222-222222222222", NeverInvoke())
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/api/messages", json={"type": "message", "text": "hello"},
                                     headers={"Authorization": header} if header else {})
        assert response.status == 401


def test_extracts_text_not_mcp_metadata():
    body = {"status": "completed", "output": [
        {"type": "mcp_call", "output": '{"_meta":{"ui":{}}}'},
        {"type": "message", "content": [{"type": "output_text", "text": "real answer"}]},
    ]}
    assert response_text(body) == "real answer"


@pytest.mark.parametrize("body", [{"status": "failed"}, {"status": "completed", "output": []}])
def test_does_not_claim_empty_or_failed_response_pass(body):
    with pytest.raises(ValueError):
        response_text(body)


def test_backend_uses_configured_endpoint():
    backend = Foundry(None, "https://example.invalid/api/projects/test/", "test-agent")
    assert backend.endpoint == (
        "https://example.invalid/api/projects/test/agents/test-agent/endpoint/protocols/openai/responses"
    )


@pytest.mark.parametrize("endpoint", ["http://example.invalid", "https://user@example.invalid"])
def test_backend_rejects_invalid_endpoint(endpoint):
    with pytest.raises(ValueError):
        Foundry(None, endpoint, "test-agent")


def test_channel_diagnostic_retains_shape_not_payload():
    activity = Activity(
        type="message", id="synthetic-activity", channel_id="test:channel",
        text="must not be logged",
        conversation=ConversationAccount(id="synthetic-conversation", tenant_id="test-tenant",
                                         conversation_type="personal", is_group=False),
        channel_data={"tenant": {"id": "test-tenant"}, "secret": "must not be logged"},
    )
    summary = channel_diagnostic(activity, "test-tenant")
    assert summary["channel"] == "test:channel"
    assert summary["channel_tenant_matches"] is True
    assert summary["conversation_tenant_matches"] is True
    assert summary["conversation_type"] == "personal"
    assert "must not be logged" not in str(summary)
    assert "test-tenant" not in str(summary)


def test_channel_diagnostic_handles_missing_metadata():
    summary = channel_diagnostic(Activity(type="message", channel_id="unknown"), "test-tenant")
    assert summary["conversation_type"] is None
    assert summary["channel_tenant_present"] is False
    assert summary["conversation_tenant_present"] is False
