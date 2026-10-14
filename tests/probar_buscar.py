import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos_informe
A, db, ids, admin = datos_informe.preparar()
F = datos_informe.FALSO
c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
fallas = []
def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok: fallas.append(n)
F.con.execute("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, dni, creado_por, creado_en) VALUES ('C000001','2026-10-01','Uno','Prueba','111',?,?)", (admin, '2026-10-01 10:00:00'))
pid1 = F.con.execute("SELECT id FROM protocolos WHERE numero='C000001'").fetchone()['id']
pid106 = F.con.execute("SELECT id FROM protocolos WHERE numero='C000106'").fetchone()['id']
def ir(q):
    r = c.get('/buscar', query_string={'q': q})
    return r.status_code, r.headers.get('Location', '')
for q, esperado in (('0001', pid1), ('00001', pid1), ('C0001', pid1), ('C0000001', pid1), ('0000000001', pid1), ('c 0106', pid106), ('1', pid1), ('C000001', pid1), ('c1', pid1), ('000001', pid1), ('c000001', pid1), (' 1 ', pid1), ('106', pid106), ('C000106', pid106)):
    st, loc = ir(q)
    chequear(f'"{q}" abre el protocolo', st == 302 and loc.endswith(f'/protocolo/{esperado}'), (st, loc))
st, loc = ir('999')
chequear('un número que no existe no filtra: avisa', st == 302 and loc.endswith('/') or 'tablero' in loc or loc in ('/', ''), (st, loc))
r = c.get('/buscar', query_string={'q': '999'}, follow_redirects=True)
chequear('mensaje de protocolo inexistente', 'No existe el protocolo C000999' in r.get_data(as_text=True))
st, loc = ir('Álvarez')
chequear('un texto (apellido) sigue buscando en el tablero', st == 302 and 'q=' in loc and 'ver=todos' in loc, (st, loc))
st, loc = ir('')
chequear('vacío va al tablero', st == 302)
h = c.get('/').get_data(as_text=True)
chequear('el formulario de la barra apunta a /buscar', 'action="/buscar"' in h and 'name="ver"' not in h.split('class="buscar"')[1].split('</form>')[0])
print('FALLAS:', fallas)
