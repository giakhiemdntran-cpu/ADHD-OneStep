from __future__ import annotations
from datetime import timedelta


def _events(events, user, occ, types, left=None, right=None):
    return sorted((e for e in events
        if e['user_id']==user and e['occurrence_id']==occ
        and e['event_type'] in types
        and (left is None or e['timestamp'] >= left)
        and (right is None or e['timestamp'] <= right)),
        key=lambda e:e['timestamp'])


def xay_dung_nhan(events, decision):
    """Evidence-bound PCBM labels. Null means NOT observed, never failure.

    Anchor REMINDER_SENT -> after-cue recall and verified completion.
    Anchor ITI_WINDOW_OPENED -> self-initiated start before any prompt.
    """
    t=decision['timestamp']; uid=decision['user_id']; occ=decision['occurrence_id']
    kind=decision['event_type']; d=decision.get('data') or {}
    out={'y_recall_success':None, 'y_cue_assisted_recall':None,
         'y_independent_task_initiation':None,
         'y_complete_within_30m_verified':None,
         'y_started_within_10m':None, 'y_start_delay_minutes':None,
         'y_complete_within_30m':None,'y_complete_within_60m':None,
         'y_completion_delay_minutes':None,'y_snooze':None,'y_forgot':None}
    end=t+timedelta(minutes=30)
    if kind == 'ITI_WINDOW_OPENED':
        # Reject any trial already prompted at start, even if task was started later.
        prior=_events(events,uid,occ,{'REMINDER_SENT'},None,t)
        if prior: return out
        prompts=_events(events,uid,occ,{'REMINDER_SENT'},t,end)
        cutoff=prompts[0]['timestamp'] if prompts else end
        starts=_events(events,uid,occ,{'TASK_STARTED'},t,cutoff)
        valid=[e for e in starts if (e.get('data') or {}).get('independent_verified') is True
               and (e.get('data') or {}).get('trigger')=='self_initiated'
               and (e.get('data') or {}).get('source')=='user_action']
        if valid:
            out['y_independent_task_initiation']=1
        elif not prompts:
            closes=_events(events,uid,occ,{'ITI_OBSERVATION_VERIFIED'},end,None)
            for e in closes:
                ed=e.get('data') or {}
                if (str(ed.get('window_event_id'))==str(decision['event_id'])
                    and ed.get('continuous_observation') is True
                    and ed.get('no_unprompted_start') is True
                    and ed.get('reviewed_by') and ed.get('evidence_source')
                    and not starts):
                    out['y_independent_task_initiation']=0
                    break
        return out

    if kind != 'REMINDER_SENT': return out
    reminder_type=str(d.get('reminder_type','')).lower().strip()
    if reminder_type=='generic':
        recall=_events(events,uid,occ,{'RECALL_SUCCESS','RECALL_FAILURE'},t+timedelta(microseconds=1),t+timedelta(minutes=2))
        if recall:
            out['y_cue_assisted_recall']=int(recall[0]['event_type']=='RECALL_SUCCESS')
            out['y_recall_success']=out['y_cue_assisted_recall']
    started=_events(events,uid,occ,{'TASK_STARTED'},t+timedelta(microseconds=1),t+timedelta(minutes=60))
    if started:
        delta=(started[0]['timestamp']-t).total_seconds()/60
        out['y_start_delay_minutes']=round(delta,3)
        out['y_started_within_10m']=int(delta<=10)
    completed=_events(events,uid,occ,{'TASK_COMPLETED'},t+timedelta(microseconds=1),t+timedelta(minutes=180))
    if completed:
        delta=(completed[0]['timestamp']-t).total_seconds()/60
        out['y_completion_delay_minutes']=round(delta,3)
        out['y_complete_within_30m']=int(delta<=30)
        out['y_complete_within_60m']=int(delta<=60)
        if delta<=30: out['y_complete_within_30m_verified']=1
    if out['y_complete_within_30m_verified'] is None:
        closes=_events(events,uid,occ,{'OBSERVATION_WINDOW_VERIFIED'},end,None)
        for e in closes:
            ed=e.get('data') or {}
            if (str(ed.get('reminder_event_id'))==str(decision['event_id'])
                and ed.get('continuous_observation') is True
                and ed.get('verified_no_completion') is True
                and ed.get('reviewed_by') and ed.get('evidence_source')
                and not _events(events,uid,occ,{'TASK_COMPLETED'},t,end)):
                out['y_complete_within_30m_verified']=0
                break
    snooze=_events(events,uid,occ,{'SNOOZE'},t,t+timedelta(minutes=10))
    out['y_snooze']=int(bool(snooze))
    forgot=_events(events,uid,occ,{'USER_FORGOT','USER_REMEMBERED','RECALL_FAILURE','RECALL_SUCCESS'},t,t+timedelta(minutes=10))
    if forgot: out['y_forgot']=int(forgot[0]['event_type'] in {'USER_FORGOT','RECALL_FAILURE'})
    return out
