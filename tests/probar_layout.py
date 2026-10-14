import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos_informe
A, db, ids, admin = datos_informe.preparar()
F = datos_informe.FALSO
c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
c.get('/')
pid = F.con.execute('SELECT id FROM protocolos ORDER BY id LIMIT 1').fetchone()[0]
r = c.get(f'/protocolo/{pid}')
h = r.get_data(as_text=True)
print(r.status_code)
i = {k: h.find(k) for k in ('Paciente</h2>', 'datos-fila', '<h2>Estudios', 'Comentarios del protocolo', 'Vuelta al sistema', '<h2>Historial')}
print(i)
print(sorted(i, key=i.get))
