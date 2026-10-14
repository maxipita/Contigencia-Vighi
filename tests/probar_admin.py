import os, re, sys
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos_informe
from werkzeug.datastructures import MultiDict
A, db, ids, admin = datos_informe.preparar()
F = datos_informe.FALSO
c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
c.get('/')
with c.session_transaction() as s:
    csrf = s['csrf']
fallas = []
def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok: fallas.append(n)
h = c.get('/administracion').get_data(as_text=True)
chequear('abre el panel Administración (Finanzas)', 'Administración' in h and 'Cobros previstos' in h and 'Nueva factura' in h and 'Facturas emitidas' in h)
chequear('muestra Reclamo de pagos, Presupuestos y Autorizaciones como próximamente', 'Reclamo de pagos' in h and 'Presupuestos' in h and 'Dashboard autorizaciones' in h and h.count('próximamente') >= 3)
chequear('vacío: Sin cobros cargados y leyenda', 'Sin cobros cargados' in h and 'Fecha tentativa' in h and 'Fecha confirmada' in h and 'Cobro atrasado +5d' in h)
chequear('la barra superior lleva al panel', 'href="/administracion"' in h)
hoy = date.today()
def factura(cob, total, fec, tipo, estado='emitida'):
    F.con.execute("INSERT INTO facturas (numero, estado, cobertura, fecha_factura, fecha_estimada_cobro, fec_tipo, total, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?, '2026-10-01 10:00:00')",
                  (f'F-{cob}-{total}', estado, cob, '2026-09-01', fec, tipo, total, admin))
factura('SMG', 2724068, (hoy - timedelta(days=40)).isoformat(), 'tentativa')
factura('AMCI', 30168, (hoy - timedelta(days=3)).isoformat(), 'cargada')
factura('OSDE', 111116795, (hoy + timedelta(days=2)).isoformat(), 'cargada')
factura('GALENO', 37680929, (hoy + timedelta(days=3)).isoformat(), 'confirmada')
factura('OMINT', 5433452, (hoy + timedelta(days=4)).isoformat(), 'tentativa')
factura('CMG', 21628661, (hoy + timedelta(days=45)).isoformat(), 'cargada')
factura('PARTICULAR', 1000, None, 'tentativa')
factura('COBRADA SA', 999, (hoy + timedelta(days=1)).isoformat(), 'cargada', 'cobrada')
h = c.get('/administracion').get_data(as_text=True)
chequear('lista las facturas emitidas con importes sin decimales', 'SMG' in h and '$ 2.724.068<' in h and 'OSDE' in h)
def sem(cob):
    for fila in h.split('class="cobro-fila"')[1:]:
        if '>' + cob + '<' in fila:
            c = re.search(r'estado-cobro (\w+)"', fila).group(1)
            s = re.search(r'#i-cobro-(\w+)"', fila).group(1)
            return (c, s)
    return None
chequear('atraso mayor a 5 días: rojo', sem('SMG') == ('atr5', 'tent'), sem('SMG'))
chequear('atraso hasta 5 días: naranja (con fecha cargada = tilde)', sem('AMCI') == ('atr', 'conf'), sem('AMCI'))
chequear('en fecha y cargada: verde con tilde', sem('OSDE') == ('ok', 'conf'), sem('OSDE'))
chequear('en fecha y confirmada: verde con tilde', sem('GALENO') == ('ok', 'conf'), sem('GALENO'))
chequear('en fecha y tentativa: verde con ?', sem('OMINT') == ('ok', 'tent'), sem('OMINT'))
chequear('no incluye las cobradas', 'COBRADA SA' not in h)
chequear('avisa las emitidas sin fecha', 'sin fecha estimada de cobro' in h)
chequear('agrupa en columnas por mes con total', h.count('cobros-mes-cab') >= 2)
fid = F.con.execute("SELECT id FROM facturas WHERE cobertura='OSDE'").fetchone()['id']
h = c.post(f'/facturacion/{fid}/fec', data=MultiDict([('_csrf', csrf), ('fecha_estimada_cobro', (hoy + timedelta(days=9)).isoformat()), ('fec_tipo', 'confirmada')]), follow_redirects=True).get_data(as_text=True)
chequear('se puede cambiar la FEC y su tipo', 'Fecha estimada de cobro actualizada' in h and F.con.execute("SELECT fec_tipo FROM facturas WHERE id=?", (fid,)).fetchone()['fec_tipo'] == 'confirmada')
h = c.post(f'/facturacion/{fid}/fec', data=MultiDict([('_csrf', csrf), ('fecha_estimada_cobro', 'mañana'), ('fec_tipo', 'confirmada')]), follow_redirects=True).get_data(as_text=True)
chequear('rechaza una fecha inválida', 'no es válida' in h)
fid_omint = F.con.execute("SELECT id FROM facturas WHERE cobertura='OMINT'").fetchone()['id']
c.post(f'/facturacion/{fid_omint}/cobrar', data=MultiDict([('_csrf', csrf), ('fecha_cobro', hoy.isoformat())]), follow_redirects=True)
h2 = c.get('/administracion').get_data(as_text=True)
chequear('al registrarse el cobro la factura sale de Cobros previstos', 'OMINT' not in h2 and 'SMG' in h2)
c2 = A.app.test_client()
F.con.execute("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, debe_cambiar_clave) VALUES ('ZZSIN','Sin','ingreso',0,1,0)")
with c2.session_transaction() as s:
    s['uid'] = F.con.execute("SELECT id FROM usuarios WHERE iniciales='ZZSIN'").fetchone()['id']
r = c2.get('/administracion', follow_redirects=True)
chequear('sin permiso no entra al panel', 'No tenés permiso' in r.get_data(as_text=True))
print('FALLAS:', fallas)
