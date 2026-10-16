import base64
import os
import sys
import threading

os.environ['PROBAR_D1'] = '1'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos_informe

A, db, ids, admin = datos_informe.preparar()
from vighi.servicios import lotes as srv_lotes
F = datos_informe.FALSO
from vighi.core import d1
import fake_d1

fallas = []


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


def cliente():
    c = A.app.test_client()
    with c.session_transaction() as s:
        s['uid'] = admin
    c.get('/')
    return c


def tok(c):
    with c.session_transaction() as s:
        return s['csrf']


def uno(sql, params=()):
    r = F.con.execute(sql, params).fetchone()
    return dict(r) if r else None


def confirmar(cl, inicio, n, lote='ENDO'):
    if not uno("SELECT 1 FROM ubicaciones WHERE abreviatura='UB'"):
        F.con.execute("INSERT INTO ubicaciones (abreviatura) VALUES ('UB')")
    return cl.post('/api/etiquetas/confirmar', json={'tipo': 'bp', 'inicio': inicio, 'n': n, 'params': {'fecha': '2026-10-09', 'lote': lote, 'cito': '', 'ubicacion': 'UB'}},
                   headers={'X-CSRF': tok(cl)})


c = cliente()
print('1) etiquetas de Recepción (bloqueo + lote atómico)')
r = confirmar(c, 1, 5).get_json()
chequear('se confirma el rango C000001 a C000005', r.get('ok'), r)
protos = [dict(x) for x in F.con.execute("SELECT numero, borrador, etiqueta_lote_id FROM protocolos WHERE numero BETWEEN 'C000001' AND 'C000005' ORDER BY numero")]
chequear('se crean 5 protocolos borrador, todos ligados al lote de etiquetas', len(protos) == 5 and all(p['borrador'] == 1 and p['etiqueta_lote_id'] == r['id'] for p in protos), protos)
est = [dict(x) for x in F.con.execute("SELECT e.tipo, e.lote_id FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id WHERE p.etiqueta_lote_id=?", (r['id'],))]
lote = uno("SELECT id, codigo FROM lotes WHERE codigo LIKE 'ENDO-%'")
chequear('cada uno con un estudio BP en el mismo lote nuevo', len(est) == 5 and all(e['tipo'] == 'BP' and e['lote_id'] == lote['id'] for e in est), (est, lote))
chequear('el bloqueo se liberó', uno("SELECT COUNT(*) AS n FROM bloqueos")['n'] == 0)
r2 = confirmar(c, 3, 5)
chequear('un rango que se pisa se rechaza (409) sin crear nada', r2.status_code == 409 and uno("SELECT COUNT(*) AS n FROM protocolos WHERE numero BETWEEN 'C000006' AND 'C000007'")['n'] == 0, r2.get_json())
chequear('y el bloqueo también se libera', uno("SELECT COUNT(*) AS n FROM bloqueos")['n'] == 0)
r3 = confirmar(c, 10, 3).get_json()
chequear('otro rango del mismo día reutiliza el lote abierto (no crea otro)', r3.get('ok') and uno("SELECT COUNT(*) AS n FROM lotes WHERE codigo LIKE 'ENDO-%'")['n'] == 1, r3)

print('2) cuatro PCs confirman el mismo rango a la vez: solo una gana')
resultados = []


def intento():
    cc = cliente()
    resultados.append(confirmar(cc, 500, 10, 'ONCO').status_code)


hilos = [threading.Thread(target=intento) for _ in range(4)]
[h.start() for h in hilos]
[h.join() for h in hilos]
chequear('solo uno se confirma (200) y los demás chocan (409)', sorted(resultados) == [200, 409, 409, 409], resultados)
chequear('el rango quedó con 10 protocolos, sin duplicados', uno("SELECT COUNT(*) AS n FROM protocolos WHERE numero BETWEEN 'C000500' AND 'C000509'")['n'] == 10)
chequear('sin bloqueos colgados', uno("SELECT COUNT(*) AS n FROM bloqueos")['n'] == 0)

print('3) un lote grande (1000 protocolos) cabe en los límites de D1')
antes_p, antes_s = F.pedidos, F.sentencias
r = confirmar(c, 1000, 1000, 'ONCO')
chequear('se confirma sin pasar el límite de 100 parámetros ni de tamaño por sentencia', r.status_code == 200 and r.get_json().get('ok'), r.get_json())
print('       pedidos:', F.pedidos - antes_p, '| sentencias:', F.sentencias - antes_s)
chequear('crea los 1000 protocolos y 1000 estudios',
         uno("SELECT COUNT(*) AS n FROM protocolos WHERE numero BETWEEN 'C001000' AND 'C001999'")['n'] == 1000
         and uno("SELECT COUNT(*) AS n FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id WHERE p.numero BETWEEN 'C001000' AND 'C001999'")['n'] == 1000)

print('4) archivos (firma y PDF) viajan y vuelven idénticos')
firma = uno("SELECT imagen FROM firmas LIMIT 1")
with A.app.app_context():
    original = bytes(db.uno("SELECT imagen FROM firmas LIMIT 1")['imagen'])
chequear('la firma se guarda como texto y vuelve como bytes iguales', original[:4] == b'\x89PNG' and firma['imagen'].startswith('~b64~') and base64.b64decode(firma['imagen'][5:]) == original)
r = c.post(f"/protocolo/{ids['p_mix']}/informe.pdf", data={'_csrf': tok(c)})
pdf = c.get(r.headers['Location'])
guardado = uno("SELECT pdf FROM informes_emitidos WHERE protocolo_id=?", (ids['p_mix'],))
chequear('el PDF del informe se guarda y se sirve igual', pdf.data[:4] == b'%PDF' and pdf.data == base64.b64decode(guardado['pdf'][5:]))

print('5) texto con tildes y símbolos')
with A.app.app_context():
    db.ex("UPDATE protocolos SET observaciones=? WHERE id=?", ('Ñandú µ ≥ 3 — “comillas” 日本', ids['p_bp']))
    leido = db.uno("SELECT observaciones FROM protocolos WHERE id=?", (ids['p_bp'],))['observaciones']
chequear('se conserva exactamente', leido == 'Ñandú µ ≥ 3 — “comillas” 日本', leido)

print('6) caché por pedido')
with A.app.test_request_context():
    db.q("SELECT COUNT(*) AS n FROM usuarios")
    antes = F.pedidos
    db.q("SELECT COUNT(*) AS n FROM usuarios")
    db.q("SELECT COUNT(*) AS n FROM usuarios")
    chequear('repetir la misma consulta en un pedido no vuelve a ir a internet', F.pedidos == antes)
    db.ex("UPDATE usuarios SET nombre=nombre WHERE id=?", (admin,))
    antes = F.pedidos
    db.q("SELECT COUNT(*) AS n FROM usuarios")
    chequear('después de escribir, sí vuelve a consultar', F.pedidos == antes + 1)
with A.app.test_request_context():
    db.q("SELECT nombre FROM usuarios WHERE id=?", (admin,))
    db.ex("UPDATE usuarios SET nombre='Cambiado' WHERE id=?", (admin,))
    chequear('y lee lo nuevo, no lo guardado', db.uno("SELECT nombre FROM usuarios WHERE id=?", (admin,))['nombre'] == 'Cambiado')
    db.ex("UPDATE usuarios SET nombre='Administrador' WHERE id=?", (admin,))

print('7) errores y reintentos')
with A.app.test_request_context():
    F.fallos = 1
    chequear('una lectura que recibe un 503 se reintenta y funciona', db.uno("SELECT 1 AS x FROM usuarios LIMIT 1")['x'] == 1)
    F.fallos = 1
    try:
        db.ex("UPDATE usuarios SET nombre=nombre WHERE id=?", (admin,))
        ok = False
    except d1.ErrorD1:
        ok = True
    chequear('una escritura NO se reintenta sola (podría duplicarse): avisa el error', ok)
    F.fallos = 0
    malo = d1.Conexion(fake_d1.CUENTA, fake_d1.BASE, 'token-equivocado')
    try:
        malo.execute("SELECT 1")
        msg = ''
    except d1.ErrorD1 as e:
        msg = str(e)
    chequear('un token equivocado da un error claro que no muestra el token', 'Authentication' in msg and 'token-equivocado' not in msg, msg)
    caido = d1.Conexion(fake_d1.CUENTA, fake_d1.BASE, fake_d1.TOKEN)
    caido._url = 'http://127.0.0.1:9/accounts/x/d1/database/y/query'
    try:
        caido.execute("SELECT 1")
        msg = ''
    except d1.ErrorD1 as e:
        msg = str(e)
    chequear('sin conexión da un error claro', 'No hay conexión' in msg, msg)
dura = A.app.test_client()
with dura.session_transaction() as s:
    s['uid'] = admin
F.fallos = 99
r = dura.get('/')
F.fallos = 0
chequear('la pantalla muestra "Sin conexión con la base de datos" (503) en vez de romperse', r.status_code == 503 and 'Sin conexión con la base de datos' in r.get_data(as_text=True), r.status_code)
chequear('y vuelve a andar cuando vuelve la conexión', cliente().get('/').status_code == 200)

print('8) restricciones de unicidad llegan como IntegrityError (lo que espera el código)')
with A.app.test_request_context():
    try:
        db.ex("INSERT INTO lotes (codigo, tipo_lote, fecha, numero, creado_en) VALUES ('ENDO-1009.9','ENDO','2026-10-09',9,'x')")
        db.ex("INSERT INTO lotes (codigo, tipo_lote, fecha, numero, creado_en) VALUES ('ENDO-1009.9','ENDO','2026-10-09',9,'x')")
        ok = False
    except db.IntegrityError:
        ok = True
    chequear('un código de lote repetido lanza db.IntegrityError', ok)
    chequear('crear_lote() funciona', srv_lotes.crear_lote('TACOS', admin)['codigo'].startswith('TACOS-'))

print('9) velocidad: pocas consultas por pantalla y datos fijos en memoria')
cv = cliente()
pm = ids['p_mix']
for nombre, url, tope in (('tablero', '/', 3), ('protocolo', f'/protocolo/{pm}', 3), ('estudio', f"/estudio/{ids['mix_b1']}", 4), ('lotes', '/lotes', 6)):
    cv.get(url)
    antes = F.pedidos
    r = cv.get(url)
    chequear(f'{nombre}: {F.pedidos - antes} consultas a internet (tope {tope}) y sin errores', r.status_code == 200 and F.pedidos - antes <= tope, F.pedidos - antes)
with A.app.test_request_context():
    antes = len(db.feriados())
    db.feriados()
    n_antes = F.pedidos
    db.feriados()
    chequear('los feriados salen de memoria (sin ir a internet) mientras no cambian', F.pedidos == n_antes)
    db.ex("INSERT INTO feriados (fecha, descripcion) VALUES ('2031-01-01', 'prueba')")
    chequear('al editarlos se refrescan en el acto', len(db.feriados()) == antes + 1)
    db.ex("DELETE FROM feriados WHERE fecha='2031-01-01'")
    chequear('y al borrar también', len(db.feriados()) == antes)
with A.app.test_request_context():
    cuenta_antes = F.pedidos
    db.precargar([("SELECT COUNT(*) AS n FROM usuarios", ()), ("SELECT COUNT(*) AS n FROM protocolos", ()), ("SELECT COUNT(*) AS n FROM estudios", ())])
    db.q("SELECT COUNT(*) AS n FROM usuarios")
    db.q("SELECT COUNT(*) AS n FROM protocolos")
    db.q("SELECT COUNT(*) AS n FROM estudios")
    chequear('precargar trae varias lecturas en un solo viaje', F.pedidos - cuenta_antes == 1, F.pedidos - cuenta_antes)
    F.fallos = 0
with A.app.test_request_context():
    n0 = F.pedidos
    db.precargar([("SELECT * FROM tabla_que_no_existe", ()), ("SELECT 1 AS x", ())])
    chequear('si una lectura adelantada falla, no rompe: se resuelve por el camino normal', F.pedidos >= n0 + 1)

print(chr(10) + 'FALLAS:', fallas if fallas else 'ninguna')
