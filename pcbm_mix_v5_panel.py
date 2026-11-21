"""One-click training of the three PCBM v5 targets, research-only."""
import json
import pandas as pd
import streamlit as st
from huan_luyen_pcbm.pcbm_mix_v5 import run_experiment, TARGETS
from huan_luyen_pcbm.pcbm_dataset_v5_2 import generate_dataset


def render_pcbm_mix_v5(db_path, key_prefix="pcbm_v5_train_all"):
    st.subheader("🧠 Huấn luyện 3 mục tiêu PCBM v5")
    st.caption("Recall sau gợi ý (chuẩn hóa từ v4) · ITI chủ động bắt đầu · Completion 30 phút có kiểm chứng")
    st.info("Một nút chạy pipeline cho cả ba mục tiêu. Mô hình chưa đủ hai lớp nhãn sẽ báo lý do, không tạo AUC giả. Model Buddy hiện tại không bị thay đổi.")
    # Single primary action: run real-only first; if no eligible binary labels anywhere,
    # explicitly switch to a clearly flagged DEMO technical run.
    if st.button("🚀 Huấn luyện 3 mô hình PCBM v5", key=f"{key_prefix}_run_all", type="primary", use_container_width=True):
        try:
            with st.spinner("Đang tạo nhãn và đánh giá ba mục tiêu..."):
                manifest, audited_df = generate_dataset(db_path, output_dir="data/pcbm_v5_2")
                report, df = run_experiment(db_path, method="user", exclude_demo=True, dataset_df=audited_df)
                usable = sum(v.get("eligible_after_filter", 0) for v in report["targets"].values())
                if usable == 0:
                    report, df = run_experiment(db_path, method="user", exclude_demo=False, dataset_df=audited_df)
                    report["automatic_demo_fallback"] = True
                else:
                    report["automatic_demo_fallback"] = False
            st.session_state[f"{key_prefix}_result"] = (report, df)
            st.session_state[f"{key_prefix}_manifest"] = manifest
        except Exception as exc:
            st.error(f"Không thể huấn luyện: {exc}")
            return
    saved = st.session_state.get(f"{key_prefix}_result")
    if saved is None:
        st.caption("Nhấn nút phía trên để tạo nhãn, train trên dữ liệu phù hợp và xem Confusion Matrix ngay tại đây.")
        return
    report, df = saved
    manifest = st.session_state.get(f"{key_prefix}_manifest", {})
    if manifest:
        st.markdown('#### Kiểm soát chất lượng bộ dữ liệu huấn luyện v5.2')
        s1,s2,s3,s4=st.columns(4)
        s1.metric('Số sự kiện',f"{manifest.get('rows_events',0):,}")
        s2.metric('Dòng gán nhãn',f"{manifest.get('rows_decisions',0):,}")
        s3.metric('Dòng demo',f"{manifest.get('demo_records',0):,}")
        s4.metric('Người dùng',f"{manifest.get('unique_users',0):,}")
        st.caption('Bộ dữ liệu mới đã lưu trong data/pcbm_v5_2/. Ba mục tiêu được phân biệt: Recall sau gợi ý; ITI trước lời nhắc; Completion có kiểm chứng.')
        st.dataframe(pd.DataFrame([{'Mục tiêu':t['name'], 'Nhãn 1':t['positive'],'Nhãn 0':t['negative'],'Unknown':t['unknown']} for t in manifest.get('targets',{}).values()]),hide_index=True,use_container_width=True)
        if manifest.get('status')=='TECHNICAL_DEMO_ONLY':
            st.error('Toàn bộ dataset hiện tại là TEST/DEMO. Chỉ sử dụng để thử kỹ thuật, không dùng làm minh chứng trên học sinh thật.')
    if report.get("automatic_demo_fallback"):
        st.error("⚠️ Chỉ có dữ liệu DEMO/TEST đáp ứng bước lọc. Kết quả sau đây là KIỂM THỬ KỸ THUẬT, không phải bằng chứng hiệu quả trên học sinh thực tế.")
    else:
        st.success("Đã thực hiện huấn luyện/đánh giá với các nhãn hợp lệ không thuộc dữ liệu demo; kiểm tra chi tiết từng mô hình bên dưới.")
    st.caption(f"Nguồn: {report['events']:,} sự kiện · {report['records']:,} quyết định · tách tập theo người dùng · chưa phải kiểm định triển khai thực tế")
    summary=[]
    for target, r in report['targets'].items():
        summary.append({
            'Mục tiêu':r['name'], 'Nhãn 1':r['positives'], 'Nhãn 0':r['negatives'],
            'Unknown':r['unknown'], 'Mẫu dùng train/test':r['eligible_after_filter'],
            'ROC-AUC':round(r['roc_auc'],3) if r['status']=='evaluated' else 'N/A',
            'PR-AUC':round(r['pr_auc'],3) if r['status']=='evaluated' else 'N/A',
            'Recall':f"{r['recall']:.1%}" if r['status']=='evaluated' else 'N/A',
            'F1':round(r['f1'],3) if r['status']=='evaluated' else 'N/A',
            'Trạng thái':'Đã train & đánh giá' if r['status']=='evaluated' else 'Chưa thể train',
        })
    st.dataframe(pd.DataFrame(summary), use_container_width=True, hide_index=True)
    for target,r in report['targets'].items():
        st.markdown(f"#### {r['name']}")
        if r['status']!='evaluated':
            st.warning(r.get('reason','Chưa đủ dữ liệu hợp lệ.'))
            if target == 'y_independent_task_initiation':
                st.caption('Cần log TASK_STARTED/USER_REMEMBERED trước lời nhắc, có evidence_source và xác nhận thời gian quan sát; không chuyển Unknown thành 0.')
            elif target == 'y_complete_within_30m_verified':
                st.caption('Cần các phiên có xác nhận quan sát đầy đủ 30 phút không hoàn thành, để tạo lớp 0 được kiểm chứng.')
            continue
        a,b,c,d=st.columns(4)
        a.metric('ROC-AUC',f"{r['roc_auc']:.3f}")
        b.metric('PR-AUC',f"{r['pr_auc']:.3f}")
        c.metric('Recall',f"{r['recall']:.1%}")
        d.metric('Precision',f"{r['precision']:.1%}")
        a,b,c,d=st.columns(4)
        a.metric('F1',f"{r['f1']:.3f}")
        b.metric('Balanced Accuracy',f"{r['balanced_accuracy']:.1%}")
        tn,fp=r['confusion_matrix'][0]; fn,tp=r['confusion_matrix'][1]
        total=tn+fp+fn+tp
        c.metric('Accuracy',f"{(tn+tp)/total:.1%}" if total else 'N/A')
        d.metric('Test samples',str(r['test_n']))
        st.write('**Confusion Matrix trên tập kiểm thử:**')
        st.dataframe(pd.DataFrame([[tn,fp],[fn,tp]],index=['Thực tế 0','Thực tế 1'],columns=['Dự đoán 0','Dự đoán 1']),use_container_width=False)
        st.caption(f"TN={tn} · FP={fp} · FN={fn} · TP={tp}; số user trùng train/test={r['user_overlap']}; lưu model: {r.get('saved_model') or 'chưa lưu'}")
    st.download_button('⬇️ Tải báo cáo huấn luyện JSON',json.dumps(report,ensure_ascii=False,indent=2,default=str),file_name='pcbm_v5_train_all_report.json',mime='application/json',key=f'{key_prefix}_download')
    if df is not None and not df.empty:
        with st.expander('Kiểm tra nhãn & nguồn bằng chứng (100 dòng đầu)'):
            show=[x for x in ['user_id','occurrence_id','decision_time','is_demo','y_cue_assisted_recall','y_independent_task_initiation','y_complete_within_30m_verified','label_reason'] if x in df.columns]
            st.dataframe(df[show].head(100),use_container_width=True,hide_index=True)
    st.caption('Không tự động thay đổi Level, không đụng model Buddy v4, không diễn giải PCBM là công cụ chẩn đoán ADHD.')
