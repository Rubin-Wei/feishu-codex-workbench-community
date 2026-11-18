import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from feishu_codex_workbench.accounts import AccountCache, normalize_rate_limits
from feishu_codex_workbench.rpc import RpcError


ACCOUNT = {"account": {"type": "chatgpt", "email": "owner@example.com", "planType": "pro"},
           "requiresOpenaiAuth": True}
LIMITS = {"rateLimits": {
    "primary": {"usedPercent": 18, "windowDurationMins": 300, "resetsAt": 1795000000},
    "secondary": {"usedPercent": 36, "windowDurationMins": 10080, "resetsAt": 1795500000},
}}


def fixture_cache(responses, **kwargs):
    client = AsyncMock()
    client.request.side_effect = responses
    connect = AsyncMock(return_value=client)
    return AccountCache(connect, **kwargs), connect, client


async def test_account_and_weekly_quota_are_allowlisted_cached_and_read_only():
    account = {**ACCOUNT, "accessToken": "must-not-leak", "account": {
        **ACCOUNT["account"], "email": "owner\x00@example.com", "token": "must-not-leak"}}
    limits = {**LIMITS, "accountId": "must-not-leak", "rateLimitUpsell": {"token": "must-not-leak"}}
    now = [1000.0]
    cache, connect, client = fixture_cache([account, limits, ACCOUNT, LIMITS],
                                          clock=lambda: now[0], monotonic=lambda: now[0])
    first = await cache.get("d")
    assert first == {
        "status": "ok", "account": ACCOUNT["account"],
        "weekly": {"usedPercent": 36, "remainingPercent": 64,
                   "windowDurationMins": 10080, "resetsAt": 1795500000},
        "primary": {"usedPercent": 18, "remainingPercent": 82,
                    "windowDurationMins": 300, "resetsAt": 1795000000},
        "updatedAt": 1000000, "stale": False, "error": None,
    }
    assert "must-not-leak" not in json.dumps(first)
    first["account"]["email"] = "mutated"
    assert (await cache.get("d"))["account"]["email"] == "owner@example.com"
    snapshot = cache.snapshot()
    snapshot["d"]["weekly"]["remainingPercent"] = -1
    assert cache.snapshot()["d"]["weekly"]["remainingPercent"] == 64
    now[0] += 60
    assert (await cache.get("d"))["updatedAt"] == 1060000
    assert connect.await_count == 2
    assert [(c.args, c.kwargs) for c in client.request.await_args_list] == [
        (("account/read", {"refreshToken": False}), {"timeout": 20}),
        (("account/rateLimits/read", {}), {"timeout": 20}),
    ] * 2


@pytest.mark.parametrize("account,status,kind", [
    (None, "not_logged_in", None),
    ({"type": "apiKey", "apiKey": "must-not-leak"}, "api_key", "apiKey"),
    ({"type": "amazonBedrock", "usesCodexManagedCredentials": True}, "unsupported_auth", "amazonBedrock"),
    ({"type": "future-provider", "token": "must-not-leak"}, "unsupported_auth", "unknown"),
])
async def test_non_chatgpt_accounts_have_no_subscription_quota(account, status, kind):
    cache, _, client = fixture_cache([{"account": account, "requiresOpenaiAuth": True}])
    value = await cache.get("h")
    assert value["status"] == status
    assert (value["account"] or {}).get("type") == kind
    assert value["weekly"] is None and value["primary"] is None
    assert client.request.await_count == 1
    assert "must-not-leak" not in json.dumps(value)


def test_named_codex_bucket_overrides_legacy_bucket():
    value = normalize_rate_limits({**LIMITS, "rateLimitsByLimitId": {
        "codex": {"primary": {"usedPercent": 9, "windowDurationMins": 10080, "resetsAt": None}},
        "other-model": LIMITS["rateLimits"],
    }})
    assert value["weekly"]["remainingPercent"] == 91
    assert value["weekly"]["resetsAt"] is None


def test_unknown_duration_does_not_invent_weekly_window_or_reset():
    value = normalize_rate_limits({"rateLimits": {
        "primary": {"usedPercent": 110, "windowDurationMins": 300},
        "secondary": {"usedPercent": 4, "windowDurationMins": None, "resetsAt": 1795500000},
    }})
    assert value["weekly"] is None
    assert value["primary"]["remainingPercent"] == 0
    assert value["primary"]["resetsAt"] is None
    assert normalize_rate_limits({"rateLimits": {"secondary": {
        "usedPercent": 20, "windowDurationMins": 1440}}})["weekly"] is None


@pytest.mark.parametrize("window", [None, "bad", {}, {"usedPercent": True}, {"usedPercent": "12"},
                                     {"usedPercent": float("nan")}])
def test_malformed_windows_are_unavailable(window):
    assert normalize_rate_limits({"rateLimits": {"primary": window, "secondary": window}}) == {
        "weekly": None, "primary": None}


async def test_rpc_failure_keeps_prior_values_but_marks_stale_and_redacts_error():
    secret_error = RpcError({"code": -32603, "message": "bearer must-not-leak"})
    cache, _, _ = fixture_cache([ACCOUNT, LIMITS, secret_error])
    fresh = await cache.get("d")
    failed = await cache.get("d", force=True)
    assert failed["status"] == "unavailable" and failed["stale"]
    assert failed["weekly"] == fresh["weekly"]
    assert failed["updatedAt"] == fresh["updatedAt"]
    assert failed["error"] and "must-not-leak" not in json.dumps(failed)


async def test_quota_failure_is_separate_from_persisted_account_and_respects_account_change():
    other = {"account": {**ACCOUNT["account"], "email": "new@example.com"}, "requiresOpenaiAuth": True}
    failure = RpcError({"code": -32601, "message": "unknown method secret"})
    cache, _, _ = fixture_cache([ACCOUNT, LIMITS, ACCOUNT, failure, other, failure])
    fresh = await cache.get("d")
    stale = await cache.get("d", force=True)
    assert stale["stale"] and stale["weekly"] == fresh["weekly"]
    changed = await cache.get("d", force=True)
    assert changed["account"]["email"] == "new@example.com"
    assert changed["status"] == "unavailable" and not changed["stale"]
    assert changed["weekly"] is None and changed["primary"] is None


async def test_errors_are_cached_briefly_and_hosts_are_isolated():
    now = [1000.0]
    cache, connect, client = fixture_cache([ACCOUNT, LIMITS], monotonic=lambda: now[0])
    connect.side_effect = [ConnectionError("secret"), client, client]
    failed = await cache.get("h")
    assert failed["status"] == "unavailable" and failed["account"] is None and not failed["stale"]
    assert await cache.get("h") == failed
    assert connect.await_count == 1
    assert (await cache.get("d"))["status"] == "ok"
    now[0] += 10
    client.request.side_effect = [ACCOUNT, LIMITS]
    assert (await cache.get("h"))["status"] == "ok"
    assert connect.await_count == 3


async def test_concurrent_reads_share_one_refresh_and_cancellation_is_not_cached():
    cache, connect, client = fixture_cache([ACCOUNT, LIMITS])
    values = await asyncio.gather(*(cache.get("d") for _ in range(5)))
    assert all(value == values[0] for value in values)
    assert connect.await_count == 1 and client.request.await_count == 2
    client.request.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await cache.get("d", force=True)
    assert cache.snapshot()["d"] == values[0]


async def test_malformed_rpc_payload_and_connection_timeout_are_unavailable():
    cache, _, _ = fixture_cache([{"not_an_account": "secret"}])
    assert (await cache.get("d"))["status"] == "unavailable"
    cache, _, _ = fixture_cache([ACCOUNT, {"rateLimits": None}])
    assert (await cache.get("d"))["status"] == "unavailable"
    async def stalled(host):
        await asyncio.sleep(1)
    cache = AccountCache(stalled, timeout=0.01)
    assert (await cache.get("d"))["status"] == "unavailable"
