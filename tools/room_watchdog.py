"""Watch the room for "should be working but isn't" and say so.

A per-turn timeout cannot catch the case where no turn ever starts. This script
only reports; it never sends messages on the user's behalf or restarts anything.
"""
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOM = "http://127.0.0.1:8765"
LOG = Path(__file__).with_name("room-watchdog.log")
INTERVAL = 60
THRESHOLD = 2  # consecutive detections before reporting
COOLDOWN = 300  # seconds between wake attempts while still stuck


def stalled(snapshot):
    """True when work is queued but neither running nor scheduled to start."""
    return (not snapshot.get("active")
            and int(snapshot.get("pendingCount") or 0) > 0
            and int(snapshot.get("waiting") or 0) == 0
            and not snapshot.get("paused")
            and not snapshot.get("publicationHeld")
            and not snapshot.get("inputBlocked"))


def log(line):
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(time.strftime("%Y-%m-%d %H:%M:%S") + "  " + line + "\n")


def state():
    with urllib.request.urlopen(ROOM + "/api/state", timeout=5) as response:
        return json.loads(response.read())


def post(action, payload):
    html = urllib.request.urlopen(ROOM + "/", timeout=5).read().decode()
    token = re.search(r'name="room-token" content="([^"]+)"', html).group(1)
    request = urllib.request.Request(
        ROOM + "/api/" + action, data=json.dumps(payload, ensure_ascii=False).encode(),
        method="POST", headers={"Content-Type": "application/json", "X-Room-Token": token})
    urllib.request.urlopen(request, timeout=5).read()


def notify(text):
    post("notify", {"text": text})


def recover():
    """Wake a stuck scheduler; raises when the running build has no recover endpoint."""
    post("recover", {})


def due(hits, now, last_attempt, threshold=THRESHOLD, cooldown=COOLDOWN):
    """Retry while still stalled, but never faster than the cooldown."""
    if hits < threshold:
        return False
    return last_attempt is None or now - last_attempt >= cooldown


def supports_recover(snapshot):
    """The running build must advertise the endpoint before we call it."""
    return snapshot.get("recoverSupported") is True


def main():
    hits = 0
    last_attempt = None
    down = 0
    while True:
        try:
            snapshot = state()
            down = 0
        except (urllib.error.URLError, OSError) as exc:
            down += 1
            if down >= 3:
                log("room unreachable: " + type(exc).__name__)
                down = 0
            time.sleep(INTERVAL)
            continue

        now = time.monotonic()
        if stalled(snapshot):
            hits += 1
            if due(hits, now, last_attempt):
                last_attempt = now
                if not supports_recover(snapshot):
                    log("stalled, but this build has no recover endpoint")
                    try:
                        notify("看门狗：调度未启动；当前版本没有恢复入口")
                    except Exception:
                        log("missing recover endpoint and notify failed")
                    time.sleep(INTERVAL)
                    continue
                try:
                    recover()
                except urllib.error.HTTPError as exc:
                    if exc.code == 400:
                        log("recover refused by the room (400)")
                    else:
                        log("recover unavailable (HTTP " + str(exc.code) + ")")
                        try:
                            notify("看门狗：恢复入口不可用")
                        except Exception:
                            pass
                except Exception as exc:
                    log("recover failed: " + type(exc).__name__)
                    try:
                        notify("看门狗：恢复入口不可用（" + type(exc).__name__ + "）")
                    except Exception:
                        log("recover failed and notify failed")
                else:
                    log("recover sent")
                    try:
                        notify("看门狗：调度未启动，已尝试唤醒")
                    except Exception as exc:
                        log("recovered but notify failed: " + type(exc).__name__)
        else:
            hits = 0
            last_attempt = None
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
