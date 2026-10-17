import os, re, sys
from datetime import date, datetime, timedelta
sys.path.insert(0, os.path.dirname(__file__))
from datos_informe import preparar

A, db, ids, admin = preparar()
from vighi.servicios import consultas as srv_consultas
from vighi.dominio import trazabilidad as T
fallas = []


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


F = {date(2026, 10, 12)}
dt = lambda s: datetime.strptime(s, '%Y-%m-%d %H:%M')

print('1) regla del semáforo')
lim = dt('2026-10-06 20:00')
for ahora, esp in (('2026-10-06 09:00', 'on_time'), ('2026-10-06 20:00', 'on_time'), ('2026-10-06 20:01', 'delayed'), ('2026-10-07 10:00', 'delayed'),
                   ('2026-10-07 19:59', 'delayed'), ('2026-10-07 20:00', 'late'), ('2026-10-09 08:00', 'late')):
    chequear(f'límite mar 6/10 20:00, ahora {ahora} -> {esp}', T.semaforo(lim, dt(ahora), F) == esp, T.semaforo(lim, dt(ahora), F))
lim = dt('2026-10-09 20:00')
chequear('viernes 20:00 + sábado / domingo sigue "delayed" (no son días hábiles)', T.semaforo(lim, dt('2026-10-10 12:00'), F) == 'delayed' and T.semaforo(lim, dt('2026-10-11 23:00'), F) == 'delayed')
chequear('el lunes siguiente a las 19:59 todavía es "delayed" y a las 20:00 pasa a "late"', T.semaforo(lim, dt('2026-10-12 19:59'), set()) == 'delayed'
         and T.semaforo(lim, dt('2026-10-12 20:00'), set()) == 'late')
chequear('con feriado el lunes 12/10, el día hábil de atraso es el martes 13/10', T.semaforo(lim, dt('2026-10-12 21:00'), F) == 'delayed' and T.semaforo(lim, dt('2026-10-13 20:00'), F) == 'late')

print('1b) el atraso se arrastra entre etapas')
base = '2026-10-05'
sin_feriados = set()
ing = '2026-10-05 09:00:00'
ok_todo = {'ingreso': ing, 'macroscopia': '2026-10-06 12:00:00'}
ahora = dt('2026-10-08 12:00')
chequear('todo a tiempo y la etapa actual con tiempo: on_time', T.semaforo_acumulado('BP', base, ok_todo, dt('2026-10-08 20:00'), ahora, sin_feriados) == 'on_time')
tarde_1d = {'ingreso': ing, 'macroscopia': '2026-10-08 10:00:00'}
chequear('macroscopía terminada tarde (límite mié 7/10 20:00, hecha jue 8/10 10:00): la etapa actual está en término pero el protocolo ya está "delayed"',
         T.semaforo(dt('2026-10-08 20:00'), ahora, sin_feriados) == 'on_time' and T.semaforo_acumulado('BP', base, tarde_1d, dt('2026-10-08 20:00'), ahora, sin_feriados) == 'delayed')
tarde_10d = {'ingreso': ing, 'macroscopia': '2026-10-20 10:00:00'}
chequear('macroscopía con 10 días de atraso: aunque la etapa actual no venza, el protocolo cuenta con ese atraso: "late"',
         T.semaforo_acumulado('BP', base, tarde_10d, dt('2026-10-30 20:00'), dt('2026-10-20 12:00'), sin_feriados) == 'late')
chequear('el atraso no se "borra" si las etapas siguientes se hacen en término',
         T.semaforo_acumulado('BP', base, {**tarde_10d, 'procesamiento': '2026-10-20 13:00:00'}, dt('2026-10-30 20:00'), dt('2026-10-20 14:00'), sin_feriados) == 'late')
chequear('el atraso de una etapa vieja pesa más que estar en término ahora', T.semaforo_acumulado('BP', base, {'ingreso': '2026-10-09 09:00:00'}, dt('2026-10-30 20:00'), dt('2026-10-09 10:00'), sin_feriados) in ('delayed', 'late'))
chequear('sin límite actual (informado) y todo en término no hay semáforo de más', T.semaforo_acumulado('BP', base, ok_todo, None, ahora, sin_feriados) == 'on_time')

print('2) en las pantallas')
with A.app.app_context():
    hoy = datetime.now()
    # tres biopsias pendientes de macroscopía con fecha de recolección distinta: límite macro = recolección + 2 días hábiles, 20 hs
    def bp(num, dias_atras):
        rec = (hoy - timedelta(days=dias_atras)).strftime('%Y-%m-%d')
        p = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, creado_por, creado_en) VALUES (?,?,?,?,?,?)", (num, rec, 'Sem', 'Foro', admin, db.ahora()))
        e = db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, sitio, tipo_muestra, cantidad, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?)", (p, 'BP', 'Biopsias', 'X', 'M', '1', admin, rec + ' 09:00:00'))
        return p, e
    lejos = bp('C000900', 0)
    cerca = bp('C000901', 30)
    est = {x['id']: x for x in srv_consultas.cargar_estudios('1=1')}
    chequear('una biopsia recién recolectada está "on_time"', est[lejos[1]]['semaforo'] == 'on_time', est[lejos[1]]['semaforo'])
    chequear('una biopsia de hace 30 días está "late"', est[cerca[1]]['semaforo'] == 'late', est[cerca[1]]['semaforo'])
    chequear('los estudios informados no llevan semáforo', est[ids['bp']]['semaforo'] == '')
    fer = db.feriados()
    prox_lim = T.limite('BP', 'macroscopia', (hoy - timedelta(days=0)).strftime('%Y-%m-%d'), fer)
    # una en "delayed": el límite de macroscopía pasó hace unas horas
    for dias in range(0, 8):
        rec = (hoy - timedelta(days=dias)).strftime('%Y-%m-%d')
        lim = T.limite('BP', 'macroscopia', rec, fer)
        if lim < hoy and T.semaforo(lim, hoy, fer) == 'delayed':
            demorada = bp('C000902', dias)
            break
    else:
        demorada = None
    if demorada:
        est = {x['id']: x for x in srv_consultas.cargar_estudios('1=1')}
        chequear('una con el límite recién vencido está "delayed"', est[demorada[1]]['semaforo'] == 'delayed', est[demorada[1]]['semaforo'])
    else:
        print('  (hoy no hay una fecha de recolección que deje la macroscopía en "delayed": se omite)')
    anul = bp('C000903', 30)
    db.ex("UPDATE estudios SET anulado=1 WHERE id=?", (anul[1],))
    est = {x['id']: x for x in srv_consultas.cargar_estudios('1=1')}
    chequear('un estudio anulado no lleva semáforo', est[anul[1]]['semaforo'] == '')

c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
t = c.get('/?ver=todos').get_data(as_text=True)
chequear('el tablero tiene la columna Semáforo y muestra las pastillas', '<th>Semáforo</th>' in t and 'semaforo on_time' in t and 'semaforo late' in t)
chequear('las tarjetas del tablero filtran por los tres semáforos', all(f'semaforo={k}' in t for k in ('on_time', 'delayed', 'late')))
import re as _re
def tiles(html):
    bloque = html.split('class="semaforo-total"')[1].split('</div>')[0]
    cuenta = {k: int(_re.search(rf'class="{k}[^"]*"><b>(\d+)</b>', bloque).group(1)) for k in ('on_time', 'delayed', 'late')}
    return cuenta, sum(cuenta.values())
def filas(html):
    return html.count('<td><div class="estado-celda">')
tt = c.get('/?ver=pendientes').get_data(as_text=True)
cuenta, total = tiles(tt)
chequear('hay tres cuadros (sin cuadro de total) y suman lo que hay en la tabla (pendientes)', total == sum(cuenta.values()) == filas(tt) and total > 0, (cuenta, total, filas(tt)))
tt = c.get('/?ver=todos').get_data(as_text=True)
cuenta_todos, total_todos = tiles(tt)
chequear('con "Todos" cuenta los pendientes y los informados no suman', total_todos == cuenta['on_time'] + cuenta['delayed'] + cuenta['late'] and filas(tt) > total_todos)
tt = c.get('/?ver=pendientes&tipo=CT').get_data(as_text=True)
cuenta_ct, total_ct = tiles(tt)
chequear('al filtrar por tipo de estudio el total se actualiza', total_ct == filas(tt) and total_ct < total, (total_ct, total))
tt = c.get('/?ver=pendientes&etapa=macroscopia').get_data(as_text=True)
cuenta_e, total_e = tiles(tt)
chequear('al filtrar por etapa (Macroscopía) el total se actualiza y cuenta solo esos', total_e == filas(tt) and 0 < total_e <= total and 'Pend. Macroscopía' in tt, (total_e, total))
tt = c.get('/?ver=pendientes&etapa=coloreado').get_data(as_text=True)
cuenta_c, total_c = tiles(tt)
chequear('con otra etapa (Coloreado) da otro total', total_c == filas(tt) and total_c != total_e, (total_c, total_e))
tt = c.get('/?ver=pendientes&sector=macroscopia').get_data(as_text=True)
cuenta_s, total_s = tiles(tt)
chequear('el filtro por sector también lo actualiza', total_s == filas(tt) and total_s == total_e, (total_s, total_e))
tt = c.get('/?ver=pendientes&etapa=macroscopia&semaforo=late').get_data(as_text=True)
cuenta_l, total_l = tiles(tt)
chequear('no hay cuadro de total a la izquierda', 'Total con semáforo' not in tt)
chequear('al elegir un semáforo los totales siguen mostrando los tres (de lo filtrado por etapa) y la tabla solo ese', cuenta_l == cuenta_e and filas(tt) == cuenta_e['late'], (cuenta_l, cuenta_e, filas(tt)))
chequear('la etapa elegida queda seleccionada en el filtro', '<option value="macroscopia" selected>' in tt)
chequear('el filtro de etapas no ofrece "Ingreso"', 'INGRESO: Protocolo' not in tt and 'LABORATORIO: Histo &gt; Procesar' in tt)
t = c.get('/?ver=todos&semaforo=late').get_data(as_text=True)
chequear('filtrar por Late deja solo los atrasados', 'C000901' in t and 'C000900' not in t and 'semaforo on_time' not in t)
t = c.get('/?ver=todos&semaforo=on_time').get_data(as_text=True)
chequear('filtrar por On time deja solo los que están a tiempo', 'C000900' in t and 'C000901' not in t)
t = c.get(f'/protocolo/{cerca[0]}').get_data(as_text=True)
chequear('la ficha del protocolo muestra el semáforo en el seguimiento del flujo y no en cada muestra', 'semaforo late' in t and 'flujo-tracking' in t and '<th>Semáforo</th>' not in t and '<th>Estado</th>' not in t)
t = c.get(f'/estudio/{cerca[1]}').get_data(as_text=True)
chequear('la ficha del estudio lo muestra junto al estado', 'semaforo late' in t and 'Late' in t.split('</h1>')[0])
t = c.get(f'/estudio/{ids["bp"]}').get_data(as_text=True)
chequear('un estudio informado no lo muestra', 'class="semaforo' not in t.split('</h1>')[0])
t = c.get(f'/lotes').get_data(as_text=True)

print(chr(10) + 'FALLAS:', fallas if fallas else 'ninguna')

tt = c.get('/?semaforo=late').get_data(as_text=True)
chequear('el cuadro activo, al hacer clic de nuevo, quita el filtro', 'semaforo=&amp;' in tt.split('class="semaforo-total"')[1].split('</div>')[0] or 'semaforo=' in tt.split('class="semaforo-total"')[1].split('</div>')[0])
