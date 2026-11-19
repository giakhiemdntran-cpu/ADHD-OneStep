"""PCBM Human-in-the-loop: conservative approval policy (experimental).
Pure functions, intentionally no model re-training or hidden automatic changes.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class SupportDecision:
    current_level: int
    recommended_level: int
    final_level: int
    action: str
    accepted: bool
    reason: str
    needs_confirmation: bool = False


def decide_support(current_level, recommended_level, action, *,
                   independently_validated=False, evidence_of_independence=False):
    """actions: accept, keep, request_more, request_less, undecided.
    Reduction requires separately validated evidence AND explicit agreement.
    Default is conservative (no reduction); direct increase requests remain user-led.
    """
    current = max(0, min(2, int(current_level)))
    recommended = max(0, min(2, int(recommended_level)))
    if action not in {'accept', 'keep', 'request_more', 'request_less', 'undecided'}:
        raise ValueError('Unsupported response')
    if action in ('keep', 'undecided'):
        return SupportDecision(current, recommended, current, action, False,
                               'Người dùng muốn giữ nguyên hoặc chưa chắc. Không thay đổi mức hỗ trợ.')
    if action == 'request_more':
        new = min(2, current + 1)
        return SupportDecision(current, recommended, new, action, new != current,
                               'Người dùng chủ động yêu cầu hỗ trợ thêm.')
    if action == 'request_less':
        return SupportDecision(current, recommended, current, action, False,
                               'Đã ghi nhận mong muốn giảm nhắc; cần xem xét riêng bằng chứng an toàn trước khi giảm.')
    if recommended < current:
        if not (independently_validated and evidence_of_independence):
            return SupportDecision(current, recommended, current, action, False,
                'Chưa có bằng chứng kiểm thử độc lập và hành vi ổn định; không giảm hỗ trợ dù người dùng đồng ý.')
        return SupportDecision(current, recommended, recommended, action, True,
                               'Đã xác nhận, có kiểm thử độc lập và bằng chứng hành vi ổn định.')
    if recommended > current:
        return SupportDecision(current, recommended, recommended, action, True,
                               'Người dùng đã đồng ý với đề xuất tăng hỗ trợ.')
    return SupportDecision(current, recommended, current, action, True,
                           'Giữ mức hỗ trợ được đề xuất.')
