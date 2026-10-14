import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from datos_informe import preparar

A, db, ids, admin = preparar()
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
pid = ids['p_bp']                      # protocolo de una biopsia, ya informado


def panel():
    t = c.get(f'/protocolo/{pid}').get_data(as_text=True)
    return t, t.split('class="cols"')[0]


print('1) informe emitido y vigente')
r = c.post(f'/protocolo/{pid}/informe.pdf', data={'_csrf': tk})
with A.app.app_context():
    iid = db.uno("SELECT id, estudios FROM informes_emitidos WHERE protocolo_id=?", (pid,))
chequear('se guardan los estudios que incluyó', iid['estudios'] == str(ids['bp']), dict(iid))
t, cab = panel()
chequear('el panel dice "Informe emitido" con "Ver informe"', 'Informe emitido' in cab and 'Ver informe' in cab and 'desactualizado' not in cab)
chequear('y el PDF se puede abrir', c.get(f'/informe/{iid["id"]}.pdf').mimetype == 'application/pdf')

print('2) se agrega un estudio pendiente')
with A.app.app_context():
    nuevo = db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, sitio, tipo_muestra, cantidad, responsable_id, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?)",
                  (pid, 'CT', 'Citologías', 'Orina', 'Orina', '1', ids['med'], admin, db.ahora()))
t, cab = panel()
chequear('el panel pasa a "Informe desactualizado" y explica qué falta', 'Informe desactualizado' in cab and 'Citología' in cab and 'pendiente Coloreado' in cab, cab[-600:])
chequear('ya no ofrece "Ver informe" ni "Generar"', 'Ver informe' not in cab and 'Generar' not in cab and 'Informe emitido' not in cab)
r = c.get(f'/informe/{iid["id"]}.pdf')
chequear('el PDF anterior ya no se entrega (vuelve al protocolo con un aviso)', r.status_code == 302 and r.mimetype != 'application/pdf' and f'/protocolo/{pid}' in r.headers['Location'], (r.status_code, r.mimetype))
r = c.get(f'/informe/{iid["id"]}.pdf', follow_redirects=True)
chequear('y el aviso lo explica', 'ya no se puede entregar' in r.get_data(as_text=True))
r = c.get(f'/protocolo/{pid}/informe', follow_redirects=True)
chequear('tampoco se puede generar uno nuevo con estudios pendientes', 'Falta' in r.get_data(as_text=True) and 'Citología' in r.get_data(as_text=True))
r = c.post(f'/protocolo/{pid}/informe.pdf', data={'_csrf': tk}, follow_redirects=True)
chequear('ni forzando el POST', r.mimetype != 'application/pdf')

print('3) el estudio nuevo se informa: igual hay que regenerar (no estaba en el informe)')
with A.app.app_context():
    db.ex("INSERT INTO micro (estudio_id, descripcion, conclusion) VALUES (?,?,?)", (nuevo, 'Sin atipia.', 'Negativo.'))
    for et in ('coloreado', 'microscopia'):
        db.ex("INSERT INTO etapas (estudio_id, etapa, usuario_id, fecha_hora) VALUES (?,?,?,?)", (nuevo, et, ids['med'], '2026-10-04 10:00:00'))
t, cab = panel()
chequear('completo pero desactualizado: ofrece generar, pero no ver el viejo', 'Informe desactualizado' in cab and 'Generar de nuevo' in cab and 'Ver informe' not in cab and 'Cambiaron los estudios' in cab, cab[-500:])
chequear('el PDF viejo sigue sin entregarse', c.get(f'/informe/{iid["id"]}.pdf').status_code == 302)
r = c.post(f'/protocolo/{pid}/informe.pdf', data={'_csrf': tk})
t, cab = panel()
chequear('al generar de nuevo vuelve a estar vigente (con los dos estudios)', 'Informe emitido' in cab and 'Ver informe' in cab and 'desactualizado' not in cab)
with A.app.app_context():
    f = db.uno("SELECT id, estudios, version FROM informes_emitidos WHERE protocolo_id=?", (pid,))
chequear('queda una sola fila con los dos estudios y emisión 2', f['estudios'] == f"{ids['bp']},{nuevo}" and f['version'] == 2, dict(f))
chequear('y el PDF nuevo se abre', c.get(f'/informe/{f["id"]}.pdf').mimetype == 'application/pdf')

print('4) se anula el estudio agregado')
with A.app.app_context():
    db.ex("UPDATE estudios SET anulado=1 WHERE id=?", (nuevo,))
t, cab = panel()
chequear('cambió el conjunto de estudios: queda desactualizado de nuevo', 'Informe desactualizado' in cab and 'Ver informe' not in cab)

print('5) informes guardados antes de registrar los estudios (columna vacía)')
with A.app.app_context():
    db.ex("UPDATE informes_emitidos SET estudios=NULL WHERE protocolo_id=?", (pid,))
t, cab = panel()
chequear('se consideran vigentes si el protocolo está completo', 'Informe emitido' in cab and 'Ver informe' in cab)

print(chr(10) + 'FALLAS:', fallas if fallas else 'ninguna')
