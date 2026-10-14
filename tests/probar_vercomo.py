import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos_informe
from werkzeug.datastructures import MultiDict
A, db, ids, admin = datos_informe.preparar()
F = datos_informe.FALSO
fallas = []
def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok: fallas.append(n)

def cliente(uid):
    c = A.app.test_client()
    with c.session_transaction() as s:
        s['uid'] = uid
    c.get('/')
    with c.session_transaction() as s:
        t = s['csrf']
    return c, t

def post(c, t, url, datos=None):
    return c.post(url, data=MultiDict([('_csrf', t)] + list((datos or {}).items())), follow_redirects=True)

ing = F.con.execute("SELECT id FROM usuarios WHERE iniciales='ZZADM'").fetchone()
F.con.execute("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, debe_cambiar_clave) VALUES ('ZZING','Ingreso Prueba','ingreso',0,1,1)")
F.con.execute("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, debe_cambiar_clave) VALUES ('ZZINA','Inactivo','ingreso',0,0,0)")
uid = F.con.execute("SELECT id FROM usuarios WHERE iniciales='ZZING'").fetchone()['id']
ina = F.con.execute("SELECT id FROM usuarios WHERE iniciales='ZZINA'").fetchone()['id']
perfil = F.con.execute("SELECT id FROM perfiles WHERE nombre='Ingreso'").fetchone()['id']
F.con.execute("UPDATE usuarios SET perfil_id=? WHERE id=?", (perfil, uid))
otro = F.con.execute("SELECT id FROM usuarios WHERE iniciales='DM'").fetchone()['id']

c, t = cliente(admin)
h = c.get('/usuarios').get_data(as_text=True)
chequear('la lista de usuarios ya NO tiene el botón (evita clics por error)', 'ver-como' not in h and 'Ver como' not in h)
h = c.get(f'/usuarios/{uid}').get_data(as_text=True)
chequear('el botón está dentro de Editar usuario', f'/usuarios/{uid}/ver-como' in h and 'Ver como ZZING' in h and 'data-confirmar' in h)
h = c.get(f'/usuarios/{admin}').get_data(as_text=True)
chequear('no se ofrece verse como uno mismo', 'ver-como' not in h)
h = c.get(f'/usuarios/{ina}').get_data(as_text=True)
chequear('ni como un usuario inactivo', 'ver-como' not in h)

r = post(c, t, f'/usuarios/{uid}/ver-como')
h = r.get_data(as_text=True)
chequear('entra viendo como el usuario', 'Viendo el sistema como Ingreso Prueba' in h and 'Volver a mi usuario' in h and 'solo para mirar' in h)
chequear('no obliga a cambiar la clave temporal del usuario visto', r.request.path == '/')
chequear('ve lo que ve ese usuario: sin Facturación ni menú de administración', 'title="Facturación"' not in h and 'Perfiles y permisos' not in h and 'Listados' not in h)
chequear('sí ve lo suyo (Por completar)', 'title="Por completar"' in h)
chequear('las pantallas de administración quedan vedadas', c.get('/usuarios').status_code == 403 and c.get('/listados').status_code == 403)

r = post(c, t, '/protocolo/1/datos', {'medico': 'CAMBIO NO PERMITIDO'})
chequear('en modo vista no se guardan cambios (formularios)', 'solo para mirar' in r.get_data(as_text=True) and
         F.con.execute("SELECT medico FROM protocolos WHERE id=1").fetchone()['medico'] != 'CAMBIO NO PERMITIDO')
r = c.post('/api/etiquetas/confirmar', json={'tipo': 'lab', 'items': []}, headers={'X-CSRF': t})
chequear('ni por el API', r.status_code == 403 and 'solo es para mirar' in (r.get_json() or {}).get('error', '') or r.status_code == 403)

r = post(c, t, f'/usuarios/{otro}/ver-como')
chequear('se puede cambiar de usuario sin volver', 'Viendo el sistema como' in r.get_data(as_text=True) and 'Ingreso Prueba' not in r.get_data(as_text=True).split('Viendo el sistema como', 1)[1][:60])
chequear('quedó auditado quién miró a quién', F.con.execute("SELECT COUNT(*) AS n FROM auditoria WHERE accion='ver_como'").fetchone()['n'] >= 2)

r = post(c, t, '/dejar-de-ver-como')
h = r.get_data(as_text=True)
chequear('vuelve a su usuario', 'Volviste a tu usuario' in h and 'Viendo el sistema como' not in h)
chequear('de nuevo puede administrar y escribir', c.get('/usuarios').status_code == 200)
with c.session_transaction() as s:
    chequear('la sesión ya no guarda la suplantación', 'real_uid' not in s and s['uid'] == admin)

F.con.execute('UPDATE usuarios SET debe_cambiar_clave=0 WHERE id=?', (uid,))
c2, t2 = cliente(uid)
r = c2.post(f'/usuarios/{otro}/ver-como', data={'_csrf': t2})
chequear('un usuario que no es administrador no puede usarlo', r.status_code == 403)
with c2.session_transaction() as s:
    s['real_uid'] = uid
r = c2.get('/')
chequear('no se puede falsear real_uid sin ser administrador', 'Viendo el sistema como' not in r.get_data(as_text=True))
r = post(c, t, f'/usuarios/{ina}/ver-como')
chequear('un inactivo no se puede ver', 'no existe o está inactivo' in r.get_data(as_text=True))
print('FALLAS:', fallas)
