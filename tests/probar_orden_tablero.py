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


INGRESOS = (('C000100', '2026-01-05 10:00:00'), ('P1165658-BP', '2026-01-06 08:00:00'), ('C000010', '2026-01-07 09:00:00'), ('C000009', '2026-01-07 09:00:00'))
with A.app.app_context():
    for numero, creado in INGRESOS:
        pid = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, borrador, creado_por, creado_en) VALUES (?,?,?,?,0,?,?)",
                    (numero, '2026-10-14', 'Orden', numero, admin, creado))
        db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?)",
              (pid, 'BP', 'Biopsias', 'Digestiva', 'Estómago', 'Biopsia', '1', admin, creado))

c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
c.get('/')
h = c.get('/?ver=todos').get_data(as_text=True)
numeros = re.findall(r'(C\d{6}|P1165658-BP)', h)
vistos = list(dict.fromkeys(numeros))
propios = [n for n in vistos if n in ('C000009', 'C000010', 'C000100', 'P1165658-BP')]
chequear('ordena por fecha de ingreso, el más viejo primero (aunque el número sea mayor)', propios[:2] == ['C000100', 'P1165658-BP'], propios)
chequear('con el mismo ingreso, C000009 va antes que C000010 (como persona, no como texto)', propios == ['C000100', 'P1165658-BP', 'C000009', 'C000010'], propios)
fechas = re.findall(r'<td class="muted">(\d\d)/(\d\d)/(\d{4}) (\d\d):(\d\d)</td>', h)
claves = [(a, m, d, hh, mm) for d, m, a, hh, mm in fechas]
chequear('toda la columna Ingresado está en orden ascendente', len(claves) > 4 and claves == sorted(claves), claves[:6])

print()
print('FALLAS:', 'ninguna' if not fallas else fallas)
sys.exit(1 if fallas else 0)
