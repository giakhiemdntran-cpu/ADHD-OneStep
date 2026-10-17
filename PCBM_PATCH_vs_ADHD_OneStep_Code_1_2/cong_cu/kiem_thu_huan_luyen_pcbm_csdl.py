#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dich_vu.co_so_du_lieu import khoi_tao_co_so_du_lieu, lay_ket_noi_csdl
from dich_vu.dich_vu_pcbm import DichVuPCBM

khoi_tao_co_so_du_lieu()
with lay_ket_noi_csdl() as c:
    n = c.execute('SELECT COUNT(*) FROM pcbm_events').fetchone()[0]
print('pcbm_events:', n)

pcbm = DichVuPCBM()
r = pcbm.huan_luyen_tu_sqlite()
print('success:', r['success'])
print('events_used:', r['events_used'])
print('training_records:', r['training_records'])
print('users:', r['users'])
for key in ('recall_model', 'completion_model'):
    item = r[key]
    ev = item['evaluation']
    print(key, 'model=', item.get('model_name') or ev.get('selected_model'))
    print('  rows=', item['training_rows'], 'PR-AUC=', ev.get('pr_auc'), 'ROC-AUC=', ev.get('roc_auc'), 'F1=', ev.get('f1'))
print('saved_models:', r['saved_models'])
