import argparse
import json
from datetime import datetime
from pathlib import Path

import joblib

from huan_luyen_pcbm.xay_dung_du_lieu import tai_du_lieu_jsonl, xay_dung_ban_ghi_hoc
from huan_luyen_pcbm.huan_luyen_tu_csdl import _huan_luyen_cuoi, TRAINING_VERSION


def chay_chuong_trinh():
    ap = argparse.ArgumentParser(description="Huấn luyện PCBM từ file JSONL")
    ap.add_argument("--input", default="data/sample_events_4133.jsonl")
    ap.add_argument("--model-dir", default="models")
    args = ap.parse_args()

    events = tai_du_lieu_jsonl(args.input)
    df = xay_dung_ban_ghi_hoc(events)
    model_dir = Path(args.model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    source = f"jsonl:{Path(args.input).name}"

    recall = _huan_luyen_cuoi(df, "y_recall_success", source)
    completion = _huan_luyen_cuoi(df, "y_complete_within_30m", source)

    recall_path = model_dir / "pcbm_recall.joblib"
    completion_path = model_dir / "pcbm_completion.joblib"
    joblib.dump(recall, recall_path)
    joblib.dump(completion, completion_path)

    users = sorted({str(e["user_id"]) for e in events})
    meta = {
        "training_version": TRAINING_VERSION,
        "source": source,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "events": len(events),
        "records": len(df),
        "users": len(users),
        "user_ids": users,
        "dataset_summary": {
            "generic_cue_records": int((df["reminder_type"].astype(str).str.lower() == "generic").sum()),
            "recall_labeled_records": int(df["y_recall_success"].notna().sum()),
            "recall_label_definition": "RECALL_SUCCESS/FAILURE within 2 minutes after generic cue only",
        },
        "recall_model": {
            "path": str(recall_path),
            "model_name": recall["model_name"],
            "training_rows": recall["training_rows"],
            "positive_rate": recall["positive_rate"],
            "evaluation": recall["evaluation"],
        },
        "completion_model": {
            "path": str(completion_path),
            "model_name": completion["model_name"],
            "training_rows": completion["training_rows"],
            "positive_rate": completion["positive_rate"],
            "evaluation": completion["evaluation"],
        },
        "note": "PCBM sample/file training; cùng pipeline với huấn luyện từ SQLite.",
    }
    (model_dir / "pcbm_model_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    chay_chuong_trinh()
