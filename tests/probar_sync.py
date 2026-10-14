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
def fila(pid):
    r = F.con.execute('SELECT apellido, nombre, cobertura, email, medico, dni FROM protocolos WHERE id=?', (pid,)).fetchone()
    return tuple(r)
F.con.execute("UPDATE protocolos SET email='a@x' WHERE id=2")
print('antes', fila(1), fila(2))
c.post('/protocolo/1/datos', data={'_csrf': csrf, 'apellido': 'Reciente', 'nombre': 'Nuevo'})
print('rapido nombre', fila(1), fila(2), fila(6))
c.post('/protocolo/1/datos', data={'_csrf': csrf, 'medico': 'SOLO DE ESTE'})
print('medico no se propaga', fila(1)[4], fila(2)[4])
c.post('/protocolo/1/datos', data={'_csrf': csrf, 'cobertura': 'PAMI'})
print('cobertura', fila(2)[:3])
F.con.execute("UPDATE protocolos SET dni='99' WHERE id=3")
print('dni distinto intacto', fila(3), fila(1)[:2])
