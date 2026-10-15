import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar
from werkzeug.datastructures import MultiDict

A, db, ids, admin = preparar()
from vighi.dominio.estudios import REGISTRO

fallas = []


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


with A.app.app_context():
    ahora = db.ahora()
    pid = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, borrador, creado_por, creado_en) VALUES ('C000950','2026-10-15','IHQ','Vacia',0,?,?)", (admin, ahora))
    eid = db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, responsable_id, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (pid, 'BP', 'Biopsias', 'Digestiva', 'Estómago', 'Biopsia', '1', ids['med'], admin, ahora))
    for clave, _, _ in REGISTRO['BP'].flujo(0):
        if clave == 'microscopia':
            break
        db.ex("INSERT INTO etapas (estudio_id, etapa, usuario_id, fecha_hora) VALUES (?,?,?,?)", (eid, clave, admin, ahora))
    db.ex("INSERT INTO macro (estudio_id, descripcion) VALUES (?, 'x')", (eid,))
    db.ex("INSERT INTO micro (estudio_id, descripcion, conclusion, solicita_ihq) VALUES (?, 'Cortes', 'Gastritis', 1)", (eid,))

c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
c.get('/')
with c.session_transaction() as s:
    csrf = s['csrf']


def post(url, datos=None):
    return c.post(url, data=MultiDict([('_csrf', csrf)] + list((datos or {}).items())), follow_redirects=True).get_data(as_text=True)


def etapa_hecha(clave):
    with A.app.app_context():
        return db.uno("SELECT 1 FROM etapas WHERE estudio_id=? AND etapa=?", (eid, clave)) is not None


print('1) IHQ pedida pero sin marcadores no avanza')
h = c.get(f'/estudio/{eid}').get_data(as_text=True)
chequear('la tarjeta IHQ está visible para cargar los marcadores', 'id="ihq" hidden' not in h and 'data-lista-ihq' in h and 'Confirmar pedido de IHQ' in h)
h = post(f'/estudio/{eid}/listo/microscopia')
chequear('no deja completar la microscopía', 'Falta confirmar el pedido de IHQ' in h and not etapa_hecha('microscopia'))
h = post(f'/estudio/{eid}/ihq/pedir', {'marcadores': ''})
chequear('no deja confirmar un pedido vacío', 'al menos un marcador' in h)
with A.app.app_context():
    micro = db.uno("SELECT solicita_ihq FROM micro WHERE estudio_id=?", (eid,))
    ihq = db.uno("SELECT pedido_en FROM ihq WHERE estudio_id=?", (eid,))
chequear('y el pedido sigue sin confirmar', micro['solicita_ihq'] == 1 and (ihq is None or not ihq['pedido_en']))

print('2) con marcadores y pedido confirmado sí')
h = post(f'/estudio/{eid}/ihq/pedir', {'marcadores': 'p53, Ki67'})
chequear('confirma el pedido', 'Pedido de IHQ confirmado (2 marcador(es))' in h)
h = post(f'/estudio/{eid}/listo/microscopia')
chequear('ahora la microscopía se puede completar', etapa_hecha('microscopia'), h[:200])
h = post(f'/estudio/{eid}/listo/corte_ihq')
chequear('y avanza el primer paso de IHQ', etapa_hecha('corte_ihq'), h[:200])

print('3) un borrador con IHQ pedida y marcadores sigue siendo borrador')
with A.app.app_context():
    pid3 = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, borrador, creado_por, creado_en) VALUES ('C000951','2026-10-15','IHQ','Borrador',0,?,?)", (admin, ahora))
    e3 = db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, responsable_id, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?)",
               (pid3, 'BP', 'Biopsias', 'Digestiva', 'Estómago', 'Biopsia', '1', ids['med'], admin, ahora))
    for clave, _, _ in REGISTRO['BP'].flujo(0):
        if clave == 'microscopia':
            break
        db.ex("INSERT INTO etapas (estudio_id, etapa, usuario_id, fecha_hora) VALUES (?,?,?,?)", (e3, clave, admin, ahora))
    db.ex("INSERT INTO micro (estudio_id, descripcion, solicita_ihq) VALUES (?, 'Cortes', 1)", (e3,))
    tareas_antes = db.uno("SELECT COUNT(*) AS n FROM tareas WHERE protocolo_id=?", (pid3,))['n']
r = c.post(f'/estudio/{e3}/ihq', data={'_csrf': csrf, 'autoguardar': '1', 'marcadores': 'CD10'}, headers={'Accept': 'application/json'})
r = c.post(f'/estudio/{e3}/ihq', data={'_csrf': csrf, 'autoguardar': '1', 'marcadores': 'CD10, CD20'}, headers={'Accept': 'application/json'})
with A.app.app_context():
    ihq3 = db.uno("SELECT marcadores, pedido_en FROM ihq WHERE estudio_id=?", (e3,))
chequear('los dos marcadores quedan guardados aunque ya hubiera uno', ihq3['marcadores'] == 'CD10, CD20' and not ihq3['pedido_en'], dict(ihq3))
h = c.get(f'/estudio/{e3}').get_data(as_text=True)
chequear('sigue ofreciendo confirmar el pedido', 'Confirmar pedido de IHQ' in h and 'name="resultado"' not in h)
h = post(f'/estudio/{e3}/ihq/pedir', {'marcadores': 'CD10, CD20'})
with A.app.app_context():
    tarea = db.uno("SELECT * FROM tareas WHERE protocolo_id=? ORDER BY id DESC", (pid3,))
    n_t = db.uno("SELECT COUNT(*) AS n FROM tareas WHERE protocolo_id=?", (pid3,))['n']
chequear('al confirmar se crea la tarea con los dos marcadores', n_t == tareas_antes + 1 and '- CD10' in tarea['descripcion'] and '- CD20' in tarea['descripcion'], tarea['descripcion'] if tarea else None)

print('4) datos anteriores que ya pasaron la microscopía quedan confirmados')
with A.app.app_context():
    pid4 = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, borrador, creado_por, creado_en) VALUES ('C000952','2026-10-15','IHQ','Anterior',0,?,?)", (admin, ahora))
    e4 = db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, responsable_id, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?)",
               (pid4, 'BP', 'Biopsias', 'Digestiva', 'Estómago', 'Biopsia', '1', ids['med'], admin, ahora))
    db.ex("INSERT INTO etapas (estudio_id, etapa, usuario_id, fecha_hora) VALUES (?,?,?,?)", (e4, 'microscopia', admin, '2026-10-01 10:00:00'))
    db.ex("INSERT INTO micro (estudio_id, descripcion, solicita_ihq) VALUES (?, 'x', 1)", (e4,))
    db.ex("INSERT INTO ihq (estudio_id, marcadores) VALUES (?, 'p53')", (e4,))
    db.preparar_esquema(db.con())
    db.con().commit()
    viejo = db.uno("SELECT pedido_en FROM ihq WHERE estudio_id=?", (e4,))
chequear('el pedido anterior queda confirmado con la fecha de la microscopía', viejo and viejo['pedido_en'] == '2026-10-01 10:00:00', dict(viejo) if viejo else None)
with A.app.app_context():
    ihq_e3 = db.uno("SELECT pedido_en FROM ihq WHERE estudio_id=?", (e3,))
chequear('y lo ya confirmado de otro modo no se toca', ihq_e3['pedido_en'] and ihq_e3['pedido_en'] != '2026-10-01 10:00:00')

print()
print('FALLAS:', 'ninguna' if not fallas else fallas)
sys.exit(1 if fallas else 0)
