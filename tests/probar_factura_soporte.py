import io
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar

A, db, ids, admin = preparar()
import openpyxl
from vighi.dominio import soporte

fallas = []


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


ENCABEZADO = ['Fecha', 'Protocolo', 'Descripcion', 'Paciente', 'DNI', 'Cobertura', 'NroCredencial', 'Medico', 'Matricula', 'Procedencia', 'Nomenclador',
              'Honorarios', 'Unidades', 'Neto', 'Cond.IVA', 'IVA', 'Bruto', 'Autorizacion']
FILAS = [
    [datetime(2026, 8, 12), '1139502', 'Ki 67', 'Dmitruk, Pablo', '18522593', 'OSDE', '51947/03', 'Dr X', 'MN 1', 'Sanatorio', '155053', '56536', '1', '56536', 'Exento', '0', '56536', '102'],
    [datetime(2026, 8, 12), '1139502', 'CD10', 'Dmitruk, Pablo', '18522593', 'OSDE', '51947/03', 'Dr X', 'MN 1', 'Sanatorio', '150162', '60061', '1', '60061', 'Exento', '0', '60061', '102'],
    ['2026-09-30', '1162210', 'Citología Exocervical', 'Cisneros, Viviana', '18872218', 'OSDE', '62306/2', 'Dra Y', 'MN 2', 'Paraguay', '150106', '12620', '2', '25240', 'Exento', '0', '25240', 'WP-1'],
]


def xlsx(filas, encabezado=ENCABEZADO):
    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.append(encabezado)
    for f in filas:
        hoja.append(f)
    hoja.append([None] * 13 + [sum(float(f[13]) for f in filas)])
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def cliente(uid):
    c = A.app.test_client()
    with c.session_transaction() as s:
        s['uid'] = uid
    c.get('/')
    with c.session_transaction() as s:
        return c, s['csrf']


c, tk = cliente(admin)
TOTAL = 56536 + 60061 + 25240

print('1) lectura del soporte')
leido, err = soporte.leer_soporte('s.xlsx', xlsx(FILAS))
chequear('lee el Excel, ignora la fila de total', not err and len(leido['filas']) == 3 and soporte.resumen(leido['filas'])['total'] == TOTAL, err)
chequear('toma cobertura, cantidad y unitario', leido['cobertura'] == 'OSDE' and leido['filas'][2]['cantidad'] == 2 and leido['filas'][2]['unitario'] == 12620.0)
chequear('acepta fechas en texto y en fecha', [f['fecha'] for f in leido['filas']] == ['2026-08-12', '2026-08-12', '2026-09-30'])
texto_csv = (';'.join(ENCABEZADO) + '\r\n' + '1/9/2026;77;Biopsia;Perez, Ana;1;OSDE;9;M;1;P;150101;1.234,56;1;1.234,56;Exento;0;1.234,56;1\r\n').encode('utf-16')
leido_csv, err = soporte.leer_soporte('s.csv', texto_csv)
chequear('lee un CSV en UTF-16 con importes argentinos', not err and leido_csv['filas'][0]['importe'] == 1234.56 and leido_csv['filas'][0]['fecha'] == '2026-09-01', err)
_, err = soporte.leer_soporte('s.xlsx', xlsx(FILAS, ['Fecha', 'Protocolo']))
chequear('un archivo sin las columnas pedidas se rechaza', err and 'Faltan columnas' in err[0], err)
malas = [[None if i == 0 else v for i, v in enumerate(FILAS[0])]] + FILAS[1:]
_, err = soporte.leer_soporte('s.xlsx', xlsx(malas))
chequear('una fila con fecha vacía no deja cargar nada', err and 'fecha' in err[0] and 'No se cargó nada' in err[-1], err)
_, err = soporte.leer_soporte('s.pdf', b'%PDF')
chequear('otro tipo de archivo se rechaza', bool(err))

print('2) cargar una factura del sistema anterior desde el soporte')
r = c.get('/facturacion/historica')
chequear('la pantalla existe y está en Facturación', r.status_code == 200 and 'Cargar una factura del sistema anterior' in r.get_data(as_text=True) and 'historica' in c.get('/facturacion').get_data(as_text=True))


def cargar(numero='PJ_Sept26', ff='2026-10-05', fec='2026-11-05', contenido=None, nombre='soporte.xlsx', **extra):
    datos = {'_csrf': tk, 'numero': numero, 'cobertura': '', 'fecha_factura': ff, 'fecha_estimada_cobro': fec, 'fec_tipo': 'tentativa',
             'soporte': (io.BytesIO(contenido if contenido is not None else xlsx(FILAS)), nombre)}
    datos.update(extra)
    return c.post('/facturacion/historica', data=datos, content_type='multipart/form-data', follow_redirects=False)


with A.app.app_context():
    db.ex("INSERT INTO listas (nombre, valor, orden) VALUES ('cobertura','OSDE',1)")
r = cargar(numero='')
chequear('sin número no se carga', r.status_code == 200 and 'número' in r.get_data(as_text=True))
r = cargar(ff='')
chequear('sin fecha de factura no se carga', r.status_code == 200 and 'fecha de factura' in r.get_data(as_text=True))
r = cargar()
with A.app.app_context():
    f = db.uno("SELECT * FROM facturas WHERE numero='PJ_Sept26'")
chequear('crea la factura emitida con las fechas escritas a mano', r.status_code == 302 and f and f['estado'] == 'emitida' and f['fecha_factura'] == '2026-10-05'
         and f['fecha_estimada_cobro'] == '2026-11-05' and f['cobertura'] == 'OSDE', f and dict(f))
chequear('los totales salen del soporte (exento)', f and (f['exento'], f['gravado'], f['iva'], f['total']) == (TOTAL, 0, 0, TOTAL), f and dict(f))
fid = f['id']
chequear('no se repite el número', 'Ya existe' in cargar().get_data(as_text=True))

print('3) vista previa y planilla')
h = c.get(f'/facturacion/{fid}').get_data(as_text=True)
chequear('la factura muestra el soporte con sus totales y la diferencia en cero', 'Soporte del sistema anterior' in h and 'Total del soporte' in h and 'dif-cobro' not in h.split('Total del soporte')[1][:400])
chequear('ofrece descargar la planilla', f'/facturacion/{fid}/planilla.csv' in h)
r = c.get(f'/facturacion/{fid}/planilla.csv')
cuerpo = r.data.decode('utf-8-sig').splitlines()
chequear('la planilla tiene las 13 columnas del sistema nuevo', r.status_code == 200 and cuerpo[0].split(';') == ['Factura', 'Cobertura', 'Protocolo', 'Paciente', 'Afiliado', 'Fecha', 'Estudio', 'Nomenclador', 'Descripción', 'Cantidad', 'Importe unitario', 'IVA', 'Importe'], cuerpo[:1])
chequear('con una fila por línea del soporte', len(cuerpo) == 4 and cuerpo[1].startswith('PJ_Sept26;OSDE;1139502;Dmitruk, Pablo;51947/03;2026-08-12;Ki 67;155053;'), cuerpo[1:2])
chequear('cantidad, unitario e importe correctos', cuerpo[3].split(';')[9:] == ['2', '12620,00', 'Exento', '25240,00'], cuerpo[3])

print('4) subir el soporte a una factura ya cargada')
with A.app.app_context():
    vieja = db.ex("INSERT INTO facturas (numero, estado, cobertura, fecha_factura, exento, gravado, iva, total, creado_en) VALUES ('0001-0000777','emitida','OSDE','2026-09-01',?,0,0,?,?)", (TOTAL + 100, TOTAL + 100, db.ahora()))
h = c.get(f'/facturacion/{vieja}').get_data(as_text=True)
chequear('una factura vieja ofrece subir el soporte', 'Subir soporte' in h and 'Descargar planilla' not in h)
c.post(f'/facturacion/{vieja}/soporte', data={'_csrf': tk, 'soporte': (io.BytesIO(xlsx(FILAS)), 'a.xlsx')}, content_type='multipart/form-data')
h = c.get(f'/facturacion/{vieja}').get_data(as_text=True)
chequear('la carga queda y avisa la diferencia con el total de la factura', 'Descargar planilla' in h and 'dif-cobro' in h and 'no coincide' in h)
c.post(f'/facturacion/{vieja}/soporte', data={'_csrf': tk, 'soporte': (io.BytesIO(xlsx(FILAS[:2])), 'b.xlsx')}, content_type='multipart/form-data')
with A.app.app_context():
    n = db.uno("SELECT COUNT(*) AS n FROM factura_soporte_filas WHERE factura_id=?", (vieja,))['n']
chequear('subir otro soporte reemplaza al anterior', n == 2, n)
c.post(f'/facturacion/{vieja}/soporte', data={'_csrf': tk, 'soporte': (io.BytesIO(b'x'), 'malo.xlsx')}, content_type='multipart/form-data')
with A.app.app_context():
    n = db.uno("SELECT COUNT(*) AS n FROM factura_soporte_filas WHERE factura_id=?", (vieja,))['n']
chequear('un archivo inválido no pisa el soporte cargado', n == 2, n)
c.post(f'/facturacion/{vieja}/soporte/quitar', data={'_csrf': tk})
with A.app.app_context():
    n = db.uno("SELECT COUNT(*) AS n FROM factura_soporte_filas WHERE factura_id=?", (vieja,))['n']
chequear('se puede quitar', n == 0 and c.get(f'/facturacion/{vieja}/planilla.csv').status_code == 302)

print('5) lo que no corresponde')
with A.app.app_context():
    est_fila = db.uno("SELECT id, protocolo_id FROM estudios LIMIT 1")
    est, proto_id = est_fila['id'], est_fila['protocolo_id']
    con_items = db.ex("INSERT INTO facturas (numero, estado, cobertura, creado_en) VALUES ('NUEVA-1','borrador','OSDE',?)", (db.ahora(),))
    db.ex("INSERT INTO factura_items (factura_id, estudio_id, protocolo_id, numero_protocolo, paciente, afiliado, fecha, estudio, codigo, descripcion, cantidad, unitario, iva, importe) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (con_items, est, proto_id, 'C1', 'P', 'A', '2026-10-01', 'BP', '1', 'd', 1, 10, 'exento', 10))
r = c.get(f'/facturacion/{con_items}')
h = r.get_data(as_text=True)
chequear('una factura con estudios del sistema nuevo no ofrece el soporte', r.status_code == 200 and 'Archivos adjuntos' in h and 'Soporte del sistema anterior' not in h)
c.post(f'/facturacion/{con_items}/soporte', data={'_csrf': tk, 'soporte': (io.BytesIO(xlsx(FILAS)), 'a.xlsx')}, content_type='multipart/form-data')
with A.app.app_context():
    chequear('y rechaza el pedido', db.uno("SELECT 1 FROM factura_soportes WHERE factura_id=?", (con_items,)) is None)
with A.app.app_context():
    sin = db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, debe_cambiar_clave) VALUES ('ZZSF','Sin Fact','',0,1,0)")
cs, tks = cliente(sin)
chequear('sin el permiso de facturación no entra', cs.get('/facturacion/historica').status_code == 302 and cs.get(f'/facturacion/{fid}/planilla.csv').status_code == 302)
with A.app.app_context():
    chequear('queda en el historial', db.uno("SELECT 1 FROM auditoria WHERE accion='factura_historica'") is not None and db.uno("SELECT 1 FROM auditoria WHERE accion='factura_soporte'") is not None)
print('FALLAS:', fallas or 'ninguna')
