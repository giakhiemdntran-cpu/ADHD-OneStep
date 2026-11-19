"""Conservative PCBM decision gate. Never confuses in-sample/OOF AUC with independent validation."""
from dataclasses import dataclass
from datetime import datetime, timedelta

@dataclass(frozen=True)
class GateReport:
    eligible_for_decrease: bool
    eligible_for_increase_suggestion: bool
    trustworthy_prediction: bool
    reason: str
    details: dict


def check_gate(evaluation=None, behavior=None, *, independent_validated=False, consent=False,
               is_demo=False, min_recall_auc=0.70, min_recall_samples=100,
               min_observed_tasks=10, min_observation_days=7):
    """Deliberately rejects reduction until an independently validated model is approved.

    Workflow evidence and evaluation are separate gates, not arbitrarily weighted.
    - Walk-forward scores or a fresh temporal holdout alone do NOT assert independent validation.
    - Model AUC alone is NOT sufficient to authorize reducing support.
    """
    evaluation = evaluation or {}
    behavior = behavior or {}
    auc = evaluation.get('roc_auc')
    samples = int(evaluation.get('test_rows') or 0)
    observations = int(behavior.get('observed_tasks') or 0)
    days = int(behavior.get('observation_days') or 0)
    successes = int(behavior.get('independent_starts') or 0)
    errors = []
    if is_demo:
        errors.append('Đây là dữ liệu Demo; không đủ căn cứ để thay đổi hỗ trợ thật.')
    if auc is None or not (min_recall_auc <= float(auc) <= 1.0):
        errors.append('ROC-AUC Recall chưa đạt ngưỡng kiểm tra kỹ thuật hoặc không xác định.')
    if samples < min_recall_samples:
        errors.append('Tập đánh giá chưa đủ số mẫu theo tiêu chí thử nghiệm.')
    if not independent_validated:
        errors.append('Chưa có kiểm định độc lập được xác nhận.')
    if observations < min_observed_tasks or days < min_observation_days:
        errors.append('Lịch sử nhiệm vụ thực tế chưa đủ số lượt/ngày quan sát.')
    if observations and successes / max(1, observations) < 0.8:
        errors.append('Tỷ lệ chủ động bắt đầu chưa đạt tiêu chí thử nghiệm.')
    if not consent:
        errors.append('Người dùng chưa đồng ý giảm mức hỗ trợ.')
    details = dict(roc_auc=auc, test_rows=samples, observed_tasks=observations,
                   observation_days=days, independent_starts=successes,
                   independent_validated=bool(independent_validated), consent=bool(consent),
                   is_demo=bool(is_demo), policy='pcbm_safe_v1_trial')
    return GateReport(not errors, not is_demo, bool(auc is not None and samples >= min_recall_samples and float(auc) >= min_recall_auc),
                      'Đủ điều kiện xem xét thử giảm có giám sát.' if not errors else ' '.join(errors), details)
