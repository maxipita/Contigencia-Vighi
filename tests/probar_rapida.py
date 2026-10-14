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
pid = F.con.execute('SELECT id FROM protocolos WHERE borrador=0 ORDER BY id LIMIT 1').fetchone()[0]
h = c.get(f'/protocolo/{pid}').get_data(as_text=True)
print('form', 'name="apellido"' in h, 'data-editar' in h, 'name="cobertura"' in h)
r = c.post(f'/protocolo/{pid}/datos', data={'_csrf': csrf, 'apellido': 'Nuevo', 'nombre': 'Cambio', 'fecha_nacimiento': '1980-05-06', 'cobertura': 'OSDE',
                                             'medico': 'PEREZ, JUAN', 'lugar_recoleccion': 'Sede X', 'fecha_recoleccion': '2026-10-08'})
print(r.status_code, r.headers.get('Location'))
p = dict(F.con.execute('SELECT * FROM protocolos WHERE id=?', (pid,)).fetchone())
print({k: p[k] for k in ('apellido', 'nombre', 'fecha_nacimiento', 'cobertura', 'medico', 'lugar_recoleccion', 'fecha_recoleccion', 'dni')})
print([tuple(x) for x in F.con.execute("SELECT accion, detalle FROM auditoria WHERE protocolo_id=? ORDER BY id DESC LIMIT 1", (pid,)).fetchall()])
h = c.get(f'/protocolo/{pid}').get_data(as_text=True)
print('Nuevo, Cambio' in h, '(1980)' in h)
r = c.post(f'/protocolo/{pid}/datos', data={'_csrf': 'mal'})
print('csrf mal', r.status_code)
bor = F.con.execute('SELECT id FROM protocolos WHERE borrador=1 LIMIT 1').fetchone()
if bor:
    r = c.post(f'/protocolo/{bor[0]}/datos', data={'_csrf': csrf, 'apellido': 'X'})
    print('borrador ->', r.headers.get('Location'))
h = c.get(f'/protocolo/{pid}').get_data(as_text=True)
print('formularios', h.count('class="edicion"'), 'lapices', h.count('data-editar'), 'cancelar', h.count('data-cancelar'), 'campos', all(k in h for k in ('name="apellido"', 'name="cobertura"', 'name="medico"', 'name="fecha_recoleccion"')))
print('viejos', 'Editar rápido' in h, 'Todos los datos' in h)
r = c.post(f'/protocolo/{pid}/datos', data={'_csrf': csrf, 'cobertura': 'OSDE'})
p = dict(F.con.execute('SELECT * FROM protocolos WHERE id=?', (pid,)).fetchone())
print('solo cobertura:', p['apellido'], p['medico'], p['cobertura'])
r = c.post(f'/protocolo/{pid}/datos', data={'_csrf': csrf, 'medico': 'LOPEZ, ANA'})
p = dict(F.con.execute('SELECT * FROM protocolos WHERE id=?', (pid,)).fetchone())
print('solo medico:', p['apellido'], p['medico'], p['cobertura'])
