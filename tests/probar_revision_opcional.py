import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar

A, db, ids, admin = preparar()
from vighi.dominio.estudios import REGISTRO

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


c, csrf = cliente(ids['med'])
H = {'_csrf': csrf}


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
    return pid, eid, fid


def hechas_de(fid):
    with A.app.app_context():
        return {r['etapa'] for r in db.q("SELECT etapa FROM etapas WHERE flujo_id=?", (fid,))}


print('1) entregar directo desde Micro Informar salta la revisión')
pid1, eid1, fid1 = nuevo_bp('C000601')
h = c.get(f'/estudio/{eid1}').get_data(as_text=True)
chequear('se ofrecen las dos opciones de cierre', 'name="cierre" value="directo"' in h and 'name="cierre" value="revision"' in h, None)
chequear('todavía no se ve Revisión en el tracking (no se decidió)', 'Micro &gt; Revisar' not in h)
r = c.post(f'/estudio/{eid1}/micro', data={**H, 'descripcion': 'Cortes.', 'conclusion': 'Benigno.', 'cierre': 'directo'}, follow_redirects=True)
chequear('sin malignidad asignada no se puede entregar directo', 'asignar la malignidad' in r.get_data(as_text=True))
chequear('la microscopía no quedó marcada', 'microscopia' not in hechas_de(fid1))
c.post(f'/protocolo/{pid1}/malignidad', data={**H, 'tipo': 'BP', 'valor': 'NMA'})
c.post(f'/estudio/{eid1}/micro', data={**H, 'descripcion': 'Cortes.', 'conclusion': 'Benigno.', 'cierre': 'directo'})
hechas1 = hechas_de(fid1)
chequear('la microscopía queda marcada', 'microscopia' in hechas1)
chequear('la revisión nunca se agrega', 'revision' not in hechas1)
h = c.get(f'/estudio/{eid1}').get_data(as_text=True)
chequear('el flujo queda informado sin pasar por revisión', '>INFORMADO<' in h)
chequear('la pantalla ya no muestra un pendiente de revisión', 'Pend. Revisión' not in h and 'Micro &gt; Revisar' not in h)

print('2) enviar a revisión mantiene el paso extra, como antes')
pid2, eid2, fid2 = nuevo_bp('C000602')
c.post(f'/estudio/{eid2}/micro', data={**H, 'descripcion': 'Cortes.', 'conclusion': 'Atípico.', 'cierre': 'revision'})
hechas2 = hechas_de(fid2)
chequear('la microscopía queda marcada', 'microscopia' in hechas2)
chequear('pero la revisión queda pendiente', 'revision' not in hechas2)
chequear('el flujo todavía no está informado', REGISTRO['BP'].estado(hechas2, False)[0] == 'Pend. Revisión')
h = c.get(f'/estudio/{eid2}').get_data(as_text=True)
chequear('ahora sí se ve el paso de Revisión en el tracking', 'Micro &gt; Revisar' in h)
r = c.post(f'/estudio/{eid2}/listo/revision', data=H, follow_redirects=True)
chequear('para cerrar la revisión también hace falta la malignidad', 'asignar la malignidad' in r.get_data(as_text=True))
c.post(f'/protocolo/{pid2}/malignidad', data={**H, 'tipo': 'BP', 'valor': 'SOSPECHOSO'})
c.post(f'/estudio/{eid2}/listo/revision', data=H)
hechas2 = hechas_de(fid2)
chequear('ahora la revisión queda marcada y el flujo informado', 'revision' in hechas2 and REGISTRO['BP'].estado(hechas2, False)[0] == 'INFORMADO')

print('3) el botón genérico «Completar» (sin elegir) no salta la revisión')
pid3, eid3, fid3 = nuevo_bp('C000603')
c.post(f'/estudio/{eid3}/micro', data={**H, 'descripcion': 'Cortes.', 'conclusion': 'Benigno.'})
c.post(f'/estudio/{eid3}/listo/microscopia', data=H)
hechas3 = hechas_de(fid3)
chequear('la microscopía queda marcada', 'microscopia' in hechas3)
chequear('por defecto queda pendiente de revisión (no se entrega sola)', 'revision' not in hechas3 and REGISTRO['BP'].estado(hechas3, False)[0] == 'Pend. Revisión')

print()
print('FALLAS:', fallas if fallas else 'ninguna')
sys.exit(1 if fallas else 0)
