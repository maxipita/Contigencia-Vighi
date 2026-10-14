import json, os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
from datos_informe import preparar

A, db, ids, admin = preparar()
from vighi.servicios import etiquetas as srv_etiquetas
fallas = []


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
c.get('/')
with c.session_transaction() as s:
    tk = s['csrf']

print('1) código de muestra PAP desde el protocolo')
for texto, cod in (('Citología Endocervical', 'ENDO'), ('Citología Exocervical', 'EXO'), ('Cúpula Vaginal', 'CUPULA'), ('Liquido', 'DERRAME'),
                   ('PAAF', 'PAAF'), ('', ''), (None, '')):
    chequear(f'{texto!r} -> {cod!r}', srv_etiquetas.codigo_muestra_pap(texto) == cod, srv_etiquetas.codigo_muestra_pap(texto))

for texto, cant, cod in (('Citología Endocervical', '1/2', 'ENDO/EXO'), ('Citología Exocervical', '1/2', 'ENDO/EXO'), ('Cúpula Vaginal', '1/2', 'ENDO/EXO'),
                         ('Citología Endocervical', '1', 'ENDO'), ('Citología Exocervical', '2', 'EXO'), ('Cúpula Vaginal', '', 'CUPULA')):
    chequear(f'{texto} con cantidad {cant!r} -> {cod}', srv_etiquetas.codigo_muestra_pap(texto, cant) == cod, srv_etiquetas.codigo_muestra_pap(texto, cant))
print('2) los casos traen el responsable y la muestra')
with A.app.app_context():
    # un PAP de Cúpula Vaginal con 2 etiquetas ("2") y una biopsia de dos frascos
    pid = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, creado_por, creado_en) VALUES ('C000300','2026-10-01','Lab','Etiq',?,?)", (admin, db.ahora()))
    pap = db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, responsable_id, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (pid, 'PAP', 'Citologías', 'Ginecológica', 'Vagina', 'Cúpula Vaginal', '2', ids['cito'], admin, db.ahora()))
    casos = {x['id']: x for x in srv_etiquetas.etiquetas_casos()}
    etiquetas_ok = srv_etiquetas.etiquetas_cantidad('1/2') == 1       # un vidrio, una etiqueta
chequear('el PAP trae muestra CUPULA y su citotécnico', casos[pap]['muestra'] == 'CUPULA' and casos[pap]['resp'] == 'ZZCT', casos[pap])
chequear('el PAP de cantidad 1/2 (C000102) trae ENDO/EXO aunque su muestra sea endocervical', casos[ids['pap']]['muestra'] == 'ENDO/EXO' and etiquetas_ok, casos[ids['pap']])
chequear('la biopsia trae el patólogo y sin código de muestra', casos[ids['bp']]['resp'] == 'DM' and casos[ids['bp']]['muestra'] == '', casos[ids['bp']])

print('3) confirmar etiquetas de BP-Laboratorio: el servidor toma el patólogo del protocolo')
r = c.post('/api/etiquetas/confirmar', json={'tipo': 'lab', 'items': [ids['bp'], ids['largo']],
                                              'params': {'patos': ['ZZOT', 'ZZOT', 'ZZOT'], 'pato': 'ZZOT'}},      # aunque la pantalla mande otra cosa, se ignora
           headers={'X-CSRF': tk})
j = r.get_json()
chequear('se confirma', j and j.get('ok'), j)
with A.app.app_context():
    fila = db.uno("SELECT params FROM etiquetas_lotes WHERE id=?", (j['id'],))
params = json.loads(fila['params'])
chequear('guarda un patólogo por etiqueta tomado del protocolo (DM, no lo que mandó la pantalla)', params['patos'] == ['DM'] * (2 + 10), params['patos'])
chequear('no guarda elecciones manuales ni el patólogo "para todas"', 'pato' not in params)

print('4) confirmar etiquetas PAP-Laboratorio')
r = c.post('/api/etiquetas/confirmar', json={'tipo': 'pap', 'items': [pap], 'params': {'muestras': ['EXO', 'EXO'], 'lotePap': 'EXO'}}, headers={'X-CSRF': tk})
j = r.get_json()
chequear('se confirma', j and j.get('ok'), j)
with A.app.app_context():
    params = json.loads(db.uno("SELECT params FROM etiquetas_lotes WHERE id=?", (j['id'],))['params'])
chequear('guarda el tipo de muestra del protocolo en cada etiqueta (CUPULA, no lo que mandó la pantalla)', params['muestras'] == ['CUPULA', 'CUPULA'], params.get('muestras'))
chequear('y también en el protocolo rotulado', params['items'][0]['muestra'] == 'CUPULA')
chequear('sin elección general', 'lotePap' not in params)
r = c.post('/api/etiquetas/confirmar', json={'tipo': 'pap', 'items': [ids['pap']]}, headers={'X-CSRF': tk})
with A.app.app_context():
    params2 = json.loads(db.uno("SELECT params FROM etiquetas_lotes ORDER BY id DESC LIMIT 1")['params'])
chequear('confirmar el PAP de 1/2 guarda una sola etiqueta ENDO/EXO', r.get_json().get('ok') and params2['muestras'] == ['ENDO/EXO'], params2.get('muestras'))
r = c.post('/api/etiquetas/confirmar', json={'tipo': 'pap', 'items': [ids['bp']]}, headers={'X-CSRF': tk})
chequear('una biopsia no se puede rotular en PAP', not r.get_json().get('ok'))

print('5) la pantalla ya no tiene selectores de patólogo ni de muestra')
t = c.get('/etiquetas').get_data(as_text=True)
chequear('sin "Patólogo para todas" ni "Tipo de muestra para todas"', 'Patólogo para todas' not in t and 'Tipo de muestra para todas' not in t)
chequear('sin desplegables dentro de la etiqueta', 'lab-pato-sel' not in t and 'pap-muestra-sel' not in t and 'id="pato"' not in t and 'id="lotePap"' not in t)
chequear('el JS ya no los referencia', "$('pato')" not in t and "$('lotePap')" not in t and 'opcionesPato' not in t and 'opcionesMuestra' not in t)
chequear('la nota explica de dónde sale', 'sale del responsable de cada protocolo' in t and 'sale de cada protocolo' in t)
datos = re.search(r'window\.ETIQUETAS\s*=\s*(\{.*?\});', t, re.S)
chequear('los datos que usa la pantalla traen la muestra de cada PAP', datos is not None and '"muestra"' in datos.group(1))

print('6) un lote viejo (con elecciones guardadas por etiqueta) se sigue reimprimiendo igual')
with A.app.app_context():
    viejo = {'items': [{'casoId': ids['bp'], 'protocolo': 'C000101', 'cantidad': 2, 'loteCodigo': 'X', 'resp': 'DM', 'fechaRec': '2026-10-01'}],
             'patos': ['AP', 'RP'], 'pato': ''}
    db.ex("INSERT INTO etiquetas_lotes (tipo, n, por_proto, etiquetas, params, creado_por, creado_en) VALUES ('lab',1,1,2,?,?,?)", (json.dumps(viejo), admin, db.ahora()))
t = c.get('/etiquetas').get_data(as_text=True)
chequear('el lote viejo conserva sus patos y verLote los usa por posición (elec.pato[...] = patos[i])', "elec.pato[p.key] = (b.params.patos || [])[i] || ''" in t)

print(chr(10) + 'FALLAS:', fallas if fallas else 'ninguna')
