import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
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
        tk = s['csrf']
    return c, tk


with A.app.app_context():
    otro = db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, debe_cambiar_clave) VALUES ('ZZED','Otra Persona','',1,1,0)")
    ahora = db.ahora()
    pid = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, borrador, creado_por, creado_en) VALUES ('C000900','2026-10-13',1,?,?)", (admin, ahora))
    db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?)",
          (pid, 'BP', 'Biopsias', 'Digestiva', 'Estómago', 'Biopsia', admin, ahora))
    eid = db.uno("SELECT id FROM estudios WHERE protocolo_id=?", (pid,))['id']

ca, tka = cliente(admin)
cb, tkb = cliente(otro)
URL = f'/protocolo/{pid}/editar'


def token_de(html):
    m = re.search(r'name="edicion" value="([0-9a-f]+)"', html)
    return m.group(1) if m else None


def datos(tk, token, **extra):
    d = {'_csrf': tk, 'numero': 'C000900', 'apellido': 'Prueba', 'nombre': 'Doble', 'e-0-id': str(eid), 'e-0-tipo': 'BP', 'e-0-categoria': 'Biopsias',
         'e-0-subcategoria': 'Digestiva', 'e-0-sitio': 'Estómago', 'e-0-tipo_muestra': 'Biopsia', 'e-0-cantidad': '1', 'e-0-responsable_id': str(ids['med'])}
    if token is not None:
        d['edicion'] = token
    d.update(extra)
    return d


def estudios_activos():
    with A.app.app_context():
        return db.uno("SELECT COUNT(*) AS n FROM estudios WHERE protocolo_id=? AND anulado=0", (pid,))['n']


def es_borrador():
    with A.app.app_context():
        return db.uno("SELECT borrador FROM protocolos WHERE id=?", (pid,))['borrador']


print('1) quien abre el protocolo lo reserva')
h = ca.get(URL).get_data(as_text=True)
ta = token_de(h)
chequear('el formulario trae su marca de edición', ta is not None and 'data-soltar' in h)
r = cb.get(URL)
chequear('otra persona no puede abrirlo y vuelve a "Por completar"', r.status_code == 302 and '/completar' in r.headers['Location'], r.status_code)
h = cb.get(URL, follow_redirects=True).get_data(as_text=True)
chequear('le dice quién lo está completando', 'Administrador' in h or 'está completando este protocolo' in h, h[:200])
h = cb.get('/completar').get_data(as_text=True)
chequear('en la lista figura como "lo está completando"', 'Lo está completando' in h)
h = ca.get('/completar').get_data(as_text=True)
chequear('quien lo tiene sigue viendo el botón Completar', 'Lo está completando' not in h and URL in h)

print('2) quien no tiene la reserva no puede guardar')
r = cb.post(URL, data=datos(tkb, ta), follow_redirects=True)
chequear('con la marca ajena no guarda nada', es_borrador() == 1 and estudios_activos() == 1)
r = cb.post(URL, data=datos(tkb, None), follow_redirects=True)
chequear('sin marca tampoco', es_borrador() == 1 and estudios_activos() == 1)

print('3) el mismo usuario con dos ventanas')
ta2 = token_de(ca.get(URL).get_data(as_text=True))
chequear('reabrirlo le da una marca nueva', ta2 is not None and ta2 != ta)
h = ca.post(URL, data=datos(tka, ta), follow_redirects=True).get_data(as_text=True)
chequear('la ventana vieja queda desactualizada y no guarda', 'desactualizado' in h and es_borrador() == 1)

print('4) doble envío')
ta2 = token_de(ca.get(URL).get_data(as_text=True))
r1 = ca.post(URL, data=datos(tka, ta2, **{'e-1-tipo': 'BP', 'e-1-categoria': 'Biopsias', 'e-1-subcategoria': 'Digestiva', 'e-1-sitio': 'Duodeno',
                                          'e-1-tipo_muestra': 'Biopsia', 'e-1-cantidad': '1', 'e-1-responsable_id': str(ids['med'])}))
chequear('el primer envío completa el protocolo', r1.status_code == 302 and es_borrador() == 0 and estudios_activos() == 2, (r1.status_code, estudios_activos()))
h = ca.post(URL, data=datos(tka, ta2, **{'e-1-tipo': 'BP', 'e-1-categoria': 'Biopsias', 'e-1-subcategoria': 'Digestiva', 'e-1-sitio': 'Duodeno',
                                         'e-1-tipo_muestra': 'Biopsia', 'e-1-cantidad': '1', 'e-1-responsable_id': str(ids['med'])}), follow_redirects=True).get_data(as_text=True)
chequear('el segundo envío idéntico no duplica nada', estudios_activos() == 2 and 'ya estaba completo' in h, estudios_activos())
with A.app.app_context():
    n = db.uno("SELECT COUNT(*) AS n FROM auditoria WHERE protocolo_id=? AND accion='completar'", (pid,))['n']
chequear('y "completar" queda una sola vez en el historial', n == 1, n)
with A.app.app_context():
    quedan = db.uno("SELECT COUNT(*) AS n FROM ediciones WHERE protocolo_id=?", (pid,))['n']
chequear('al completar se libera la reserva', quedan == 0, quedan)

print('5) liberar y vencimiento')
with A.app.app_context():
    pid2 = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, borrador, creado_por, creado_en) VALUES ('C000901','2026-10-13',1,?,?)", (admin, db.ahora()))
    db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?)",
          (pid2, 'BP', 'Biopsias', 'Digestiva', 'Estómago', 'Biopsia', admin, db.ahora()))
URL2 = f'/protocolo/{pid2}/editar'
t = token_de(ca.get(URL2).get_data(as_text=True))
chequear('B no puede abrir el segundo protocolo mientras A lo tiene', cb.get(URL2).status_code == 302)
r = ca.post(URL2 + '/soltar', data={'_csrf': tka, 'edicion': t})
chequear('al salir de la pantalla se libera', r.status_code == 204 and token_de(cb.get(URL2).get_data(as_text=True)) is not None)
t_b = token_de(cb.get(URL2).get_data(as_text=True))
with A.app.app_context():
    db.ex("UPDATE ediciones SET vence=0 WHERE protocolo_id=?", (pid2,))
chequear('una reserva vencida la puede tomar otra persona', token_de(ca.get(URL2).get_data(as_text=True)) is not None)
r = cb.post(URL2 + '/soltar', data={'_csrf': tkb, 'edicion': t_b})
chequear('soltar con una marca ajena no libera la reserva vigente', cb.get(URL2).status_code == 302)

print('6) eliminar un estudio (al pie de la pantalla del estudio)')
with A.app.app_context():
    activos = [r['id'] for r in db.q("SELECT id FROM estudios WHERE protocolo_id=? AND anulado=0 ORDER BY id", (pid,))]
h = ca.get(f'/protocolo/{pid}').get_data(as_text=True)
chequear('la lista de estudios del protocolo no trae botones para quitar', '/anular' not in h and 'Quitar' not in h)
h = ca.get(f'/estudio/{activos[1]}').get_data(as_text=True)
chequear('la pantalla del estudio trae la tarjeta "Eliminar este estudio" al final', 'Eliminar este estudio' in h and 'Vas a ELIMINAR el estudio' in h
         and h.rindex('Eliminar este estudio') > h.rindex('Historial'))
chequear('con aviso y motivo obligatorio', 'se va a <b>eliminar</b>' in h and 'name="motivo" required' in h)
r = ca.post(f'/estudio/{activos[1]}/anular', data={'_csrf': tka, 'volver': 'protocolo', 'motivo': ''})
chequear('sin motivo no se elimina', estudios_activos() == 2)
r = ca.post(f'/estudio/{activos[1]}/anular', data={'_csrf': tka, 'volver': 'protocolo', 'motivo': 'Duplicado al completar'})
chequear('con motivo se elimina y vuelve a la ficha del protocolo', estudios_activos() == 1 and r.status_code == 302 and r.headers['Location'].endswith(f'/protocolo/{pid}'), r.headers.get('Location'))
h = ca.get(f'/protocolo/{pid}').get_data(as_text=True)
chequear('el eliminado queda oculto detrás de "Ver anulados"', 'Ver anulados (1)' in h and 'fila-anulada' in h)
h = ca.get(f'/estudio/{activos[1]}').get_data(as_text=True)
chequear('en su pantalla se puede reactivar', 'Estudio eliminado' in h and 'Reactivar estudio' in h and 'Duplicado al completar' in h)
r = ca.post(f'/estudio/{activos[1]}/anular', data={'_csrf': tka})
chequear('reactivar lo devuelve al protocolo', estudios_activos() == 2)
print()
print('FALLAS:', 'ninguna' if not fallas else fallas)
sys.exit(1 if fallas else 0)
