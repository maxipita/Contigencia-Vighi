import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from datos_informe import preparar

A, db, ids, admin = preparar()
from vighi.core.fechas import hoy
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

with A.app.app_context():
    db.ex("INSERT INTO ubicaciones (abreviatura, nombre) VALUES ('SAN-A','Sanatorio A')")
    previsto = srv.lotes_de_hoy()['ZZCT']
f = hoy()
chequear('antes de confirmar se conoce el código del lote del citotécnico', previsto == f"ZZCT-{f[5:7]}{f[8:10]}.1", previsto)


def confirmar(inicio=700, **extra):
    p = {'fecha': hoy(), 'lote': 'PAPS', 'cito': 'ZZCT'}
    p.update(extra)
    return c.post('/api/etiquetas/confirmar', json={'tipo': 'bp', 'inicio': inicio, 'n': 3, 'params': p}, headers={'X-CSRF': tk})


print('1) la dirección es obligatoria')
r = confirmar()
chequear('sin dirección no confirma', r.status_code == 400 and 'dirección' in r.get_json()['error'], r.get_json())
r = confirmar(ubicacion='NO-EXISTE')
chequear('una dirección que no está en Ubicaciones tampoco', r.status_code == 400)

print('2) los protocolos nacen asociados a la ubicación')
r = confirmar(ubicacion='SAN-A')
chequear('confirma', r.get_json().get('ok'), r.get_json())
with A.app.app_context():
    filas = db.q("SELECT numero, lugar_recoleccion, borrador FROM protocolos WHERE numero IN ('C000700','C000701','C000702') ORDER BY numero")
    lote = db.uno("SELECT l.codigo FROM etiquetas_lotes e JOIN lotes l ON l.id=e.lote_id ORDER BY e.id DESC LIMIT 1")
chequear('los tres protocolos quedan con el lugar de recolección', [x['lugar_recoleccion'] for x in filas] == ['SAN-A'] * 3 and all(x['borrador'] for x in filas), [dict(x) for x in filas])
chequear('el lote creado coincide con el previsto para la etiqueta', lote['codigo'] == previsto, (lote['codigo'], previsto))
hist = c.get('/api/etiquetas/estado').get_json()['historial'][-1]
chequear('la tanda guarda la ubicación para reimprimir', hist['params']['ubicacion'] == 'SAN-A' and hist['loteCodigo'] == previsto, hist)

print('3) los demás lotes también llevan dirección')
r = c.post('/api/etiquetas/confirmar', json={'tipo': 'bp', 'inicio': 710, 'n': 1, 'params': {'fecha': '2026-10-16', 'lote': 'ENDO'}}, headers={'X-CSRF': tk})
chequear('un lote común sin dirección no confirma', r.status_code == 400, r.get_json())
r = c.post('/api/etiquetas/confirmar', json={'tipo': 'bp', 'inicio': 710, 'n': 1, 'params': {'fecha': '2026-10-16', 'lote': 'ENDO', 'ubicacion': 'SAN-A'}}, headers={'X-CSRF': tk})
chequear('con dirección confirma', r.get_json().get('ok'), r.get_json())
with A.app.app_context():
    p = db.uno("SELECT lugar_recoleccion FROM protocolos WHERE numero='C000710'")
chequear('y el protocolo queda con el lugar', p['lugar_recoleccion'] == 'SAN-A')

print('4) la pantalla ofrece la dirección')
h = c.get('/etiquetas').get_data(as_text=True)
chequear('hay selector de dirección y las ubicaciones llegan a la página', 'id="ubicacion"' in h and 'SAN-A' in h)
print('5) PAPURG es un lote de PAP')
r = c.post('/api/etiquetas/confirmar', json={'tipo': 'bp', 'inicio': 720, 'n': 1, 'params': {'fecha': '2026-10-16', 'lote': 'PAPURG', 'ubicacion': 'SAN-A'}}, headers={'X-CSRF': tk})
chequear('confirma sin citotécnico', r.get_json().get('ok'), r.get_json())
with A.app.app_context():
    e = db.uno("SELECT e.tipo, e.sitio, l.tipo_lote FROM protocolos p JOIN estudios e ON e.protocolo_id=p.id JOIN lotes l ON l.id=e.lote_id WHERE p.numero='C000720'")
    from vighi.servicios.lotes import tipos_lote
    en_pap, en_bp = 'PAPURG' in tipos_lote('PAP'), 'PAPURG' in tipos_lote('BP')
chequear('el protocolo nace con un PAP en lote PAPURG', e and (e['tipo'], e['tipo_lote']) == ('PAP', 'PAPURG'), e and dict(e))
chequear('PAPURG sirve a los PAP y no a las biopsias', en_pap and not en_bp)
print('6) el lote de PAP toma la fecha elegida, no la de hoy')
from datetime import datetime, timedelta
ayer = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
with A.app.app_context():
    previsto_ayer = srv.lotes_previstos(ayer)['ZZCT']
chequear('el código previsto para otra fecha usa esa fecha', previsto_ayer == f"ZZCT-{ayer[5:7]}{ayer[8:10]}.1", previsto_ayer)
r = c.get(f'/api/etiquetas/lotes-previstos?fecha={ayer}')
chequear('el servicio web lo devuelve', r.status_code == 200 and r.get_json()['ZZCT'] == previsto_ayer, r.get_json())
chequear('rechaza una fecha mal escrita', c.get('/api/etiquetas/lotes-previstos?fecha=ayer').status_code == 400)
r = confirmar(inicio=760, fecha=ayer, ubicacion='SAN-A')
chequear('confirma con la fecha de ayer', r.get_json().get('ok'), r.get_json())
with A.app.app_context():
    lote = db.uno("SELECT l.codigo, l.fecha FROM etiquetas_lotes e JOIN lotes l ON l.id=e.lote_id ORDER BY e.id DESC LIMIT 1")
chequear('el lote se crea con la fecha elegida y su código sale de esa fecha', lote['fecha'] == ayer and lote['codigo'] == previsto_ayer, dict(lote))
r = c.post('/api/etiquetas/confirmar', json={'tipo': 'bp', 'inicio': 730, 'n': 1, 'params': {'fecha': ayer, 'lote': 'PAPURG', 'ubicacion': 'SAN-A'}}, headers={'X-CSRF': tk})
with A.app.app_context():
    urg = db.uno("SELECT l.fecha FROM etiquetas_lotes e JOIN lotes l ON l.id=e.lote_id ORDER BY e.id DESC LIMIT 1")
chequear('PAPURG también toma la fecha elegida', r.get_json().get('ok') and urg['fecha'] == ayer, r.get_json())
r = c.post('/api/etiquetas/confirmar', json={'tipo': 'bp', 'inicio': 740, 'n': 1, 'params': {'fecha': ayer, 'lote': 'ENDO', 'ubicacion': 'SAN-A'}}, headers={'X-CSRF': tk})
with A.app.app_context():
    endo = db.uno("SELECT l.fecha FROM etiquetas_lotes e JOIN lotes l ON l.id=e.lote_id ORDER BY e.id DESC LIMIT 1")
chequear('los lotes de biopsias siguen siendo del día en que se arman', r.get_json().get('ok') and endo['fecha'] == hoy(), r.get_json())
chequear('la pantalla pide el código previsto de la fecha elegida', 'previstos' in c.get('/etiquetas').get_data(as_text=True))

print('FALLAS:', fallas or 'ninguna')
