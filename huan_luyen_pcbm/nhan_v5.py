"""PCBM v5: evidence-qualified labels, additive (does not replace v4)."""
from datetime import timedelta

SCHEMA_VERSION = '5.0-experimental'


def _events(events, decision, types, after=None, through=None):
    xs = []
    for e in events:
        if e.get('user_id') != decision.get('user_id') or e.get('occurrence_id') != decision.get('occurrence_id'):
            continue
        if e.get('event_type') not in types:
            continue
        t = e.get('timestamp')
        if t is None or (after is not None and t <= after) or (through is not None and t > through):
            continue
        xs.append(e)
    return sorted(xs, key=lambda e: (e['timestamp'], str(e.get('event_id', ''))))


def _is_eligible_spontaneous(e):
    data = e.get('data') or {}
    return (e.get('event_type') == 'USER_REMEMBERED' and
            data.get('evidence_source') in ('self_initiated_report', 'user_initiated_action') and
            data.get('is_demo') is not True and data.get('simulation') is not True)


def tao_nhan_v5(events, decision, observation_end, *, previous_prompt_time=None):
    """Return evidence-aware labels at an observed decision point.

    observation_end: latest trustworthy event observation time (not the wall clock of evaluation).
    previous_prompt_time: latest actual prompt before current decision if known; absence
      prevents positive independent recall inference unless the whole task history is available.
    Unknown is None (never treated as negative automatically).
    """
    t = decision['timestamp']
    if observation_end < t:
        raise ValueError('observation_end must be >= decision timestamp')
    reminder_type = str((decision.get('data') or {}).get('reminder_type','')).strip().lower()
    result = {
        'label_schema_version': SCHEMA_VERSION,
        'recall_after_cue': None,
        'independent_recall': None,
        'started_within_10m': None,
        'completed_within_30m': None,
        'label_quality': 'partial',
        'label_reasons': [],
    }
    reasons = result['label_reasons']

    # A generic cue is already an intervention, so it cannot prove no-prompt recall.
    if reminder_type == 'generic':
        cutoff = t + timedelta(minutes=2)
        signals = _events(events, decision, {'RECALL_SUCCESS','RECALL_FAILURE'}, t, min(cutoff, observation_end))
        if signals:
            result['recall_after_cue'] = int(signals[0]['event_type'] == 'RECALL_SUCCESS')
        else:
            reasons.append('no_recall_answer_in_2m' if observation_end >= cutoff else 'recall_window_not_fully_observed')
    else:
        reasons.append('not_a_generic_cue')

    # Positive spontaneous evidence only. Cannot safely infer negative from silence.
    before = _events(events, decision, {'USER_REMEMBERED'}, None, t)
    if previous_prompt_time is not None:
        before = [e for e in before if e['timestamp'] > previous_prompt_time]
    else:
        # Without an observed prompting boundary, do not claim independent recall.
        before = []
    if any(_is_eligible_spontaneous(e) for e in before):
        result['independent_recall'] = 1
    else:
        reasons.append('independent_recall_not_observed')

    for key, types, minutes in (
        ('started_within_10m', {'TASK_STARTED'}, 10),
        ('completed_within_30m', {'TASK_COMPLETED'}, 30),
    ):
        end = t + timedelta(minutes=minutes)
        hits = _events(events, decision, types, t, min(end, observation_end))
        if hits:
            result[key] = 1
        elif observation_end >= end:
            result[key] = 0  # Only if followup coverage is explicitly verified.
        else:
            reasons.append(f'{key}_censored')

    # Observation end alone cannot establish continuous monitoring; the caller must
    # provide an independently verified coverage flag before treating non-events as 0.
    if result['recall_after_cue'] is not None and result['completed_within_30m'] is not None:
        result['label_quality'] = 'observed'
    return result


def ap_dung_kiem_tra_coverage(label, *, observed_continuously=False):
    """Fail closed on absence-of-event negatives when the monitoring window was not verified."""
    out = dict(label)
    out['label_reasons'] = list(label.get('label_reasons', []))
    if not observed_continuously:
        for key in ('started_within_10m', 'completed_within_30m'):
            if out.get(key) == 0:
                out[key] = None
                out['label_reasons'].append(f'{key}_no_verified_coverage')
        out['label_quality'] = 'partial'
    return out
