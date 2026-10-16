import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar
from werkzeug.datastructures import MultiDict

A, db, ids, admin = preparar()
fallas = []


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
c.get('/')
with c.session_transaction() as s:
    csrf = s['csrf']


def post(url, datos):
    pares = [('_csrf', csrf)]
    for k, v in datos.items():
        for x in (v if isinstance(v, list) else [v]):
            pares.append((k, x))
    return c.post(url, data=MultiDict(pares), follow_redirects=True).get_data(as_text=True)


print('1) crear lotes con otra fecha')
h = post('/lotes/nuevo', {'tipo_lote': 'ENDO', 'fecha': '2026-09-03'})
with A.app.app_context():
    l1 = db.uno("SELECT * FROM lotes WHERE fecha='2026-09-03' AND tipo_lote='ENDO'")
chequear('crea el lote con la fecha elegida', l1 is not None and l1['codigo'] == 'ENDO-0903.1' and '03/09/2026' in h, dict(l1) if l1 else h[:200])
h = post('/lotes/nuevo', {'tipo_lote': 'ENDO', 'fecha': '2026-09-03'})
with A.app.app_context():
    l2 = db.uno("SELECT * FROM lotes WHERE codigo='ENDO-0903.2'")
chequear('el segundo del mismo día lleva el número siguiente', l2 is not None)
h = post('/lotes/nuevo', {'tipo_lote': 'ENDO', 'fecha': '2025-09-03'})
with A.app.app_context():
    l3 = db.uno("SELECT * FROM lotes WHERE fecha='2025-09-03' AND tipo_lote='ENDO'")
chequear('otro año con el mismo día y mes no choca con el código', l3 is not None and l3['codigo'] != 'ENDO-0903.1' and l3['codigo'].startswith('ENDO-0903.'), dict(l3) if l3 else h[:200])
h = post('/lotes/nuevo', {'tipo_lote': 'ENDO', 'fecha': '2026-02-31'})
chequear('rechaza una fecha inexistente', 'no es válida' in h)
h = post('/lotes/nuevo', {'tipo_lote': 'ENDO', 'fecha': ''})
with A.app.app_context():
    hoy = db.uno("SELECT COUNT(*) AS n FROM lotes WHERE creado_por=? AND fecha=?", (admin, __import__('datetime').date.today().isoformat()))['n']
chequear('sin fecha usa la de hoy', hoy >= 1)
h = c.get('/lotes?fecha=2026-09-03').get_data(as_text=True)
chequear('la pantalla del día muestra el formulario con esa fecha', 'ENDO-0903.1' in h and 'name="fecha" value="2026-09-03"' in h)

print('2) mover protocolos en conjunto')
with A.app.app_context():
    ahora = db.ahora()
    destino = l2['id']
    cerrado = db.ex("INSERT INTO lotes (codigo, tipo_lote, fecha, numero, cerrado) VALUES ('ENDO-CERR.1','ENDO','2026-09-03',9,1)")
    onco = db.ex("INSERT INTO lotes (codigo, tipo_lote, fecha, numero) VALUES ('ONCO-0903.1','ONCO','2026-09-03',1)")
    primeros = []
    for n in ('C000801', 'C000802', 'C000803'):
        pid = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, borrador, creado_por, creado_en) VALUES (?,?,?,?,0,?,?)", (n, '2026-09-03', 'Mover', n, admin, ahora))
        e1 = db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, lote_id, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (pid, 'BP', 'Biopsias', 'Digestiva', 'Colon', 'Biopsia', '1', l1['id'], admin, ahora))
        db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, lote_id, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?)",
              (pid, 'BP', 'Biopsias', 'Digestiva', 'Estómago', 'Biopsia', '1', l1['id'], admin, ahora))
        primeros.append((pid, e1))
h = c.get(f"/lotes/{l1['id']}").get_data(as_text=True)
chequear('el lote trae casillas por protocolo, marcar todos y el destino', h.count('name="eids"') == 3 and 'data-marcar-protocolos' in h and 'Mover protocolos' in h and 'ENDO-0903.2' in h)
chequear('no ofrece lotes cerrados', 'ENDO-CERR.1' not in h)
h = post(f"/lotes/{l1['id']}/mover", {'destino': str(destino), 'eids': [str(primeros[0][1]), str(primeros[1][1])]})
with A.app.app_context():
    lotes_de = {pid: {r['lote_id'] for r in db.q("SELECT lote_id FROM estudios WHERE protocolo_id=? AND anulado=0", (pid,))} for pid, _ in primeros}
    aud = db.uno("SELECT COUNT(*) AS n FROM auditoria WHERE accion='lote' AND detalle LIKE ?", (f"ENDO-0903.1 → ENDO-0903.2",))['n']
chequear('mueve los dos protocolos marcados con todos sus estudios', lotes_de[primeros[0][0]] == {destino} and lotes_de[primeros[1][0]] == {destino}, lotes_de)
chequear('el no marcado se queda', lotes_de[primeros[2][0]] == {l1['id']})
chequear('avisa cuántos movió', '2 protocolo(s) movidos' in h)
chequear('queda en el historial de cada protocolo', aud == 2, aud)
h = post(f"/lotes/{l1['id']}/mover", {'destino': str(cerrado), 'eids': [str(primeros[2][1])]})
chequear('no mueve a un lote cerrado', 'cerrado' in h)
h = post(f"/lotes/{l1['id']}/mover", {'destino': str(l1['id']), 'eids': [str(primeros[2][1])]})
chequear('no mueve al mismo lote', 'mismo' in h)
h = post(f"/lotes/{l1['id']}/mover", {'destino': str(destino)})
chequear('pide marcar al menos uno', 'al menos un protocolo' in h)
h = post(f"/lotes/{l1['id']}/mover", {'eids': [str(primeros[2][1])]})
chequear('pide el destino', 'lote de destino' in h)
h = post(f"/lotes/{l1['id']}/mover", {'destino': str(onco), 'eids': [str(primeros[2][1])]})
with A.app.app_context():
    lote_final = db.uno("SELECT lote_id FROM estudios WHERE id=?", (primeros[2][1],))['lote_id']
chequear('un lote de otro tipo compatible también sirve', lote_final == onco, lote_final)

print('3) mover a un lote nuevo, con su fecha, desde la misma tarjeta')
with A.app.app_context():
    ahora = db.ahora()
    lote_o = db.ex("INSERT INTO lotes (codigo, tipo_lote, fecha, numero) VALUES ('NO ONCO-0905.1','NO ONCO','2026-09-05',1)")
    ps = []
    for n in ('C000811', 'C000812'):
        pid = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, borrador, creado_por, creado_en) VALUES (?,?,?,?,0,?,?)", (n, '2026-09-05', 'Nuevo', n, admin, ahora))
        e1 = db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, lote_id, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (pid, 'BP', 'Biopsias', 'Digestiva', 'Colon', 'Biopsia', '1', lote_o, admin, ahora))
        ps.append((pid, e1))
h = c.get(f'/lotes/{lote_o}').get_data(as_text=True)
chequear('sin otro lote igual abierto la tarjeta igual aparece y ofrece crear uno', 'Mover protocolos' in h and 'value="nuevo"' in h and 'name="fecha"' in h)
h = post(f'/lotes/{lote_o}/mover', {'destino': 'nuevo', 'tipo_lote': 'NO ONCO', 'fecha': '2026-09-06', 'eids': [str(ps[0][1]), str(ps[1][1])]})
with A.app.app_context():
    nuevo_lote = db.uno("SELECT * FROM lotes WHERE fecha='2026-09-06' AND tipo_lote='NO ONCO'")
    lotes_nuevos = {r['lote_id'] for r in db.q("SELECT lote_id FROM estudios WHERE protocolo_id IN (?,?)", (ps[0][0], ps[1][0]))}
chequear('crea el lote con la fecha elegida y mueve los protocolos', nuevo_lote is not None and lotes_nuevos == {nuevo_lote['id']} and '2 protocolo(s) movidos' in h, (dict(nuevo_lote) if nuevo_lote else None, lotes_nuevos))
h = post(f'/lotes/{nuevo_lote["id"]}/mover', {'destino': 'nuevo', 'tipo_lote': 'NO ONCO', 'fecha': 'mal', 'eids': [str(ps[0][1])]})
chequear('con una fecha inválida no crea nada', 'fecha válida' in h)
h = post(f'/lotes/{nuevo_lote["id"]}/mover', {'destino': 'nuevo', 'tipo_lote': 'NO ONCO', 'fecha': '2026-09-07'})
with A.app.app_context():
    n_7 = db.uno("SELECT COUNT(*) AS n FROM lotes WHERE fecha='2026-09-07'")['n']
chequear('sin protocolos marcados no deja un lote vacío', n_7 == 0 and 'al menos un protocolo' in h)

print()
print('FALLAS:', 'ninguna' if not fallas else fallas)
sys.exit(1 if fallas else 0)
