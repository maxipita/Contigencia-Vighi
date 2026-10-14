import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos_informe
A, db, ids, admin = datos_informe.preparar()
F = datos_informe.FALSO
c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
c.get('/')
for pid in (1, 3):
    h = c.get(f'/paciente/{pid}').get_data(as_text=True)
    print(pid, re.search(r'<h1>(.*?)</h1>', h, re.S).group(1).strip()[:40], h.count('class="muted">') )
