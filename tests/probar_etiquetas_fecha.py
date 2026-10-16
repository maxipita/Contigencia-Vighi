import os, re, sys
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(__file__))
from datos_informe import preparar

A, db, ids, admin = preparar()
from vighi.servicios import etiquetas as srv
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
    tk = s['csrf']

hoy = datetime.now().strftime('%Y-%m-%d')
ayer = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
viejo = (datetime.now() - timedelta(days=20)).strftime('%Y-%m-%d')
impreso_viejo = (datetime.now() - timedelta(days=19)).strftime('%Y-%m-%d 10:00:00')

with A.app.app_context():
    def lote(codigo, tipo, fecha):
        return db.ex("INSERT INTO lotes (codigo, tipo_lote, fecha, numero, creado_por, creado_en) VALUES (?,?,?,1,?,?)", (codigo, tipo, fecha, admin, db.ahora()))

    def estudio(numero, tipo, lote_id, etiquetado=None):
        pid = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, creado_por, creado_en) VALUES (?,?,?,?,?,?)",
                    (numero, fecha_rec, 'Fecha', numero, admin, db.ahora()))
        return db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, responsable_id, lote_id, lab_etiquetado_en, creado_por, creado_en) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (pid, tipo, 'Citologías', 'Ginecológica', 'Vagina', 'Cúpula Vaginal', '1', ids['cito'], lote_id, etiquetado, admin, db.ahora()))
    fecha_rec = hoy
    l_hoy = lote('ZZCT-HOY.1', 'ZZCT', hoy)
    l_ayer = lote('ZZCT-AYER.1', 'ZZCT', ayer)
    l_viejo = lote('ZZCT-VIEJO.1', 'ZZCT', viejo)
    e_hoy = estudio('C000501', 'PAP', l_hoy)
    e_ayer = estudio('C000502', 'PAP', l_ayer)
    e_ayer_impreso = estudio('C000503', 'PAP', l_ayer, datetime.now().strftime('%Y-%m-%d 08:00:00'))
    e_viejo_impreso = estudio('C000504', 'PAP', l_viejo, impreso_viejo)
    e_viejo_pend = estudio('C000505', 'PAP', l_viejo)

print('1) sin filtro: lo de siempre (pendientes de cualquier fecha y lo impreso hace poco)')
with A.app.app_context():
    base = {x['id'] for x in srv.etiquetas_casos()}
chequear('trae los pendientes de hoy, de ayer y de un lote viejo', {e_hoy, e_ayer, e_viejo_pend} <= base, base)
chequear('trae lo impreso hace poco', e_ayer_impreso in base)
chequear('no trae lo impreso hace mucho', e_viejo_impreso not in base)

print('2) filtro por fecha del lote')
with A.app.app_context():
    d_ayer = srv.etiquetas_casos(ayer)
    d_viejo = srv.etiquetas_casos(viejo)
chequear('con la fecha de ayer trae solo los lotes de ayer, impresos o no', {x['id'] for x in d_ayer} == {e_ayer, e_ayer_impreso}, [x['id'] for x in d_ayer])
chequear('con una fecha vieja trae también lo ya impreso, para reimprimir', {x['id'] for x in d_viejo} == {e_viejo_impreso, e_viejo_pend}, [x['id'] for x in d_viejo])
chequear('cada caso trae la fecha de su lote', all(x['loteFecha'] == ayer for x in d_ayer))
chequear('marca cuáles ya estaban impresas', {x['id']: x['etiquetado'] for x in d_viejo} == {e_viejo_impreso: True, e_viejo_pend: False})
with A.app.app_context():
    vacio = srv.etiquetas_casos('2020-01-01')
chequear('una fecha sin lotes da una lista vacía', vacio == [])

print('3) lote pedido desde su página (/etiquetas?lote=)')
with A.app.app_context():
    con_lote = {x['id'] for x in srv.etiquetas_casos(lote_id=l_viejo)}
chequear('trae el lote aunque sea viejo y ya esté impreso', e_viejo_impreso in con_lote and e_viejo_pend in con_lote and e_hoy in con_lote)
t = c.get(f'/etiquetas?lote={l_viejo}').get_data(as_text=True)
chequear('la pantalla lo recibe con ese lote', '"C000504"' in t or 'C000504' in t)

print('4) servicio web')
r = c.get(f'/api/etiquetas/estado?fecha={viejo}')
j = r.get_json()
chequear('responde los casos de esa fecha', r.status_code == 200 and {x['id'] for x in j['casos']} == {e_viejo_impreso, e_viejo_pend} and 'historial' in j)
chequear('rechaza una fecha mal escrita', c.get('/api/etiquetas/estado?fecha=ayer').status_code == 400)
r = c.get(f'/api/etiquetas/estado?lote={l_viejo}')
chequear('con lote trae además ese lote', e_viejo_impreso in {x['id'] for x in r.get_json()['casos']})
chequear('sin parámetros sigue igual', e_viejo_impreso not in {x['id'] for x in c.get('/api/etiquetas/estado').get_json()['casos']})

print('5) reimprimir etiquetas de un lote de otro día')
r = c.post('/api/etiquetas/confirmar', json={'tipo': 'pap', 'items': [e_viejo_impreso, e_ayer]}, headers={'X-CSRF': tk})
j = r.get_json()
chequear('se confirma la reimpresión de lo ya impreso junto con un pendiente de ayer', j and j.get('ok'), j)
with A.app.app_context():
    nuevo = db.uno("SELECT lab_etiquetado_en FROM estudios WHERE id=?", (e_ayer,))['lab_etiquetado_en']
chequear('queda marcado como impreso', bool(nuevo))

print('6) la pantalla')
t = c.get('/etiquetas').get_data(as_text=True)
chequear('tiene el campo de fecha del lote y el botón para volver a lo reciente', 'id="fechaLote"' in t and 'id="fechaLoteQuitar"' in t)
chequear('el campo de fecha de recolección de Recepción sigue estando', 'id="fecha"' in t)

print()
print('FALLAS:', fallas if fallas else 'ninguna')
