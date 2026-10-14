import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos_informe
A, db, ids, admin = datos_informe.preparar()
F = datos_informe.FALSO
c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
c.get('/')
rows = F.con.execute('SELECT id, numero, dni, apellido, borrador FROM protocolos ORDER BY id').fetchall()
print([tuple(r) for r in rows])
pid = rows[0][0]
F.con.execute("INSERT INTO protocolos (numero, dni, apellido, nombre, borrador, creado_en) VALUES ('ZZ1', ?, ?, 'Otro', 0, '2026-10-01 10:00:00')", (rows[0][2], rows[0][3]))
r = c.get(f'/paciente/{pid}')
h = r.get_data(as_text=True)
print(r.status_code, h.count('<tr'), 'ZZ1' in h, 'Ver informe' in h)
print('enlace' , f'/paciente/{pid}' in c.get(f'/protocolo/{pid}').get_data(as_text=True))
print(c.get('/paciente/9999').status_code)
