import os
import re
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
    return c


def nuevo(numero, tipo, responsable, etapas):
    with A.app.app_context():
        ahora = db.ahora()
        pid = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, cobertura, lugar_recoleccion, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?)",
                    (numero, ahora[:10], 'Dash', numero, 'OSDE', 'SEDE-A', admin, ahora))
        fid = db.ex("INSERT INTO flujos (protocolo_id, tipo, creado_en) VALUES (?,?,?)", (pid, tipo, ahora))
        db.ex("INSERT INTO estudios (protocolo_id, flujo_id, tipo, categoria, sitio, tipo_muestra, cantidad, responsable_id, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?)",
              (pid, fid, tipo, 'Biopsias' if tipo == 'BP' else 'Citologías', 'Mama', 'Muestra', '1', responsable, admin, ahora))
        for etapa in etapas:
            db.ex("INSERT INTO etapas (flujo_id, etapa, usuario_id, fecha_hora) VALUES (?,?,?,?)", (fid, etapa, admin, ahora))
        db.olvidar_cache()
    return pid


nuevo('C000901', 'PAP', ids['cito'], ['coloreado', 'citotecnicos'])
nuevo('C000902', 'PAP', ids['cito'], ['coloreado', 'citotecnicos'])
nuevo('C000903', 'BP', ids['med'], ['macroscopia', 'procesamiento', 'inclusion', 'corte', 'coloreado'])
nuevo('C000904', 'PAP', ids['otro'], ['coloreado', 'citotecnicos'])


def filas(h):
    return re.findall(r'<tr><td><b>([^<]+)</b>.*?</td><td>(\w+)</td>\s*<td class="num[^"]*"[^>]*>(?:<a [^>]*>)?(\d+)', h, re.S)


c = cliente(admin)
h = c.get('/dashboards?vista=citotecnicos').get_data(as_text=True)
f = filas(h)
chequear('Citotécnicos lista a las personas con sus PAP pendientes de microscopía', ('Cito Tecnica', 'PAP', '2') in f, f)
chequear('cada citotécnico aparece solo con PAP', all(t == 'PAP' for _, t, _ in f), f)
chequear('no mezcla a los patólogos con sus biopsias', not any(n == 'Diana Miserendino' for n, _, _ in f), f)
chequear('un PAP a cargo de otra persona también se lista, con su nombre', ('Otto Tester', 'PAP', '1') in f, f)
chequear('el desplegable lista a los citotécnicos y dice Citotécnico', '<select name="persona" title="Citotécnico"' in h and 'value="ZZCT"' in h and 'Citotécnico: todos' in h)
chequear('no ofrece elegir el flujo ni la actividad', 'name="tipo"' not in h and 'name="actividad"' not in h)
chequear('los números no llevan al listado del firmante', 'mf=ZZCT' not in h and 'ver listado' not in h and 'Ver todo el listado' not in h)
h = c.get('/dashboards?vista=citotecnicos&persona=ZZCT').get_data(as_text=True)
f = filas(h)
chequear('al elegir una persona queda solo ella', f == [('Cito Tecnica', 'PAP', '2')], f)
h = c.get('/dashboards?vista=citotecnicos&tipo=BP').get_data(as_text=True)
chequear('pedir otro flujo por la dirección no mezcla nada', not filas(h))

h = c.get('/dashboards?vista=patologos').get_data(as_text=True)
f = filas(h)
chequear('Patólogos ya no muestra a los citotécnicos', not any(n == 'Cito Tecnica' for n, _, _ in f), f)
chequear('ni los PAP de microscopía', not any(t == 'PAP' for _, t, _ in f), f)
chequear('sigue mostrando las biopsias de los patólogos', ('Diana Miserendino', 'BP', '1') in f, f)
chequear('el desplegable de patólogos no lista a los citotécnicos', 'value="ZZCT"' not in h and 'Patólogo: todos' in h)
chequear('Patólogos conserva su actividad y el listado del firmante', 'name="actividad"' in h and 'mf=DM' in h)

with A.app.app_context():
    db.ex("UPDATE usuarios SET permisos_mas='dashboard_citotecnicos' WHERE id=?", (ids['cito'],))
    db.olvidar_cache()
h = cliente(ids['cito']).get('/dashboards?vista=citotecnicos').get_data(as_text=True)
f = filas(h)
chequear('un citotécnico sin «Ver todos los estudios» ve solo lo suyo y se le avisa', f == [('Cito Tecnica', 'PAP', '2')] and 'los de todos los citotécnicos' in h, f)

print('FALLAS:', ', '.join(fallas) if fallas else 'ninguna')
