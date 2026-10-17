import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar
from werkzeug.security import generate_password_hash

A, db, ids, admin = preparar()
fallas = []


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


with A.app.app_context():
    db.ex("UPDATE usuarios SET clave_hash=? WHERE id=?", (generate_password_hash('clave-admin'), admin))
    otro = db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, debe_cambiar_clave, clave_hash) "
                 "VALUES ('ZZLOG','Login Test','ingreso',0,1,0,?)", (generate_password_hash('clave-correcta'),))


def cliente():
    c = A.app.test_client()
    c.get('/login')
    with c.session_transaction() as s:
        return c, s['csrf']


def intentar(c, tk, ini, clave):
    return c.post('/login', data={'_csrf': tk, 'iniciales': ini, 'clave': clave}, follow_redirects=False)


print('1) bloqueo tras varios intentos fallidos')
c, tk = cliente()
for i in range(5):
    r = intentar(c, tk, 'ZZLOG', 'mala')
    chequear(f'intento fallido {i + 1} no bloquea todavía', 'Demasiados intentos' not in r.get_data(as_text=True))
r = intentar(c, tk, 'ZZLOG', 'mala')
chequear('el 6to intento fallido bloquea', 'Demasiados intentos' in r.get_data(as_text=True))
r = intentar(c, tk, 'ZZLOG', 'clave-correcta')
chequear('bloqueado, ni con la clave correcta deja entrar', 'Demasiados intentos' in r.get_data(as_text=True))

print('2) el bloqueo es por usuario, no global')
c2, tk2 = cliente()
r = intentar(c2, tk2, 'ZZADM', 'mala')
chequear('otro usuario no está bloqueado', 'Demasiados intentos' not in r.get_data(as_text=True))
r = intentar(c2, tk2, 'ZZADM', 'clave-admin')
chequear('y puede entrar con su clave', r.status_code == 302 and '/login' not in r.headers.get('Location', ''))

print('3) se destraba con el tiempo, y al entrar se borra el registro')
with A.app.app_context():
    pasado = (datetime.now() - timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M:%S')
    db.ex("UPDATE intentos_login SET bloqueado_hasta=? WHERE iniciales='ZZLOG'", (pasado,))
r = intentar(c, tk, 'ZZLOG', 'clave-correcta')
chequear('pasado el bloqueo, la clave correcta entra', r.status_code == 302 and '/login' not in r.headers.get('Location', ''))
with A.app.app_context():
    chequear('al entrar se borra el registro de intentos', db.uno("SELECT 1 FROM intentos_login WHERE iniciales='ZZLOG'") is None)

print('FALLAS:', fallas or 'ninguna')
