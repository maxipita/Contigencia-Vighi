import hashlib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.pop('PROBAR_PG', None)
os.environ.pop('DATABASE_URL', None)
import datos_informe

A, db, ids, admin = datos_informe.preparar()
from vighi.core import d1
from vighi.herramientas import migrar_d1_a_pg
from vighi.core import pg
import psycopg

URL = 'postgresql://postgres:@127.0.0.1:55138/postgres'
fallas = []
VOLCADO = {}


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


c0 = A.app.test_client()
with c0.session_transaction() as s:
    s['uid'] = admin
c0.get('/')
with c0.session_transaction() as s:
    csrf = s['csrf']

import io
from PIL import Image
from werkzeug.datastructures import MultiDict
buf = io.BytesIO()
Image.frombytes('RGB', (500, 400), os.urandom(500 * 400 * 3)).save(buf, 'JPEG', quality=80)
r = c0.post(f"/protocolo/{ids['p_bp']}/imagenes", data={'_csrf': csrf, 'imagenes': (io.BytesIO(buf.getvalue()), 'foto1.jpg'), 'descripcion': 'prueba'},
            content_type='multipart/form-data')
print('subir imagen', r.status_code)
r = c0.post(f"/protocolo/{ids['p_bp']}/informe.pdf", data=MultiDict([('_csrf', csrf), ('comentario', 'migración')]))
print('generar informe', r.status_code, r.headers.get('Location'))

with A.app.app_context():
    prots = [r['id'] for r in db.q('SELECT id FROM protocolos ORDER BY id')]
    imgs = [r['id'] for r in db.q('SELECT id FROM imagenes ORDER BY id')]
    infs = [r['id'] for r in db.q('SELECT id FROM informes_emitidos ORDER BY id')]
print('origen: protocolos', len(prots), 'imagenes', len(imgs), 'informes', len(infs))


def foto(cliente):
    salida = {}
    urls = ['/', '/tablero', '/lotes', '/listados', '/facturacion', '/usuarios', '/templates'] + [f'/protocolo/{p}' for p in prots] + \
           [f'/imagen/{i}' for i in imgs] + [f'/imagen/{i}/mini' for i in imgs] + [f'/informe/{i}.pdf' for i in infs] + [f'/usuarios/{u}/firma' for u in (ids['med'],)]
    for u in urls:
        r = cliente.get(u)
        cuerpo = r.get_data()
        if r.mimetype == 'text/html':
            t = cuerpo.decode('utf-8', 'replace')
            t = re.sub(r'name="_csrf" value="[^"]+"|content="[0-9a-f]{20,}"', '', t)
            t = re.sub(r'\d{2}/\d{2}/\d{4} \d{2}:\d{2}( hs)?', 'FH', t)
            t = re.sub(r'window\.CSRF = "[0-9a-f]+"', 'CSRF', t)
            t = re.sub(r'<small class="base-modo">[^<]*</small>', '', t)
            t = re.sub(r'<div class="aviso ok">[^<]*</div>', '', t)
            cuerpo = t.encode()
        elif r.mimetype == 'application/pdf':
            cuerpo = re.sub(rb'/(CreationDate|ModDate|ID)[^/>]*', b'', cuerpo)
        salida[u] = (r.status_code, hashlib.sha1(cuerpo).hexdigest())
        VOLCADO.setdefault(id(cliente), {})[u] = cuerpo
    return salida


antes = foto(c0)

origen = d1.Conexion(os.environ['CLOUDFLARE_ACCOUNT_ID'], os.environ['CLOUDFLARE_D1_ID'], os.environ['CLOUDFLARE_API_TOKEN'])
with psycopg.connect(URL, autocommit=True) as cx:
    cx.execute('DROP SCHEMA public CASCADE')
    cx.execute('CREATE SCHEMA public')
pg._con_id.clear()
destino = pg.Conexion(URL)
informe = migrar_d1_a_pg.migrar(origen, destino, lambda cant: True)
print('filas:', {t: n for t, n in informe['filas'].items() if n})
print('omitidas:', informe['omitidas'], 'diferencias:', informe['diferencias'], 'error:', informe.get('error'))
chequear('migración sin error ni diferencias', not informe.get('error') and not informe['diferencias'], informe)
chequear('copió filas', sum(informe['filas'].values()) > 100, sum(informe['filas'].values()))

with A.app.app_context():
    cuenta = {t: db.uno(f'SELECT COUNT(*) AS n FROM {t}')['n'] for t in informe['filas']}
chequear('el origen no cambió', all(cuenta[t] == informe['cantidades_origen'][t] for t in cuenta))

os.environ['DATABASE_URL'] = URL
c1 = A.app.test_client()
with c1.session_transaction() as s:
    s['uid'] = admin
c1.get('/')
despues = foto(c1)
dif = [u for u in antes if antes[u] != despues[u]]
chequear('todas las pantallas, imágenes, firmas y PDF salen igual desde PostgreSQL', not dif, [(u, antes[u], despues[u]) for u in dif][:6])
chequear('hay imágenes y PDFs entre lo comparado', len(imgs) > 0 and len(infs) > 0, (len(imgs), len(infs)))

with A.app.app_context():
    nuevo = db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo) VALUES ('ZZNUEVO','Nuevo','ingreso',0,1)")
    maximo = db.uno('SELECT MAX(id) AS m FROM usuarios')['m']
chequear('la secuencia sigue después del máximo copiado', nuevo == maximo, (nuevo, maximo))
import difflib
if dif:
    a = VOLCADO[id(c0)][dif[0]].decode('utf-8','replace').splitlines(); b = VOLCADO[id(c1)][dif[0]].decode('utf-8','replace').splitlines()
    for linea in list(difflib.unified_diff(a, b, lineterm='', n=0))[:16]:
        print(linea[:240])
print('FALLAS:', fallas or 'ninguna')
