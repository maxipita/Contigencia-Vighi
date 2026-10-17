import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar

A, db, ids, admin = preparar()
fallas = []


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
c.get('/')
with A.app.app_context():
    prot = db.q("SELECT p.id, p.numero FROM protocolos p WHERE p.borrador=0 AND EXISTS (SELECT 1 FROM estudios e WHERE e.protocolo_id=p.id) ORDER BY p.id")[:3]
    dias = ['2026-10-12 08:30:00', '2026-10-14 23:59:59', '2026-10-16 00:00:00']
    for p, d in zip(prot, dias):
        db.ex("UPDATE estudios SET creado_en=? WHERE protocolo_id=?", (d, p['id']))
n12, n14, n16 = [p['numero'] for p in prot]


def pagina(q):
    return c.get('/?ver=todos&' + q).get_data(as_text=True)


h = pagina('')
chequear('el tablero ofrece día, mes y año y el rango de fechas', all(f'name="{k}"' in h for k in ('dia', 'mes', 'anio', 'desde', 'hasta')))
chequear('sin fechas se ven los tres', all(n in h for n in (n12, n14, n16)))
h = pagina('desde=2026-10-12&hasta=2026-10-16')
chequear('el rango incluye los dos extremos', all(n in h for n in (n12, n14, n16)))
h = pagina('desde=2026-10-13&hasta=2026-10-15')
chequear('un rango intermedio deja solo el del medio (hasta las 23:59 cuenta)', n14 in h and n12 not in h and n16 not in h)
h = pagina('desde=2026-10-14')
chequear('solo desde: ese día en adelante', n14 in h and n16 in h and n12 not in h)
h = pagina('hasta=2026-10-14')
chequear('solo hasta: ese día hacia atrás', n12 in h and n14 in h and n16 not in h)
h = pagina('desde=2026-10-20&hasta=2026-10-25')
chequear('un rango sin casos no deja ninguno', not any(n in h for n in (n12, n14, n16)))
h = pagina('desde=basura&hasta=31/12/2026')
chequear('una fecha inválida se ignora', all(n in h for n in (n12, n14, n16)))
h = pagina('desde=2026-10-13&hasta=2026-10-15&q=' + n14)
chequear('se combina con los demás filtros', n14 in h and n12 not in h)
h = pagina('desde=2026-10-13')
chequear('la pantalla recuerda las fechas elegidas y permite quitarlas', 'value="2026-10-13"' in h and 'Quitar filtros' in h)
h = pagina('dia=14&mes=10&anio=2026')
chequear('día, mes y año juntos dejan solo ese día', n14 in h and n12 not in h and n16 not in h)
h = pagina('mes=10&anio=2026')
chequear('mes y año dejan todo el mes', all(n in h for n in (n12, n14, n16)))
h = pagina('dia=16')
chequear('solo el día filtra en cualquier mes', n16 in h and n12 not in h and n14 not in h)
h = pagina('anio=2025')
chequear('otro año no deja ninguno', not any(n in h for n in (n12, n14, n16)))
h = pagina('dia=99&mes=xx&anio=20')
chequear('un día, mes o año inválido se ignora', all(n in h for n in (n12, n14, n16)))
h = pagina('mes=10&anio=2026')
chequear('queda elegido en la lista', '<option value="10" selected>' in h and '<option value="2026" selected>' in h)
print('FALLAS:', ', '.join(fallas) if fallas else 'ninguna')
