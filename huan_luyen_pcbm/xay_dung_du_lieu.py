import argparse
import json
from pathlib import Path
import pandas as pd

from huan_luyen_pcbm.xay_dung_dac_trung import xay_dung_dac_trung
from huan_luyen_pcbm.xay_dung_nhan import xay_dung_nhan

PIPELINE_VERSION = "pcbm-training-v4"
FEATURE_SCHEMA_VERSION = "4.0"
LABEL_SCHEMA_VERSION = "4.0"

def tai_du_lieu_jsonl(path):
    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            e = json.loads(line)
            e["timestamp"] = pd.Timestamp(e["timestamp"]).to_pydatetime()
            e["event_type"] = str(e["event_type"]).upper().strip()
            events.append(e)

    events.sort(key=lambda x: (x["user_id"], x["timestamp"], x["event_id"]))
    return events

def xay_dung_ban_ghi_hoc(events):
    """Tạo training records theo từng user để chạy tốt với bộ dữ liệu lớn.

    Feature/label của PCBM chỉ phụ thuộc lịch sử của chính user_id. Vì vậy việc
    chia events theo user trước khi tính giúp giảm mạnh chi phí quét dữ liệu mà
    vẫn giữ nguyên ranh giới thời gian và kết quả nhãn/đặc trưng.
    """
    events_by_user = {}
    for e in events:
        events_by_user.setdefault(e["user_id"], []).append(e)

    rows = []
    for user_id, user_events in events_by_user.items():
        user_events.sort(key=lambda x: (x["timestamp"], x["event_id"]))
        decisions = [e for e in user_events if e["event_type"] == "REMINDER_SENT"]
        for d in decisions:
            row = {}
            row.update(xay_dung_dac_trung(user_events, d))
            row.update(xay_dung_nhan(user_events, d))
            row["feature_schema_version"] = FEATURE_SCHEMA_VERSION
            row["label_schema_version"] = LABEL_SCHEMA_VERSION
            row["pipeline_version"] = PIPELINE_VERSION
            rows.append(row)

    rows.sort(key=lambda r: (r["decision_time"], r["user_id"], r["occurrence_id"]))
    return pd.DataFrame(rows)

def chay_chuong_trinh():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    events = tai_du_lieu_jsonl(args.input)
    df = xay_dung_ban_ghi_hoc(events)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)

    print("Events:", len(events))
    print("Training records:", len(df))
    print("Output:", out)

    show_cols = [
        "user_id","task_id","decision_time","task_type",
        "completion_rate_7d","prompt_level",
        "y_recall_success","y_started_within_10m",
        "y_complete_within_30m","y_complete_within_60m",
        "y_snooze","y_forgot"
    ]
    print(df[show_cols].to_string(index=False))

if __name__ == "__main__":
    chay_chuong_trinh()
