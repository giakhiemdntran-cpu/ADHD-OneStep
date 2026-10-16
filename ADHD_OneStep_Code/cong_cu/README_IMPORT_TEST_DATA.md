# Tool import dữ liệu test cho OneStep v9.9

## Import toàn bộ dữ liệu test

```bash
python tools/import_test_data.py --all
```

Bao gồm:
- Sample PCBM event log từ `data/sample_events.jsonl`
- Task hiện tại/quá khứ/tương lai
- Task history
- Habit profile
- Coaching event
- Memory check
- Vision/object sighting

## Tạo lại từ đầu

```bash
python tools/import_test_data.py --reset --all
```

Tool chỉ xóa dữ liệu được đánh dấu là dữ liệu test, không xóa task thật.

## Chỉ import PCBM

```bash
python tools/import_test_data.py --pcbm-only
```

## Chỉ tạo dữ liệu Dashboard

```bash
python tools/import_test_data.py --app-only
```

## Dịch sample PCBM tới gần thời gian hiện tại

```bash
python tools/import_test_data.py --reset --pcbm-only --shift-to-now
```

## Xóa test data

```bash
python tools/import_test_data.py --reset-only
```

## Xem trước mà không ghi DB

```bash
python tools/import_test_data.py --all --dry-run
```
