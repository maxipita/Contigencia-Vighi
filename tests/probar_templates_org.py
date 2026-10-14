import os, re, sys
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
def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok: fallas.append(n)
h = c.get('/templates').get_data(as_text=True)
chequear('la pantalla Templates carga', 'Asignar a los templates marcados' in h and 'sin órgano asignado' in h)
tot = F.con.execute("SELECT COUNT(*) AS n FROM templates").fetchone()['n']
chequear('lista templates', h.count('name="ids"') > 100, h.count('name="ids"'))
tpl = [r['id'] for r in F.con.execute("SELECT id FROM templates WHERE clase='macro' ORDER BY id LIMIT 3").fetchall()]
r = c.post('/templates', data=MultiDict([('_csrf', csrf), ('organo', 'Colon'), ('tipo', 'Resección')] + [('ids', str(i)) for i in tpl]), follow_redirects=True)
chequear('asigna órgano y tipo', 'Se actualizaron 3 templates' in r.get_data(as_text=True))
filas = [dict(x) for x in F.con.execute("SELECT id, tipo_biopsia, organo, tipo_muestra FROM templates WHERE id IN (%s)" % ','.join(map(str, tpl))).fetchall()]
print('  ', filas)
chequear('guarda órgano, tipo y completa la zona', all(x['organo'] == 'Colon' and x['tipo_muestra'] == 'Resección' and x['tipo_biopsia'] == 'Digestiva' for x in filas))
r = c.post('/templates', data=MultiDict([('_csrf', csrf), ('organo', '__vaciar__')] + [('ids', str(tpl[0]))]), follow_redirects=True)
chequear('vacía un campo', F.con.execute("SELECT organo FROM templates WHERE id=?", (tpl[0],)).fetchone()['organo'] is None)
h = c.get('/templates?estado=sin_organo&clase=macro').get_data(as_text=True)
chequear('filtro de sin órgano', str(tpl[1]) not in re.findall(r'name="ids" value="(\d+)"', h))
r = c.post('/templates', data=MultiDict([('_csrf', csrf)]), follow_redirects=True)
chequear('sin marcados avisa', 'Marcá al menos un template' in r.get_data(as_text=True))
e = F.con.execute("SELECT id FROM estudios WHERE tipo='BP' AND anulado=0 LIMIT 1").fetchone()['id']
h = c.get(f'/estudio/{e}').get_data(as_text=True)
chequear('el estudio trae filtros y datos de cada template', 'filtro-templates' in h and 'data-organo="Colon"' in h and 'data-zona=' in h)
print('FALLAS:', fallas)
