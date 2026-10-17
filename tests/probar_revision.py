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


from datetime import date
from vighi.dominio import informes, trazabilidad
from vighi.dominio.estudios import ETAPAS, REGISTRO, Variante

print('1) la etapa Revisión es la última de cada flujo')
for tipo in ('BP', 'PAP', 'CT'):
    claves = [p[0] for p in REGISTRO[tipo].flujo(False)]
    chequear(f'{tipo}: termina en revisión, después de la microscopía', claves[-2:] == ['microscopia', 'revision'], claves)
bp = [p[0] for p in REGISTRO['BP'].flujo(Variante(True, False))]
chequear('BP con IHQ: la revisión va después de la interpretación de la IHQ', bp[-2:] == ['interp_ihq', 'revision'], bp)
chequear('es «Micro > Revisar» del sector firmante', ETAPAS['revision'][1] == 'firmante' and ETAPAS['revision'][4] == 'Micro > Revisar' and ETAPAS['revision'][0] == 'Revisión')

print('2) plazo: un día hábil después de la microscopía (o de la interpretación de la IHQ)')
base = '2026-10-05'
micro = trazabilidad.limite('BP', 'microscopia', base, [], False, False)
revision = trazabilidad.limite('BP', 'revision', base, [], False, False)
chequear('sin IHQ vence el día hábil siguiente a la microscopía', revision.date() == trazabilidad.sumar_habiles(micro.date(), 1, []) and revision.hour == 20, (micro, revision))
interp = trazabilidad.limite('BP', 'interp_ihq', base, [], False, True)
revision_ihq = trazabilidad.limite('BP', 'revision', base, [], False, True)
chequear('con IHQ vence el día hábil siguiente a la interpretación', revision_ihq.date() == trazabilidad.sumar_habiles(interp.date(), 1, []), (interp, revision_ihq))
decal = trazabilidad.limite('BP', 'revision', base, [], True, False)
chequear('con decalcificación se corre un día más', decal.date() == trazabilidad.sumar_habiles(revision.date(), 1, []), (revision, decal))

print('3) el flujo se informa recién con la revisión')
pid, eid = ids['p_pendiente'], ids['pendiente']
with A.app.app_context():
    fid = db.uno("SELECT flujo_id FROM estudios WHERE id=?", (eid,))['flujo_id']
    db.ex("INSERT INTO macro (flujo_id, descripcion) VALUES (?,?)", (fid, 'Fragmento de 1 cm.'))
    db.ex("INSERT INTO micro (flujo_id, descripcion, conclusion, solicita_revision) VALUES (?,?,?,1)", (fid, 'Sin atipia.', 'Negativo.'))
    for clave in ('macroscopia', 'procesamiento', 'inclusion', 'corte', 'coloreado', 'microscopia'):
        db.ex("INSERT INTO etapas (flujo_id, etapa, usuario_id, fecha_hora) VALUES (?,?,?,?)", (fid, clave, ids['med'], '2026-10-05 10:00:00'))
    hechas = {r['etapa'] for r in db.q("SELECT etapa FROM etapas WHERE flujo_id=?", (fid,))}
estado, prox = REGISTRO['BP'].estado(hechas, False)
chequear('con la microscopía hecha queda pendiente de revisión', estado == 'Pend. Revisión' and prox[0] == 'revision', (estado, prox))
cm, tm = cliente(ids['med'])
h = cm.get('/?ver=pendientes').get_data(as_text=True)
chequear('el tablero lo muestra en pendientes con su etapa', 'C000105' in h and 'Pend. Revisión' in h)
h = cm.get('/?ver=informados').get_data(as_text=True)
chequear('y no en informados', 'C000105' not in h)
with A.app.app_context():
    try:
        informes.armar(pid)
        sin_informe = False
    except informes.InformeError as e:
        sin_informe = 'Revisión' in str(e)
chequear('el informe no se genera hasta que se revise', sin_informe)

print('4) quién la marca y qué se edita mientras se revisa')
cc, tc = cliente(ids['cito'])
cc.post(f'/estudio/{eid}/listo/revision', data={'_csrf': tc})
with A.app.app_context():
    marcada = db.uno("SELECT 1 FROM etapas WHERE flujo_id=? AND etapa='revision'", (fid,))
chequear('un citotécnico (sin el sector firmante) no la puede marcar', marcada is None)
r = cm.get(f'/estudio/{eid}')
html = r.get_data(as_text=True)
chequear('el firmante ve el botón para completarla', r.status_code == 200 and f'/estudio/{eid}/listo/revision' in html)
cm.post(f'/estudio/{eid}/micro', data={'_csrf': tm, 'descripcion': 'Sin atipia.', 'conclusion': 'Negativo, revisado.'})
with A.app.app_context():
    revisado = db.uno("SELECT conclusion FROM micro WHERE flujo_id=?", (fid,))['conclusion']
chequear('mientras se revisa se puede corregir la microscopía', revisado == 'Negativo, revisado.', revisado)
r = cm.post(f'/estudio/{eid}/listo/revision', data={'_csrf': tm}, follow_redirects=True)
chequear('no se puede cerrar la revisión sin la malignidad', 'asignar la malignidad' in r.get_data(as_text=True))
with A.app.app_context():
    chequear('la revisión no quedó marcada', db.uno("SELECT 1 FROM etapas WHERE flujo_id=? AND etapa='revision'", (fid,)) is None)
cm.post(f'/protocolo/{pid}/malignidad', data={'_csrf': tm, 'tipo': 'BP', 'valor': 'MALIGNO'})
cm.post(f'/estudio/{eid}/listo/revision', data={'_csrf': tm})
with A.app.app_context():
    marcada = db.uno("SELECT e.usuario_id FROM etapas e WHERE e.flujo_id=? AND e.etapa='revision'", (fid,))
    hechas = {r['etapa'] for r in db.q("SELECT etapa FROM etapas WHERE flujo_id=?", (fid,))}
chequear('el firmante la marca y queda registrada con su usuario', marcada is not None and marcada['usuario_id'] == ids['med'])
chequear('el flujo queda informado', REGISTRO['BP'].estado(hechas, False)[0] == 'INFORMADO')
cm.post(f'/estudio/{eid}/micro', data={'_csrf': tm, 'descripcion': 'Otra', 'conclusion': 'Cambio tardío'})
with A.app.app_context():
    despues = db.uno("SELECT conclusion FROM micro WHERE flujo_id=?", (fid,))['conclusion']
    informe = informes.armar(pid)
chequear('ya revisada, la microscopía vuelve a bloquearse', despues == 'Negativo, revisado.', despues)
chequear('y el informe ya se puede armar', bool(informe['estudios']))

print('5) los flujos que ya estaban informados no se reabren (una sola vez)')
with A.app.app_context():
    def flujo_con_microscopia(numero, tipo, origen=None, ihq=False, interp=False):
        p = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, borrador, creado_por, creado_en, origen) VALUES (?,?,?,?,0,?,?,?)",
                  (numero, '2026-10-01', 'Retro', numero, admin, db.ahora(), origen))
        f = db.ex("INSERT INTO flujos (protocolo_id, tipo, creado_en) VALUES (?,?,?)", (p, tipo, db.ahora()))
        db.ex("INSERT INTO estudios (protocolo_id, flujo_id, tipo, categoria, sitio, tipo_muestra, cantidad, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?)",
              (p, f, tipo, 'Biopsias', 'Mama', 'Biopsia', '1', admin, db.ahora()))
        db.ex("INSERT INTO micro (flujo_id, solicita_ihq, solicita_revision) VALUES (?,?,1)", (f, 1 if ihq else 0))
        db.ex("INSERT INTO etapas (flujo_id, etapa, usuario_id, fecha_hora) VALUES (?,?,?,?)", (f, 'microscopia', ids['med'], '2026-10-02 09:00:00'))
        if interp:
            db.ex("INSERT INTO etapas (flujo_id, etapa, usuario_id, fecha_hora) VALUES (?,?,?,?)", (f, 'interp_ihq', ids['med'], '2026-10-09 15:30:00'))
        return f
    nativo = flujo_con_microscopia('R000001', 'BP')
    migrado = flujo_con_microscopia('R000002', 'BP', origen='anterior')
    ihq_pendiente = flujo_con_microscopia('R000003', 'BP', ihq=True)
    ihq_hecha = flujo_con_microscopia('R000004', 'BP', ihq=True, interp=True)

    from vighi.servicios import tablero as tablero_servicio
    p_tab = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, borrador, creado_por, creado_en) VALUES (?,?,?,?,0,?,?)",
                  ('R000005', '2026-10-01', 'Tablero', 'IHQ', admin, '2026-10-01 08:30:00'))
    f_tab = db.ex("INSERT INTO flujos (protocolo_id, tipo, creado_en) VALUES (?,?,?)", (p_tab, 'BP', '2026-10-01 08:30:00'))
    db.ex("INSERT INTO estudios (protocolo_id, flujo_id, tipo, categoria, sitio, tipo_muestra, cantidad, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?)",
          (p_tab, f_tab, 'BP', 'Biopsias', 'Mama', 'Biopsia', '1', admin, '2026-10-01 08:30:00'))
    db.ex("INSERT INTO micro (flujo_id, solicita_ihq, solicita_revision) VALUES (?,1,1)", (f_tab,))
    for clave, fecha in (('macroscopia', '2026-10-05 09:00:00'), ('procesamiento', '2026-10-06 09:00:00'), ('inclusion', '2026-10-06 10:00:00'),
                         ('corte', '2026-10-07 09:00:00'), ('coloreado', '2026-10-08 09:00:00'), ('microscopia', '2026-10-09 09:00:00'),
                         ('corte_ihq', '2026-10-12 09:00:00'), ('envio_ihq', '2026-10-13 09:00:00'), ('proc_ihq', '2026-10-14 09:00:00'),
                         ('interp_ihq', '2026-10-20 09:00:00')):
        db.ex("INSERT INTO etapas (flujo_id, etapa, usuario_id, fecha_hora) VALUES (?,?,?,?)", (f_tab, clave, ids['med'], fecha))
    feriados = db.feriados()
    esperado = trazabilidad.limite('BP', 'revision', '2026-10-01', feriados, False, True)
    protocolos_t, fechas_t, _ = tablero_servicio.cargar_protocolos()
    muestra_t = protocolos_t[p_tab].muestras[0]
    chequear('el tablero ve la Revisión como próxima (con la IHQ ya interpretada)', muestra_t.proxima and muestra_t.proxima[0] == 'revision', muestra_t.proxima)
    tablero_servicio.plazos(protocolos_t[p_tab], muestra_t, fechas_t, feriados, trazabilidad.datetime(2026, 10, 20, 14, 0, 0))
    chequear('el tablero calcula el vencimiento de Revisión desde la interpretación de IHQ, no desde la microscopía',
             muestra_t.vence == esperado, (muestra_t.vence, esperado))
    chequear('y por lo tanto no la marca atrasada estando en término', muestra_t.semaforo == 'on_time', muestra_t.semaforo)

    db.ex("DELETE FROM pasos_unicos WHERE clave='revision'")
    c = db._conectar()
    db.preparar_esquema(c)

    def revision_de(f):
        return db.uno("SELECT usuario_id, fecha_hora FROM etapas WHERE flujo_id=? AND etapa='revision'", (f,))
    r_nativo = revision_de(nativo)
    chequear('un flujo propio con la microscopía hecha pasa a tener la revisión hecha, con su usuario', r_nativo is not None and r_nativo['usuario_id'] == ids['med'], r_nativo)
    chequear('el migrado del sistema anterior queda pendiente de revisión', revision_de(migrado) is None)
    chequear('con IHQ sin interpretar no se completa la revisión', revision_de(ihq_pendiente) is None)
    r_ihq = revision_de(ihq_hecha)
    chequear('con IHQ interpretada sí, con la fecha de lo último hecho', r_ihq is not None and r_ihq['fecha_hora'] == '2026-10-09 15:30:00', r_ihq)
    db.ex("DELETE FROM etapas WHERE flujo_id=? AND etapa='revision'", (nativo,))
    db.preparar_esquema(c)
    chequear('es de una sola vez: al volver a arrancar no repite', revision_de(nativo) is None)
    chequear('queda registrado que se hizo', db.uno("SELECT 1 FROM pasos_unicos WHERE clave='revision'") is not None)

print('FALLAS:', ', '.join(fallas) if fallas else 'ninguna')
sys.exit(1 if fallas else 0)
