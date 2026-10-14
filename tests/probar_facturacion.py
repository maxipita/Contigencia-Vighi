import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos_informe
from werkzeug.datastructures import MultiDict

A, db, ids, admin = datos_informe.preparar()
from vighi.dominio import estudios as dom_estudios
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
    if not ok:
        fallas.append(n)


def post(url, datos=None):
    pares = [('_csrf', csrf)] + (list(datos.items()) if isinstance(datos, dict) else list(datos or []))
    return c.post(url, data=MultiDict(pares), follow_redirects=True).get_data(as_text=True)


coberturas = [r['valor'] for r in F.con.execute("SELECT valor FROM listas WHERE nombre='cobertura' ORDER BY orden").fetchall()]
COB, COB2 = coberturas[0], coberturas[1]
general = F.con.execute("SELECT id FROM tarifarios WHERE nombre='TARIFA GENERAL'").fetchone()['id']
print('coberturas:', COB, '|', COB2, '| tarifa general id', general)

chequear('existe la tarifa general', general is not None)
chequear('existe el sector Facturación', 'facturacion' in dom_estudios.SECTORES)
chequear('existe el perfil Facturación con el permiso', F.con.execute("SELECT 1 FROM perfiles WHERE nombre='Facturación' AND permisos LIKE '%facturacion%'").fetchone() is not None)
h = c.get('/').get_data(as_text=True)
chequear('la barra superior tiene Facturación', 'title="Facturación"' in h and 'href="/administracion"' in h)
h = c.get('/usuarios/nuevo').get_data(as_text=True)
chequear('el sector Facturación se puede elegir en usuarios', 's_facturacion' in h)
h = c.get('/?sector=facturacion').get_data(as_text=True)
chequear('el filtro de sectores del tablero no ofrece Facturación', 'Pendiente en Facturación' not in h)

h = post('/tarifario', {'accion': 'valor', 'tarifario': str(general), 'codigo': '150101', 'descripcion': 'Biopsia por incisión o punción', 'importe': '11.051,46', 'vigente_desde': '2026-09-01'})
chequear('carga un importe con su descripción', 'Importe de 150101 guardado' in h and F.con.execute("SELECT importe FROM tarifario_valores WHERE codigo='150101'").fetchone()['importe'] == 11051.46, h[:200])
post('/tarifario', {'accion': 'valor', 'tarifario': str(general), 'codigo': '150102', 'descripcion': 'Pieza operatoria simple', 'importe': '23429,24', 'vigente_desde': '2026-09-01'})
post('/tarifario', {'accion': 'valor', 'tarifario': str(general), 'codigo': '150106', 'descripcion': 'Citología exfoliativa oncológica', 'importe': '9375,78', 'vigente_desde': '2026-09-01'})
h = c.get('/tarifario').get_data(as_text=True)
chequear('lista las vigentes con formato', '150101' in h and '$ 11.051,46' in h and 'Modificar' in h)

h = post('/tarifario', {'accion': 'valor', 'tarifario': str(general), 'codigo': '150101', 'importe': '12.000', 'vigente_desde': '2026-10-01'})
h = c.get(f'/tarifario?tarifario={general}&ver=vigentes').get_data(as_text=True)
chequear('"Vigentes" muestra solo el último', h.count('150101') >= 1 and '$ 12.000,00' in h and '$ 11.051,46' not in h)
h = c.get(f'/tarifario?tarifario={general}&ver=todas').get_data(as_text=True)
chequear('"Todas" muestra el historial', '$ 12.000,00' in h and '$ 11.051,46' in h)
h = post('/tarifario', {'accion': 'valor', 'tarifario': str(general), 'codigo': '150101', 'importe': '15000', 'vigente_desde': '2099-01-01'})
h = c.get(f'/tarifario?tarifario={general}&ver=vigentes').get_data(as_text=True)
chequear('un importe a futuro no es vigente todavía', '$ 15.000,00' not in h and '$ 12.000,00' in h)

h = post('/tarifario', {'accion': 'bloque', 'tarifario': str(general), 'porcentaje': '10', 'vigente_desde': '2026-10-15'})
chequear('modifica en bloque (+10%)', 'Se actualizaron' in h)
r = F.con.execute("SELECT importe FROM tarifario_valores WHERE codigo='150102' AND vigente_desde='2026-10-15'").fetchone()
chequear('el bloque calcula sobre el vigente y conserva el historial', r and abs(r['importe'] - round(23429.24 * 1.1, 2)) < 0.005 and
         F.con.execute("SELECT COUNT(*) AS n FROM tarifario_valores WHERE codigo='150102'").fetchone()['n'] == 2, r and dict(r))
F.con.execute("DELETE FROM tarifario_valores WHERE vigente_desde IN ('2026-10-15','2099-01-01')")
F.con.execute("DELETE FROM tarifario_valores WHERE codigo='150101' AND vigente_desde='2026-10-01'")

h = post('/nomencladores', {'accion': 'asignar', 'tipo': 'BP', 'tipo_muestra': '', 'sitio': '', 'codigo': '150102'})
chequear('asigna nomenclador general a BP', 'Asignación guardada' in h)
h = post('/nomencladores', {'accion': 'asignar', 'tipo': 'BP', 'tipo_muestra': 'Biopsia', 'sitio': '', 'codigo': '150101'})
h = post('/nomencladores', {'accion': 'asignar', 'tipo': 'CT', 'tipo_muestra': '', 'sitio': '', 'codigo': '150106'})
h = post('/nomencladores', {'accion': 'asignar', 'tipo': 'BP', 'tipo_muestra': '', 'sitio': '', 'codigo': 'NOEXISTE'})
chequear('no asigna un nomenclador inexistente', 'que exista' in h)
h = post('/nomencladores', {'accion': 'importar', 'texto': 'BP; Resección; ; 150102\nPAP; ; ; 150106'})
chequear('importa asignaciones', 'Se importaron 2 asignaciones' in h)
h = post('/nomencladores', {'accion': 'importar', 'texto': 'XX; ; ; 150102'})
chequear('importación inválida no carga nada', 'No se importó nada' in h)
h = c.get('/nomencladores').get_data(as_text=True)
chequear('pantalla de nomencladores', '150101' in h and 'Biopsia por incisión' in h)

from vighi.dominio import facturacion
with A.app.app_context():
    ctx = facturacion.contexto()
    ok1 = facturacion.resolver(ctx, COB, 'BP', 'Colon', 'Biopsia', '2026-09-15')
    ok2 = facturacion.resolver(ctx, COB, 'BP', 'Colon', 'Resección', '2026-09-15')
    ok3 = facturacion.resolver(ctx, COB, 'BP', 'Colon', 'Otra cosa', '2026-09-15')
    antes = facturacion.resolver(ctx, COB, 'BP', 'Colon', 'Biopsia', '2026-08-01')
chequear('Biopsia → 150101 al importe vigente', ok1['ok'] and ok1['codigo'] == '150101' and ok1['importe'] == 11051.46, ok1)
chequear('Resección (sin acentos) → 150102', ok2['ok'] and ok2['codigo'] == '150102', ok2)
chequear('un tipo de muestra sin asignar usa el general del estudio', ok3['ok'] and ok3['codigo'] == '150102', ok3)
chequear('antes de la vigencia no hay importe', not antes['ok'] and 'sin importe vigente' in antes['motivo'], antes)

h = post('/tarifario', {'accion': 'crear_tarifario', 'nombre': 'OSDE', 'iva': 'gravado'})
osde = F.con.execute("SELECT id FROM tarifarios WHERE nombre='OSDE'").fetchone()['id']
chequear('crea una tarifa nueva', osde is not None and 'creada' in h)
h = post('/tarifario', {'accion': 'crear_tarifario', 'nombre': 'osde', 'iva': 'exento'})
chequear('no repite el nombre', 'Ya existe' in h)
h = post('/tarifario', {'accion': 'valor', 'tarifario': str(osde), 'codigo': '150101', 'importe': '20000', 'vigente_desde': '2026-09-01'})
h = post('/tarifario', [('accion', 'guardar_tarifario'), ('tarifario', str(osde)), ('iva', 'gravado'), ('coberturas', COB)])
chequear('asigna coberturas a la tarifa', F.con.execute("SELECT tarifario_id FROM tarifario_coberturas WHERE cobertura=?", (COB,)).fetchone()['tarifario_id'] == osde)
with A.app.app_context():
    ctx = facturacion.contexto()
    a = facturacion.resolver(ctx, COB, 'BP', 'Colon', 'Biopsia', '2026-09-15')
    b = facturacion.resolver(ctx, COB, 'BP', 'Colon', 'Resección', '2026-09-15')
    cc = facturacion.resolver(ctx, COB2, 'BP', 'Colon', 'Biopsia', '2026-09-15')
chequear('la cobertura usa su propia tarifa e IVA', a['importe'] == 20000 and a['iva'] == 'gravado' and a['tarifario'] == 'OSDE', a)
chequear('si falta un nomenclador usa la tarifa general', b['ok'] and b['importe'] == 23429.24 and b['tarifario'] == 'OSDE', b)
chequear('otra cobertura sigue con la general', cc['importe'] == 11051.46 and cc['iva'] == 'exento', cc)

F.con.execute("UPDATE protocolos SET cobertura=?, exento='No'", (COB,))
F.con.execute("UPDATE protocolos SET cobertura=? WHERE numero='C000106'", (COB2,))
F.con.execute("UPDATE estudios SET tipo_muestra='Biopsia' WHERE tipo='BP'")
F.con.execute("UPDATE protocolos SET fecha_recoleccion='2026-09-20'")
h = c.get(f'/facturar?buscar=1&cobertura={COB}&informados=&facturados=').get_data(as_text=True)
filas = re.findall(r'name="ids" value="(\d+)"', h)
chequear('Facturar trae estudios con nomenclador e importe', len(filas) > 0 and '150101' in h and '$ 20.000,00' in h)

est_bp = [r['id'] for r in F.con.execute("SELECT e.id FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id WHERE e.tipo='BP' AND e.anulado=0 AND p.cobertura=? ORDER BY e.id", (COB,)).fetchall()]
est_ct = [r['id'] for r in F.con.execute("SELECT e.id FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id WHERE e.tipo='CT' AND e.anulado=0 AND p.cobertura=? ORDER BY e.id", (COB,)).fetchall()]
elegidos = est_bp[:2] + est_ct[:1]
h = post('/facturar', [('ids', str(i)) for i in elegidos])
fid = int(F.con.execute("SELECT MAX(id) AS n FROM facturas").fetchone()['n'] or 0)
chequear('genera el borrador', fid > 0 and 'Se generó el borrador' in h, h[:300])
fac = dict(F.con.execute("SELECT * FROM facturas WHERE id=?", (fid,)).fetchone())
items = [dict(x) for x in F.con.execute("SELECT * FROM factura_items WHERE factura_id=?", (fid,)).fetchall()]
print('  ', {k: fac[k] for k in ('estado', 'cobertura', 'exento', 'gravado', 'iva', 'total')}, [(i['codigo'], i['unitario'], i['iva']) for i in items])
chequear('ítems con nomenclador de la tarifa de la cobertura', all(i['codigo'] in ('150101', '150106') for i in items) and any(i['unitario'] == 20000 for i in items))
exento_esp = round(sum(i['importe'] for i in items if i['iva'] == 'exento'), 2)
gravado_esp = round(sum(i['importe'] for i in items if i['iva'] == 'gravado'), 2)
chequear('totales con IVA 21% sobre lo gravado', fac['exento'] == exento_esp and fac['gravado'] == gravado_esp and fac['iva'] == round(gravado_esp * 0.21, 2) and gravado_esp > 0, fac)

h = post('/facturar', [('ids', str(elegidos[0]))])
chequear('no factura dos veces el mismo estudio', 'ya está en la factura' in h)
F.con.execute("UPDATE estudios SET tipo_muestra='Rara' WHERE id=?", (est_bp[-1],))
F.con.execute("DELETE FROM nomenclador_muestras WHERE tipo='BP'")
h = post('/facturar', [('ids', str(est_bp[-1]))])
chequear('sin nomenclador no factura y lo explica', 'sin nomenclador' in h, h[:300])


h = c.get('/facturar').get_data(as_text=True)
chequear('Facturar abre con el mes actual y todos los filtros del proyecto', all(x in h for x in ('name="desde"', 'name="hasta"', 'name="cobertura"', 'name="plan"', 'name="procedencia"', 'name="iva"', 'name="flujo"', 'name="zona"', 'name="clase"', 'name="informados"', 'name="prioridad"')))
chequear('sin buscar no lista y propone el mes en curso', 'value="2026-10-01"' in h and 'value="2026-10-31"' in h and 'name="ids"' not in h)
F.con.execute("UPDATE protocolos SET lugar_recoleccion='Consultorio Norte' WHERE numero='C000101'")
F.con.execute("UPDATE estudios SET tecnicas_especiales='Pas' WHERE id=?", (est_bp[0],))
def ids_de(url):
    return set(re.findall(r'name="ids" value="(\d+)"', c.get(url).get_data(as_text=True)))
todos = ids_de(f'/facturar?buscar=1&cobertura={COB}&informados=&facturados=')
chequear('filtro por procedencia', ids_de(f'/facturar?buscar=1&cobertura={COB}&informados=&facturados=&procedencia=Consultorio+Norte') < todos)
chequear('filtro por flujo CT', ids_de(f'/facturar?buscar=1&cobertura={COB}&informados=&facturados=&flujo=CT') == {str(i) for i in est_ct} | set())
chequear('filtro tipo biopsias', ids_de(f'/facturar?buscar=1&cobertura={COB}&informados=&facturados=&clase=biop') < todos)
chequear('prioridad técnicas especiales', ids_de(f'/facturar?buscar=1&cobertura={COB}&informados=&facturados=&prioridad=te') == {str(est_bp[0])})
h = c.get(f'/facturacion/{fid}').get_data(as_text=True)
chequear('detalle del borrador', 'Borrador de factura' in h and 'Emitir factura' in h)
h = post(f'/facturacion/{fid}/emitir', {'numero': '0001-00000123', 'fecha_factura': '2026-10-13', 'fecha_estimada_cobro': '2026-12-12'})
chequear('emite con fecha estimada de cobro (FEC)', F.con.execute("SELECT estado, fecha_estimada_cobro FROM facturas WHERE id=?", (fid,)).fetchone()['fecha_estimada_cobro'] == '2026-12-12')
h = c.get('/facturacion').get_data(as_text=True)
chequear('el listado muestra FEC (estimada) y no la de cobro', '12/12/2026' in h and 'Fecha estimada de cobro' in h)
h = post(f'/facturacion/{fid}/cobrar', {'fecha_cobro': '2026-10-20'})
chequear('registra el cobro', 'Cobro registrado' in h)
r = c.get(f'/facturacion/{fid}.csv')
chequear('descarga CSV con nomenclador', r.status_code == 200 and b'0001-00000123' in r.data and b'Nomenclador' in r.data)
h = c.get('/facturacion?estado=cobrada').get_data(as_text=True)
chequear('listado con totales', '0001-00000123' in h and 'totales-fact' in h)

F.con.execute("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, debe_cambiar_clave) VALUES ('ZZSIN','Sin permiso','ingreso',0,1,0)")
uid = F.con.execute("SELECT id FROM usuarios WHERE iniciales='ZZSIN'").fetchone()['id']
c2 = A.app.test_client()
with c2.session_transaction() as s:
    s['uid'] = uid
for ruta in ('/facturacion', '/facturar', '/tarifario', '/nomencladores'):
    r = c2.get(ruta, follow_redirects=True)
    chequear(f'sin permiso no entra a {ruta}', 'No tenés permiso' in r.get_data(as_text=True))
h = c2.get('/').get_data(as_text=True)
chequear('sin permiso no ve Admin en la barra', 'href="/administracion"' not in h)
print('FALLAS:', fallas)
