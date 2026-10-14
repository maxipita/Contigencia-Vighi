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
print(pasos)
e = F.con.execute("SELECT id, protocolo_id FROM estudios WHERE tipo='BP' AND anulado=0 ORDER BY id LIMIT 1").fetchone()
eid = e['id']
F.con.execute('DELETE FROM etapas WHERE estudio_id=?', (eid,))


def cargar_hasta(etapa):
    F.con.execute('DELETE FROM etapas WHERE estudio_id=?', (eid,))
    for p in pasos:
        if p == etapa:
            break
        F.con.execute("INSERT INTO etapas (estudio_id, etapa, usuario_id, fecha_hora) VALUES (?,?,?,'2026-10-01 10:00:00')", (eid, p, admin))


def guardar(texto):
    c.post(f'/estudio/{eid}/macro', data={'_csrf': csrf, 'descripcion': texto, 'cassettes': '2'})
    r = F.con.execute('SELECT descripcion FROM macro WHERE estudio_id=?', (eid,)).fetchone()
    return r['descripcion'] if r else None


cargar_hasta('macroscopia')
chequear('en macro se edita', guardar('uno') == 'uno')
cargar_hasta('microscopia')
h = c.get(f'/estudio/{eid}').get_data(as_text=True)
i = h.index('id="macro"')
chequear('en micro la macro no está bloqueada', '🔒' not in h[i:i + 400])
chequear('en micro se guarda la macro', guardar('dos') == 'dos')
cargar_hasta('informe') if 'informe' in pasos else None
siguiente = pasos[pasos.index('microscopia') + 1] if 'microscopia' in pasos and pasos.index('microscopia') + 1 < len(pasos) else None
if siguiente:
    cargar_hasta(siguiente)
    F.con.execute("INSERT INTO etapas (estudio_id, etapa, usuario_id, fecha_hora) VALUES (?,?,?,'2026-10-01 10:00:00')", (eid, 'microscopia', admin))
    chequear('pasada la micro vuelve a bloquear', guardar('tres') == 'dos')
cargar_hasta('lote') if 'lote' in pasos else None
print('FALLAS:', fallas)
