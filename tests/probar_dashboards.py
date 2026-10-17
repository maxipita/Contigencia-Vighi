import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar

A, db, ids, admin = preparar()
from vighi.core import permisos
from vighi.servicios import dashboards as dash

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
    return c


def tabs(h):
    return re.findall(r'href="/dashboards\?vista=(\w+)"', h)


def nuevo_bp(numero, responsable, etapas):
    with A.app.app_context():
        ahora = db.ahora()
        pid = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, cobertura, lugar_recoleccion, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?)",
                    (numero, ahora[:10], 'Dash', numero, 'OSDE', 'SEDE-A', admin, ahora))
        fid = db.ex("INSERT INTO flujos (protocolo_id, tipo, creado_en) VALUES (?,?,?)", (pid, 'BP', ahora))
        db.ex("INSERT INTO estudios (protocolo_id, flujo_id, tipo, categoria, sitio, tipo_muestra, cantidad, responsable_id, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?)",
              (pid, fid, 'BP', 'Biopsias', 'Mama', 'Biopsia', '1', responsable, admin, ahora))
        for etapa, usuario in etapas:
            db.ex("INSERT INTO etapas (flujo_id, etapa, usuario_id, fecha_hora) VALUES (?,?,?,?)", (fid, etapa, usuario, ahora))
        db.olvidar_cache()
    return pid


print('1) permisos de los dashboards')
claves = ['dashboard_' + k for k, _ in dash.VISTAS]
chequear('hay un permiso por dashboard', all(c in permisos.PERMISOS for c in claves))
chequear('«tablero_todos» es un permiso', 'tablero_todos' in permisos.PERMISOS)
perfiles = {n: p for n, (_, p) in permisos.PERFILES_INICIALES.items()}
chequear('cada sector arranca con el suyo', 'dashboard_ingreso' in perfiles['Ingreso'] and 'dashboard_laboratorio' in perfiles['Laboratorio']
         and 'dashboard_macroscopia' in perfiles['Macroscopía'] and 'dashboard_traslados' in perfiles['Traslados']
         and 'dashboard_citotecnicos' in perfiles['Citotécnico'] and 'dashboard_patologos' in perfiles['Médico firmante'])
chequear('Gerencial, Performance y el tablero completo no vienen en ningún perfil',
         all(x not in p for p in perfiles.values() for x in ('dashboard_gerencial', 'dashboard_performance', 'tablero_todos')))

pid_a = nuevo_bp('C000801', ids['med'], [('macroscopia', ids['med']), ('microscopia', ids['med'])])
pid_b = nuevo_bp('C000802', ids['otro'], [('macroscopia', ids['med']), ('microscopia', ids['otro'])])
pid_c = nuevo_bp('C000803', ids['otro'], [])
PRE_MICRO = [(e, ids['med']) for e in ('macroscopia', 'procesamiento', 'inclusion', 'corte', 'coloreado')]
pid_d = nuevo_bp('C000804', ids['med'], PRE_MICRO)
pid_e = nuevo_bp('C000805', ids['otro'], PRE_MICRO)

print('2) cada uno ve solo los dashboards que tiene')
c_adm = cliente(admin)
h = c_adm.get('/dashboards').get_data(as_text=True)
chequear('el administrador ve las ocho solapas', tabs(h) == [k for k, _ in dash.VISTAS], tabs(h))
with A.app.app_context():
    db.ex("UPDATE usuarios SET permisos_mas='dashboard_laboratorio' WHERE id=?", (ids['cito'],))
    db.olvidar_cache()
c_cito = cliente(ids['cito'])
r = c_cito.get('/dashboards')
h = r.get_data(as_text=True)
chequear('quien tiene uno solo ve solo ese', r.status_code == 200 and tabs(h) == ['laboratorio'], tabs(h))
h = c_cito.get('/dashboards?vista=gerencial').get_data(as_text=True)
chequear('pedir otro no lo deja entrar: queda en el suyo', tabs(h) == ['laboratorio'] and 'Pendientes por sector' not in h and '<th>Actividad</th>' in h)
chequear('el menú muestra «Dashboards»', 'title="Dashboards"' in h)
with A.app.app_context():
    db.ex("UPDATE usuarios SET permisos_mas='', permisos_menos='dashboard_laboratorio,dashboard_citotecnicos,dashboard_ingreso' WHERE id=?", (ids['cito'],))
    db.olvidar_cache()
c_cito = cliente(ids['cito'])
r = c_cito.get('/dashboards')
chequear('sin ningún dashboard es 403 y el menú no lo muestra', r.status_code == 403 and 'title="Dashboards"' not in c_cito.get('/').get_data(as_text=True))

print('3) todas las pantallas se arman, con y sin filtros')
for vista, _ in dash.VISTAS:
    for query in ('', '&tipo=BP&ubicacion=SEDE-A&cobertura=OSDE', '&anio=2025&mes=12', '&anio=zz&mes=99'):
        r = c_adm.get(f'/dashboards?vista={vista}{query}')
        chequear(f'{vista}{query or " (sin filtros)"} responde 200', r.status_code == 200, r.status_code)
for actividad, _ in dash.ACTIVIDADES:
    r = c_adm.get(f'/dashboards?vista=performance&actividad={actividad}&unidad=estudios')
    chequear(f'performance con la actividad {actividad}', r.status_code == 200, r.status_code)

print('4) sector: pendientes y hechas')
h = c_adm.get('/dashboards?vista=macroscopia').get_data(as_text=True)
fila = re.search(r'<td><b>Macroscopía</b></td>(.*?)</tr>', h, re.S).group(1)
numeros = [int(x) for x in re.findall(r'<td class="num[^"]*">(?:<a [^>]*>)?(\d+)(?:</a>)?</td>', fila)]
chequear('cuenta los pendientes de la actividad con su semáforo', len(numeros) == 4 and numeros[0] >= 1 and numeros[0] == sum(numeros[1:]), numeros)
chequear('no muestra lo ya hecho (eso se ve en Performance)', 'Hechas hoy' not in h and 'Hechas en el período' not in h and 'Por persona' not in h)
h = c_adm.get('/dashboards?vista=ingreso').get_data(as_text=True)
chequear('ingreso muestra los pendientes de completar y de validar', 'Protocolos por completar' in h and 'por validar' in h)

h = c_adm.get('/dashboards?vista=macroscopia').get_data(as_text=True)
chequear('los pendientes y el semáforo llevan a la lista de Estudios con ese filtro', 'href="/?etapa=macroscopia"' in h and 'href="/?etapa=macroscopia&amp;semaforo=' in h)
h = c_adm.get('/dashboards?vista=gerencial').get_data(as_text=True)
chequear('Gerencial enlaza el semáforo y los sectores', 'href="/?semaforo=late"' in h and 'href="/?sector=' in h)

print('5) performance: producción y demora de cada persona')
h = c_adm.get('/dashboards?vista=performance&actividad=macroscopia&unidad=protocolos').get_data(as_text=True)
chequear('la producción del usuario aparece con su cantidad', 'Cantidad: 4 ·' in h, None)
chequear('trae las tres tablas (mes, semana, día)', 'Usuario / Mes' in h and 'Usuario / Semana' in h and 'Usuario / Día' in h and 'Cantidad diaria' in h)
h = c_adm.get('/dashboards?vista=performance&actividad=macroscopia&unidad=protocolos&tipo=PAP').get_data(as_text=True)
chequear('el filtro de flujo saca lo que no es de ese flujo', 'Nadie registró esta actividad' in h)

print('6) Patólogos: cada médico ve lo suyo')
h = c_adm.get('/dashboards?vista=patologos').get_data(as_text=True)
chequear('el administrador ve a todos los patólogos', len(set(re.findall(r'<tr><td><b>([^<]+)</b>', h))) >= 2, h.count('<tr><td><b>'))
c_med = cliente(ids['med'])
h = c_med.get('/dashboards?vista=patologos').get_data(as_text=True)
nombres = set(re.findall(r'<tr><td><b>([^<]+)</b>', h))
chequear('el médico firmante ve solo lo suyo y se le avisa', nombres == {'Diana Miserendino'} and 'Ves solamente tus propios pendientes' in h, nombres)
with A.app.app_context():
    db.ex("UPDATE usuarios SET permisos_mas='tablero_todos' WHERE id=?", (ids['med'],))
    db.olvidar_cache()
c_med = cliente(ids['med'])
h = c_med.get('/dashboards?vista=patologos').get_data(as_text=True)
nombres = set(re.findall(r'<tr><td><b>([^<]+)</b>', h))
chequear('con «Ver todos los estudios» ve a todos', len(nombres) >= 2 and 'Ves solamente' not in h, nombres)

h = c_adm.get('/dashboards?vista=patologos').get_data(as_text=True)
chequear('muestra solo los pendientes (lo informado se ve en Performance)', 'Informados en' not in h and '<th class="num">Pendientes</th>' in h and 'Hechas' not in h)
chequear('el pendiente de cada patólogo lleva a su lista de Estudios filtrada', 'mf=DM' in h and 'etapa=microscopia' in h)
chequear('cada patólogo lleva a su listado completo en Estudios', 'href="/?mf=DM"' in h)
chequear('el desplegable «Patólogo» lista a los firmantes', '<select name="persona"' in h and '<option value="DM"' in h)
h = c_adm.get('/dashboards?vista=patologos&persona=DM').get_data(as_text=True)
nombres_dm = set(re.findall(r'<tr><td><b>([^<]+)</b>', h))
chequear('al elegir una persona solo queda ella y aparece el botón con todo su listado', nombres_dm == {'Diana Miserendino'} and 'Ver todo el listado de Diana Miserendino' in h and 'href="/?mf=DM"' in h, nombres_dm)

print('7) Estudios: el firmante ve solo sus protocolos')
with A.app.app_context():
    db.ex("UPDATE usuarios SET permisos_mas='' WHERE id=?", (ids['med'],))
    db.olvidar_cache()


def numeros_del_tablero(c, ver='todos'):
    h = c.get(f'/?ver={ver}&q=C0008').get_data(as_text=True)
    return set(re.findall(r'<td><a href="/protocolo/\d+"><b>(C0008\d+)</b>', h)), h


c_med = cliente(ids['med'])
vistos, h = numeros_del_tablero(c_med)
chequear('el firmante ve el protocolo donde él es el responsable y no el de otro', {'C000801', 'C000804'} <= vistos and not {'C000802', 'C000803', 'C000805'} & vistos, vistos)
vistos, _ = numeros_del_tablero(c_adm)
chequear('el administrador ve todos', {'C000801', 'C000802', 'C000803', 'C000804', 'C000805'} <= vistos, vistos)
resumen = re.search(r'(\d+)–(\d+) de (\d+) protocolos?', h)
chequear('los contadores y la paginación también cuentan solo lo suyo', resumen and int(resumen.group(3)) == 2, resumen and resumen.groups())
with A.app.app_context():
    db.ex("UPDATE usuarios SET permisos_mas='tablero_todos' WHERE id=?", (ids['med'],))
    db.olvidar_cache()
c_med = cliente(ids['med'])
vistos, _ = numeros_del_tablero(c_med)
chequear('con «Ver todos los estudios» ve todos', {'C000801', 'C000802', 'C000803', 'C000804', 'C000805'} <= vistos, vistos)
c_cito = cliente(ids['cito'])
with A.app.app_context():
    db.ex("UPDATE usuarios SET permisos_menos='' WHERE id=?", (ids['cito'],))
    db.olvidar_cache()
c_cito = cliente(ids['cito'])
vistos, _ = numeros_del_tablero(c_cito)
chequear('quien no es firmante sigue viendo todos', {'C000801', 'C000802', 'C000803', 'C000804', 'C000805'} <= vistos, vistos)

print()
print('FALLAS:', fallas if fallas else 'ninguna')
sys.exit(1 if fallas else 0)
