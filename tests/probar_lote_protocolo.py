import os, re, sqlite3, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from datos_informe import preparar

A, db, ids, admin = preparar()
from vighi.servicios import lotes as srv_lotes
fallas = []


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
c.get('/')


def tk():
    with c.session_transaction() as s:
        return s['csrf']


def lotes_de(pid):
    with A.app.app_context():
        return [r['lote_id'] for r in db.q("SELECT lote_id FROM estudios WHERE protocolo_id=? AND anulado=0 ORDER BY id", (pid,))]


def cod(lid):
    with A.app.app_context():
        r = db.uno("SELECT codigo FROM lotes WHERE id=?", (lid,)) if lid else None
        return r['codigo'] if r else None


with A.app.app_context():
    endo = srv_lotes.crear_lote('ENDO', admin)['id']
    ct = srv_lotes.crear_lote('CT', admin)['id']
    onco = srv_lotes.crear_lote('ONCO', admin)['id']
    pid = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, creado_por, creado_en) VALUES ('C000400','2026-10-02','Lote','Prueba',?,?)", (admin, db.ahora()))
    bp = db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, sitio, tipo_muestra, cantidad, responsable_id, lote_id, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?)",
               (pid, 'BP', 'Biopsias', 'Estómago', 'Biopsia', '1', ids['med'], endo, admin, db.ahora()))

print('1) al agregar una citología a un protocolo con lote, hereda el del primer flujo')
r = c.post(f'/protocolo/{pid}/estudio/nuevo', data={'_csrf': tk(), 'e-0-tipo': 'CT', 'e-0-subcategoria': 'Digestiva', 'e-0-sitio': 'Peritoneo', 'e-0-tipo_muestra': 'PAAF',
                                                   'e-0-cantidad': '3', 'e-0-responsable_id': str(ids['med']), 'e-0-lote_id': f'nuevo:CT'})
l = lotes_de(pid)
chequear('quedan dos estudios en el mismo lote ENDO (lo que se eligió para la CT se ignora)', len(l) == 2 and l[0] == l[1] == endo, [cod(x) for x in l])
with A.app.app_context():
    n_ct = db.uno("SELECT COUNT(*) AS n FROM lotes WHERE tipo_lote='CT'")['n']
chequear('y no se creó ningún lote CT nuevo', n_ct == 1, n_ct)

print('2) protocolo nuevo con BP + CT: el lote lo marca el primero')
r = c.post('/protocolo/nuevo', data={'_csrf': tk(), 'numero': 'C000401', 'apellido': 'A', 'nombre': 'B',
                                     'e-0-tipo': 'BP', 'e-0-subcategoria': 'Digestiva', 'e-0-sitio': 'Colon', 'e-0-tipo_muestra': 'Biopsia', 'e-0-cantidad': '1',
                                     'e-0-responsable_id': str(ids['med']), 'e-0-lote_id': str(onco),
                                     'e-1-tipo': 'CT', 'e-1-subcategoria': 'Digestiva', 'e-1-sitio': 'Peritoneo', 'e-1-tipo_muestra': 'PAAF', 'e-1-cantidad': '1',
                                     'e-1-responsable_id': str(ids['med']), 'e-1-lote_id': 'nuevo:CT'})
with A.app.app_context():
    p2 = db.uno("SELECT id FROM protocolos WHERE numero='C000401'")['id']
l = lotes_de(p2)
chequear('los dos van en el lote del primer flujo (ONCO)', len(l) == 2 and l[0] == l[1] == onco, [cod(x) for x in l])
with A.app.app_context():
    n_ct = db.uno("SELECT COUNT(*) AS n FROM lotes WHERE tipo_lote='CT'")['n']
chequear('y el lote CT elegido en el segundo estudio no se creó', n_ct == 1, n_ct)

print('3) editar estudios')
with A.app.app_context():
    segundo = db.uno("SELECT id FROM estudios WHERE protocolo_id=? ORDER BY id DESC", (p2,))['id']
    primero = db.uno("SELECT id FROM estudios WHERE protocolo_id=? ORDER BY id", (p2,))['id']
t = c.get(f'/estudio/{segundo}/editar').get_data(as_text=True)
chequear('en el segundo estudio el formulario no deja elegir lote y dice cuál es', 'sin-lote' in t and 'Lote del protocolo:' in t and cod(onco) in t, '')
t = c.get(f'/estudio/{primero}/editar').get_data(as_text=True)
chequear('en el primero sí se puede elegir', 'form-estudios"' in t and 'sin-lote' not in t)
campos = lambda eid, **x: {'_csrf': tk(), 'e-0-tipo': 'BP' if eid == primero else 'CT', 'e-0-subcategoria': 'Digestiva', 'e-0-sitio': 'Colon', 'e-0-tipo_muestra': 'Biopsia', 'e-0-cantidad': '1',
                           'e-0-responsable_id': str(ids['med']), **x}
c.post(f'/estudio/{segundo}/editar', data=campos(segundo, **{'e-0-lote_id': str(endo)}))
chequear('cambiar el lote desde el segundo estudio no hace nada', lotes_de(p2) == [onco, onco], [cod(x) for x in lotes_de(p2)])
c.post(f'/estudio/{primero}/editar', data=campos(primero, **{'e-0-lote_id': str(endo)}))
chequear('cambiarlo desde el primero mueve todo el protocolo', lotes_de(p2) == [endo, endo], [cod(x) for x in lotes_de(p2)])
with A.app.app_context():
    a = db.q("SELECT detalle, estudio_id FROM auditoria WHERE protocolo_id=? AND accion='lote' ORDER BY id", (p2,))
chequear('queda una sola línea de historial por cambio de lote del protocolo', len(a) == 2 and 'ONCO' in a[1]['detalle'] and 'ENDO' in a[1]['detalle'] and a[1]['estudio_id'] is None, [x['detalle'] for x in a])

print('4) pantalla del lote')
t = c.get(f'/lotes/{endo}').get_data(as_text=True)
chequear('el lote muestra los estudios de ambos protocolos', t.count('C000400') >= 2 and t.count('C000401') >= 2)
chequear('"Quitar" aparece una sola vez por protocolo', t.count('lote_quitar') == 0 and t.count('/quitar/') == 2, t.count('/quitar/'))
c.post(f'/lotes/{endo}/quitar/{primero}', data={'_csrf': tk()})
chequear('quitar saca todo el protocolo del lote', lotes_de(p2) == [None, None], lotes_de(p2))
t = c.get(f'/lotes/{endo}').get_data(as_text=True)
chequear('y ya no figura en el lote, pero sí se ofrece para agregarlo (una vez, con sus flujos)', t.count('C000401') >= 1 and 'BP c/ CT' in t and t.count(f'value="{primero}"') == 1, '')
r = c.post(f'/lotes/{onco}/agregar', data={'_csrf': tk(), 'estudio_id': str(primero)}, follow_redirects=True)
chequear('agregarlo a otro lote lo lleva con todos sus estudios', lotes_de(p2) == [onco, onco], lotes_de(p2))
r = c.post(f'/lotes/{ct}/agregar', data={'_csrf': tk(), 'protocolo': 'C000401'}, follow_redirects=True).get_data(as_text=True)
chequear('un lote CT no acepta un protocolo cuyo primer flujo es BP (aunque tenga una CT)', 'empieza con' in r and lotes_de(p2) == [onco, onco], r[:0])
r = c.post(f'/lotes/{endo}/agregar', data={'_csrf': tk(), 'protocolo': 'C000401'}, follow_redirects=True).get_data(as_text=True)
chequear('mover a otro lote compatible avisa de dónde estaba', 'estaba en' in r and lotes_de(p2) == [endo, endo])

print('5) lote del protocolo con PAP primero')
with A.app.app_context():
    cito = srv_lotes.crear_lote('ZZCT', admin)['id']
    pid3 = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, creado_por, creado_en) VALUES ('C000402','2026-10-02','P','Q',?,?)", (admin, db.ahora()))
    pap = db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, responsable_id, lote_id, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (pid3, 'PAP', 'Citologías', 'Ginecológica', 'Vagina', 'Citología Endocervical', '1', ids['cito'], cito, admin, db.ahora()))
r = c.post(f'/protocolo/{pid3}/estudio/nuevo', data={'_csrf': tk(), 'e-0-tipo': 'BP', 'e-0-subcategoria': 'Ginecológica', 'e-0-sitio': 'Cuello', 'e-0-tipo_muestra': 'Biopsia', 'e-0-cantidad': '1',
                                                    'e-0-responsable_id': str(ids['med']), 'e-0-lote_id': str(endo)})
chequear('una biopsia ginecológica agregada a un protocolo que empieza con PAP va en el lote del citotécnico', lotes_de(pid3) == [cito, cito], [cod(x) for x in lotes_de(pid3)])

print(chr(10) + 'FALLAS:', fallas if fallas else 'ninguna')
