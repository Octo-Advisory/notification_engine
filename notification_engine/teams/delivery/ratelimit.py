"""Per-destination token bucket in Redis, shared by all workers of the bench."""

import time

import frappe

# KEYS[1] bucket hash, KEYS[2] block key. ARGV: rate/s, burst, now (s).
# Returns {allowed (0/1), wait seconds as string}.
_TAKE_LUA = """
local blocked_ms = redis.call('PTTL', KEYS[2])
if blocked_ms > 0 then
	return {0, tostring(blocked_ms / 1000)}
end
local rate = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil or ts == nil then
	tokens = burst
	ts = now
end
if now > ts then
	tokens = math.min(burst, tokens + (now - ts) * rate)
	ts = now
end
local allowed = 0
local wait = 0
if tokens >= 1 then
	tokens = tokens - 1
	allowed = 1
else
	wait = (1 - tokens) / rate
end
redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'ts', tostring(ts))
redis.call('EXPIRE', KEYS[1], math.ceil(burst / rate) + 60)
return {allowed, tostring(wait)}
"""


def clock() -> float:
	"""Seconds since the epoch. Patched in tests to simulate time."""
	return time.time()


def _keys(destination: str) -> tuple[str, str]:
	base = f"teams_notify:rl:{frappe.local.site}:{destination}"
	return base, f"{base}:block"


# Bot limits are far higher than Workflows': per conversation about 1800/hour, per app 50/s.
# Webhooks use the Teams Settings defaults.
TYPE_DEFAULTS = {"Bot Conversation": (0.5, 5), "Bot (Personal Chat)": (10.0, 20)}


def get_limits(destination) -> tuple[float, int]:
	"""(rate per second, burst): destination override, else the type default, else Teams Settings."""
	type_rate, type_burst = TYPE_DEFAULTS.get(destination.destination_type, (None, None))
	rate = (
		destination.rate_per_second
		or type_rate
		or frappe.db.get_single_value("Teams Settings", "default_rate_per_second")
	)
	burst = destination.burst or type_burst or frappe.db.get_single_value("Teams Settings", "default_burst")
	rate, burst = rate or 0.07, burst or 1
	return float(rate), max(1, int(burst))


def take(destination: str, rate: float, burst: int) -> tuple[bool, float]:
	"""Take one token. Returns (allowed, seconds to wait when not allowed)."""
	allowed, wait = frappe.cache.eval(_TAKE_LUA, 2, *_keys(destination), rate, burst, clock())
	return bool(int(allowed)), float(wait)


def block(destination: str, seconds: float):
	"""Stop all sends to `destination` for `seconds` (e.g. after a 429)."""
	if seconds > 0:
		frappe.cache.set(_keys(destination)[1], 1, px=int(seconds * 1000))


def reset(destination: str):
	frappe.cache.delete(*_keys(destination))
