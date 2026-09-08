"""Explicit v2 fixture migration authorized by the owner; no runtime stubs."""
import json
import re
from tc import api
from tc.evidence import parse_packet


def bind_packet(task, db_path, text):
    root = db_path.parent.parent
    path = root / 'behavior.txt'
    if not path.exists():
        path.write_text('controlled fixture behavior\n')
    # Old prose criterion names become stable fixture IDs; expected/observed
    # behaviors and every test assertion remain intact.
    text = re.sub(r'(?m)^CRITERION: (.+)$', lambda m: 'CRITERION: ' + re.sub(r'[^A-Za-z0-9_-]', '_', m[1]), text)
    records = parse_packet(text)['records']
    contract = {'schemaVersion': 2, 'criteria': [{'id': r['criterion'], 'expected': r['expected']} for r in records], 'sources': ['behavior.txt']}
    api.update_task(task_id=task['id'], metadata={'acceptanceContract': contract}, db_path=db_path)
    identity = api.capture_qa_identity(task_id=task['id'], db_path=db_path)['identity_line']
    return re.sub(r'(?m)^IDENTITY:.*$', lambda _: identity, text)
