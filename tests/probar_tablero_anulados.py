import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar

A, db, ids, admin = preparar()

fallas = []


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


CREADO = '2026-03-02 09:00:00'
CASOS = {'ANU0001': (1, 1), 'ANU0002': (1, 0), 'ANU0003': (0, 0), 'ANU0004': (1,)}

with A.app.app_context():
    sentencias = []
    for numero, anulados in CASOS.items():
        sentencias.append(("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, dni, borrador, cargado_sistema, creado_por, creado_en) VALUES (?,?,?,?,?,0,0,?,?)",
                           (numero, '2026-03-02', 'Anulados', numero, '3' + numero[-4:] + '000', admin, CREADO)))
        sentencias.append(("INSERT INTO flujos (protocolo_id, tipo, creado_en) SELECT id, 'BP', ? FROM protocolos WHERE numero=?", (CREADO, numero)))
        for anulado in anulados:
            sentencias.append(("INSERT INTO estudios (protocolo_id, flujo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, anulado, creado_por, creado_en) "
                               "SELECT p.id, f.id, 'BP', 'Biopsias', 'Digestiva', 'Estómago', 'Biopsia', '1', ?, ?, ? FROM protocolos p JOIN flujos f ON f.protocolo_id=p.id AND f.tipo='BP' WHERE p.numero=?",
                               (anulado, admin, CREADO, numero)))
    db.lote_ex(sentencias)

c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
c.get('/')


def numeros(ver):
    h = c.get(f'/?ver={ver}&q=ANU').get_data(as_text=True)
    return h, set(re.findall(r'<td><a href="/protocolo/\d+"><b>([^<]+)</b>', h))


print('1) la solapa Anulados lista solo los protocolos anulados enteros')
h, anulados = numeros('anulados')
chequear('aparecen los que tienen todos sus estudios anulados', {'ANU0001', 'ANU0004'} <= anulados, anulados)
chequear('no aparece el que tiene un estudio anulado y otro activo', 'ANU0002' not in anulados, anulados)
chequear('no aparece el que no tiene nada anulado', 'ANU0003' not in anulados, anulados)
chequear('la fila dice ANULADO y cuenta las dos muestras del protocolo anulado', 'ANULADO' in h and '2 muestras' in h and 'chip flujos">BP' in h)

print('2) el protocolo con un estudio anulado sigue en las demás solapas')
for ver in ('pendientes', 'todos'):
    _, presentes = numeros(ver)
    chequear(f'ANU0002 sigue en {ver}', 'ANU0002' in presentes, presentes)
_, presentes = numeros('todos')
chequear('el anulado entero sigue visible en Todos', 'ANU0001' in presentes, presentes)

print('FALLAS:', ', '.join(fallas) if fallas else 'ninguna')
sys.exit(1 if fallas else 0)
