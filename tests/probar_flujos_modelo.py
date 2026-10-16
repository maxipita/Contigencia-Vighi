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


c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
c.get('/')
with c.session_transaction() as s:
    csrf = s['csrf']


def post(url, datos=None):
    return c.post(url, data=MultiDict([('_csrf', csrf)] + list((datos or {}).items())), follow_redirects=True).get_data(as_text=True)


def uno(sql, *params):
    with A.app.app_context():
        return db.uno(sql, params)


def todos(sql, *params):
    with A.app.app_context():
        return [dict(r) for r in db.q(sql, params)]


pm = ids['p_mix']
b1, b2, c1 = ids['mix_b1'], ids['mix_b2'], ids['mix_c']

print('1) el protocolo agrupa flujos y los flujos agrupan estudios')
flujos = todos("SELECT id, tipo FROM flujos WHERE protocolo_id=? ORDER BY tipo", pm)
chequear('un protocolo con biopsias y una citología tiene dos flujos', [f['tipo'] for f in flujos] == ['BP', 'CT'], flujos)
fl = {r['id']: r['flujo_id'] for r in todos("SELECT id, flujo_id FROM estudios WHERE protocolo_id=?", pm)}
chequear('las dos biopsias comparten flujo y la citología tiene el suyo', fl[b1] == fl[b2] and fl[b1] != fl[c1], fl)
chequear('ningún estudio queda sin flujo', not todos("SELECT id FROM estudios WHERE flujo_id IS NULL"))

print('2) el seguimiento, la macro y la micro son del flujo')
etapas_bp = todos("SELECT etapa FROM etapas WHERE flujo_id=?", fl[b1])
chequear('cada etapa existe una sola vez por flujo (no una por estudio)', len(etapas_bp) == len({e['etapa'] for e in etapas_bp}) == len(REGISTRO['BP'].flujo(0)), etapas_bp)
chequear('una sola macro y una sola micro por flujo', len(todos("SELECT 1 FROM macro WHERE flujo_id=?", fl[b1])) == 1 and len(todos("SELECT 1 FROM micro WHERE flujo_id=?", fl[b1])) == 1)
with A.app.app_context():
    from vighi.servicios.consultas import cargar_estudios
    filas = {e['id']: e for e in cargar_estudios("e.protocolo_id=?", (pm,))}
chequear('las dos biopsias muestran el mismo estado', filas[b1]['estado'] == filas[b2]['estado'] and filas[b1]['proxima'] == filas[b2]['proxima'])
chequear('la citología tiene su propio tracking', filas[c1]['tipo'] == 'CT')

print('3) marcar y deshacer se hacen sobre el flujo')
pend = ids['pendiente']
with A.app.app_context():
    db.ex("INSERT INTO macro (flujo_id, descripcion) VALUES ((SELECT flujo_id FROM estudios WHERE id=?),?)", (pend, 'Fragmento pardo.'))
    db.ex("INSERT INTO tecnicas (estudio_id, numero, fragmentos, inclusion, cassettes, usuario_id, creado_en) VALUES (?,?,?,?,?,?,?)", (pend, 'A', 1, 'Reserva', 1, admin, db.ahora()))
fid = uno("SELECT flujo_id FROM estudios WHERE id=?", pend)['flujo_id']
h = post(f'/estudio/{pend}/listo/macroscopia')
n = uno("SELECT COUNT(*) AS n FROM etapas WHERE flujo_id=? AND etapa='macroscopia'", fid)['n']
chequear('marcar la etapa guarda una sola fila para el flujo', n == 1, h[:200])
h = post(f'/estudio/{pend}/deshacer')
n = uno("SELECT COUNT(*) AS n FROM etapas WHERE flujo_id=? AND etapa='macroscopia'", fid)['n']
chequear('deshacer la quita del flujo', n == 0)

print('4) un estudio nuevo se suma al flujo existente')
with A.app.app_context():
    from vighi.servicios.protocolos import crear_estudio
    nuevo = crear_estudio(pm, {'tipo': 'BP', 'categoria': 'Biopsias', 'subcategoria': 'Digestiva', 'sitio': 'Colon', 'tipo_muestra': 'Biopsia', 'cantidad': '1',
                               'citologia_hormonal': '', 'observaciones': '', 'responsable_id': ids['med'], 'tecnicas_especiales': ''}, None, admin)
chequear('el estudio nuevo entra al flujo de las otras biopsias', uno("SELECT flujo_id FROM estudios WHERE id=?", nuevo)['flujo_id'] == fl[b1])
chequear('y no se crea otro flujo', len(todos("SELECT id FROM flujos WHERE protocolo_id=? AND tipo='BP'", pm)) == 1)
with A.app.app_context():
    nuevo_f = crear_estudio(ids['p_pap'], {'tipo': 'CT', 'categoria': 'Citologías', 'subcategoria': 'Líquido', 'sitio': 'Líquido pleural', 'tipo_muestra': 'Líquido', 'cantidad': '1',
                                           'citologia_hormonal': '', 'observaciones': '', 'responsable_id': ids['med'], 'tecnicas_especiales': ''}, None, admin)
chequear('un tipo que el protocolo no tenía abre un flujo nuevo', uno("SELECT COUNT(*) AS n FROM flujos WHERE protocolo_id=?", ids['p_pap'])['n'] == 2)

print('5) anular un estudio no toca los datos del flujo')
antes = uno("SELECT descripcion FROM micro WHERE flujo_id=?", fl[b1])['descripcion']
h = post(f'/estudio/{b2}/anular', {'motivo': 'Prueba'})
chequear('el flujo conserva su micro al anular uno de sus estudios', uno("SELECT descripcion FROM micro WHERE flujo_id=?", fl[b1])['descripcion'] == antes)
chequear('el otro estudio sigue con el mismo flujo', uno("SELECT flujo_id FROM estudios WHERE id=?", b1)['flujo_id'] == fl[b1])

print('6) pantalla por flujo y ficha del protocolo')
r = c.get(f'/protocolo/{pm}/flujo/BP')
chequear('abre la pantalla del flujo de biopsias', r.status_code == 200 and 'Técnicas' in r.get_data(as_text=True))
chequear('y la del flujo de citologías', c.get(f'/protocolo/{pm}/flujo/CT').status_code == 200)
chequear('un flujo que el protocolo no tiene da 404', c.get(f'/protocolo/{pm}/flujo/PAP').status_code == 404)
h = c.get(f'/protocolo/{pm}').get_data(as_text=True)
chequear('la ficha del protocolo enlaza a cada flujo y muestra su seguimiento', f'/protocolo/{pm}/flujo/BP' in h and f'/protocolo/{pm}/flujo/CT' in h and 'flujo-tracking' in h)

print('7) en la ficha el acceso es solo por el flujo')
h = c.get(f'/protocolo/{pm}').get_data(as_text=True)
chequear('las muestras de la ficha no enlazan a su estudio', f'href="/estudio/{b1}"' not in h and f'href="/estudio/{c1}"' not in h)
chequear('no repiten estado, semáforo ni vencimiento por muestra', '<th>Estado</th>' not in h and '<th>Semáforo</th>' not in h and '<th>Vence</th>' not in h)
chequear('el seguimiento queda una vez por flujo', h.count('flujo-tracking') == 2, h.count('flujo-tracking'))
h = c.get(f"/lotes/{ids['p_mix'] and uno('SELECT lote_id FROM estudios WHERE id=?', ids['bp'])['lote_id'] or 0}").get_data(as_text=True) if uno('SELECT lote_id FROM estudios WHERE id=?', ids['bp'])['lote_id'] else ''
chequear('en un lote las muestras enlazan al flujo', not h or f'/flujo/' in h)

print()
print('FALLAS:', 'ninguna' if not fallas else fallas)
sys.exit(1 if fallas else 0)
