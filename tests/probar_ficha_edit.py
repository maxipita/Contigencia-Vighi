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
h = c.get('/paciente/1').get_data(as_text=True)
print('form', 'name="dni"' in h, 'data-editar' in h, 'protocolo(s)' in h)
r = c.post('/paciente/1/datos', data={'_csrf': csrf, 'apellido': 'Nuevo', 'nombre': 'Completo', 'dni': '30111222', 'sexo': 'Mujer', 'cobertura': 'OSDE',
                                      'fecha_nacimiento': '1970-01-02', 'n_afiliado': '55', 'exento': 'No', 'email': 'a@b.com', 'telefono': '11'})
print(r.status_code)
for pid in (1, 2, 6):
    print(tuple(F.con.execute('SELECT apellido, nombre, sexo, n_afiliado, email, medico FROM protocolos WHERE id=?', (pid,)).fetchone()))
print(F.con.execute("SELECT COUNT(*) FROM auditoria WHERE accion='editar_paciente'").fetchone()[0])
r = c.post('/paciente/1/datos', data={'_csrf': csrf, 'dni': '30111222'})
print('vacio ->', r.status_code, tuple(F.con.execute('SELECT apellido FROM protocolos WHERE id=1').fetchone()))
r = c.post('/paciente/1/datos', data={'_csrf': csrf, 'apellido': 'Otro', 'nombre': 'DNIcambiado', 'dni': '777'})
print('cambio dni', [tuple(x) for x in F.con.execute("SELECT id, dni, apellido FROM protocolos ORDER BY id").fetchall()])
