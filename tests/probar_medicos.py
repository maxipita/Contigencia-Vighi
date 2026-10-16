import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar

A, db, ids, admin = preparar()

fallas = []


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


def cliente(uid):
    c = A.app.test_client()
    with c.session_transaction() as s:
        s['uid'] = uid
    c.get('/')
    with c.session_transaction() as s:
        return c, s['csrf']


def medico(nombre):
    with A.app.app_context():
        return db.uno("SELECT * FROM medicos WHERE nombre=?", (nombre,))


c, tk = cliente(admin)
with A.app.app_context():
    ub = db.ex("INSERT INTO ubicaciones (abreviatura, nombre) VALUES ('CLIMED','Clínica Médica')")
    ub2 = db.ex("INSERT INTO ubicaciones (abreviatura, nombre) VALUES ('SANMED','Sanatorio Médico')")
    db.ex("INSERT INTO medicos (nombre) VALUES ('GARCIA, Ana')")

print('1) lista y alta')
r = c.get('/medicos')
h = r.get_data(as_text=True)
chequear('la lista abre y ofrece el alta', r.status_code == 200 and 'Nuevo médico' in h and 'GARCIA, Ana' in c.get('/medicos?q=garcia+ana').get_data(as_text=True))
chequear('aparece en Configuraciones y en el menú', 'medicos' in c.get('/configuraciones').get_data(as_text=True) and '/medicos' in h)
r = c.post('/medicos/nuevo', data={'_csrf': tk, 'nombre': '', 'email': ''})
chequear('sin nombre no se crea', r.status_code == 200 and 'Falta el nombre' in r.get_data(as_text=True))
r = c.post('/medicos/nuevo', data={'_csrf': tk, 'nombre': '  PEREZ,   Juan  ', 'email': 'JPerez@Correo.com'})
m = medico('PEREZ, Juan')
chequear('crea el médico con el nombre limpio y el e-mail en minúsculas', r.status_code == 302 and m and m['email'] == 'jperez@correo.com', m and dict(m))
r = c.post('/medicos/nuevo', data={'_csrf': tk, 'nombre': 'pérez juan', 'email': ''})
chequear('rechaza un nombre repetido aunque cambien tildes, mayúsculas y coma', r.status_code == 200 and 'Ya existe' in r.get_data(as_text=True))
r = c.post('/medicos/nuevo', data={'_csrf': tk, 'nombre': 'LOPEZ, Maria', 'email': 'no-es-mail'})
chequear('rechaza un e-mail inválido', r.status_code == 200 and 'e-mail no es válido' in r.get_data(as_text=True))

print('2) alta desde una ubicación')
h = c.get(f'/ubicaciones/{ub}').get_data(as_text=True)
chequear('la ubicación ofrece crear el médico', f'/medicos/nuevo?ubicacion={ub}' in h)
r = c.get(f'/medicos/nuevo?ubicacion={ub}')
chequear('el formulario avisa a qué ubicación se asocia', r.status_code == 200 and 'CLIMED' in r.get_data(as_text=True))
r = c.post('/medicos/nuevo', data={'_csrf': tk, 'nombre': 'RUIZ, Pedro', 'email': '', 'ubicacion': str(ub)})
m2 = medico('RUIZ, Pedro')
with A.app.app_context():
    asoc = db.uno("SELECT 1 FROM ubicacion_medicos WHERE ubicacion_id=? AND medico_id=?", (ub, m2['id']))
chequear('lo crea y lo asocia, y vuelve a la ubicación', r.status_code == 302 and f'/ubicaciones/{ub}' in r.headers['Location'] and asoc is not None)

print('3) ficha: editar, asociar, quitar')
mid = m['id']
h = c.get(f'/medicos/{mid}').get_data(as_text=True)
chequear('la ficha abre', 'PEREZ, Juan' in h and 'jperez@correo.com' in h)
with A.app.app_context():
    db.ex("INSERT INTO protocolos (numero, nombre, apellido, medico, borrador, creado_en) VALUES ('C990001','A','B','PEREZ, Juan',0,?)", (db.ahora(),))
r = c.post(f'/medicos/{mid}/editar', data={'_csrf': tk, 'nombre': 'PEREZ, Juan Carlos', 'email': ''})
with A.app.app_context():
    p = db.uno("SELECT medico FROM protocolos WHERE numero='C990001'")
chequear('al renombrarlo se actualiza el nombre en sus protocolos', r.status_code == 302 and medico('PEREZ, Juan Carlos') and p['medico'] == 'PEREZ, Juan Carlos', p and dict(p))
chequear('puede dejar el e-mail vacío', medico('PEREZ, Juan Carlos')['email'] is None)
r = c.post(f'/medicos/{mid}/editar', data={'_csrf': tk, 'nombre': 'GARCIA, ana', 'email': ''}, follow_redirects=True)
chequear('no se puede renombrar a uno que ya existe', 'Ya existe' in r.get_data(as_text=True) and medico('PEREZ, Juan Carlos'))
c.post(f'/medicos/{mid}/ubicacion', data={'_csrf': tk, 'ubicacion': 'CLIMED'})
c.post(f'/medicos/{mid}/ubicacion', data={'_csrf': tk, 'ubicacion': 'SANMED'})
r = c.post(f'/medicos/{mid}/ubicacion', data={'_csrf': tk, 'ubicacion': 'CLIMED'}, follow_redirects=True)
with A.app.app_context():
    n = db.uno("SELECT COUNT(*) AS n FROM ubicacion_medicos WHERE medico_id=?", (mid,))['n']
chequear('asocia a dos ubicaciones y no repite', n == 2 and 'Ya está asociado' in r.get_data(as_text=True), n)
r = c.post(f'/medicos/{mid}/ubicacion', data={'_csrf': tk, 'ubicacion': 'NOEXISTE'}, follow_redirects=True)
chequear('una ubicación inexistente se rechaza', 'No encontré esa ubicación' in r.get_data(as_text=True))
c.post(f'/medicos/{mid}/ubicaciones/quitar', data={'_csrf': tk, 'ubicacion': [str(ub2)]})
with A.app.app_context():
    n = db.uno("SELECT COUNT(*) AS n FROM ubicacion_medicos WHERE medico_id=?", (mid,))['n']
chequear('quita las ubicaciones marcadas', n == 1, n)

print('4) búsqueda y eliminación')
h = c.get('/medicos?q=perez').get_data(as_text=True)
chequear('busca sin tildes ni mayúsculas', 'PEREZ, Juan Carlos' in h and 'GARCIA' not in h)
c.post(f'/medicos/{mid}/editar', data={'_csrf': tk, 'nombre': 'PEREZ, Juan Carlos', 'email': 'jperez@correo.com'})
h = c.get('/medicos?q=jperez').get_data(as_text=True)
chequear('también busca por e-mail', 'PEREZ, Juan Carlos' in h and 'GARCIA' not in h)
r = c.post(f'/medicos/{mid}/eliminar', data={'_csrf': tk}, follow_redirects=True)
chequear('no se elimina con protocolos', 'No se puede eliminar' in r.get_data(as_text=True) and medico('PEREZ, Juan Carlos'))
with A.app.app_context():
    db.ex("DELETE FROM protocolos WHERE numero='C990001'")
c.post(f'/medicos/{mid}/eliminar', data={'_csrf': tk})
with A.app.app_context():
    sobra = db.uno("SELECT 1 FROM ubicacion_medicos WHERE medico_id=?", (mid,))
chequear('sin protocolos se elimina junto con sus asociaciones', medico('PEREZ, Juan Carlos') is None and sobra is None)
nombres = c.get('/api/medicos').get_json()
chequear('los médicos nuevos salen en las sugerencias del protocolo', 'RUIZ, Pedro' in nombres and 'PEREZ, Juan Carlos' not in nombres)

print('5) permisos')
with A.app.app_context():
    sin = db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, debe_cambiar_clave) VALUES ('ZZMD','Sin Permiso','',0,1,0)")
cs, tks = cliente(sin)
chequear('sin el permiso puede ver la lista pero no el alta', cs.get('/medicos').status_code == 200 and cs.get('/medicos/nuevo').status_code == 302)
cs.post('/medicos/nuevo', data={'_csrf': tks, 'nombre': 'INTRUSO, Ian', 'email': ''})
chequear('y no crea ni edita', medico('INTRUSO, Ian') is None)
r = cs.post(f"/medicos/{m2['id']}/editar", data={'_csrf': tks, 'nombre': 'OTRO, Nombre', 'email': ''})
chequear('no edita', medico('RUIZ, Pedro') is not None and medico('OTRO, Nombre') is None)
with A.app.app_context():
    chequear('las altas y bajas quedaron en el historial', db.uno("SELECT 1 FROM auditoria WHERE accion='medico' AND detalle LIKE 'Alta:%'") is not None
             and db.uno("SELECT 1 FROM auditoria WHERE accion='medico' AND detalle LIKE 'Baja:%'") is not None)
print('FALLAS:', fallas or 'ninguna')
