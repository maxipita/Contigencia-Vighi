import os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
from datos_informe import preparar

A, db, ids, admin = preparar()
c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
c.get('/')
mala = []
n = 0
with A.app.app_context():
    lote = db.uno("SELECT id FROM lotes LIMIT 1")
    uid = db.uno("SELECT id FROM usuarios LIMIT 1")['id']
for rule in sorted(A.app.url_map.iter_rules(), key=lambda r: r.rule):
    if 'GET' not in rule.methods or rule.endpoint in ('static', 'logout'):
        continue
    url = rule.rule
    args = {a: {'eid': ids['mix_b1'], 'pid': ids['p_mix'], 'uid': uid, 'iid': 1, 'lote_id': (lote['id'] if lote else 1)}.get(a, 1) for a in rule.arguments}
    try:
        url = A.app.url_map.bind('localhost').build(rule.endpoint, args)
    except Exception:
        continue
    r = c.get(url)
    n += 1
    if r.status_code >= 500:
        mala.append((url, r.status_code))
    print(r.status_code, url)
print('\nrutas GET probadas:', n, '| con error 5xx:', mala if mala else 'ninguna')
