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
        return c, {'_csrf': s['csrf']}


def nuevo_bp(numero):
    with A.app.app_context():
        pid = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, creado_por, creado_en) VALUES (?,?,?,?,?,?)",
                    (numero, '2026-10-01', 'Test', numero, admin, db.ahora()))
        fid = db.ex("INSERT INTO flujos (protocolo_id, tipo, creado_en) VALUES (?,?,?)", (pid, 'BP', db.ahora()))
        eid = db.ex("INSERT INTO estudios (protocolo_id, flujo_id, tipo, categoria, sitio, tipo_muestra, cantidad, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?)",
                    (pid, fid, 'BP', 'Biopsias', 'Mama', 'Biopsia', '1', admin, db.ahora()))
        db.ex("INSERT INTO macro (flujo_id, descripcion) VALUES (?,?)", (fid, 'Fragmento.'))
        for clave in ('macroscopia', 'procesamiento', 'inclusion', 'corte', 'coloreado'):
            db.ex("INSERT INTO etapas (flujo_id, etapa, usuario_id, fecha_hora) VALUES (?,?,?,?)", (fid, clave, admin, '2026-10-02 10:00:00'))
    return pid, eid


def firmante(pid):
    with A.app.app_context():
        return db.uno("SELECT firmante_id FROM protocolos WHERE id=?", (pid,))['firmante_id']


with A.app.app_context():
    db.ex("UPDATE usuarios SET permisos_mas='micro,informe,etapas' WHERE id=?", (ids['otro'],))
med, H_med = cliente(ids['med'])
otro, H_otro = cliente(ids['otro'])

print('1) la pantalla de microscopía no tiene Guardar ni casilla de firma')
pid, eid = nuevo_bp('C000701')
h = med.get(f'/estudio/{eid}').get_data(as_text=True)
micro = h[h.index('id="micro"'):]
micro = micro[:micro.index('</form>')]
chequear('el formulario de microscopía no tiene botón Guardar', '>Guardar<' not in micro, None)
chequear('sigue el guardado automático', 'data-autoguardar' in h and 'data-autoestado' in micro)
chequear('siguen los botones de cierre', 'name="cierre" value="directo"' in micro and 'name="cierre" value="revision"' in micro)
chequear('no hay casilla «Quiero firmar el informe yo»', 'Quiero firmar' not in h and 'firmar_yo' not in h)

print('2) quien publica el informe es el firmante')
med.post(f'/protocolo/{pid}/malignidad', data={**H_med, 'tipo': 'BP', 'valor': 'NMA'})
med.post(f'/estudio/{eid}/micro', data={**H_med, 'descripcion': 'Cortes.', 'conclusion': 'Benigno.', 'cierre': 'directo'})
chequear('firma quien lo publicó, sin tildar nada', firmante(pid) == ids['med'], firmante(pid))

print('3) enviado a revisión: firma quien la completa')
pid2, eid2 = nuevo_bp('C000702')
med.post(f'/estudio/{eid2}/micro', data={**H_med, 'descripcion': 'Cortes.', 'conclusion': 'Atípico.', 'cierre': 'revision'})
chequear('al enviar a revisión todavía no hay firmante', firmante(pid2) is None, firmante(pid2))
otro.post(f'/protocolo/{pid2}/malignidad', data={**H_otro, 'tipo': 'BP', 'valor': 'SOSPECHOSO'})
otro.post(f'/estudio/{eid2}/listo/revision', data=H_otro)
chequear('firma quien completó la revisión', firmante(pid2) == ids['otro'], firmante(pid2))

print('4) mientras el protocolo no se cierra no hay firmante')
pid3, eid3 = nuevo_bp('C000703')
chequear('un protocolo sin informar no tiene firmante', firmante(pid3) is None)

print()
print('FALLAS:', fallas if fallas else 'ninguna')
sys.exit(1 if fallas else 0)
