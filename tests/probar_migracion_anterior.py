import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar

A, db, ids, admin = preparar()
from vighi.dominio import anterior
from vighi.servicios import migracion_anterior as mig

fallas = []


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


def seguimiento(accion, completada=None, usuario=None):
    return {'accion': accion, 'actividad': accion, 'limite': '', 'completada': completada, 'usuario': usuario}


def flujo(idp, idf, titulo, estudios, tracking, **extra):
    base = {'numero': f'#P{idp}', 'tipo': titulo.split('-')[1].split()[0], 'titulo': titulo, 'validado': 'Validado', 'paciente': {'id': '77', 'nombre': 'ORGE PORTELA, FLORENCIA'},
            'edad': '31 (1995)', 'cobertura': 'GALENO (AZU/BLA)', 'credencial': '#0205', 'dni': '', 'medico': {'id': '1', 'nombre': 'NUEVO MIGRADO, JUAN'},
            'procedencia': {'id': '2', 'nombre': 'UBICNUEVA'}, 'entrega': {'id': '2', 'nombre': 'UBICNUEVA'}, 'lote_tipo': 'ONCO', 'lote': {'id': '9', 'nombre': 'ONCO-1013.2'},
            'asignado': None, 'macro': 'Pieza de 4 cm.', 'micro': None, 'autor_macro': 'SULLCA, Daiana', 'firmante': 'Dra. NO EXISTE, Ana',
            'recoleccion': ': 01/10/2026', 'tracking': tracking, 'pendientes': [{'accion': 'Micro > Informar'}], 'estudios': estudios, 'tecnicas': [], 'idp': str(idp), 'idf': str(idf)}
    base.update(extra)
    return base


def fila(orden, nombre, organo, tacos='1 taco', comentarios=None):
    return {'eid': '1', 'orden': orden, 'nombre': nombre, 'libre': f'{organo} libre', 'organo': organo, 'tacos': tacos, 'tecnicas_pub': None,
            'detalle': {'nomenclador': '150102', 'unidades': '1', 'tipo': 'Biopsias', 'zona': 'Digestiva', 'organo': organo, 'tacos': tacos.split()[0], 'libre': f'{organo} libre',
                        'comentarios': comentarios or []}}


def practica(nombre, nomenclador):
    return {'eid': '2', 'orden': None, 'nombre': nombre, 'libre': None, 'organo': 'N/A', 'tacos': None,
            'detalle': {'nomenclador': nomenclador, 'unidades': '1', 'tipo': 'Biopsias', 'zona': None, 'organo': 'N/A', 'comentarios': []}}


COMENTARIO = {'usuario': 'Daiana', 'fecha': '2 oct. 11:26hs', 'texto': 'encontre otro ganglio'}
tracking_bp = [seguimiento('Protocolo > Cargar', '01/10/2026 15:37 hs', 'ZZNU'), seguimiento('Macro > Informar', '02/10/2026 11:27 hs', 'ZZDS'),
               seguimiento('Histo > Procesar', '05/10/2026 5:07 hs', 'ZZNU'), seguimiento('Taco > Cortar (nuevo corte)', '13/10/2026 19:49 hs', 'ZZNU'),
               seguimiento('Taco > Archivar', '14/10/2026 8:00 hs', 'ZZNU')]
GRUPO_BP = [
    flujo(1111111, 10, '#P1111111-BP c/IHQ', [fila('A', 'Resección', 'Vesícula', comentarios=[COMENTARIO]), fila('B', 'Resección', 'Estómago', '2 tacos', comentarios=[COMENTARIO]),
                                              practica('Intraoperatoria', '150104'), practica('Helicobacter Pylori', '150167'), practica('CD20', '150262'), practica('Ki 67', '150265')],
          tracking_bp, tecnicas=['Vesícula Reseccion A 6F/R/3C', 'Estómago Resección B VF/IT/1C']),
    flujo(1111111, 11, '#P1111111-BPC (U)', [fila('A', 'Biopsia', 'Cuello')], [seguimiento('Protocolo > Cargar', '01/10/2026 15:37 hs', 'ZZNU')]),
]
PAP = [flujo(2222222, 20, '#P2222222-PAP', [fila('A', 'Citología Exocervical', 'Vagina')], [seguimiento('Protocolo > Cargar', '03/10/2026 10:00 hs', 'ZZNU'),
                                                                                        seguimiento('Porta > Colorear', '04/10/2026 9:00 hs', 'ZZNU')],
             lote={'id': '5', 'nombre': 'PAPS-1004.1'}, lote_tipo='PAPS', macro=None, firmante=None)]
PACIENTES = {'77': {'nombre': 'ORGE PORTELA, FLORENCIA', 'dni': '38.563.670', 'sexo': 'Mujer', 'edad': '31 (1995)', 'telefono': '(+54911) 6530', 'email': 'FLORORGE@GMAIL.COM',
                    'cobertura': 'GALENO', 'credencial': '020547170104', 'iva': 'Exento'}}
FORM_PAP = {'20': [{'form': 'micro/pap/', 'campos': {'DD_Leucocitos': '[+] Escasa cantidad', 'tb_Pavimentosas': 'Abundantes', 'tb_Diagnostico': 'NILM'}}]}
FORM_BP = {'10': [{'form': 'micro/bp/', 'campos': {'tb_macro': 'Macro del formulario', 'tb_micro': 'Se observa tejido.', 'tb_diagnostico': 'Colecistitis crónica.', 'tb_observaciones': 'Obs.'}}]}


def armar():
    r1 = anterior.protocolo_de(GRUPO_BP, PACIENTES['77'], FORM_BP)
    r2 = anterior.protocolo_de(PAP, PACIENTES['77'], FORM_PAP)
    return [r1, r2]


print('1) lectura y normalización')
r1, r2 = armar()
chequear('número sin #, fecha ISO, DNI solo con dígitos', r1['numero'] == 'P1111111' and r1['fecha_recoleccion'] == '2026-10-01' and r1['dni'] == '38563670', (r1['numero'], r1['dni']))
chequear('cobertura del paciente, plan del encabezado, afiliado sin #, exento', (r1['cobertura'], r1['plan'], r1['n_afiliado'], r1['exento']) == ('GALENO', 'AZU/BLA', '020547170104', 'Si'),
         (r1['cobertura'], r1['plan'], r1['n_afiliado'], r1['exento']))
chequear('BP y BPC del mismo protocolo quedan en un solo flujo BP con las 3 muestras', len(r1['flujos']) == 1 and r1['flujos'][0]['tipo'] == 'BP' and len(r1['flujos'][0]['estudios']) == 3)
chequear('el nacimiento queda en las observaciones y se marca la urgencia', 'Año de nacimiento: 1995' in r1['observaciones'] and 'Urgente' in r1['observaciones'] and 'Intraoperatoria (150104)' in r1['observaciones'])
chequear('las etapas hechas se mapean, sin repetir el nuevo corte ni lo que no existe', [e['etapa'] for e in r1['flujos'][0]['etapas']] == ['macroscopia', 'procesamiento'], r1['flujos'][0]['etapas'])
chequear('los comentarios repetidos en cada muestra quedan una sola vez', len(r1['comentarios']) == 1)
tecnica = r1['flujos'][0]['estudios'][0]['tecnica']
chequear('la técnica 6F/R/3C: varios fragmentos, reserva, 3 cassettes', (tecnica['fragmentos'], tecnica['inclusion'], tecnica['cassettes']) == (4, 'Reserva', 3), tecnica)
chequear('la macro del formulario pisa a la de la página y suma cassettes', r1['flujos'][0]['macro']['descripcion'] == 'Macro del formulario' and r1['flujos'][0]['macro']['cassettes'] == 4)
chequear('el PAP trae sus campos estructurados sin la marca de la escala', r2['flujos'][0]['micro']['pap']['leucocitos'] == 'Escasa cantidad' and r2['flujos'][0]['micro']['pap']['resultado'] == 'NILM')

print('2) ensayo: no escribe nada')
with A.app.app_context():
    antes = db.uno("SELECT COUNT(*) AS n FROM protocolos")['n']
    res = mig.importar([r1, r2], ensayo=True)
    despues = db.uno("SELECT COUNT(*) AS n FROM protocolos")['n']
chequear('el ensayo cuenta pero no crea', res['importados'] == 2 and antes == despues and not res['errores'], res)
chequear('el ensayo avisa qué crearía', 'ZZNU' in res['nuevos']['usuarios'] and 'UBICNUEVA' in res['nuevos']['ubicaciones'] and 'NUEVO MIGRADO, JUAN' in res['nuevos']['medicos'] and 'ONCO-1013.2' in res['nuevos']['lotes'], res['nuevos'])

print('3) importación')
with A.app.app_context():
    res = mig.importar([r1, r2])
chequear('importa los dos', res['importados'] == 2 and not res['errores'], res)
with A.app.app_context():
    p = db.uno("SELECT * FROM protocolos WHERE numero='P1111111'")
    fl = db.q("SELECT * FROM flujos WHERE protocolo_id=?", (p['id'],))
    es = db.q("SELECT * FROM estudios WHERE protocolo_id=? ORDER BY id", (p['id'],))
    flujo_id = fl[0]['id']
    etapas = db.q("SELECT e.etapa, u.iniciales, e.fecha_hora FROM etapas e JOIN usuarios u ON u.id=e.usuario_id WHERE e.flujo_id=? ORDER BY e.etapa", (flujo_id,))
    macro = db.uno("SELECT * FROM macro WHERE flujo_id=?", (flujo_id,))
    micro = db.uno("SELECT * FROM micro WHERE flujo_id=?", (flujo_id,))
    ihq = db.uno("SELECT * FROM ihq WHERE flujo_id=?", (flujo_id,))
    tecs = db.q("SELECT t.numero, t.fragmentos, t.inclusion, t.cassettes, t.estudio_id FROM tecnicas t JOIN estudios e ON e.id=t.estudio_id WHERE e.protocolo_id=? ORDER BY t.numero", (p['id'],))
    lote = db.uno("SELECT * FROM lotes WHERE codigo='ONCO-1013.2'")
    com = db.q("SELECT * FROM comentarios WHERE protocolo_id=?", (p['id'],))
chequear('el protocolo conserva el número anterior, sin número C, y queda cargado en el sistema', p['numero'] == 'P1111111' and p['origen'] == 'anterior' and p['protocolo_sistema'] == 'P1111111'
         and p['cargado_sistema'] == 1 and p['borrador'] == 0 and p['pendiente_validacion'] == 0 and p['creado_en'] == '2026-10-01 15:37:00', dict(p))
chequear('datos del paciente y del protocolo', (p['apellido'], p['nombre'], p['sexo'], p['email'], p['medico'], p['lugar_recoleccion'], p['plan']) ==
         ('ORGE PORTELA', 'FLORENCIA', 'Mujer', 'flororge@gmail.com', 'NUEVO MIGRADO, JUAN', 'UBICNUEVA', 'AZU/BLA'), dict(p))
chequear('un flujo BP con tres muestras con su detalle y las técnicas especiales en la primera', len(fl) == 1 and fl[0]['tipo'] == 'BP' and len(es) == 3 and es[0]['tecnicas_especiales'] == 'Helicobacter Pylori'
         and es[0]['sitio'] == 'Vesícula' and es[0]['observaciones'] == 'Vesícula libre' and es[0]['lote_id'] == lote['id'], [dict(x) for x in es][:1])
chequear('las etapas hechas llevan su fecha y el usuario del sistema anterior', [(e['etapa'], e['iniciales'], e['fecha_hora']) for e in etapas] ==
         [('macroscopia', 'ZZDS', '2026-10-02 11:27:00'), ('procesamiento', 'ZZNU', '2026-10-05 05:07:00')], [dict(e) for e in etapas])
chequear('macro, micro (con conclusión) e IHQ con sus marcadores', macro['descripcion'] == 'Macro del formulario' and macro['cassettes'] == 4 and micro['descripcion'] == 'Se observa tejido.'
         and 'Colecistitis' in micro['conclusion'] and micro['solicita_ihq'] == 1 and ihq['marcadores'] == 'CD20; Ki 67' and ihq['pedido_en'], (dict(macro), dict(micro), ihq and dict(ihq)))
chequear('técnicas por muestra', [(t['numero'], t['fragmentos'], t['inclusion'], t['cassettes']) for t in tecs] == [('A', 4, 'Reserva', 3), ('B', 4, 'Inclusión total', 1)], [dict(t) for t in tecs])
chequear('el lote se crea con su código y los comentarios llegan una vez', lote and lote['tipo_lote'] == 'ONCO' and lote['fecha'] == '2026-10-13' and lote['numero'] == 2 and len(com) == 1
         and 'Daiana' in com[0]['texto'] and com[0]['fecha_hora'] == '2026-10-02 11:26:00', com and dict(com[0]))
with A.app.app_context():
    pap = db.uno("SELECT * FROM protocolos WHERE numero='P2222222'")
    pf = db.uno("SELECT * FROM flujos WHERE protocolo_id=?", (pap['id'],))
    pm = db.uno("SELECT * FROM micro WHERE flujo_id=?", (pf['id'],))
    pl = db.uno("SELECT * FROM lotes WHERE codigo='PAPS-1004.1'")
    nuevos = [db.uno("SELECT activo, nombre FROM usuarios WHERE iniciales=?", (i,)) for i in ('ZZNU', 'ANT')]
    medico = db.uno("SELECT 1 FROM medicos WHERE nombre='NUEVO MIGRADO, JUAN'")
    ubic = db.uno("SELECT 1 FROM ubicaciones WHERE abreviatura='UBICNUEVA'")
    aud = db.uno("SELECT 1 FROM auditoria WHERE accion='importar_anterior' AND protocolo_id=?", (p['id'],))
chequear('el PAP queda con su flujo, su micro estructurada y su lote', pf['tipo'] == 'PAP' and pm['resultado'] == 'NILM' and pm['leucocitos'] == 'Escasa cantidad' and pl is not None)
chequear('se crean los usuarios, médicos y ubicaciones que faltaban', nuevos[0]['activo'] == 1 and nuevos[1]['nombre'] == 'Sistema anterior' and nuevos[1]['activo'] == 0 and medico and ubic and aud)
chequear('avisa el firmante que no encontró', 'Dra. NO EXISTE, Ana' in res['nuevos']['sin_firmante'], res['nuevos'])

print('4) repetible: no duplica')
with A.app.app_context():
    res = mig.importar([r1, r2])
    n = db.uno("SELECT COUNT(*) AS n FROM protocolos WHERE numero IN ('P1111111','P2222222')")['n']
    e = db.uno("SELECT COUNT(*) AS n FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id WHERE p.numero='P1111111'")['n']
chequear('una segunda corrida saltea lo ya importado', res['importados'] == 0 and res['existentes'] == 2 and n == 2 and e == 3, res)

print('5) el protocolo importado se abre y sigue su curso en el sistema')
c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
c.get('/')
with A.app.app_context():
    pid = db.uno("SELECT id FROM protocolos WHERE numero='P1111111'")['id']
    eid = db.uno("SELECT id FROM estudios WHERE protocolo_id=? ORDER BY id LIMIT 1", (pid,))['id']
for url in (f'/protocolo/{pid}', f'/estudio/{eid}', f'/protocolo/{pid}/flujo/BP', '/'):
    r = c.get(url)
    chequear(f'abre {url}', r.status_code == 200, r.status_code)
html = c.get('/?ver=todos').get_data(as_text=True)
chequear('aparece en el tablero con el número anterior', 'P1111111' in html)
chequear('la próxima etapa pendiente es Inclusión', 'Inclusión' in c.get(f'/protocolo/{pid}').get_data(as_text=True))
print('6) pantalla de migración')
import json
with A.app.app_context():
    sin = db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, debe_cambiar_clave) VALUES ('ZZNA','No Admin','',0,1,0)")
cn = A.app.test_client()
with cn.session_transaction() as s:
    s['uid'] = sin
cn.get('/')
chequear('solo los administradores entran', cn.get('/migracion').status_code == 403 and c.get('/migracion').status_code == 200)
with c.session_transaction() as s:
    tk = s['csrf']
cab = {'X-CSRF': tk, 'Content-Type': 'application/json'}
nuevo = json.loads(json.dumps(r1))
nuevo['numero'] = 'P3333333'
r = c.post('/api/migracion/lote', data=json.dumps({'registros': [nuevo], 'ensayo': True}), headers=cab)
with A.app.app_context():
    hay = db.uno("SELECT 1 FROM protocolos WHERE numero='P3333333'")
chequear('el ensayo por la API responde y no escribe', r.status_code == 200 and r.get_json()['importados'] == 1 and hay is None, r.get_data(as_text=True)[:200])
r = c.post('/api/migracion/lote', data=json.dumps({'registros': [nuevo], 'ensayo': False}), headers=cab)
with A.app.app_context():
    hay = db.uno("SELECT 1 FROM protocolos WHERE numero='P3333333'")
    aud = db.uno("SELECT 1 FROM auditoria WHERE accion='migracion'")
chequear('el lote real escribe y queda auditado', r.status_code == 200 and hay is not None and aud is not None)
chequear('rechaza un pedido vacío o mal armado', c.post('/api/migracion/lote', data=json.dumps({'registros': []}), headers=cab).status_code == 400
         and c.post('/api/migracion/lote', data=json.dumps({'registros': [{'numero': 'x'}]}), headers=cab).status_code == 400)
chequear('rechaza más de 25 protocolos por pedido', c.post('/api/migracion/lote', data=json.dumps({'registros': [nuevo] * 26}), headers=cab).status_code == 400)
chequear('sin CSRF no pasa', c.post('/api/migracion/lote', data=json.dumps({'registros': [nuevo]}), headers={'Content-Type': 'application/json'}).status_code == 400)
chequear('un usuario común tampoco por la API', cn.post('/api/migracion/lote', data=json.dumps({'registros': [nuevo]}), headers={'X-CSRF': tk, 'Content-Type': 'application/json'}).status_code in (400, 403))
h = c.get('/migracion').get_data(as_text=True)
chequear('la pantalla lista los usuarios creados con solo iniciales y cuenta lo cargado', 'ZZNU' in h and 'ANT' not in h.split('Usuarios creados')[1] and 'Ya cargados' in h)
chequear('está en Configuraciones', 'migracion' in c.get('/configuraciones').get_data(as_text=True))
print('7) PAP sin datos del paciente y sin letra de muestra')
with A.app.app_context():
    db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, debe_cambiar_clave) VALUES ('ZZTP','Tobias Pardo','citotecnico',0,1,0)")
pap_sin = flujo(4444444, 20, '#P4444444-PAP', [{'eid': '3', 'orden': None, 'nombre': 'Citología Endocervical', 'libre': '-', 'organo': 'Vagina', 'tacos': None, 'tecnicas_pub': None,
                                                'detalle': {'nomenclador': '150106', 'unidades': '1', 'tipo': 'Citologías', 'zona': 'Ginecológica', 'organo': 'Vagina', 'comentarios': []}}],
                [seguimiento('Protocolo > Cargar', '13/10/2026 12:20 hs', 'ZZNU')], paciente=None, lote={'id': '1', 'nombre': 'ZZTP-1014.1'}, lote_tipo='PAPS',
                asignado='PARDO, Tobias', macro=None, firmante='Dra. PAPARATTO, Andrea')
r4 = anterior.protocolo_de([pap_sin], None, {})
with A.app.app_context():
    res = mig.importar([r4])
    p4 = db.uno("SELECT * FROM protocolos WHERE numero='P4444444'")
    e4 = db.q("SELECT * FROM estudios WHERE protocolo_id=?", (p4['id'],))
    l4 = db.uno("SELECT * FROM lotes WHERE codigo='ZZTP-1014.1'")
    u4 = db.uno("SELECT id FROM usuarios WHERE iniciales='ZZTP'")
chequear('el PAP sin letra queda como muestra, no como práctica', len(r4['flujos'][0]['estudios']) == 1 and not r4['flujos'][0]['practicas'] and res['importados'] == 1 and len(e4) == 1, res)
chequear('sin paciente entra como provisorio a validar', (p4['apellido'], p4['nombre'], p4['pendiente_validacion']) == ('IA', 'EnProceso', 1), dict(p4))
chequear('el lote del PAP es el del citotécnico y él queda de responsable', l4 and l4['tipo_lote'] == 'ZZTP' and e4[0]['responsable_id'] == u4['id'] and e4[0]['lote_id'] == l4['id'], (l4 and dict(l4), dict(e4[0])))

print('7b) títulos en el nombre del firmante o asignado')
with A.app.app_context():
    uid_mad = db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, debe_cambiar_clave) VALUES ('ZZMAD','Miguel Ángel Domenianni','citotecnico',0,1,0)")
    ctx = mig.Contexto(ensayo=True)
    chequear('«Ct. DOMENIANNI, Miguel Angel» encuentra a Miguel Ángel Domenianni', ctx.persona('Ct. DOMENIANNI, Miguel Angel') == uid_mad and not ctx.nuevos['sin_firmante'], ctx.nuevos['sin_firmante'])
    chequear('sin el título también lo encuentra', ctx.persona('DOMENIANNI, Miguel Angel') == uid_mad)

print('8) imágenes y órdenes')
import io
from PIL import Image
from vighi.servicios import migracion_imagenes as mi


def png(color):
    salida = io.BytesIO()
    Image.new('RGB', (400, 300), color).save(salida, 'PNG')
    return salida.getvalue()


BYTES = {'https://s3.us-west-2.amazonaws.com/repo.southernbits.com/svighi/2026/9/24/3333333_1.jpg': png((200, 10, 10)),
         'https://s3.us-west-2.amazonaws.com/repo.southernbits.com/svighi/2026/10/2/Batch1_00000001_5_fte.png': png((10, 200, 10))}
mi.descargar = lambda url: BYTES[url] if url in BYTES else (_ for _ in ()).throw(ValueError('origen no permitido'))
IMGS = [{'url': 'https://s3.us-west-2.amazonaws.com/repo.southernbits.com/svighi/2026/9/24/3333333_1.jpg', 'tipo': 'Muestra'},
        {'url': 'https://s3.us-west-2.amazonaws.com/repo.southernbits.com/svighi/2026/10/2/Batch1_00000001_5_fte.png', 'tipo': 'Orden médica'},
        {'url': 'https://otro.sitio/ataque.jpg', 'tipo': 'Muestra'}]
chequear('el normalizador junta las imágenes de los formularios sin repetir', len(anterior.imagenes_de({'1': [{'imagenes': IMGS[:2]}], '2': [{'imagenes': IMGS[:2]}]})) == 2)
r = c.post('/api/migracion/imagenes', data=json.dumps({'numero': 'P3333333', 'imagenes': IMGS, 'ensayo': True}), headers=cab)
with A.app.app_context():
    n0 = db.uno("SELECT COUNT(*) AS n FROM imagenes")['n']
chequear('el ensayo cuenta y no copia', r.status_code == 200 and r.get_json()['importadas'] == 3 and n0 == 0, r.get_data(as_text=True)[:200])
r = c.post('/api/migracion/imagenes', data=json.dumps({'numero': 'P3333333', 'imagenes': IMGS, 'ensayo': False}), headers=cab)
d = r.get_json()
with A.app.app_context():
    pid3 = db.uno("SELECT id FROM protocolos WHERE numero='P3333333'")['id']
    im = db.q("SELECT nombre, descripcion, creado_en FROM imagenes WHERE protocolo_id=?", (pid3,))
    od = db.q("SELECT nombre, pagina, metodo FROM ordenes WHERE protocolo_id=?", (pid3,))
chequear('copia la imagen como imagen y la orden como orden, y rechaza un origen ajeno', d['importadas'] == 2 and len(d['errores']) == 1 and len(im) == 1 and len(od) == 1, d)
chequear('conserva nombre, tipo y fecha original', im[0]['nombre'] == '3333333_1.jpg' and im[0]['descripcion'] == 'Muestra' and im[0]['creado_en'] == '2026-09-24 00:00:00' and od[0]['nombre'].startswith('Batch1_'))
chequear('se ven en la ficha', c.get(f'/protocolo/{pid3}').status_code == 200)
r = c.post('/api/migracion/imagenes', data=json.dumps({'numero': 'P3333333', 'imagenes': IMGS[:2], 'ensayo': False}), headers=cab)
d = r.get_json()
with A.app.app_context():
    n1 = db.uno("SELECT COUNT(*) AS n FROM imagenes WHERE protocolo_id=?", (pid3,))['n']
chequear('repetible: no duplica', d['importadas'] == 0 and d['existentes'] == 2 and n1 == 1, d)
chequear('un protocolo que no se importó se rechaza con aviso', c.post('/api/migracion/imagenes', data=json.dumps({'numero': 'P9999999', 'imagenes': IMGS[:1], 'ensayo': False}), headers=cab).get_json()['errores'])
chequear('pedido mal armado: 400', c.post('/api/migracion/imagenes', data=json.dumps({'numero': 'P3333333', 'imagenes': []}), headers=cab).status_code == 400)
print('FALLAS:', fallas or 'ninguna')
