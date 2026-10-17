import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar

A, db, ids, admin = preparar()
from vighi.dominio import trazabilidad
from vighi.servicios import tablero
from vighi.servicios.consultas import cargar_estudios

fallas = []


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


BASE = '2026-10-05'
PASOS = ('macroscopia', 'procesamiento', 'inclusion', 'corte', 'coloreado', 'microscopia')
PASOS_IHQ = ('corte_ihq', 'envio_ihq', 'proc_ihq', 'interp_ihq')
eid = ids['pendiente']


def armar_flujo(con_ihq):
    with A.app.app_context():
        e = db.uno("SELECT flujo_id, protocolo_id FROM estudios WHERE id=?", (eid,))
        db.ex("DELETE FROM etapas WHERE flujo_id=?", (e['flujo_id'],))
        db.ex("DELETE FROM micro WHERE flujo_id=?", (e['flujo_id'],))
        db.ex("INSERT INTO micro (flujo_id, descripcion, conclusion, solicita_ihq, solicita_revision) VALUES (?,?,?,?,1)", (e['flujo_id'], 'x', 'y', 1 if con_ihq else 0))
        for clave in PASOS + (PASOS_IHQ if con_ihq else ()):
            db.ex("INSERT INTO etapas (flujo_id, etapa, usuario_id, fecha_hora) VALUES (?,?,?,?)", (e['flujo_id'], clave, ids['med'], BASE + ' 10:00:00'))
        db.ex("UPDATE protocolos SET fecha_recoleccion=? WHERE id=?", (BASE, e['protocolo_id']))
        db.olvidar_cache()
        return e['flujo_id'], e['protocolo_id']


def del_tablero(fid, pid):
    protocolos, fechas, _ = tablero.cargar_protocolos()
    p = protocolos[pid]
    m = next(m for m in p.muestras if m.flujo_id == fid)
    tablero.plazos(p, m, fechas, db.feriados(), datetime.now())
    return m


print('1) BP con IHQ pendiente de revisión: el tablero vence igual que la pantalla del estudio')
fid, pid = armar_flujo(True)
with A.app.app_context():
    estudio = cargar_estudios("e.id=?", (eid,))[0]
    m = del_tablero(fid, pid)
    correcto = trazabilidad.limite('BP', 'revision', BASE, db.feriados(), False, True)
    sin_ihq = trazabilidad.limite('BP', 'revision', BASE, db.feriados(), False, False)
chequear('la próxima etapa es la revisión', m.proxima[0] == 'revision' and estudio['proxima'][0] == 'revision', (m.proxima, estudio['proxima']))
chequear('la muestra sabe que su flujo pidió IHQ', getattr(m, 'ihq', None) is True)
chequear('el plazo con IHQ es posterior al de sin IHQ (si no, la prueba no distingue nada)', correcto > sin_ihq, (correcto, sin_ihq))
chequear('vence igual que en la pantalla del estudio', m.vence == estudio['vence'], (m.vence, estudio['vence']))
chequear('vence un día hábil después de la interpretación de la IHQ', m.vence == correcto, (m.vence, correcto))
chequear('el semáforo coincide con el de la pantalla del estudio', m.semaforo == estudio['semaforo'], (m.semaforo, estudio['semaforo']))

print('2) BP sin IHQ pendiente de revisión: no cambia')
fid, pid = armar_flujo(False)
with A.app.app_context():
    estudio = cargar_estudios("e.id=?", (eid,))[0]
    m = del_tablero(fid, pid)
    esperado = trazabilidad.limite('BP', 'revision', BASE, db.feriados(), False, False)
chequear('la muestra no tiene IHQ', getattr(m, 'ihq', None) is False)
chequear('vence igual que en la pantalla del estudio', m.vence == estudio['vence'], (m.vence, estudio['vence']))
chequear('vence un día hábil después de la microscopía', m.vence == esperado, (m.vence, esperado))

print('FALLAS:', ', '.join(fallas) if fallas else 'ninguna')
sys.exit(1 if fallas else 0)
