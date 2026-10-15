import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from datos_informe import preparar

A, db, ids, admin = preparar()
from vighi.servicios import consultas as srv_consultas
fallas = []


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


for tipos, ihq, esperado in (({'BP'}, False, 'BP'), ({'BP', 'CT'}, False, 'BP c/ CT'), ({'CT', 'BP'}, True, 'BP c/ CT + IHQ'), ({'BP'}, True, 'BP + IHQ'),
                             ({'CT'}, False, 'CT'), ({'PAP'}, False, 'PAP'), ({'PAP', 'BP', 'CT'}, False, 'BP c/ CT y PAP'), (set(), False, '')):
    r = srv_consultas.etiqueta_flujos(tipos, ihq)
    chequear(f'{sorted(tipos)} ihq={ihq} -> "{esperado}"', r == esperado, r)

with A.app.app_context():
    f = srv_consultas.flujos_de()
    chequear('protocolo de una biopsia: "BP"', f[ids['p_bp']] == 'BP', f)
    chequear('protocolo mixto 2 BP + 1 CT: "BP c/ CT"', f[ids['p_mix']] == 'BP c/ CT', f[ids['p_mix']])
    chequear('PAP: "PAP"', f[ids['p_pap']] == 'PAP')
    db.ex("INSERT INTO micro (flujo_id, descripcion, solicita_ihq) VALUES ((SELECT flujo_id FROM estudios WHERE id=?),?,1)", (ids['pendiente'], 'x')) if not db.uno("SELECT 1 FROM micro WHERE flujo_id=(SELECT flujo_id FROM estudios WHERE id=?)", (ids['pendiente'],)) else None
    db.ex("UPDATE micro SET solicita_ihq=1 WHERE flujo_id=(SELECT flujo_id FROM estudios WHERE id=?)", (ids['mix_b1'],))
    chequear('si un BP pide IHQ: "BP c/ CT + IHQ"', srv_consultas.flujos_de([ids['p_mix']])[ids['p_mix']] == 'BP c/ CT + IHQ', srv_consultas.flujos_de([ids['p_mix']]))
    chequear('pedir uno solo no mezcla otros protocolos', list(srv_consultas.flujos_de([ids['p_mix']])) == [ids['p_mix']])
    db.ex("UPDATE estudios SET anulado=1 WHERE id=?", (ids['mix_c'],))
    chequear('si se anula la CT, queda "BP + IHQ"', srv_consultas.flujos_de([ids['p_mix']])[ids['p_mix']] == 'BP + IHQ', srv_consultas.flujos_de([ids['p_mix']]))
    db.ex("UPDATE estudios SET anulado=0 WHERE id=?", (ids['mix_c'],))

c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
pm = ids['p_mix']
t = c.get(f'/protocolo/{pm}').get_data(as_text=True)
chequear('el protocolo muestra el chip junto al número', '#C000106' in t and 'chip flujos' in t and 'BP c/ CT + IHQ' in t.split('</h1>')[0])
t = c.get(f'/estudio/{ids["mix_b1"]}').get_data(as_text=True)
chequear('la ficha del estudio lo muestra junto al protocolo', 'chip flujos' in t and 'BP c/ CT + IHQ' in t)
t = c.get('/?ver=todos').get_data(as_text=True)
chequear('el tablero lo muestra en cada fila', t.count('chip flujos') >= 3 and 'BP c/ CT + IHQ' in t)
print(chr(10) + 'FALLAS:', fallas if fallas else 'ninguna')
