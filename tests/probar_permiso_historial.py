import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar

A, db, ids, admin = preparar()
from vighi.core import permisos

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
    return c


with A.app.app_context():
    pid = db.uno("SELECT protocolo_id FROM estudios WHERE id=?", (ids['pendiente'],))['protocolo_id']

print('1) el permiso existe y no viene en ningún perfil')
chequear('«historial» es un permiso', 'historial' in permisos.PERMISOS)
chequear('ningún perfil inicial lo trae', all('historial' not in p for _, p in permisos.PERFILES_INICIALES.values()))

print('2) quien no lo tiene no ve el historial')
for nombre, uid in (('el médico firmante', ids['med']), ('el citotécnico', ids['cito'])):
    c = cliente(uid)
    hp = c.get(f'/protocolo/{pid}').get_data(as_text=True)
    he = c.get(f'/estudio/{ids["pendiente"]}').get_data(as_text=True)
    chequear(f'{nombre} no ve el historial del protocolo ni del estudio', '<h2>Historial</h2>' not in hp and 'Historial del estudio' not in he and 'Historial del flujo' not in he)

print('3) el administrador lo ve sin que nadie se lo dé')
c = cliente(admin)
hp = c.get(f'/protocolo/{pid}').get_data(as_text=True)
he = c.get(f'/estudio/{ids["pendiente"]}').get_data(as_text=True)
chequear('ve el historial del protocolo y del estudio', '<h2>Historial</h2>' in hp and ('Historial del estudio' in he or 'Historial del flujo' in he))

print('4) un usuario común con el permiso lo ve')
with A.app.app_context():
    db.ex("UPDATE usuarios SET permisos_mas='historial' WHERE id=?", (ids['med'],))
    db.olvidar_cache()
c = cliente(ids['med'])
hp = c.get(f'/protocolo/{pid}').get_data(as_text=True)
chequear('con el permiso ve el historial del protocolo', '<h2>Historial</h2>' in hp)

print()
print('FALLAS:', fallas if fallas else 'ninguna')
sys.exit(1 if fallas else 0)
