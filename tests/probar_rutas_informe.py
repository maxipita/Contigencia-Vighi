import io, os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
from datos_informe import preparar

A, db, ids, admin = preparar()
from PIL import Image

fallas = []


def chequear(nombre, ok, detalle=''):
    print(('  OK   ' if ok else '  FALLA'), nombre, '' if ok else detalle)
    if not ok:
        fallas.append(nombre)


def cliente(uid):
    c = A.app.test_client()
    with c.session_transaction() as s:
        s['uid'] = uid
    c.get('/')                                   # crea el token CSRF
    return c


def token(c):
    with c.session_transaction() as s:
        return s['csrf']


def png(w=300, h=120, formato='PNG'):
    b = io.BytesIO()
    Image.new('RGB', (w, h), (255, 255, 255)).save(b, formato)
    return b.getvalue()


with A.app.app_context():
    med = db.uno("SELECT id FROM usuarios WHERE iniciales='DM'")['id']          # médica firmante: perfil "Médico firmante"
    ing = db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, debe_cambiar_clave, perfil_id) VALUES ('ZZING','Ingreso','ingreso',0,1,0,(SELECT id FROM perfiles WHERE nombre='Ingreso'))")
    perfil_firmante = db.uno("SELECT id, permisos FROM perfiles WHERE nombre='Médico firmante'")
bp, pap, pendiente = ids['bp'], ids['pap'], ids['pendiente']
p_bp, p_pap, p_pendiente, p_ct = ids['p_bp'], ids['p_pap'], ids['p_pendiente'], ids['p_ct']

print('1) permiso del perfil')
chequear('el perfil "Médico firmante" trae el permiso informe', 'informe' in perfil_firmante['permisos'], perfil_firmante['permisos'])

print('2) quién puede generar el informe')
ca, cm, ci = cliente(admin), cliente(med), cliente(ing)
for nombre, c in (('administrador', ca), ('médica firmante', cm)):
    r = c.get(f'/protocolo/{p_bp}/informe')
    chequear(f'{nombre} ve la pantalla de revisión', r.status_code == 200 and 'Informe Histopatológico' in r.get_data(as_text=True), r.status_code)
r = ci.get(f'/protocolo/{p_bp}/informe')
chequear('un usuario de Ingreso (sin permiso) es rechazado', r.status_code == 302, r.status_code)
r = ci.post(f'/protocolo/{p_bp}/informe.pdf', data={'_csrf': token(ci)})
chequear('y no puede bajar el PDF por la ruta directa', r.status_code == 302 and r.mimetype != 'application/pdf', (r.status_code, r.mimetype))
r = cliente(admin).post(f'/protocolo/{p_bp}/informe.pdf', data={})
chequear('sin token CSRF se rechaza', r.status_code == 400, r.status_code)
r = A.app.test_client().get(f'/protocolo/{p_bp}/informe')
chequear('sin iniciar sesión va al login', r.status_code == 302 and '/login' in r.headers['Location'])

print('3) el PDF')
r = cm.post(f'/protocolo/{p_bp}/informe.pdf', data={'_csrf': token(cm), 'comentario': 'Correlacionar con clínica <b>& estudios</b> "especiales" ñandú µ'}, follow_redirects=True)
chequear('devuelve un PDF', r.status_code == 200 and r.mimetype == 'application/pdf' and r.data[:4] == b'%PDF', (r.status_code, r.mimetype))
chequear('se abre en el navegador con nombre de archivo', 'inline' in r.headers.get('Content-Disposition', '') and 'Informe_C000101.pdf' in r.headers.get('Content-Disposition', ''), r.headers.get('Content-Disposition'))
import fitz
texto = '\n'.join(p.get_text() for p in fitz.open(stream=r.data, filetype='pdf'))
chequear('el comentario va con sus caracteres especiales tal cual (sin interpretar HTML)', '<b>& estudios</b>' in texto and 'ñandú' in texto, texto[-700:])
chequear('lleva los datos del protocolo', 'MANCINI' in texto and 'C000101' in texto and 'Adenocarcinoma' in texto)
with A.app.app_context():
    ult = db.uno("SELECT * FROM auditoria WHERE accion='informe_pdf' ORDER BY id DESC")
chequear('queda registrado quién lo generó', ult and ult['usuario_id'] == med and ult['protocolo_id'] == p_bp and 'Diana' in ult['detalle'], dict(ult) if ult else None)
r = cm.post(f'/protocolo/{p_pendiente}/informe.pdf', data={'_csrf': token(cm)})
chequear('un estudio sin informar no genera PDF', r.status_code == 302 and r.mimetype != 'application/pdf')
with A.app.app_context():
    db.ex("UPDATE estudios SET anulado=1 WHERE id=?", (ids['ct'],))
r = cm.post(f'/protocolo/{p_ct}/informe.pdf', data={'_csrf': token(cm)})
chequear('un estudio anulado no genera PDF', r.status_code == 302 and r.mimetype != 'application/pdf')
r = cm.post('/protocolo/99999/informe.pdf', data={'_csrf': token(cm)})
chequear('un estudio inexistente no rompe (no es un 500)', r.status_code in (302, 404), r.status_code)
r = cm.post(f'/protocolo/{p_bp}/informe.pdf', data={'_csrf': token(cm), 'comentario': 'x' * 50000}, follow_redirects=True)
chequear('un comentario enorme se recorta y no rompe', r.status_code == 200 and r.data[:4] == b'%PDF')

print('4) botón en la ficha del estudio')
t = cm.get(f'/estudio/{bp}').get_data(as_text=True)
chequear('aparece en un estudio informado para quien tiene el permiso', 'El informe en PDF es del protocolo completo' in t)
t = ci.get(f'/estudio/{bp}').get_data(as_text=True)
chequear('no aparece para quien no tiene el permiso', 'El informe en PDF es del protocolo completo' not in t)

print('5) firma y matrícula en Usuarios')
r = ca.get(f'/usuarios/{med}')
t = r.get_data(as_text=True)
chequear('el formulario tiene los campos nuevos y acepta archivos', r.status_code == 200 and 'name="mn"' in t and 'name="firma"' in t and 'multipart/form-data' in t)
chequear('muestra la firma ya cargada', f'/usuarios/{med}/firma' in t)


def guardar(c, uid, firma=None, **extra):
    with A.app.app_context():
        pid = db.uno("SELECT id FROM perfiles WHERE nombre='Médico firmante'")['id']
    datos = {'_csrf': token(c), 'iniciales': 'DM', 'nombre': 'Diana Miserendino', 's_firmante': '1', 'activo': '1', 'perfil_id': str(pid),
             'titulo': 'Dra.', 'mn': '98395', 'mp': '451876'}
    datos.update(extra)
    if firma:
        datos['firma'] = (io.BytesIO(firma[0]), firma[1])
    return c.post(f'/usuarios/{uid}', data=datos, content_type='multipart/form-data')


def firma_guardada():
    with A.app.app_context():
        f = db.uno("SELECT imagen FROM firmas WHERE usuario_id=?", (med,))
        from vighi.core import almacen
        return almacen.leer(f['imagen']) if f else None


antes = firma_guardada()
r = guardar(ca, med, firma=(b'esto es texto, no una imagen', 'firma.png'))
chequear('un archivo que no es imagen (aunque se llame .png) se rechaza', 'no es una imagen' in r.get_data(as_text=True) and firma_guardada() == antes)
r = guardar(ca, med, firma=(png(formato='GIF'), 'firma.gif'))
chequear('un GIF se rechaza (solo PNG o JPG)', firma_guardada() == antes)
r = guardar(ca, med, firma=(png(2400, 900, 'JPEG'), 'firma.jpg'))
nueva = firma_guardada()
img = Image.open(io.BytesIO(nueva))
chequear('un JPG grande se acepta y se guarda como PNG achicado', r.status_code == 302 and nueva != antes and img.format == 'PNG' and img.size[0] <= 900 and img.size[1] <= 360, (r.status_code, img.format, img.size))
r = guardar(ca, med, titulo='Presidente', mn='9' * 80)
with A.app.app_context():
    u = db.uno("SELECT titulo, mn, mp FROM usuarios WHERE id=?", (med,))
chequear('un título inventado se ignora y la matrícula se recorta a 20', u['titulo'] == '' and len(u['mn']) == 20, dict(u))
guardar(ca, med)                                          # vuelve a Dra. y sus matrículas, sin tocar la firma
with A.app.app_context():
    u = db.uno("SELECT titulo, mn, mp FROM usuarios WHERE id=?", (med,))
chequear('guardar sin subir archivo conserva la firma', firma_guardada() == nueva and u['titulo'] == 'Dra.' and u['mp'] == '451876')
r = ca.get(f'/usuarios/{med}/firma')
chequear('el administrador puede ver la firma', r.status_code == 200 and r.mimetype == 'image/png')
chequear('un usuario común no puede ver la imagen de la firma', cm.get(f'/usuarios/{med}/firma').status_code == 403)
chequear('ni un usuario sin permisos', ci.get(f'/usuarios/{med}/firma').status_code == 403)
chequear('ni sin sesión', A.app.test_client().get(f'/usuarios/{med}/firma').status_code in (302, 403))
chequear('un usuario común no puede cambiar firmas por la ruta de edición', cm.post(f'/usuarios/{med}', data={'_csrf': token(cm), 'iniciales': 'DM'}).status_code in (302, 403))
r = ca.post(f'/usuarios/{med}', data={'_csrf': token(ca), 'iniciales': 'DM', 'firma': (io.BytesIO(b'0' * (41 * 1024 * 1024)), 'enorme.png')}, content_type='multipart/form-data')
chequear('un envío de más de 40 MB se corta y avisa', r.status_code == 302, r.status_code)
guardar(ca, med, quitar_firma='1')
chequear('se puede quitar la firma', firma_guardada() is None)
with A.app.app_context():
    d = __import__('vighi.dominio.informes', fromlist=['x']).armar(bp)
chequear('sin firma el informe lo avisa', any('firma' in a for a in d['avisos']))
r = cm.post(f'/protocolo/{p_bp}/informe.pdf', data={'_csrf': token(cm)}, follow_redirects=True)
chequear('y igual se genera (sin la imagen de la firma)', r.status_code == 200 and r.data[:4] == b'%PDF')
with A.app.app_context():
    n = db.uno("SELECT COUNT(*) AS n FROM auditoria WHERE accion='firma'")['n']
chequear('cargar y quitar firmas queda en la auditoría', n >= 2, n)

print('\nFALLAS:', fallas if fallas else 'ninguna')
