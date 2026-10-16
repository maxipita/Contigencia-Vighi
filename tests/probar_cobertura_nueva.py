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


def coberturas():
    with A.app.app_context():
        return [r['valor'] for r in db.q("SELECT valor FROM listas WHERE nombre='cobertura' ORDER BY orden")]


c, tk = cliente(admin)
antes = coberturas()

print('1) alta de una cobertura')
h = c.get('/coberturas').get_data(as_text=True)
chequear('la pantalla ofrece crear una cobertura', 'Nueva cobertura' in h and '/coberturas/nueva' in h)
r = c.post('/coberturas/nueva', data={'_csrf': tk, 'nombre': '  FUNDACIÓN   CUERPO Y ALMA '})
chequear('crea la cobertura con el nombre limpio y abre su pantalla', r.status_code == 302 and 'cobertura?c=' in r.headers['Location'], r.headers.get('Location'))
despues = coberturas()
chequear('queda al final de la lista', despues == antes + ['FUNDACIÓN CUERPO Y ALMA'], despues[-3:])
r = c.get('/cobertura', query_string={'c': 'FUNDACIÓN CUERPO Y ALMA'})
chequear('se puede editar (IVA, plazo y tarifa)', r.status_code == 200 and 'FUNDACIÓN CUERPO Y ALMA' in r.get_data(as_text=True))
chequear('figura en la lista de coberturas', 'FUNDACIÓN CUERPO Y ALMA' in c.get('/coberturas').get_data(as_text=True))
with A.app.app_context():
    chequear('queda auditada', db.uno("SELECT 1 FROM auditoria WHERE accion='cobertura' AND detalle LIKE 'Alta:%'") is not None)

print('2) validaciones')
r = c.post('/coberturas/nueva', data={'_csrf': tk, 'nombre': ''}, follow_redirects=True)
chequear('sin nombre no se crea', 'Falta el nombre' in r.get_data(as_text=True) and coberturas() == despues)
r = c.post('/coberturas/nueva', data={'_csrf': tk, 'nombre': 'fundacion cuerpo y alma'}, follow_redirects=True)
chequear('rechaza una repetida aunque cambien tildes y mayúsculas', 'Ya existe' in r.get_data(as_text=True) and coberturas() == despues)

print('3) permisos')
with A.app.app_context():
    sin = db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo) VALUES ('ZZ','Sin permisos','',0,1)")
c2, tk2 = cliente(sin)
r = c2.post('/coberturas/nueva', data={'_csrf': tk2, 'nombre': 'OTRA'})
chequear('sin el permiso de facturación no puede crear', r.status_code in (302, 403) and 'OTRA' not in coberturas())

print('4) el alta no se envía sola mientras se escribe')
h = c.get('/coberturas').get_data(as_text=True)
trozo = h[h.index('coberturas/nueva') - 80:h.index('coberturas/nueva') + 80]
chequear('el formulario de alta no es un filtro de envío automático', 'class="filtros"' not in trozo and 'en-linea' in trozo, trozo)

print('5) baja de una cobertura')
c.post('/coberturas/nueva', data={'_csrf': tk, 'nombre': 'BORRABLE'})
with A.app.app_context():
    db.ex("INSERT INTO cobertura_pago (cobertura, dias) VALUES ('BORRABLE', 30)")
    db.ex("INSERT INTO cobertura_pago (cobertura, dias) VALUES ('EN USO', 30)")
    db.ex("INSERT INTO listas (nombre, orden, valor) VALUES ('cobertura', 999, 'EN USO')")
    db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, cobertura, borrador, creado_por, creado_en) VALUES ('C990001','2026-10-14','Uso','Uno','EN USO',0,?,?)",
          (admin, db.ahora()))
h = c.get('/cobertura', query_string={'c': 'BORRABLE'}).get_data(as_text=True)
chequear('sin usos ofrece eliminar la cobertura', 'Eliminar cobertura' in h and 'disabled' not in h[h.index('Eliminar cobertura') - 120:h.index('Eliminar cobertura')])
r = c.post('/cobertura', data={'_csrf': tk, 'c': 'BORRABLE', 'accion': 'eliminar'})
with A.app.app_context():
    resto = db.uno("SELECT (SELECT COUNT(*) FROM cobertura_pago WHERE cobertura='BORRABLE') AS pago, (SELECT COUNT(*) FROM tarifario_coberturas WHERE cobertura='BORRABLE') AS tarifa")
    auditada = db.uno("SELECT 1 FROM auditoria WHERE accion='cobertura' AND detalle='Baja: BORRABLE'")
chequear('se elimina de la lista y de su configuración', r.status_code == 302 and 'BORRABLE' not in coberturas() and resto['pago'] == 0 and resto['tarifa'] == 0, coberturas()[-3:])
chequear('la baja queda auditada', auditada is not None)
chequear('ya no figura en la lista de la pantalla', 'cobertura?c=BORRABLE' not in c.get('/coberturas').get_data(as_text=True))
chequear('abrir una eliminada da 404', c.get('/cobertura', query_string={'c': 'BORRABLE'}).status_code == 404)
r = c.post('/cobertura', data={'_csrf': tk, 'c': 'EN USO', 'accion': 'eliminar'}, follow_redirects=True)
chequear('una cobertura con protocolos no se elimina', 'EN USO' in coberturas() and 'No se puede eliminar' in r.get_data(as_text=True))

print('FALLAS:', ', '.join(fallas) if fallas else 'ninguna')
