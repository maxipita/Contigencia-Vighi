import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos_informe

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


def post(url, **datos):
    return c.post(url, data={'_csrf': csrf, **datos}, follow_redirects=True).get_data(as_text=True)


F.con.execute("INSERT INTO lotes (codigo, tipo_lote, fecha, numero, cerrado, creado_por, creado_en) VALUES ('ENDO-1013.1','ENDO','2026-10-13',1,0,?, '2026-10-13 08:00:00')", (admin,))
_lid = F.con.execute("SELECT id FROM lotes WHERE codigo='ENDO-1013.1'").fetchone()['id']
F.con.execute("UPDATE estudios SET lote_id=? WHERE tipo='BP' AND anulado=0", (_lid,))
lotes = F.con.execute("""SELECT l.id, l.codigo, COUNT(*) AS n FROM lotes l JOIN estudios e ON e.lote_id=l.id
                         WHERE e.anulado=0 AND e.tipo='BP' GROUP BY l.id ORDER BY n DESC""").fetchall()
print('lotes:', [tuple(r) for r in lotes][:5])
lid = lotes[0]['id']
est = F.con.execute("SELECT id, protocolo_id, tipo FROM estudios WHERE lote_id=? AND anulado=0", (lid,)).fetchall()
pids = sorted({e['protocolo_id'] for e in est})
print('estudios del lote:', len(est), 'protocolos:', pids)
F.con.execute("UPDATE protocolos SET borrador=0 WHERE id IN (%s)" % ','.join(map(str, pids)))
F.con.execute("DELETE FROM etapas WHERE estudio_id IN (SELECT id FROM estudios WHERE lote_id=?)", (lid,))
F.con.execute('DELETE FROM tecnicas')
F.con.execute('DELETE FROM macro')
F.con.execute('DELETE FROM micro')

h = c.get(f'/lotes/{lid}').get_data(as_text=True)
chequear('el lote muestra el botón de avanzar (macroscopía)', 'Avanzar lote: completar Macroscopía' in h)

h = post(f'/lotes/{lid}/avanzar', etapa='macroscopia')
chequear('sin macro cargada no avanza y dice cuál falta', 'No se avanzó el lote' in h and 'descripción macroscópica' in h)
chequear('no se registró nada', F.con.execute("SELECT COUNT(*) AS n FROM etapas WHERE estudio_id IN (SELECT id FROM estudios WHERE lote_id=?)", (lid,)).fetchone()['n'] == 0)

duenos = {}
for e in est:
    duenos.setdefault((e['protocolo_id'], e['tipo']), []).append(e['id'])
for ids_ in duenos.values():
    cab = min(ids_)
    F.con.execute("INSERT INTO macro (estudio_id, descripcion) VALUES (?, 'macro de prueba')", (cab,))
h = post(f'/lotes/{lid}/avanzar', etapa='macroscopia')
chequear('sin técnicas tampoco avanza', 'Faltan las técnicas' in h and F.con.execute("SELECT COUNT(*) AS n FROM etapas WHERE estudio_id IN (SELECT id FROM estudios WHERE lote_id=?)", (lid,)).fetchone()['n'] == 0)
for e in est:
    F.con.execute("INSERT INTO tecnicas (estudio_id, numero, fragmentos, inclusion, tacos, cassettes, comentarios, usuario_id, creado_en) VALUES (?, 'A', 1, 'Reserva', 1, 1, '', ?, '2026-10-01 10:00:00')", (e['id'], admin))

h = post(f'/lotes/{lid}/avanzar', etapa='procesamiento')
chequear('rechaza si la etapa no coincide con la actual', 'cambió de etapa' in h)

h = post(f'/lotes/{lid}/avanzar', etapa='macroscopia')
n = F.con.execute("SELECT COUNT(*) AS n FROM etapas WHERE etapa='macroscopia'").fetchone()['n']
chequear('avanza todos los estudios del lote', n == len(est) and 'registrada' in h)
chequear('audita una línea por protocolo', F.con.execute("SELECT COUNT(*) AS n FROM auditoria WHERE accion='listo' AND detalle LIKE '%(lote %'").fetchone()['n'] == len(duenos))
h = c.get(f'/lotes/{lid}').get_data(as_text=True)
chequear('ahora ofrece la etapa siguiente', 'Avanzar lote: completar Procesamiento' in h)

h = post(f'/lotes/{lid}/avanzar', etapa='procesamiento')
chequear('avanza otra vez (procesamiento)', F.con.execute("SELECT COUNT(*) AS n FROM etapas WHERE etapa='procesamiento'").fetchone()['n'] == len(est))

if len(duenos) > 1:
    un_flujo = list(duenos.values())[0]
    F.con.execute("INSERT INTO etapas (estudio_id, etapa, usuario_id, fecha_hora) VALUES (?, 'inclusion', ?, '2026-10-02 10:00:00')", (un_flujo[0], admin))
    for x in un_flujo[1:]:
        F.con.execute("INSERT INTO etapas (estudio_id, etapa, usuario_id, fecha_hora) VALUES (?, 'inclusion', ?, '2026-10-02 10:00:00')", (x, admin))
    h = c.get(f'/lotes/{lid}').get_data(as_text=True)
    chequear('con etapas distintas no ofrece el botón y explica por qué', 'Avanzar lote: completar' not in h and 'no están todas en la misma etapa' in h)
    h = post(f'/lotes/{lid}/avanzar', etapa='inclusion')
    chequear('y el POST directo tampoco avanza', 'no están todas en la misma etapa' in h)
    chequear('sin cambios en la base', F.con.execute("SELECT COUNT(*) AS n FROM etapas WHERE etapa='inclusion'").fetchone()['n'] == len(un_flujo))
else:
    print('  (un solo protocolo en el lote: no se prueba la mezcla)')

print('FALLAS:', fallas)
