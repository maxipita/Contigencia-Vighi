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


with A.app.app_context():
    ahora = db.ahora()
    for numero in ('C000009', 'C000100', 'P1165658-BP', 'C000010'):
        pid = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, borrador, creado_por, creado_en) VALUES (?,?,?,?,0,?,?)",
                    (numero, '2026-10-14', 'Orden', numero, admin, ahora))
        db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?)",
              (pid, 'BP', 'Biopsias', 'Digestiva', 'Estómago', 'Biopsia', '1', admin, ahora))

c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
c.get('/')
h = c.get('/?ver=todos').get_data(as_text=True)
numeros = re.findall(r'(C\d{6}|P1165658-BP)', h)
vistos = list(dict.fromkeys(numeros))
propios = [n for n in vistos if n in ('C000009', 'C000010', 'C000100', 'P1165658-BP')]
chequear('ordena por número de protocolo, el mayor primero', propios == ['C000100', 'C000010', 'C000009', 'P1165658-BP'], propios)
todos_c = [n for n in vistos if n.startswith('C')]
chequear('C000010 va antes que C000009 (como persona, no como texto)', todos_c.index('C000010') < todos_c.index('C000009'))
chequear('toda la lista de números C está en orden descendente', todos_c == sorted(todos_c, reverse=True), todos_c)

print()
print('FALLAS:', 'ninguna' if not fallas else fallas)
sys.exit(1 if fallas else 0)
