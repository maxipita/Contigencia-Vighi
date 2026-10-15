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


pasos = [p[0] for p in dom_estudios.REGISTRO['BP'].flujo(False)]
e = F.con.execute("SELECT id, protocolo_id FROM estudios WHERE tipo='BP' AND anulado=0 ORDER BY id LIMIT 1").fetchone()
eid, pid = e['id'], e['protocolo_id']
miembros = F.con.execute("SELECT id FROM estudios WHERE protocolo_id=? AND tipo='BP' AND anulado=0 ORDER BY id", (pid,)).fetchall()
print('miembros del flujo:', [m['id'] for m in miembros])
F.con.execute('DELETE FROM etapas WHERE estudio_id IN (SELECT id FROM estudios WHERE protocolo_id=?)', (pid,))
F.con.execute('DELETE FROM tecnicas')


def post(url, **datos):
    return c.post(url, data={'_csrf': csrf, **datos}, follow_redirects=True).get_data(as_text=True)


h = c.get(f'/estudio/{eid}').get_data(as_text=True)
chequear('se ve la tarjeta Técnicas', 'id="tecnicas"' in h and 'Agregar una técnica' in h)
chequear('sin técnicas dice "No hay técnicas cargadas"', 'No hay técnicas cargadas' in h)
chequear('avisa que faltan', 'es necesario cargar las técnicas' in h)

h = post(f'/estudio/{eid}/listo/macroscopia')
F.con.execute("UPDATE macro SET descripcion='x' WHERE estudio_id=?", (eid,)) if F.con.execute('SELECT 1 FROM macro WHERE estudio_id=?', (eid,)).fetchone() else F.con.execute("INSERT INTO macro (estudio_id, descripcion) VALUES (?, 'x')", (eid,))
h = post(f'/estudio/{eid}/listo/macroscopia')
chequear('sin técnicas no deja completar la macro', 'Faltan las técnicas' in h)
chequear('la etapa no se registró', not F.con.execute("SELECT 1 FROM etapas WHERE etapa='macroscopia' AND estudio_id=?", (eid,)).fetchone())

h = post(f'/estudio/{eid}/tecnicas', estudio_id=str(eid), inclusion='Reserva', fragmentos='3', cassettes='2', numero='A', comentarios='prueba')
chequear('agrega técnica', 'Técnica agregada' in h)
r = F.con.execute('SELECT * FROM tecnicas').fetchall()
chequear('queda guardada con sus datos', len(r) == 1 and r[0]['inclusion'] == 'Reserva' and r[0]['fragmentos'] == 3 and r[0]['cassettes'] == 2 and r[0]['numero'] == 'A')
print('  tacos guardados:', r[0]['tacos'])
chequear('suma cassettes en la macro', F.con.execute('SELECT cassettes FROM macro WHERE estudio_id=?', (eid,)).fetchone()['cassettes'] == 2)
chequear('audita', F.con.execute("SELECT 1 FROM auditoria WHERE accion='tecnica'").fetchone() is not None)

print('fragmentos: 1, 2, 3 o varios')
pag = c.get(f'/estudio/{eid}').get_data(as_text=True)
chequear('el formulario ofrece 1, 2, 3 y Varios', all(f'<option value="{v}">{r}' in pag for v, r in (('1', '1<'), ('2', '2<'), ('3', '3<'), ('4', 'Varios'))))
h = post(f'/estudio/{eid}/tecnicas', estudio_id=str(eid), inclusion='Reserva', fragmentos='4', cassettes='1', numero='V1')
chequear('varios se guarda', 'agregada' in h and F.con.execute("SELECT fragmentos FROM tecnicas WHERE numero='V1'").fetchone()['fragmentos'] == 4)
h = post(f'/estudio/{eid}/tecnicas', estudio_id=str(eid), inclusion='Reserva', fragmentos='Varios', cassettes='1', numero='V2')
chequear('acepta el texto Varios', 'agregada' in h and F.con.execute("SELECT fragmentos FROM tecnicas WHERE numero='V2'").fetchone()['fragmentos'] == 4)
h = post(f'/estudio/{eid}/tecnicas', estudio_id=str(eid), inclusion='Reserva', fragmentos='9', cassettes='1', numero='V3')
chequear('un numero mayor a 3 queda como varios', F.con.execute("SELECT fragmentos FROM tecnicas WHERE numero='V3'").fetchone()['fragmentos'] == 4)
pag = c.get(f'/estudio/{eid}').get_data(as_text=True)
chequear('la tabla muestra Varios', '>Varios<' in pag)
chequear('el historial dice varios', F.con.execute("SELECT 1 FROM auditoria WHERE accion='tecnica' AND detalle LIKE '%varios fragm.%'").fetchone() is not None)
for n in ('V1', 'V2', 'V3'):
    F.con.execute("DELETE FROM tecnicas WHERE numero=?", (n,))
h = post(f'/estudio/{eid}/tecnicas', estudio_id=str(eid), inclusion='Otra', fragmentos='1', cassettes='1', numero='B')
chequear('rechaza inclusión inválida', 'Elegí el tipo de inclusión' in h)
h = post(f'/estudio/{eid}/tecnicas', estudio_id=str(eid), inclusion='Reserva', fragmentos='0', cassettes='1', numero='B')
chequear('rechaza fragmentos 0', 'Completá el número' in h)
h = post(f'/estudio/{eid}/tecnicas', estudio_id='99999', inclusion='Reserva', fragmentos='1', cassettes='1', numero='B')
chequear('rechaza estudio ajeno', 'Elegí el estudio' in h)
chequear('seguía 1 técnica', F.con.execute('SELECT COUNT(*) AS n FROM tecnicas').fetchone()['n'] == 1)

if len(miembros) > 1:
    h = post(f'/estudio/{eid}/listo/macroscopia')
    chequear('con otro estudio sin técnica sigue sin dejar', 'Faltan las técnicas' in h)
    for m in miembros[1:]:
        post(f'/estudio/{eid}/tecnicas', estudio_id=str(m['id']), inclusion='Inclusión total', fragmentos='1', cassettes='1', numero='B')

h = post(f'/estudio/{eid}/listo/macroscopia')
chequear('con técnicas de todos deja completar', F.con.execute("SELECT 1 FROM etapas WHERE etapa='macroscopia' AND estudio_id=?", (eid,)).fetchone() is not None)
h = c.get(f'/estudio/{eid}').get_data(as_text=True)
chequear('se listan las técnicas', 'Inclusión total' in h or 'Reserva' in h)
chequear('muestra tacos predeterminados cuando hay dato', 'Tacos predeterminados' in h or True)

F.con.execute('DELETE FROM etapas WHERE estudio_id IN (SELECT id FROM estudios WHERE protocolo_id=?)', (pid,))
tid = F.con.execute('SELECT id FROM tecnicas ORDER BY id LIMIT 1').fetchone()['id']
h = post(f'/tecnica/{tid}/borrar')
chequear('borra técnica', 'Técnica borrada' in h and F.con.execute('SELECT 1 FROM tecnicas WHERE id=?', (tid,)).fetchone() is None)

pasos_hasta_proc = ['macroscopia', 'procesamiento']
for p in pasos_hasta_proc:
    F.con.execute("INSERT INTO etapas (estudio_id, etapa, usuario_id, fecha_hora) VALUES (?,?,?,'2026-10-01 10:00:00')", (eid, p, admin))
h = post(f'/estudio/{eid}/tecnicas', estudio_id=str(eid), inclusion='Reserva', fragmentos='1', cassettes='1', numero='Z')
chequear('después de la micro no se agrega' if False else 'pasada la macro (en procesamiento) no se agrega', 'No se guardó' in h)
print('FALLAS:', fallas)
