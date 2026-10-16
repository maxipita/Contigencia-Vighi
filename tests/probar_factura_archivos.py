import io
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


def cliente(uid):
    c = A.app.test_client()
    with c.session_transaction() as s:
        s['uid'] = uid
    c.get('/')
    with c.session_transaction() as s:
        return c, s['csrf']


def subir(c, tk, fid, *archivos):
    datos = {'_csrf': tk, 'archivos': [(io.BytesIO(d), n) for n, d in archivos]}
    return c.post(f'/facturacion/{fid}/archivos', data=datos, content_type='multipart/form-data', follow_redirects=True)


def cuantos(fid):
    with A.app.app_context():
        return db.uno("SELECT COUNT(*) AS n FROM factura_archivos WHERE factura_id=?", (fid,))['n']


with A.app.app_context():
    fid = db.ex("INSERT INTO facturas (numero, estado, cobertura, creado_por, creado_en) VALUES ('0001-00000999','emitida','OSDE',?,?)", (admin, db.ahora()))
c, tk = cliente(admin)

print('1) subir y ver')
h = c.get(f'/facturacion/{fid}').get_data(as_text=True)
chequear('la factura ofrece subir archivos', 'Archivos adjuntos (0)' in h and 'name="archivos"' in h)
r = subir(c, tk, fid, ('comprobante.pdf', b'%PDF-1.4 prueba'), ('planilla.xlsx', b'PK\x03\x04xx'))
h = r.get_data(as_text=True)
chequear('sube varios a la vez', cuantos(fid) == 2 and 'Archivos adjuntos (2)' in h and 'comprobante.pdf' in h and 'planilla.xlsx' in h, h[:200])
with A.app.app_context():
    a_pdf = db.uno("SELECT id FROM factura_archivos WHERE nombre='comprobante.pdf'")['id']
    a_xls = db.uno("SELECT id FROM factura_archivos WHERE nombre='planilla.xlsx'")['id']
r = c.get(f'/facturacion/archivo/{a_pdf}')
chequear('el PDF se abre en el navegador, con su contenido', r.status_code == 200 and r.data == b'%PDF-1.4 prueba' and 'attachment' not in r.headers.get('Content-Disposition', ''), r.headers)
r = c.get(f'/facturacion/archivo/{a_xls}')
chequear('el Excel se descarga', 'attachment' in r.headers.get('Content-Disposition', '') and 'planilla.xlsx' in r.headers.get('Content-Disposition', ''))
with A.app.app_context():
    chequear('queda en el historial', db.uno("SELECT 1 FROM auditoria WHERE accion='factura_archivo'") is not None)

print('2) lo que se rechaza')
antes = cuantos(fid)
r = subir(c, tk, fid, ('virus.exe', b'MZ'))
chequear('un tipo no admitido', cuantos(fid) == antes and 'no admitido' in r.get_data(as_text=True))
r = subir(c, tk, fid, ('bueno.pdf', b'%PDF'), ('malo.js', b'x'))
chequear('si uno falla no se sube ninguno', cuantos(fid) == antes)
r = subir(c, tk, fid, ('vacio.pdf', b''))
chequear('un archivo vacío', cuantos(fid) == antes and 'vacío' in r.get_data(as_text=True))
r = c.post(f'/facturacion/{fid}/archivos', data={'_csrf': tk}, follow_redirects=True)
chequear('sin elegir nada avisa', 'Elegí al menos un archivo' in r.get_data(as_text=True))
r = subir(c, tk, fid, ('../../etc/pasaporte.pdf', b'%PDF'))
with A.app.app_context():
    n = db.uno("SELECT nombre FROM factura_archivos WHERE id=(SELECT MAX(id) FROM factura_archivos)")['nombre']
chequear('el nombre no arrastra rutas', n == 'pasaporte.pdf', n)

print('3) permisos')
with A.app.app_context():
    sin = db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, debe_cambiar_clave) VALUES ('ZZSF','Sin Fact','',0,1,0)")
cs, tks = cliente(sin)
chequear('sin el permiso de facturación no se ve ni se sube', cs.get(f'/facturacion/archivo/{a_pdf}').status_code == 302 and cs.post(f'/facturacion/{fid}/archivos', data={'_csrf': tks}).status_code == 302)
chequear('ni se borra', cs.post(f'/facturacion/archivo/{a_pdf}/borrar', data={'_csrf': tks}).status_code == 302 and cuantos(fid) > 0)

print('4) quitar')
total = cuantos(fid)
c.post(f'/facturacion/archivo/{a_xls}/borrar', data={'_csrf': tk})
chequear('quita el archivo', cuantos(fid) == total - 1)
chequear('el archivo borrado ya no se sirve', c.get(f'/facturacion/archivo/{a_xls}').status_code == 404)
with A.app.app_context():
    chequear('el borrado queda en el historial', db.uno("SELECT 1 FROM auditoria WHERE accion='factura_archivo_borrado'") is not None)
    db.ex("UPDATE facturas SET estado='anulada' WHERE id=?", (fid,))
r = subir(c, tk, fid, ('despues.pdf', b'%PDF'))
chequear('también se puede subir con la factura anulada', 'despues.pdf' in r.get_data(as_text=True))
print('FALLAS:', fallas or 'ninguna')
