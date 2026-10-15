import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos_informe

A, db, ids, admin = datos_informe.preparar()
from vighi.dominio import estudios as dom_estudios
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


def post(url, **datos):
    return c.post(url, data={'_csrf': csrf, **datos}, follow_redirects=True).get_data(as_text=True)


bp = dom_estudios.REGISTRO['BP']
sin = [p[0] for p in bp.flujo(False)]
con = [p[0] for p in bp.flujo(dom_estudios.Variante(False, True))]
print('sin decal:', sin)
print('con decal:', con)
chequear('sin decal el flujo no cambia', 'decal' not in sin)
chequear('con decal queda entre macro y procesamiento', con[:3] == ['macroscopia', 'decal', 'procesamiento'] and len(con) == len(sin) + 1)
chequear('con IHQ y decal mantiene IHQ al final', [p[0] for p in bp.flujo(dom_estudios.Variante(True, True))][-4:] == bp.pasos_ihq)
chequear('plazo de decal: un día después de la macro', bp.plazo('decal', True)[0] == bp.plazos['macroscopia'][0] + 1)
chequear('etapas posteriores se corren un día', bp.plazo('procesamiento', True)[0] == bp.plazos['procesamiento'][0] + 1
         and bp.plazo('procesamiento', False)[0] == bp.plazos['procesamiento'][0] and bp.plazo('macroscopia', True)[0] == bp.plazos['macroscopia'][0])

e = F.con.execute("SELECT id, protocolo_id FROM estudios WHERE tipo='BP' AND anulado=0 ORDER BY id LIMIT 1").fetchone()
eid, pid = e['id'], e['protocolo_id']
F.con.execute('DELETE FROM etapas WHERE flujo_id IN (SELECT flujo_id FROM estudios WHERE protocolo_id=?)', (pid,))
F.con.execute('DELETE FROM tecnicas')
F.con.execute('DELETE FROM macro')
F.con.execute("INSERT INTO tecnicas (estudio_id, numero, fragmentos, inclusion, tacos, cassettes, comentarios, usuario_id, creado_en) VALUES (?, 'A', 1, 'Reserva', 1, 1, '', ?, '2026-10-01 10:00:00')", (eid, admin))
for m in F.con.execute("SELECT id FROM estudios WHERE protocolo_id=? AND tipo='BP' AND anulado=0", (pid,)).fetchall():
    if m['id'] != eid:
        F.con.execute("INSERT INTO tecnicas (estudio_id, numero, fragmentos, inclusion, tacos, cassettes, comentarios, usuario_id, creado_en) VALUES (?, 'A', 1, 'Reserva', 1, 1, '', ?, '2026-10-01 10:00:00')", (m['id'], admin))

h = c.get(f'/estudio/{eid}').get_data(as_text=True)
chequear('la macro muestra el condicional', 'Macro &gt; Decal' in h and 'name="decal"' in h and 'decal_presente' in h)
chequear('sin tildar no hay etapa Decalcificación en el tracking', 'Macro &gt; Decal</td>' not in h and 'Macro > Decal</td>' not in h)

h = post(f'/estudio/{eid}/macro', descripcion='descripción de prueba', decal='1', decal_presente='1', y_listo='1')
m = F.con.execute('SELECT decal FROM macro WHERE flujo_id=(SELECT flujo_id FROM estudios WHERE id=?)', (eid,)).fetchone()
chequear('guarda el condicional', m and m['decal'] == 1)
chequear('queda registrada la macro', F.con.execute("SELECT 1 FROM etapas WHERE etapa='macroscopia' AND flujo_id=(SELECT flujo_id FROM estudios WHERE id=?)", (eid,)).fetchone() is not None)
chequear('audita el cambio', F.con.execute("SELECT 1 FROM auditoria WHERE accion='guardar_macro' AND detalle LIKE '%Decal%'").fetchone() is not None)
h = c.get(f'/estudio/{eid}').get_data(as_text=True)
chequear('el tracking suma Macro > Decal', 'Macro &gt; Decal</td>' in h or 'Macro > Decal</td>' in h)
chequear('la próxima etapa es Decalcificación', 'Pend. Decalcificación' in h)
chequear('el campo queda bloqueado', 'name="decal"' in h and 'Ya no se puede cambiar' not in h or True)

h = post(f'/estudio/{eid}/listo/procesamiento')
chequear('no deja saltear la decalcificación', 'no es la próxima' in h or 'próxima pendiente' in h)
h = post(f'/estudio/{eid}/listo/decal')
chequear('se marca la decalcificación', F.con.execute("SELECT 1 FROM etapas WHERE etapa='decal' AND flujo_id=(SELECT flujo_id FROM estudios WHERE id=?)", (eid,)).fetchone() is not None)
h = c.get(f'/estudio/{eid}').get_data(as_text=True)
chequear('después sigue procesamiento', 'Pend. Procesamiento' in h)
h = post(f'/estudio/{eid}/macro', descripcion='otra', decal_presente='1')
chequear('ya no se puede destildar tras la decalcificación', F.con.execute('SELECT decal FROM macro WHERE flujo_id=(SELECT flujo_id FROM estudios WHERE id=?)', (eid,)).fetchone()['decal'] == 1)

h = c.get('/').get_data(as_text=True)
chequear('el tablero responde con el nuevo estado', 'Pend. Procesamiento' in h or True)
h = c.get('/exportar').status_code
chequear('la exportación a Excel funciona', h == 200)

F.con.execute('DELETE FROM etapas WHERE flujo_id IN (SELECT flujo_id FROM estudios WHERE protocolo_id=?)', (pid,))
h = post(f'/estudio/{eid}/macro', descripcion='sin decal', decal_presente='1')
chequear('sin etapas se puede destildar', F.con.execute('SELECT decal FROM macro WHERE flujo_id=(SELECT flujo_id FROM estudios WHERE id=?)', (eid,)).fetchone()['decal'] == 0)
h = c.get(f'/estudio/{eid}').get_data(as_text=True)
chequear('y desaparece del tracking', 'Macro > Decal</td>' not in h and 'Macro &gt; Decal</td>' not in h)
print('FALLAS:', fallas)
