"""Read-only, allowlisted account and quota snapshots from the existing RPC client.

No authentication files are read and no token refresh is requested. ``resetsAt``
is the server's Unix timestamp in seconds; ``updatedAt`` uses milliseconds like
the workbench's other snapshots. A missing weekly window stays unavailable.
"""
from __future__ import annotations

import asyncio
import copy
import time
import unicodedata


WEEK_MINUTES = 7 * 24 * 60
PLAN_TYPES = {
    "free", "go", "plus", "pro", "prolite", "promax", "team", "business",
    "self_serve_business_prolite", "self_serve_business_usage_based", "ent26",
    "enterprise_cbp_automation", "enterprise_cbp_usage_based", "enterprise",
    "edu", "edu_plus", "edu_pro", "unknown",
}
ACCOUNT_UNAVAILABLE = "暂时无法读取 Codex 账户，请稍后刷新。"
QUOTA_UNAVAILABLE = "暂时无法读取 Codex 配额；当前版本或登录方式可能不支持此接口。"


def _display_string(value, limit):
    if not isinstance(value, str):
        return None
    return "".join(c for c in value if not unicodedata.category(c).startswith("C"))[:limit].strip() or None


def _account(response):
    if not isinstance(response, dict) or (
        "account" not in response and not isinstance(response.get("requiresOpenaiAuth"), bool)
    ):
        raise ValueError("Invalid account response")
    account = response.get("account")
    if account is None:
        return "not_logged_in", None
    if not isinstance(account, dict):
        raise ValueError("Invalid account response")
    kind = account.get("type")
    if kind == "chatgpt":
        plan = account.get("planType")
        return "ok", {
            "type": kind,
            "email": _display_string(account.get("email"), 254),
            "planType": plan if isinstance(plan, str) and plan in PLAN_TYPES else "unknown",
        }
    if kind == "apiKey":
        return "api_key", {"type": kind, "email": None, "planType": None}
    return "unsupported_auth", {
        "type": "amazonBedrock" if kind == "amazonBedrock" else "unknown",
        "email": None, "planType": None,
    }


def _window(value):
    if not isinstance(value, dict) or type(value.get("usedPercent")) is not int:
        return None
    used = value["usedPercent"]
    duration = value.get("windowDurationMins")
    resets = value.get("resetsAt")
    return {
        "usedPercent": used,
        "remainingPercent": max(0, min(100, 100 - used)),
        "windowDurationMins": duration if type(duration) is int and duration > 0 else None,
        "resetsAt": resets if type(resets) is int and 0 <= resets <= 253402300799 else None,
    }


def normalize_rate_limits(response):
    """Accept legacy single buckets and the current explicitly named Codex bucket."""
    if not isinstance(response, dict):
        raise ValueError("Invalid rate limit response")
    buckets = response.get("rateLimitsByLimitId")
    codex = buckets.get("codex") if isinstance(buckets, dict) else None
    bucket = codex if isinstance(codex, dict) else response.get("rateLimits")
    if not isinstance(bucket, dict):
        raise ValueError("Invalid rate limit response")
    primary = _window(bucket.get("primary"))
    secondary = _window(bucket.get("secondary"))
    weekly = next((w for w in (secondary, primary)
                   if w and w["windowDurationMins"] == WEEK_MINUTES), None)
    return {"weekly": weekly, "primary": primary}


class AccountCache:
    """Per-host TTL cache with one refresh in flight per host.

    ``get_client`` is the workbench's existing asynchronous connection accessor.
    ``get`` never submits a turn. Failed reads expose a fixed error message and
    mark any previous snapshot stale, without forwarding remote error payloads.
    """

    def __init__(self, get_client, *, ttl=60, error_ttl=10, timeout=20,
                 clock=time.time, monotonic=time.monotonic):
        self.get_client = get_client
        self.ttl, self.error_ttl, self.timeout = ttl, error_ttl, timeout
        self.clock, self.monotonic = clock, monotonic
        self._values, self._expires, self._locks = {}, {}, {}

    def snapshot(self):
        return copy.deepcopy(self._values)

    async def get(self, host, *, force=False):
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            if not force and host in self._values and self.monotonic() < self._expires[host]:
                return copy.deepcopy(self._values[host])
            previous = self._values.get(host)
            empty = {"status": "unavailable", "account": None, "weekly": None,
                     "primary": None, "updatedAt": None, "stale": False, "error": None}
            try:
                client = await asyncio.wait_for(self.get_client(host), self.timeout)
                response = await client.request("account/read", {"refreshToken": False}, timeout=self.timeout)
                status, account = _account(response)
            except asyncio.CancelledError:
                raise
            except Exception:
                value = {**(previous or empty), "status": "unavailable",
                         "stale": bool(previous and previous["updatedAt"] is not None),
                         "error": ACCOUNT_UNAVAILABLE}
            else:
                value = {**empty, "status": status, "account": account,
                         "updatedAt": int(self.clock() * 1000)}
                if status == "ok":
                    try:
                        response = await client.request("account/rateLimits/read", {}, timeout=self.timeout)
                        value.update(normalize_rate_limits(response))
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        # Never display a previous account's limits after login changes.
                        same_account = previous and previous["account"] == account
                        if same_account and (previous["weekly"] or previous["primary"]):
                            value.update({k: previous[k] for k in ("weekly", "primary", "updatedAt")})
                            value["stale"] = True
                        value.update(status="unavailable", error=QUOTA_UNAVAILABLE)
            self._values[host] = value
            self._expires[host] = self.monotonic() + (
                self.error_ttl if value["status"] == "unavailable" else self.ttl)
            return copy.deepcopy(value)
