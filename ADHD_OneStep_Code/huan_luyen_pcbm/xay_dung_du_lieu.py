import argparse
import json
from pathlib import Path
import pandas as pd

from huan_luyen_pcbm.xay_dung_dac_trung import xay_dung_dac_trung
from huan_luyen_pcbm.xay_dung_nhan import xay_dung_nhan

PIPELINE_VERSION = "pcbm-labeler-0.1"
FEATURE_SCHEMA_VERSION = "1.0"
LABEL_SCHEMA_VERSION = "1.0"

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
    # Điểm bắt đầu: REMINDER_SENT được xem là thời điểm ra quyết định.
    decisions = [e for e in events if e["event_type"] == "REMINDER_SENT"]

    rows = []
    for d in decisions:
        row = {}
        row.update(xay_dung_dac_trung(events, d))
        row.update(xay_dung_nhan(events, d))
        row["feature_schema_version"] = FEATURE_SCHEMA_VERSION
        row["label_schema_version"] = LABEL_SCHEMA_VERSION
        row["pipeline_version"] = PIPELINE_VERSION
        rows.append(row)

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
