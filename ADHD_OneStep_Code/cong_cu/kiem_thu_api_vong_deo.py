import json
import requests

BASE = "http://127.0.0.1:5000"

print("1) BAND STATE")
print(json.dumps(
    requests.get(BASE + "/api/band/state", timeout=5).json(),
    ensure_ascii=False,
    indent=2
))

print("\n2) PUSH TEST")
print(json.dumps(
    requests.post(
        BASE + "/api/band/test",
        json={
            "type": "TASK",
            "message": "Test OneBand|Mở sách Toán"
        },
        timeout=5
    ).json(),
    ensure_ascii=False,
    indent=2
))

print("\n3) BAND NEXT")
print(json.dumps(
    requests.get(BASE + "/api/band/next", timeout=5).json(),
    ensure_ascii=False,
    indent=2
))
