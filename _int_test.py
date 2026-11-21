import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from http.server import BaseHTTPRequestHandler, HTTPServer

from health_guard import gatekeeper, winapi
from health_guard.constants import DEFAULT_CONFIG
from health_guard.state import UsageState
from health_guard.util import deep_merge

MOD_CTRL, MOD_ALT, MOD_SHIFT = 2, 1, 4

mods, vk = winapi.mods_and_vk(["ctrl", "alt", "shift", "u"])
assert mods == (MOD_CTRL | MOD_ALT | MOD_SHIFT), mods
assert vk == 0x55, hex(vk)
_, vk2 = winapi.mods_and_vk(["ctrl", "alt", "shift", "x"])
assert vk2 == 0x58, hex(vk2)
print("[PASS] winapi.mods_and_vk")

idle = winapi.get_idle_seconds()
assert isinstance(idle, float) and idle >= 0
print("[PASS] winapi.get_idle_seconds ->", round(idle, 2))

rect = winapi.virtual_screen_rect()
assert rect.right > rect.left and rect.bottom > rect.top
print("[PASS] winapi.virtual_screen_rect")

windows = winapi.enumerate_visible_windows()
assert isinstance(windows, list)
print("[PASS] winapi.enumerate_visible_windows ->", len(windows), "windows")

REPLY = {"allow": True, "minutes": 25, "reason": "\u786e\u5c5e\u7d27\u6025\u5de5\u4f5c"}
REQUEST_LOG = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(n).decode("utf-8"))
        REQUEST_LOG.append(
            (self.path, self.headers.get("Authorization"), payload["model"])
        )
        content = "```json\n" + json.dumps(REPLY, ensure_ascii=False) + "\n```"
        body = json.dumps(
            {"choices": [{"message": {"content": content}}]}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


server = HTTPServer(("127.0.0.1", 0), Handler)
port = server.server_port
threading.Thread(target=server.serve_forever, daemon=True).start()

cfg = deep_merge(DEFAULT_CONFIG, {})
cfg["gatekeeper"] = dict(
    cfg["gatekeeper"],
    enabled=True,
    base_url=f"http://127.0.0.1:{port}/v1",
    api_key="sk-test",
    model="test-model",
    timeout_seconds=5,
    max_grant_minutes=60,
)
state = UsageState()
result = gatekeeper.evaluate_request(cfg, state, "老板让我交紧急报告")
print("[PASS] gatekeeper HTTP roundtrip ->", result)
assert result["allow"] is True and result["minutes"] == 25
assert REQUEST_LOG and REQUEST_LOG[0][1] == "Bearer sk-test"
assert REQUEST_LOG[0][2] == "test-model"

REPLY["minutes"] = 999
result2 = gatekeeper.evaluate_request(cfg, state, "again")
assert result2["minutes"] == 60, result2
print("[PASS] gatekeeper clamps minutes to max ->", result2["minutes"])

REPLY["allow"] = False
REPLY["minutes"] = 30
result3 = gatekeeper.evaluate_request(cfg, state, "just want to play")
assert result3["allow"] is False and result3["minutes"] == 0, result3
print("[PASS] gatekeeper deny ->", result3["reason"])

server.shutdown()

bad = deep_merge(DEFAULT_CONFIG, {})
bad["gatekeeper"] = dict(
    bad["gatekeeper"],
    enabled=True,
    base_url="http://127.0.0.1:1/v1",
    api_key="sk-test",
    timeout_seconds=2,
)
try:
    gatekeeper.evaluate_request(bad, state, "reason")
    print("[FAIL] gatekeeper unreachable should raise")
    sys.exit(1)
except gatekeeper.GatekeeperError as exc:
    print("[PASS] gatekeeper unreachable raises ->", str(exc)[:70])

print("ALL WINAPI + GATEKEEPER TESTS PASSED")
