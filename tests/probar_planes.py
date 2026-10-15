import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos_informe
from werkzeug.datastructures import MultiDict

A, db, ids, admin = datos_informe.preparar()
F = datos_informe.FALSO
from vighi.dominio import facturacion as dom
from vighi.herramientas import cargar_tarifas as carga

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
    pares = [('_csrf', csrf)] + list((datos or {}).items())
    return c.post(url, data=MultiDict(pares), follow_redirects=True).get_data(as_text=True)


coberturas = [r['valor'] for r in F.con.execute("SELECT valor FROM listas WHERE nombre='cobertura' ORDER BY orden").fetchall()]
COB, COB2 = coberturas[0], coberturas[1]


def item(cod, desc, imp, desde='01 oct. 26'):
    return {'cod': cod, 'desc': desc, 'imp': imp, 'txt': str(imp), 'desde': desde}


paquete = {
    'coberturas': [
        {'id': 1, 'nombre': COB, 'iva': 'Exento y gravado', 'cond': '30 días',
         'planes': [{'v': '5', 't': 'Centros', 's': True}, {'v': '0', 't': 'TARIFA GENERAL', 's': False}],
         'items': [item('150101', 'Biopsia plan', 99999)]},
        {'id': 2, 'nombre': COB2, 'iva': 'Siempre exento', 'cond': '[ N/A ]', 'planes': [{'v': '0', 't': 'TARIFA GENERAL', 's': True}],
         'items': [item('150101', 'Biopsia por incisión (otra descripción)', 5000, '01 sep. 26'), item('150106', 'Citología', 0),
                   item('ZZ-001', 'Código propio', 1234.5, '01 ene. 22')]},
        {'id': 3, 'nombre': 'COBERTURA QUE NO EXISTE', 'iva': 'Siempre exento', 'cond': '30 días', 'planes': [], 'items': [item('150101', 'x', 1)]},
    ],
    'planes_extra': {
        '1': {'0': {'seleccionado': 'TARIFA GENERAL', 'items': [item('150101', 'Biopsia por incisión', 4500), item('150106', 'Citología exfoliativa', 3000)]},
              '5': {'seleccionado': 'CENTROS', 'items': [item('150101', 'Biopsia por incisión', 60000)]}},
    },
}

print('1) carga de tarifas, planes y plazos')
tarifas = carga.tarifas_del_paquete(paquete)
chequear('arma una tarifa por cobertura y una por plan', [(t['cobertura'], t['plan']) for t in tarifas] ==
         [(COB, ''), (COB, 'CENTROS'), (COB2, ''), ('COBERTURA QUE NO EXISTE', '')], [(t['cobertura'], t['plan']) for t in tarifas])
chequear('usa la tarifa general de la cobertura cuando tiene planes', {i['cod']: i['imp'] for i in tarifas[0]['items']} == {'150101': 4500, '150106': 3000})
chequear('IVA: exento y gravado -> gravado, siempre exento -> exento', tarifas[0]['iva'] == 'gravado' and tarifas[2]['iva'] == 'exento')
chequear('plazo de cobro', tarifas[0]['dias'] == 30 and tarifas[2]['dias'] is None)
with A.app.app_context():
    r = carga.aplicar(tarifas, imprimir=lambda *_: None)
chequear('cuenta lo cargado y omite la cobertura inexistente', r['tarifas'] == 3 and r['planes'] == 1 and r['omitidas'] == ['COBERTURA QUE NO EXISTE'], r)
with A.app.app_context():
    t_cob = db.uno("SELECT tarifario_id FROM tarifario_coberturas WHERE cobertura=? AND plan=''", (COB,))['tarifario_id']
    t_plan = db.uno("SELECT tarifario_id FROM tarifario_coberturas WHERE cobertura=? AND plan='CENTROS'", (COB,))['tarifario_id']
    t_cob2 = db.uno("SELECT tarifario_id FROM tarifario_coberturas WHERE cobertura=? AND plan=''", (COB2,))['tarifario_id']
    ivas = {x['id']: x['iva'] for x in db.q("SELECT id, iva FROM tarifarios")}
    pago = db.uno("SELECT dias FROM cobertura_pago WHERE cobertura=?", (COB,))
    sin_pago = db.uno("SELECT dias FROM cobertura_pago WHERE cobertura=?", (COB2,))
chequear('el plan tiene su propia tarifa', t_plan != t_cob)
chequear('IVA cargado en cada tarifa', ivas[t_cob] == 'gravado' and ivas[t_plan] == 'gravado' and ivas[t_cob2] == 'exento')
chequear('guarda el plazo de cobro solo de quien lo tiene', pago and pago['dias'] == 30 and sin_pago is None)

with A.app.app_context():
    from vighi.servicios.facturas import importar_asignaciones
    general_id = db.uno("SELECT id FROM tarifarios WHERE nombre='TARIFA GENERAL'")['id']
    importar_asignaciones(general_id, 'BP; Biopsia; ; 150101\nCT; ; ; 150106')
print('2) el resolver distingue plan, cero y descripción')
with A.app.app_context():
    ctx = dom.contexto()
    general = dom.resolver(ctx, COB, 'BP', '', 'Biopsia', '2026-10-14')
    con_plan = dom.resolver(ctx, COB, 'BP', '', 'Biopsia', '2026-10-14', 'CENTROS')
    plan_desconocido = dom.resolver(ctx, COB, 'BP', '', 'Biopsia', '2026-10-14', 'OTRO')
    cero = dom.resolver(ctx, COB2, 'CT', '', 'Citología Exfoliativa', '2026-10-14')
    descr2 = dom.resolver(ctx, COB2, 'BP', '', 'Biopsia', '2026-10-14')
chequear('sin plan toma la tarifa de la cobertura', general.get('ok') and general['importe'] == 4500, general)
chequear('con plan toma la tarifa del plan', con_plan.get('ok') and con_plan['importe'] == 60000, con_plan)
chequear('un plan que no tiene tarifa usa la de la cobertura', plan_desconocido.get('ok') and plan_desconocido['importe'] == 4500, plan_desconocido)
chequear('el plan hereda el nomenclador de muestras de la cobertura', con_plan.get('codigo') == general.get('codigo'))
chequear('un importe en cero no se factura', cero and not cero['ok'] and 'importe en cero' in cero['motivo'], cero)
chequear('la descripción es la propia de cada cobertura', descr2.get('descripcion') == 'Biopsia por incisión (otra descripción)' and general['descripcion'] == 'Biopsia por incisión', (descr2, general))
with A.app.app_context():
    propias = db.q("SELECT tarifario_id, codigo FROM tarifario_descripciones")
chequear('solo guarda como propia la que difiere de la general', [(x['tarifario_id'], x['codigo']) for x in propias].count((t_cob2, '150101')) == 1
         and not any(x['tarifario_id'] == t_cob and x['codigo'] == '150101' for x in propias))
with A.app.app_context():
    r2 = carga.aplicar(carga.tarifas_del_paquete(paquete), imprimir=lambda *_: None)
    n = db.uno("SELECT COUNT(*) AS n FROM tarifario_valores WHERE tarifario_id=?", (t_cob2,))['n']
chequear('cargar dos veces no duplica', n == 3, n)

print('3) el protocolo guarda el plan')
with A.app.app_context():
    pid = db.uno("SELECT protocolo_id FROM estudios WHERE id=?", (ids['bp'],))['protocolo_id']
h = post(f'/protocolo/{pid}/datos', {'cobertura': COB, 'plan': 'CENTROS'})
with A.app.app_context():
    p = db.uno("SELECT cobertura, plan FROM protocolos WHERE id=?", (pid,))
chequear('guarda cobertura y plan', p['cobertura'] == COB and p['plan'] == 'CENTROS', dict(p))
h = post(f'/protocolo/{pid}/datos', {'cobertura': COB, 'plan': 'NO EXISTE'})
with A.app.app_context():
    p = db.uno("SELECT cobertura, plan FROM protocolos WHERE id=?", (pid,))
chequear('rechaza un plan que no es de la cobertura', 'no corresponde' in h and p['plan'] == 'CENTROS')
h = post(f'/protocolo/{pid}/datos', {'cobertura': COB2})
with A.app.app_context():
    p = db.uno("SELECT cobertura, plan FROM protocolos WHERE id=?", (pid,))
chequear('al cambiar de cobertura el plan se limpia', p['cobertura'] == COB2 and (p['plan'] or '') == '', dict(p))
h = c.get(f'/protocolo/{pid}').get_data(as_text=True)
chequear('la ficha trae el selector de plan', 'name="plan"' in h and 'data-planes' in h)
post(f'/protocolo/{pid}/datos', {'cobertura': COB, 'plan': 'CENTROS'})
h = c.get(f'/protocolo/{pid}').get_data(as_text=True)
chequear('la ficha muestra el plan', 'CENTROS' in h)

print('4) facturar usa el plan del protocolo')
with A.app.app_context():
    from vighi.servicios.facturas import facturacion_buscar
    filas = facturacion_buscar({'q': '', 'cobertura': COB, 'plan': 'CENTROS', 'tipo': '', 'flujo': '', 'clase': '', 'prioridad': '', 'zona': '', 'procedencia': '',
                                'desde': '', 'hasta': '', 'informados': '', 'facturados': '', 'iva': ''})
chequear('filtra por plan', filas and all(x['plan'] == 'CENTROS' for x in filas), len(filas))
chequear('y toma el importe del plan (lo que el plan no define cae a la cobertura)', all(x['unitario'] in (60000, 3000, None) for x in filas) and any(x['unitario'] == 60000 for x in filas), [x['unitario'] for x in filas])
h = c.get('/facturar?buscar=1&desde=2026-01-01&hasta=2026-12-31').get_data(as_text=True)
chequear('el filtro de plan de la pantalla ya está habilitado', 'name="plan"' in h and 'disabled' not in h.split('name="plan"')[1][:80])

print('5) pantalla del tarifario')
h = c.get(f'/tarifario?tarifario={t_cob2}').get_data(as_text=True)
chequear('resalta los importes en cero', 'importe-cero' in h and 'Sin importe' in h and 'en cero' in h)
chequear('marca la descripción propia', 'propia' in h and 'Biopsia por incisión (otra descripción)' in h)
h = post('/tarifario', {'accion': 'descripcion_valor', 'tarifario': str(t_cob2), 'codigo': '150101', 'descripcion': 'Descripción editada'})
with A.app.app_context():
    d = db.uno("SELECT descripcion FROM tarifario_descripciones WHERE tarifario_id=? AND codigo='150101'", (t_cob2,))
chequear('la descripción se puede editar', d and d['descripcion'] == 'Descripción editada')
h = post('/tarifario', {'accion': 'descripcion_valor', 'tarifario': str(t_cob2), 'codigo': '150101', 'descripcion': ''})
with A.app.app_context():
    d = db.uno("SELECT descripcion FROM tarifario_descripciones WHERE tarifario_id=? AND codigo='150101'", (t_cob2,))
chequear('vaciarla vuelve a la general', d is None)
h = c.get(f'/tarifario?tarifario={t_cob2}').get_data(as_text=True)
chequear('el panel de la tarifa ya no edita coberturas, planes ni plazos', 'name="coberturas"' not in h and 'plan_agregar' not in h and 'name="dias_' not in h)
chequear('en cambio lista las coberturas que la usan con su enlace', f'/cobertura?c=' in h)

print('5b) pantalla de cobertura')
h = c.get('/coberturas').get_data(as_text=True)
chequear('lista las coberturas con su tarifa, IVA y plazo', COB in h and 'Plazo de cobro' in h and '30 días' in h)
h = c.get('/coberturas?q=' + COB[:3]).get_data(as_text=True)
chequear('se puede buscar', COB in h)
h = c.get('/cobertura?c=' + COB).get_data(as_text=True)
chequear('la ficha trae IVA, plazo, tarifa y planes', 'name="iva"' in h and 'name="dias"' in h and 'name="tarifa"' in h and 'CENTROS' in h)
chequear('tiene las pestañas Datos, Planes, Tarifas y Códigos', all(x in h for x in ('>Datos<', 'Planes', '>Tarifas<', '>Códigos<')) and f'tarifario={t_cob}' in h)
h = c.get(f'/tarifario?c={COB}&tarifario={t_cob}').get_data(as_text=True)
chequear('Tarifas se ve dentro de la cobertura, con sus pestañas y sin el panel de tarifas', '>Códigos<' in h and 'Nueva tarifa' not in h and 'Importar importes' in h)
h = c.get(f'/nomencladores?c={COB}&tarifario={t_cob}').get_data(as_text=True)
chequear('Códigos también', '>Tarifas<' in h and 'Asignar nomenclador' in h)
h = c.get(f'/tarifario?c={COB}&tarifario={t_plan}').get_data(as_text=True)
chequear('con planes se elige entre la tarifa de la cobertura y la de cada plan', 'Plan CENTROS' in h and 'Tarifa de la cobertura' in h)
h = c.get(f'/tarifario?c={COB}&tarifario={t_cob2}').get_data(as_text=True)
chequear('una tarifa ajena a la cobertura vuelve a la de la cobertura', f'tarifario={t_cob}' in h)
h = c.get('/cobertura?c=' + COB + '&pestana=planes').get_data(as_text=True)
chequear('la pestaña Planes lista y agrega planes', 'CENTROS' in h and 'plan_agregar' in h)
h = c.get('/coberturas').get_data(as_text=True)
chequear('desde Coberturas se llega a la tarifa general', 'Tarifa general' in h and '/tarifario' in h and '/nomencladores' in h)
chequear('una cobertura que no existe da 404', c.get('/cobertura?c=NO%20EXISTE').status_code == 404)
h = post('/cobertura', {'c': COB, 'accion': 'guardar', 'iva': 'exento', 'dias': '45', 'tarifa': str(t_cob)})
with A.app.app_context():
    iva = db.uno("SELECT iva FROM tarifarios WHERE id=?", (t_cob,))['iva']
    dias = db.uno("SELECT dias FROM cobertura_pago WHERE cobertura=?", (COB,))['dias']
chequear('guarda IVA y plazo de la cobertura', iva == 'exento' and dias == 45 and 'IVA guardado' in h, (iva, dias))
h = post('/cobertura', {'c': COB, 'accion': 'guardar', 'iva': 'exento', 'dias': '999', 'tarifa': str(t_cob)})
chequear('rechaza un plazo fuera de rango', 'entre 0 y 365' in h)
h = post('/cobertura', {'c': COB, 'accion': 'guardar', 'iva': 'exento', 'dias': '', 'tarifa': str(t_cob)})
with A.app.app_context():
    sin = db.uno("SELECT dias FROM cobertura_pago WHERE cobertura=?", (COB,))
chequear('dejar el plazo vacío lo quita', sin is None)
post('/cobertura', {'c': COB, 'accion': 'guardar', 'iva': 'gravado', 'dias': '30', 'tarifa': str(t_cob)})
h = post('/cobertura', {'c': COB2, 'accion': 'plan_agregar', 'plan': 'premium'})
with A.app.app_context():
    fila = db.uno("SELECT tarifario_id FROM tarifario_coberturas WHERE cobertura=? AND plan='PREMIUM'", (COB2,))
    iva_plan = db.uno("SELECT iva FROM tarifarios WHERE id=?", (fila['tarifario_id'],))['iva'] if fila else None
chequear('agrega un plan con su propia tarifa y el IVA de la cobertura', fila is not None and iva_plan == 'exento' and 'PREMIUM' in h, iva_plan)
h = post('/cobertura', {'c': COB2, 'accion': 'plan_agregar', 'plan': 'PREMIUM'})
chequear('no repite el plan', 'ya tiene el plan' in h)
h = post('/cobertura', {'c': COB2, 'accion': 'plan_quitar', 'plan': 'PREMIUM'})
with A.app.app_context():
    n = db.uno("SELECT COUNT(*) AS n FROM tarifario_coberturas WHERE cobertura=? AND plan='PREMIUM'", (COB2,))['n']
chequear('quita el plan si nadie lo usa', n == 0)
h = post('/cobertura', {'c': COB, 'accion': 'plan_quitar', 'plan': 'CENTROS'})
with A.app.app_context():
    n = db.uno("SELECT COUNT(*) AS n FROM tarifario_coberturas WHERE cobertura=? AND plan='CENTROS'", (COB,))['n']
chequear('no deja quitar un plan que usa un protocolo', n == 1 and 'lo tienen' in h)
with A.app.app_context():
    general_id = db.uno("SELECT id FROM tarifarios WHERE nombre='TARIFA GENERAL'")['id']
post('/cobertura', {'c': COB2, 'accion': 'guardar', 'iva': 'exento', 'dias': '', 'tarifa': str(general_id)})
with A.app.app_context():
    propia = db.uno("SELECT 1 FROM tarifario_coberturas WHERE cobertura=? AND plan=''", (COB2,))
chequear('elegir la tarifa general deja a la cobertura sin tarifa propia', propia is None)
h = post('/cobertura', {'c': COB2, 'accion': 'guardar', 'iva': 'gravado', 'dias': '', 'tarifa': str(general_id)})
with A.app.app_context():
    nueva = db.uno("SELECT t.nombre, t.iva FROM tarifario_coberturas c JOIN tarifarios t ON t.id=c.tarifario_id WHERE c.cobertura=? AND c.plan=''", (COB2,))
chequear('cambiar el IVA de una cobertura sin tarifa propia le crea una', nueva is not None and nueva['iva'] == 'gravado' and 'tarifa propia' in h, dict(nueva) if nueva else None)

print('6) la fecha estimada de cobro se propone con el plazo de la cobertura')
with A.app.app_context():
    fid = db.ex("INSERT INTO facturas (estado, cobertura, alicuota, creado_por, creado_en) VALUES ('borrador',?,?,?,?)", (COB, 0.21, admin, db.ahora()))
    db.lote_ex(dom.sentencias_items(fid, [{'estudio_id': ids['bp'], 'protocolo_id': pid, 'numero_protocolo': 'C1', 'paciente': 'x', 'afiliado': '', 'fecha': '2026-10-01',
                                          'estudio': 'Biopsia', 'codigo': '150101', 'descripcion': 'd', 'cantidad': 1, 'unitario': 100.0, 'iva': 'exento', 'importe': 100.0}]))
post(f'/facturacion/{fid}/emitir', {'numero': 'A-0001', 'fecha_factura': '2026-10-01', 'fecha_estimada_cobro': '', 'fec_tipo': 'tentativa'})
with A.app.app_context():
    f = db.uno("SELECT estado, fecha_estimada_cobro, fec_tipo FROM facturas WHERE id=?", (fid,))
chequear('propone factura + 30 días', f['estado'] == 'emitida' and f['fecha_estimada_cobro'] == '2026-10-31' and f['fec_tipo'] == 'tentativa', dict(f))
with A.app.app_context():
    fid2 = db.ex("INSERT INTO facturas (estado, cobertura, alicuota, creado_por, creado_en) VALUES ('borrador',?,?,?,?)", (COB, 0.21, admin, db.ahora()))
    db.lote_ex(dom.sentencias_items(fid2, [{'estudio_id': ids['bp'], 'protocolo_id': pid, 'numero_protocolo': 'C1', 'paciente': 'x', 'afiliado': '', 'fecha': '2026-10-01',
                                           'estudio': 'Biopsia', 'codigo': '150101', 'descripcion': 'd', 'cantidad': 1, 'unitario': 100.0, 'iva': 'exento', 'importe': 100.0}]))
post(f'/facturacion/{fid2}/emitir', {'numero': 'A-0002', 'fecha_factura': '2026-10-01', 'fecha_estimada_cobro': '2026-11-15', 'fec_tipo': 'confirmada'})
with A.app.app_context():
    f = db.uno("SELECT fecha_estimada_cobro, fec_tipo FROM facturas WHERE id=?", (fid2,))
chequear('si la persona carga la fecha, se respeta', f['fecha_estimada_cobro'] == '2026-11-15' and f['fec_tipo'] == 'confirmada', dict(f))

print()
print('FALLAS:', 'ninguna' if not fallas else fallas)
sys.exit(1 if fallas else 0)
