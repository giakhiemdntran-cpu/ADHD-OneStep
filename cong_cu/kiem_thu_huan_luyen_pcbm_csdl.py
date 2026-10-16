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
print('recall_accuracy:', r['recall_model']['evaluation'].get('accuracy'))
print('completion_accuracy:', r['completion_model']['evaluation'].get('accuracy'))
print('saved_models:', r['saved_models'])
