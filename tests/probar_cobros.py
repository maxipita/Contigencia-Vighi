import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos_informe

A, db, ids, admin = datos_informe.preparar()
F = datos_informe.FALSO
from vighi.herramientas import cargar_cobros as carga

fallas = []


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


coberturas = [r['valor'] for r in F.con.execute("SELECT valor FROM listas WHERE nombre='cobertura' ORDER BY orden").fetchall()]
COB, COB2 = coberturas[0], coberturas[1]
F.con.execute("INSERT INTO cobertura_pago (cobertura, dias) VALUES (?,30)", (COB,))
F.con.commit()


def factura(numero, cobertura, ff, fec, tipo, exento, gravado, iva):
    return {'id': 1, 'numero': numero, 'ff': ff, 'fec': fec, 'fec_tipo': tipo, 'cobertura': cobertura,
            'exento': exento, 'gravado': gravado, 'iva': iva, 'total': round(exento + gravado + iva, 2)}


paquete = [
    factura('A-1', COB, '2026-10-01', '2026-11-15', 'confirmada', 1000, 0, 0),
    factura('A-2', COB, '2026-10-05', None, None, 500, 1000, 210),
    factura('A-3', COB2, '2026-10-05', None, None, 200, 0, 0),
    factura('A-4', 'COBERTURA DESCONOCIDA', '2026-10-06', '2026-11-20', 'tentativa', 300, 0, 0),
    factura('A-1', COB, '2026-10-01', '2026-11-15', 'confirmada', 1000, 0, 0),
]
with A.app.app_context():
    r = carga.aplicar(paquete, imprimir=lambda *_: None)
chequear('carga las facturas nuevas y no repite el número', len(r['cargadas']) == 4 and r['repetidas'] == ['A-1'], (len(r['cargadas']), r['repetidas']))
with A.app.app_context():
    filas = {x['numero']: dict(x) for x in db.q("SELECT * FROM facturas")}
chequear('quedan emitidas con sus importes', filas['A-2']['estado'] == 'emitida' and filas['A-2']['total'] == 1710 and filas['A-2']['gravado'] == 1000)
chequear('respeta la fecha y el tipo que traen', filas['A-1']['fecha_estimada_cobro'] == '2026-11-15' and filas['A-1']['fec_tipo'] == 'confirmada')
chequear('sin fecha estimada usa el plazo de la cobertura', filas['A-2']['fecha_estimada_cobro'] == '2026-11-04' and filas['A-2']['fec_tipo'] == 'tentativa'
         and '30 días' in filas['A-2']['observaciones'], filas['A-2'])
chequear('sin plazo y sin fecha queda sin fecha', filas['A-3']['fecha_estimada_cobro'] is None and r['sin_plazo'] == [('A-3', COB2)], r['sin_plazo'])
chequear('una cobertura desconocida se informa y se guarda con su nombre', r['sin_cobertura'] == ['COBERTURA DESCONOCIDA'] and filas['A-4']['cobertura'] == 'COBERTURA DESCONOCIDA')
chequear('calcula la alícuota guardada', abs(filas['A-2']['alicuota'] - 0.21) < 1e-6)

c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
c.get('/')
h = c.get('/administracion').get_data(as_text=True)
chequear('aparecen en Cobros previstos', COB in h and 'Cobros previstos' in h and '1.710' in h.replace(' ', ''), h[:200])
h = c.get('/facturacion?estado=emitida').get_data(as_text=True)
chequear('y en Facturas emitidas', 'A-2' in h and 'A-4' in h)

print('cobro: importe cobrado y desmarcar')
from werkzeug.datastructures import MultiDict
with c.session_transaction() as s:
    csrf = s['csrf']


def post(url, datos):
    return c.post(url, data=MultiDict([('_csrf', csrf)] + list(datos.items())), follow_redirects=True).get_data(as_text=True)


with A.app.app_context():
    fid = db.uno("SELECT id FROM facturas WHERE numero='A-2'")['id']
h = c.get(f'/facturacion/{fid}').get_data(as_text=True)
chequear('al registrar el cobro viene con el total y se puede cambiar', 'name="monto"' in h and 'value="1710,00"' in h)
h = post(f'/facturacion/{fid}/cobrar', {'fecha_cobro': '2026-10-20', 'monto': '1.500,00'})
with A.app.app_context():
    f = db.uno("SELECT estado, fecha_cobro, cobrado FROM facturas WHERE id=?", (fid,))
chequear('registra la fecha y el importe cobrado', f['estado'] == 'cobrada' and f['fecha_cobro'] == '2026-10-20' and f['cobrado'] == 1500, dict(f))
chequear('avisa la diferencia', 'diferencia' in h and 'Cobro registrado' in h)
h = c.get(f'/facturacion/{fid}').get_data(as_text=True)
chequear('la factura muestra lo cobrado y la diferencia', 'Cobrado' in h and 'Diferencia' in h and 'Desmarcar cobro' in h and 'Corregir cobro' in h)
h = post(f'/facturacion/{fid}/cobrar', {'fecha_cobro': '2026-10-21', 'monto': '1710'})
with A.app.app_context():
    f = db.uno("SELECT estado, fecha_cobro, cobrado FROM facturas WHERE id=?", (fid,))
chequear('se puede corregir el cobro', f['estado'] == 'cobrada' and f['fecha_cobro'] == '2026-10-21' and f['cobrado'] == 1710 and 'Cobro corregido' in h, dict(f))
h = post(f'/facturacion/{fid}/cobrar', {'fecha_cobro': '2026-10-21', 'monto': 'abc'})
with A.app.app_context():
    f = db.uno("SELECT cobrado FROM facturas WHERE id=?", (fid,))
chequear('rechaza un importe inválido', 'Indicá cuánto se cobró' in h and f['cobrado'] == 1710)
h = post(f'/facturacion/{fid}/desmarcar-cobro', {})
with A.app.app_context():
    f = db.uno("SELECT estado, fecha_cobro, cobrado, cobrada_por FROM facturas WHERE id=?", (fid,))
    aud = db.uno("SELECT COUNT(*) AS n FROM auditoria WHERE accion='factura_cobro_desmarcado'")['n']
chequear('desmarcar vuelve a emitida y limpia el cobro', f['estado'] == 'emitida' and f['fecha_cobro'] is None and f['cobrado'] is None and f['cobrada_por'] is None, dict(f))
chequear('queda auditado', aud == 1)
h = c.get('/administracion').get_data(as_text=True)
chequear('vuelve a Cobros previstos', 'A-2' in h or '1.710' in h.replace(' ', ''))
h = post(f'/facturacion/{fid}/desmarcar-cobro', {})
chequear('desmarcar una factura que no está cobrada avisa', 'no figura como cobrada' in h)
h = post(f'/facturacion/{fid}/cobrar', {'fecha_cobro': '2026-10-22', 'monto': ''})
with A.app.app_context():
    f = db.uno("SELECT estado, cobrado FROM facturas WHERE id=?", (fid,))
chequear('sin importe se toma el total', f['estado'] == 'cobrada' and f['cobrado'] == 1710, dict(f))

print()
print('FALLAS:', 'ninguna' if not fallas else fallas)
sys.exit(1 if fallas else 0)
