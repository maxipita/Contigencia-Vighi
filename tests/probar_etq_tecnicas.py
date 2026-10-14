import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos_informe
A, db, ids, admin = datos_informe.preparar()
from vighi.servicios import etiquetas as srv_etiquetas
F = datos_informe.FALSO
c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
c.get('/')
with c.session_transaction() as s:
    tk = s['csrf']
fallas = []
def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok: fallas.append(n)

bp = ids['bp']
F.con.execute("UPDATE estudios SET cantidad='2' WHERE id=?", (bp,))
F.con.execute('DELETE FROM tecnicas')
with A.app.app_context():
    casos = {x['id']: x for x in srv_etiquetas.etiquetas_casos()}
chequear('sin técnicas: una por frasco, sin Nro', casos[bp]['cantidad'] == 2 and casos[bp]['nros'] == [], casos[bp])
for num, cas in (('A', 2), ('B', 1)):
    F.con.execute("INSERT INTO tecnicas (estudio_id, numero, fragmentos, inclusion, tacos, cassettes, comentarios, usuario_id, creado_en) VALUES (?,?,1,'Reserva',1,?, '', ?, '2026-10-01 10:00:00')", (bp, num, cas, admin))
with A.app.app_context():
    casos = {x['id']: x for x in srv_etiquetas.etiquetas_casos()}
chequear('con técnicas: una por cassette con su Nro', casos[bp]['cantidad'] == 3 and casos[bp]['nros'] == ['A 1/2', 'A 2/2', 'B'], casos[bp])
chequear('conserva los frascos', casos[bp]['frascos'] == 2)
r = c.post('/api/etiquetas/confirmar', json={'tipo': 'lab', 'items': [bp]}, headers={'X-CSRF': tk})
j = r.get_json()
chequear('se confirma', j and j.get('ok'), j)
with A.app.app_context():
    fila = db.uno("SELECT params, etiquetas FROM etiquetas_lotes WHERE id=?", (j['id'],))
p = json.loads(fila['params'])
chequear('guarda un Nro por etiqueta', p['nros'] == ['A 1/2', 'A 2/2', 'B'] and len(p['patos']) == 3, p)
chequear('cuenta 3 etiquetas', fila['etiquetas'] == 3, dict(fila))
h = c.get('/etiquetas').get_data(as_text=True)
chequear('la pantalla trae los Nro y los muestra en la primera línea', "nro ? ' · '" in h.replace('"', "'") or "' · ' + esc(nro)" in h)
print('FALLAS:', fallas)
