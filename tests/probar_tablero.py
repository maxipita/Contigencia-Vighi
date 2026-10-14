import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos_informe
A, db, ids, admin = datos_informe.preparar()
F = datos_informe.FALSO
c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
fallas = []
def chequear(n, ok):
    print(('  OK   ' if ok else '  FALLA'), n)
    if not ok: fallas.append(n)
def filas(url):
    h = c.get(url).get_data(as_text=True)
    return h, re.findall(r'<td><a href="/protocolo/(\d+)"><b>([^<]+)</b>', h)
for ver in ('pendientes', 'informados', 'todos', 'anulados', 'mios', 'sin_cargar'):
    h, f = filas(f'/?ver={ver}')
    nums = [n for _, n in f]
    print(ver, nums)
    chequear(f'{ver}: una sola fila por protocolo', len(nums) == len(set(nums)))
    chequear(f'{ver}: sin columna Estudio', '<th>Estudio</th>' not in h and '<th>Protocolo</th><th>Paciente</th>' in h)
h, f = filas('/?ver=todos')
chequear('hay protocolos con varios estudios y lo indican', re.search(r'\d+ estudios</div>', h) is not None)
tot = len(f)
n_est = F.con.execute("SELECT COUNT(DISTINCT e.protocolo_id) AS n FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id WHERE p.borrador=0").fetchone()['n']
chequear('todos = cantidad de protocolos no borrador', tot == n_est)
h, f = filas('/?ver=todos&q=106')
chequear('el buscador filtra por protocolo', [n for _, n in f] == ['C000106'])
h, f = filas('/?ver=todos&tipo=PAP')
chequear('filtro por tipo responde', all(True for _ in f))
h, f = filas('/?ver=pendientes&semaforo=late')
chequear('filtro de semáforo responde', c.get('/?ver=todos&semaforo=late').status_code == 200)
m = re.search(r'Pendientes \((\d+)\)', c.get('/').get_data(as_text=True))
_, fp = filas('/?ver=pendientes')
chequear('el contador de pendientes cuenta protocolos', m and int(m.group(1)) == len(fp))
print('FALLAS:', fallas)
