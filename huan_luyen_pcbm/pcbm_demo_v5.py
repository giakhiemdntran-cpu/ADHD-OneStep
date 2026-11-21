"""Synthetic PCBM v5 demonstration dataset, kept separate from production.

Exactly 16,993 events (40 synthetic participants, 2,560 task occurrences).
Do not use synthetic metrics as real-world evidence or merge with onestep.db.
"""
from __future__ import annotations
import json
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DEMO_EVENTS = 16993
DEMO_USERS = 40
DEMO_TASKS_PER_USER = 64


def tao_sqlite_demo(path, n_users=DEMO_USERS, n_tasks=DEMO_TASKS_PER_USER,
                    seed=20261121, target_events=DEMO_EVENTS):
    """Create isolated, reproducible SQLite demo with evidential 0/1 targets.

    n_tasks means task occurrences per user, not unique task names.
    Exactly target_events is supported for the default 40 x 64 setting.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    rows = []
    base = datetime(2026, 1, 1, 9)
    task_types = ['homework', 'packing', 'reading', 'exercise', 'routine']
    for j in range(n_tasks):
        for i in range(n_users):
            uid = f'demo_v58_U{i:03d}'
            task_type = task_types[j % len(task_types)]
            task_id = f'{task_type}_{j % 10}'
            occ = f'demo_v58_{i}_{j}'
            # Different calendar days, varied hours to create a realistic temporal history.
            t = base + timedelta(days=j * 2, hours=(i % 7), minutes=(i // 7) * 4)
            ability = (i % 10) / 9.0
            difficulty = [0.00, 0.06, -0.05, 0.04, -0.02][j % 5]
            # Stable user-specific tendencies + stochastic outcomes: NO perfect labels.
            recall_p = max(.12, min(.87, .20 + .62 * ability - difficulty))
            iti_p = max(.09, min(.84, .13 + .61 * ability - difficulty))
            comp_p = max(.10, min(.88, .19 + .63 * ability - difficulty))
            iti_ok = rng.random() < iti_p
            recall_ok = rng.random() < recall_p
            completion_ok = rng.random() < comp_p
            marker = {'synthetic': True, 'dataset': 'DEMO_ONLY_v5.8'}

            def add(event_type, when, payload=None):
                data = {**marker, **(payload or {})}
                rows.append((uid, task_id, occ, event_type,
                             json.dumps(data, ensure_ascii=False),
                             when.isoformat(timespec='seconds')))

            add('TASK_CREATED', t - timedelta(hours=3),
                {'task_type': task_type, 'priority': 1 + j % 3,
                 'estimated_minutes': 10 + (j % 5) * 5})
            # Unprompted observation opens; start and no-start verified by distinct events.
            add('ITI_WINDOW_OPENED', t, {'source': 'SYNTHETIC_DEMO_ONLY'})
            if iti_ok:
                add('TASK_STARTED', t + timedelta(minutes=10),
                    {'source': 'user_action', 'trigger': 'self_initiated',
                     'independent_verified': True})
            else:
                add('ITI_OBSERVATION_VERIFIED', t + timedelta(minutes=30, seconds=1),
                    {'continuous_observation': True, 'no_unprompted_start': True,
                     'reviewed_by': 'synthetic_generator',
                     'evidence_source': 'SYNTHETIC_DEMO_ONLY',
                     'window_event_id': 'PLACEHOLDER'})
            reminder_at = t + timedelta(minutes=31)
            add('REMINDER_SENT', reminder_at,
                {'reminder_type': 'generic', 'prompt_level': 1,
                 'channel': 'Buddy'})
            add('RECALL_SUCCESS' if recall_ok else 'RECALL_FAILURE',
                reminder_at + timedelta(minutes=1))
            if completion_ok:
                add('TASK_COMPLETED', reminder_at + timedelta(minutes=18))
            else:
                add('OBSERVATION_WINDOW_VERIFIED',
                    reminder_at + timedelta(minutes=31),
                    {'continuous_observation': True, 'verified_no_completion': True,
                     'reviewed_by': 'synthetic_generator',
                     'evidence_source': 'SYNTHETIC_DEMO_ONLY',
                     'reminder_event_id': 'PLACEHOLDER'})
    # Six substantive base events per occurrence: 2560 * 6 = 15360.
    # Add 1633 context observations, known before any decision, not target labels.
    extra = target_events - len(rows)
    if extra < 0 or extra > n_users * n_tasks:
        raise ValueError(f'target_events must be between {len(rows)} and {len(rows)+n_users*n_tasks}')
    for j in range(n_tasks):
        for i in range(n_users):
            if extra <= 0:
                break
            uid = f'demo_v58_U{i:03d}'
            task_type = task_types[j % len(task_types)]
            task_id = f'{task_type}_{j % 10}'
            occ = f'demo_v58_{i}_{j}'
            t = base + timedelta(days=j*2, hours=(i % 7), minutes=(i//7)*4)
            rows.append((uid, task_id, occ, 'TASK_CONTEXT_UPDATED',
                         json.dumps({'synthetic':True,'dataset':'DEMO_ONLY_v5.8',
                                     'context': 'scheduled_activity'}, ensure_ascii=False),
                         (t - timedelta(hours=1)).isoformat(timespec='seconds')))
            extra -= 1
        if extra <= 0:
            break
    if len(rows) != target_events:
        raise AssertionError((len(rows), target_events))

    # Generate deterministic event IDs in chronological order, and bind verifications
    # to *real* anchor IDs rather than constructing fake references.
    rows.sort(key=lambda r: (r[5], r[0], r[2], r[3]))
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        con.execute('''CREATE TABLE pcbm_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, task_id TEXT,
          occurrence_id TEXT, event_type TEXT, data_json TEXT, created_at TEXT)''')
        con.executemany('''INSERT INTO pcbm_events
          (user_id, task_id, occurrence_id, event_type, data_json, created_at)
          VALUES (?,?,?,?,?,?)''', rows)
        anchors = {}
        for event_id, occ, event_type in con.execute('''SELECT id, occurrence_id, event_type
             FROM pcbm_events WHERE event_type IN ('REMINDER_SENT','ITI_WINDOW_OPENED')'''):
            anchors[(occ, event_type)] = f'DB{event_id}'
        for event_id, occ, event_type, data_json in con.execute('''SELECT id, occurrence_id,
            event_type, data_json FROM pcbm_events WHERE event_type IN
            ('ITI_OBSERVATION_VERIFIED','OBSERVATION_WINDOW_VERIFIED')''').fetchall():
            data = json.loads(data_json)
            anchor = 'ITI_WINDOW_OPENED' if event_type == 'ITI_OBSERVATION_VERIFIED' else 'REMINDER_SENT'
            field = 'window_event_id' if event_type == 'ITI_OBSERVATION_VERIFIED' else 'reminder_event_id'
            data[field] = anchors[(occ, anchor)]
            con.execute('UPDATE pcbm_events SET data_json=? WHERE id=?',
                        (json.dumps(data, ensure_ascii=False), event_id))
        con.execute('CREATE INDEX idx_demo_user_time ON pcbm_events(user_id,created_at)')
        con.commit()
        count = con.execute('SELECT COUNT(*) FROM pcbm_events').fetchone()[0]
        if count != target_events:
            raise AssertionError((count, target_events))
        return count
    finally:
        con.close()
