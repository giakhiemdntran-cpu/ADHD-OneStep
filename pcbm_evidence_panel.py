"""Embedded PCBM evidence panel for existing OneStep Streamlit admin."""
import json
from pathlib import Path
import streamlit as st
import pandas as pd
from dich_vu.pcbm_safety_gate import check_gate


def render_pcbm_evidence():
    st.title("🛡️ PCBM – Minh chứng & An toàn")
    st.caption("Đánh giá kỹ thuật mô hình khác với kiểm định độc lập. Trang này không thay đổi mức hỗ trợ thật.")
    path = Path(__file__).resolve().parent / "models" / "pcbm_safety_audit.json"
    if not path.exists():
        st.warning("Chưa có báo cáo AUC tại models/pcbm_safety_audit.json. Chạy lệnh bên dưới trước khi trình diễn.")
        st.code('python -m huan_luyen_pcbm.pcbm_audit --db storage/onestep.db --output models/pcbm_safety_audit.json',language="bash")
        return
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        st.error(f"Không đọc được báo cáo: {e}")
        return
    st.caption(f"Đánh giá lúc: {report.get('evaluated_at','Chưa ghi nhận')} | Giao thức: {report.get('protocol','Chưa ghi nhận')}")
    st.warning(report.get('limitations') or 'Đây chưa phải bằng chứng kiểm định độc lập.')
    for key,title in (("y_recall_success","Dự đoán tự nhớ (Recall)"),("y_complete_within_30m","Hoàn thành trong 30 phút")):
        data=(report.get('models') or {}).get(key) or {}
        st.subheader(title)
        if not data.get('available'):
            st.info(data.get('reason','Chưa có kết quả đánh giá hợp lệ.'))
            continue
        a,b,c=st.columns(3)
        def fmt(value):
            return "—" if value is None else f"{float(value):.3f}"
        a.metric('ROC-AUC',fmt(data.get('roc_auc')))
        b.metric('PR-AUC',fmt(data.get('pr_auc')))
        c.metric('Số mẫu kiểm thử',str(data.get('test_rows','—')))
        matrix=data.get('confusion_matrix')
        if isinstance(matrix,list) and len(matrix)==2 and all(isinstance(r,list) and len(r)==2 for r in matrix):
            st.write('**Confusion Matrix** — hàng là nhãn thực tế, cột là dự đoán')
            st.dataframe(pd.DataFrame(matrix,index=['Thực tế 0','Thực tế 1'],columns=['Dự đoán 0','Dự đoán 1']),use_container_width=True)
            st.caption(f"TN={matrix[0][0]} · FP={matrix[0][1]} · FN={matrix[1][0]} · TP={matrix[1][1]}")
    st.divider()
    st.subheader('Kiểm chứng quyết định giữ mức hỗ trợ')
    st.info('AUC/Confusion Matrix đánh giá dự đoán. Quyết định Level còn phụ thuộc bằng chứng hành vi, phê duyệt và ý kiến người dùng.')
    recall=((report.get('models') or {}).get('y_recall_success') or {})
    auc=st.number_input('Thử ROC-AUC Recall',min_value=0.0,max_value=1.0,value=float(recall.get('roc_auc') or 0.536),step=0.001,key='evidence_auc')
    samples=st.number_input('Số mẫu kiểm thử',min_value=0,value=int(recall.get('test_rows') or 0),key='evidence_n')
    observed=st.number_input('Số nhiệm vụ quan sát',min_value=0,value=12,key='evidence_tasks')
    days=st.number_input('Số ngày quan sát',min_value=0,value=7,key='evidence_days')
    starts=st.number_input('Số lần tự bắt đầu',min_value=0,max_value=observed,value=min(10,observed),key='evidence_starts')
    validated=st.checkbox('Đã kiểm định độc lập (chỉ để thử kịch bản)',key='evidence_validated')
    consent=st.checkbox('Người dùng đồng ý giảm',key='evidence_consent')
    demo=st.checkbox('Đang chạy trên dữ liệu demo',value=True,key='evidence_demo')
    decision=check_gate({'roc_auc':auc,'test_rows':samples},
                        {'observed_tasks':observed,'observation_days':days,'independent_starts':starts},
                        independent_validated=validated,consent=consent,is_demo=demo)
    if decision.eligible_for_decrease:
        st.success('Đủ điều kiện xem xét thử giảm có giám sát — KHÔNG tự động đổi Level.')
    else:
        st.info('GIỮ NGUYÊN LEVEL — chưa đủ căn cứ giảm hỗ trợ.')
    st.write('**Lý do:**',decision.reason)
    st.caption('Các ô chọn trên chỉ mô phỏng kịch bản, không xác minh kiểm định thật. Không ghi SQLite hoặc thay đổi Level.')
