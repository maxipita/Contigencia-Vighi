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


def valores():
    return [r['valor'] for r in db._conectar().execute("SELECT valor FROM listas WHERE nombre='tipos_imagen' ORDER BY orden").fetchall()]


def cliente(uid):
    c = A.app.test_client()
    with c.session_transaction() as s:
        s['uid'] = uid
    c.get('/')
    with c.session_transaction() as s:
        return c, s['csrf']


print('1) la lista nace con los seis tipos del sistema anterior')
chequear('una base nueva trae los seis tipos', valores() == list(db.TIPOS_IMAGEN_INICIALES), valores())
chequear('también «Orden médica» y «Presupuesto»', 'Orden médica' in valores() and 'Presupuesto' in valores())

print('2) una base que ya existía la recibe una sola vez')
directa = db._conectar()
directa.execute("DELETE FROM listas WHERE nombre='tipos_imagen'")
directa.execute("DELETE FROM pasos_unicos WHERE clave='tipos_imagen'")
chequear('sin la lista y sin la marca, está vacía', valores() == [])
db.inicializar()
chequear('al arrancar se crea con los seis tipos', valores() == list(db.TIPOS_IMAGEN_INICIALES), valores())
directa = db._conectar()
directa.execute("DELETE FROM listas WHERE nombre='tipos_imagen'")
directa.execute("INSERT INTO listas (nombre, orden, valor) VALUES ('tipos_imagen', 0, 'Solo este')")
db.inicializar()
chequear('un segundo arranque no pisa lo que cambió el administrador', valores() == ['Solo este'], valores())

print('3) se edita desde Listados')
c, csrf = cliente(admin)
h = c.get('/listados').get_data(as_text=True)
chequear('Listados tiene «Tipos de imagen»', 'Tipos de imagen' in h)
r = c.post('/listados', data={'_csrf': csrf, 'lista': 'tipos_imagen', 'valores': 'Macro\nMicro\nFoto de la pieza'})
chequear('guarda la lista nueva', r.status_code == 302 and valores() == ['Macro', 'Micro', 'Foto de la pieza'], valores())
with A.app.app_context():
    pid = db.uno("SELECT id FROM protocolos ORDER BY id LIMIT 1")['id']
h = c.get(f'/protocolo/{pid}').get_data(as_text=True)
chequear('el protocolo ofrece la lista editada para subir', '<option value="Foto de la pieza">' in h and 'Historia clínica' not in h)

print()
print('FALLAS:', fallas if fallas else 'ninguna')
sys.exit(1 if fallas else 0)
