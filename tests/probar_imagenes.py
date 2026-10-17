import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos_informe
from PIL import Image

A, db, ids, admin = datos_informe.preparar()
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


def foto(ancho, alto, formato='JPEG'):
    img = Image.frombytes('RGB', (ancho, alto), os.urandom(ancho * alto * 3))
    b = io.BytesIO()
    img.save(b, formato, quality=95) if formato == 'JPEG' else img.save(b, formato)
    b.seek(0)
    return b


pid = 1
chequear('sin imagenes', 'Todavía no hay imágenes' in c.get(f'/protocolo/{pid}').get_data(as_text=True))
grande = foto(4000, 3000)
print('  tamaño original', len(grande.getvalue()) // 1024, 'KB')
r = c.post(f'/protocolo/{pid}/imagenes', data={'_csrf': csrf, 'descripcion': 'Corte 40x',
                                               'imagenes': [(grande, 'micro1.jpg'), (foto(800, 600, 'PNG'), 'dos.png'), (io.BytesIO(b'no soy imagen'), 'malo.jpg')]},
           content_type='multipart/form-data')
print(r.status_code, r.headers.get('Location'))
filas = F.con.execute('SELECT id, nombre, descripcion, length(imagen), length(miniatura) FROM imagenes WHERE protocolo_id=?', (pid,)).fetchall()
print([tuple(x) for x in filas])
chequear('sin elegir tipo queda vacío', F.con.execute('SELECT COUNT(*) FROM imagenes WHERE protocolo_id=? AND COALESCE(tipo, \'\')=\'\'', (pid,)).fetchone()[0] == 2)
chequear('la lista de tipos viene cargada', 'Historia clínica' in c.get(f'/protocolo/{pid}').get_data(as_text=True) and 'name="tipo"' in c.get(f'/protocolo/{pid}').get_data(as_text=True))
r = c.post(f'/protocolo/{pid}/imagenes', data={'_csrf': csrf, 'tipo': 'Muestra', 'imagenes': [(foto(600, 400, 'PNG'), 'con_tipo.png')]}, content_type='multipart/form-data')
r = c.post(f'/protocolo/{pid}/imagenes', data={'_csrf': csrf, 'tipo': 'Inventado', 'imagenes': [(foto(600, 400, 'PNG'), 'tipo_falso.png')]}, content_type='multipart/form-data')
tipos = dict(F.con.execute('SELECT nombre, COALESCE(tipo, \'\') FROM imagenes WHERE protocolo_id=?', (pid,)).fetchall())
chequear('guarda el tipo elegido y descarta uno que no está en la lista', tipos.get('con_tipo.png') == 'Muestra' and tipos.get('tipo_falso.png') == '')
chequear('la galería muestra el tipo', '<span class="chip">Muestra</span>' in c.get(f'/protocolo/{pid}').get_data(as_text=True))
F.con.execute('DELETE FROM imagenes WHERE nombre IN (\'con_tipo.png\', \'tipo_falso.png\')')
F.con.commit()
chequear('subió 2 de 3 (la falsa se rechaza)', len(filas) == 2)
chequear('guardada (base64) < 1.7 MB', all(x[3] <= 1_700_000 for x in filas))
chequear('miniatura chica', all(x[4] < 80_000 for x in filas))
iid = filas[0][0]
r = c.get(f'/imagen/{iid}')
chequear('ver imagen', r.status_code == 200 and r.mimetype == 'image/jpeg' and 'private' in r.headers['Cache-Control'])
im = Image.open(io.BytesIO(r.data))
chequear('reducida a <=2000px', max(im.size) <= 2000)
chequear('miniatura', c.get(f'/imagen/{iid}/mini').status_code == 200)
chequear('404', c.get('/imagen/9999').status_code == 404)
h = c.get(f'/protocolo/{pid}').get_data(as_text=True)
chequear('galeria en protocolo', h.count('data-visor') == 2 and 'Corte 40x' in h)
eid = F.con.execute('SELECT id FROM estudios WHERE protocolo_id=? LIMIT 1', (pid,)).fetchone()[0]
he = c.get(f'/estudio/{eid}').get_data(as_text=True)
chequear('galeria en estudio (escritura)', he.count('data-visor') == 2 and 'Subir como imagen' in he)
r = c.post(f'/imagen/{iid}/borrar', data={'_csrf': csrf})
chequear('borrar', r.status_code == 302 and F.con.execute('SELECT COUNT(*) FROM imagenes').fetchone()[0] == 1)
print([tuple(x) for x in F.con.execute("SELECT accion, detalle FROM auditoria WHERE accion LIKE 'imagen%' ORDER BY id").fetchall()])
r = c.post(f'/protocolo/{pid}/imagenes', data={'_csrf': csrf}, content_type='multipart/form-data')
chequear('sin archivo avisa', r.status_code == 302)
anon = A.app.test_client()
chequear('sin login no ve', anon.get('/imagen/2').status_code in (302, 401))
cupo = []
for i in range(31):
    cupo.append((foto(60, 60), f'x{i}.jpg'))
c.post(f'/protocolo/{pid}/imagenes', data={'_csrf': csrf, 'imagenes': cupo}, content_type='multipart/form-data')
chequear('maximo 30', F.con.execute('SELECT COUNT(*) FROM imagenes WHERE protocolo_id=?', (pid,)).fetchone()[0] == 30)
print('FALLAS:', fallas)
