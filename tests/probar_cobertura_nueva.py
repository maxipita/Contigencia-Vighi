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

print('FALLAS:', ', '.join(fallas) if fallas else 'ninguna')
