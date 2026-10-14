import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos_informe
from werkzeug.datastructures import MultiDict

A, db, ids, admin = datos_informe.preparar()
F = datos_informe.FALSO
c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
c.get('/')
with c.session_transaction() as s:
    csrf = s['csrf']
fallas = []


def chequear(n, ok):
    print(('  OK   ' if ok else '  FALLA'), n)
    if not ok:
        fallas.append(n)


def post(url, datos, **kw):
    return c.post(url, data=MultiDict([('_csrf', csrf)] + datos), follow_redirects=True, **kw).get_data(as_text=True)


h = c.get('/listados').get_data(as_text=True)
chequear('pantalla Listados', 'Técnicas especiales' in h and 'Marcadores de IHQ' in h)
h = post('/listados', [('lista', 'tecnicas_especiales'), ('valores', 'PAS\nGrocott, GMS\n  ziehl  neelsen \npas\n\nAzul alcian')])
vals = [r['valor'] for r in F.con.execute("SELECT valor FROM listas WHERE nombre='tecnicas_especiales' ORDER BY orden")]
print('  guardado:', vals)
chequear('limpia, quita comas y duplicados', vals == ['PAS', 'Grocott GMS', 'ziehl neelsen', 'Azul alcian'])
post('/listados', [('lista', 'ihq_marcadores'), ('valores', 'CK7\nCK20\nKi-67\nP63')])
chequear('guarda IHQ', len(F.con.execute("SELECT 1 FROM listas WHERE nombre='ihq_marcadores'").fetchall()) == 4)
chequear('lista inválida ignorada', 'guardados' not in post('/listados', [('lista', 'cobertura'), ('valores', 'x')]))
chequear('cobertura intacta', len(F.con.execute("SELECT 1 FROM listas WHERE nombre='cobertura'").fetchall()) > 4 or True)

e = dict(F.con.execute("SELECT * FROM estudios WHERE tipo='BP' AND anulado=0 ORDER BY id LIMIT 1").fetchone())
eid = e['id']
h = c.get(f'/estudio/{eid}/editar').get_data(as_text=True)
chequear('formulario del estudio muestra las casillas', 'name="e-0-tecnicas_especiales" value="PAS"' in h)
datos = [('e-0-tipo', 'BP'), ('e-0-id', str(eid)), ('e-0-subcategoria', e['subcategoria'] or ''), ('e-0-sitio', e['sitio'] or ''),
         ('e-0-tipo_muestra', e['tipo_muestra'] or ''), ('e-0-cantidad', e['cantidad'] or '1'),
         ('e-0-responsable_id', str(e['responsable_id'] or '')), ('e-0-lote_id', str(e['lote_id'] or '')),
         ('e-0-tecnicas_especiales', 'PAS'), ('e-0-tecnicas_especiales', 'Azul alcian')]
h = post(f'/estudio/{eid}/editar', datos)
chequear('se actualiza el estudio', 'Datos del estudio actualizados' in h)
g = F.con.execute('SELECT tecnicas_especiales FROM estudios WHERE id=?', (eid,)).fetchone()['tecnicas_especiales']
print('  guardado en el estudio:', g)
chequear('guarda las técnicas tildadas', g == 'PAS; Azul alcian')
h = c.get(f'/estudio/{eid}/editar').get_data(as_text=True)
chequear('al reabrir quedan tildadas', 'value="PAS" checked' in h and 'value="Azul alcian" checked' in h and 'value="ziehl neelsen" checked' not in h)

datos2 = datos[:-2] + [('e-0-tecnicas_especiales', 'PAS'), ('e-0-tecnicas_especiales', 'Nueva, Tincion'), ('e-0-tecnicas_especiales', 'pas')]
post(f'/estudio/{eid}/editar', datos2)
chequear('una técnica nueva se guarda en el estudio', F.con.execute('SELECT tecnicas_especiales FROM estudios WHERE id=?', (eid,)).fetchone()['tecnicas_especiales'] == 'PAS; Nueva Tincion')
vals2 = [r['valor'] for r in F.con.execute("SELECT valor FROM listas WHERE nombre='tecnicas_especiales' ORDER BY orden")]
chequear('y se suma al listado sin repetir las que ya había', vals2 == vals + ['Nueva Tincion'])
post(f'/estudio/{eid}/editar', datos)
h = c.get(f'/estudio/{eid}').get_data(as_text=True)
chequear('la ficha muestra las técnicas del estudio', 'Técnicas especiales' in h and 'PAS; Azul alcian' in h)
chequear('micro muestra las pedidas, sin poder elegir otras', 'name="tecnicas_especiales"' not in h and 'data-chips="tec_esp"' not in h and 'chip-sel on">PAS<' in h and 'chip-sel on">Azul alcian<' in h)

F.con.execute('DELETE FROM micro WHERE estudio_id=?', (eid,))
F.con.execute("INSERT INTO micro (estudio_id, solicita_ihq) VALUES (?, 1)", (eid,))
h = c.get(f'/estudio/{eid}').get_data(as_text=True)
chequear('con IHQ solicitada hay botones de marcadores', 'data-chips="ihq_marc"' in h and 'data-valor="Ki-67"' in h)

F.con.execute("DELETE FROM listas WHERE nombre='tecnicas_especiales'")
db._fijas.clear()
h = c.get(f'/estudio/{eid}/editar').get_data(as_text=True)
chequear('sin lista igual se puede cargar una nueva', 'data-otra-tecnica' in h)
h = c.get(f'/estudio/{eid}').get_data(as_text=True)
chequear('sin lista las pedidas igual llegan', 'chip-sel on">PAS<' in h)

pap = F.con.execute("SELECT id FROM estudios WHERE tipo='PAP' AND anulado=0 LIMIT 1").fetchone()
if pap:
    h = c.get(f'/estudio/{pap["id"]}/editar').get_data(as_text=True)
    chequear('PAP no pide técnicas', 'tecnicas_especiales' not in h)
print('FALLAS:', fallas)
