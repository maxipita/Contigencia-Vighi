import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos_informe
A, db, ids, admin = datos_informe.preparar()
F = datos_informe.FALSO
c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
c.get('/')
with c.session_transaction() as s:
    csrf = s['csrf']
F.con.execute("UPDATE protocolos SET dni='555' WHERE id=6")
r = c.post('/paciente/1/datos', data={'_csrf': csrf, 'apellido': 'X', 'dni': '555'})
print([tuple(x) for x in F.con.execute("SELECT id, dni, apellido FROM protocolos ORDER BY id").fetchall()][:2], [tuple(x) for x in F.con.execute("SELECT id, dni FROM protocolos WHERE id=6").fetchall()])
r = c.post('/paciente/1/datos', data={'_csrf': csrf, 'apellido': 'X', 'dni': '888'})
print([tuple(x) for x in F.con.execute("SELECT id, dni, apellido FROM protocolos ORDER BY id").fetchall()][:3])
