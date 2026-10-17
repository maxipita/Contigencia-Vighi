import html
import os
import re
import sys
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar

A, db, ids, admin = preparar()
from vighi.dominio.estudios import REGISTRO
from vighi.servicios.lotes import orden_numero
from vighi.servicios.tablero import POR_PAGINA

fallas = []


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


TOTAL, PASO = 250, 10
hoy = date.today()
with A.app.app_context():
    flujo_bp = [clave for clave, _, _ in REGISTRO['BP'].flujo(False)]
    sentencias = []
    for i in range(TOTAL):
        numero = f'PAG{i + 1:04d}'
        creado = f'2026-03-{1 + i // 60:02d} {8 + (i % 60) // 6:02d}:{(i % 6) * 10:02d}:00'
        recoleccion = '2026-01-05' if i % 3 == 0 else (hoy - timedelta(days=i % 2)).isoformat()
        sentencias.append(("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, dni, lugar_recoleccion, borrador, cargado_sistema, creado_por, creado_en) VALUES (?,?,?,?,?,?,0,?,?,?)",
                           (numero, recoleccion, f'Paginado{i % 7}', f'Caso{i}', str(40000000 + i), 'SEDE-A' if i % 2 else 'SEDE-B', 1 if i % 4 else 0, admin, creado)))
        sentencias.append(("INSERT INTO flujos (protocolo_id, tipo, creado_en) SELECT id, 'BP', ? FROM protocolos WHERE numero=?", (creado, numero)))
        sentencias.append(("INSERT INTO estudios (protocolo_id, flujo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, anulado, creado_por, creado_en) "
                           "SELECT p.id, f.id, 'BP', 'Biopsias', 'Digestiva', 'Estómago', 'Biopsia', '1', ?, ?, ? FROM protocolos p JOIN flujos f ON f.protocolo_id=p.id AND f.tipo='BP' WHERE p.numero=?",
                           (1 if i % 25 == 24 else 0, admin, creado, numero)))
        if i % PASO == 0:
            for clave in flujo_bp:
                sentencias.append(("INSERT INTO etapas (flujo_id, etapa, usuario_id, fecha_hora) SELECT f.id, ?, ?, ? FROM flujos f JOIN protocolos p ON p.id=f.protocolo_id WHERE p.numero=? AND f.tipo='BP'",
                                   (clave, admin, '2026-03-02 09:00:00', numero)))
    for i in range(0, len(sentencias), 30):
        db.lote_ex(sentencias[i:i + 30])
    cargados = db.uno("SELECT COUNT(*) AS n FROM protocolos WHERE numero LIKE 'PAG%'")['n']

c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
c.get('/')


def pedir(url):
    return c.get(url).get_data(as_text=True)


def numeros(h):
    return [n for _, n in re.findall(r'<td><a href="/protocolo/(\d+)"><b>([^<]+)</b>', h)]


def resumen(h):
    m = re.search(r'(\d+)–(\d+) de (\d+) protocolos?', h)
    return tuple(int(x) for x in m.groups()) if m else None


def enlaces(h):
    barra = re.search(r'<nav class="paginacion".*?</nav>', h, re.S)
    return [html.unescape(x) for x in re.findall(r'href="([^"]+)"', barra.group(0))] if barra else []


def parametros(url):
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


print('1) páginas de 100 filas, en orden y sin repetir')
orden_esperado = [f'PAG{i + 1:04d}' for i in range(TOTAL) if i % 25 != 24 and i % PASO != 0]
pendientes = orden_esperado
chequear(f'se cargaron {TOTAL} protocolos de prueba y hay más de dos páginas', cargados == TOTAL and len(pendientes) > 2 * POR_PAGINA, (cargados, len(pendientes)))
chequear('los números de prueba ordenan igual como persona que como texto', sorted(orden_esperado, key=orden_numero) == orden_esperado)
chequear('el tamaño de página es de 100', POR_PAGINA == 100)
paginas = []
for n in (1, 2, 3):
    h = pedir(f'/?ver=pendientes&q=PAG&pagina={n}')
    paginas.append((numeros(h), resumen(h), h))
chequear('la primera página trae 100 filas', len(paginas[0][0]) == 100, len(paginas[0][0]))
chequear('la segunda página trae 100 filas', len(paginas[1][0]) == 100, len(paginas[1][0]))
chequear('la tercera trae el resto', len(paginas[2][0]) == len(pendientes) - 200, len(paginas[2][0]))
juntas = paginas[0][0] + paginas[1][0] + paginas[2][0]
chequear('las páginas juntas son todos los pendientes, en orden de ingreso y sin repetir', juntas == orden_esperado, (juntas[:3], orden_esperado[:3]))
chequear('el resumen dice qué filas se ven y cuántas hay en total',
         paginas[0][1] == (1, 100, len(pendientes)) and paginas[1][1] == (101, 200, len(pendientes)) and paginas[2][1] == (201, len(pendientes), len(pendientes)), [p[1] for p in paginas])
chequear('sin número de página se ve la primera', numeros(pedir('/?ver=pendientes&q=PAG')) == paginas[0][0])
chequear('el cuerpo de la página no trae más filas que la página', pedir('/?ver=pendientes&q=PAG&pagina=2').count('<tr>') <= POR_PAGINA + 1)

print('2) páginas fuera de rango o mal escritas')
ultima = (len(pendientes) + POR_PAGINA - 1) // POR_PAGINA
for texto, esperado in (('999', ultima), ('0', 1), ('-3', 1), ('abc', 1), ('', 1), ('1.5', 1), ('99999999999999999999999', 1), ('²', 1)):
    r = c.get(f'/?ver=pendientes&q=PAG&pagina={texto}')
    h = r.get_data(as_text=True)
    filas_esperadas = orden_esperado[(esperado - 1) * POR_PAGINA:esperado * POR_PAGINA]
    chequear(f'pagina={texto!r} responde 200 y muestra la página {esperado}', r.status_code == 200 and numeros(h) == filas_esperadas, r.status_code)

print('3) los conteos son de todo el conjunto, no de la página')
sems = []
for n in (1, 2, 3):
    h = paginas[n - 1][2]
    sems.append(re.findall(r'<b>(\d+)</b><span>(On time|Delayed|Late)</span>', h))
chequear('el semáforo total es el mismo en todas las páginas', sems[0] == sems[1] == sems[2], sems)
por_semaforo = {nombre: int(n) for n, nombre in sems[0]}
chequear('el semáforo total suma todos los pendientes filtrados', sum(por_semaforo.values()) == len(pendientes), (por_semaforo, len(pendientes)))
chequear('la suma del semáforo supera lo que cabe en una página (cuenta el total, no las filas visibles)', sum(por_semaforo.values()) > POR_PAGINA and len(numeros(paginas[0][2])) == POR_PAGINA, por_semaforo)
chequear('hay casos en término y casos atrasados', por_semaforo['On time'] > 0 and por_semaforo['Late'] > 0, por_semaforo)
for clave, nombre in (('on_time', 'On time'), ('late', 'Late'), ('delayed', 'Delayed')):
    h = pedir(f'/?ver=pendientes&q=PAG&semaforo={clave}')
    r = resumen(h)
    esperado = por_semaforo[nombre]
    chequear(f'filtrar por {nombre} lista exactamente los {esperado} que dice el contador', (r[2] if r else 0) == esperado and len(numeros(h)) == min(esperado, POR_PAGINA), (r, esperado))
    chequear(f'con el filtro {nombre} el semáforo total sigue contando todos', {n: int(x) for x, n in re.findall(r'<b>(\d+)</b><span>(On time|Delayed|Late)</span>', h)} == por_semaforo)

for filtro in ('ubicacion=SEDE-A', 'tipo=BP', 'desde=2026-03-01&hasta=2026-03-31', 'sector=laboratorio'):
    base = f'/?ver=pendientes&q=PAG&{filtro}'
    h = pedir(base)
    r = resumen(h)
    contadores = {n: int(x) for x, n in re.findall(r'<b>(\d+)</b><span>(On time|Delayed|Late)</span>', h)}
    if r is None:
        chequear(f'{filtro}: el semáforo suma 0 si no hay filas', sum(contadores.values()) == 0, contadores)
        continue
    chequear(f'{filtro}: los tres contadores del semáforo suman el total filtrado ({r[2]}), no las {len(numeros(h))} filas de la página', sum(contadores.values()) == r[2], (contadores, r))
    chequear(f'{filtro}: la segunda página muestra los mismos contadores', r[2] <= POR_PAGINA or {n: int(x) for x, n in re.findall(r'<b>(\d+)</b><span>(On time|Delayed|Late)</span>', pedir(base + '&pagina=2'))} == contadores)
    for clave, nombre in (('on_time', 'On time'), ('late', 'Late')):
        hs = pedir(base + f'&semaforo={clave}')
        rs = resumen(hs)
        chequear(f'{filtro}: filtrar por {nombre} da {contadores[nombre]} protocolos sobre el conjunto completo y los pagina', (rs[2] if rs else 0) == contadores[nombre] and len(numeros(hs)) == min(contadores[nombre], POR_PAGINA), (rs, contadores))

print('4) los filtros se conservan al cambiar de página')
filtros = 'ver=pendientes&q=PAG&tipo=BP&ubicacion=SEDE-A&desde=2026-01-01&hasta=2026-12-31&semaforo=late'
h = pedir('/?' + filtros)
r = resumen(h)
chequear('el filtro combinado encuentra casos', r is not None and r[2] > 0, r)
amplio = 'ver=todos&q=PAG&tipo=BP&desde=2026-01-01&hasta=2026-12-31&sector=&etapa='
h = pedir(f'/?{amplio}&pagina=2')
vinculos = enlaces(h)
chequear('la barra de páginas trae enlaces', len(vinculos) >= 3, vinculos)
conservados = all(parametros(v).get('q') == 'PAG' and parametros(v).get('tipo') == 'BP' and parametros(v).get('ver') == 'todos'
                  and parametros(v).get('desde') == '2026-01-01' and parametros(v).get('hasta') == '2026-12-31' for v in vinculos)
chequear('todos los enlaces de página conservan q, tipo, ver, desde y hasta', conservados, vinculos[:3])
paginas_vinculadas = sorted({int(parametros(v)['pagina']) for v in vinculos if 'pagina' in parametros(v)})
chequear('hay enlace a la primera, a la anterior, a la siguiente y a la última', 1 in paginas_vinculadas and 3 in paginas_vinculadas and max(paginas_vinculadas) >= 3, paginas_vinculadas)
chequear('la página actual está marcada', 'aria-current="page"' in h)
h1 = pedir(f'/?{amplio}')
chequear('en la primera página no hay "Anterior" y sí "Siguiente"', 'rel="prev"' not in h1 and 'rel="next"' in h1)
hu = pedir(f'/?{amplio}&pagina=999')
chequear('en la última página no hay "Siguiente" y sí "Anterior"', 'rel="next"' not in hu and 'rel="prev"' in hu)
for extra in ('ubicacion=SEDE-A', 'mf=ZZOT', 'sector=laboratorio'):
    h = pedir(f'/?ver=todos&q=PAG&{extra}&pagina=1')
    vinculos = enlaces(h)
    clave, valor = extra.split('=')
    chequear(f'los enlaces conservan {extra}', not vinculos or all(parametros(v).get(clave) == valor for v in vinculos), vinculos[:2])
h = pedir('/?ver=todos&q=PAG&semaforo=on_time')
vinculos = enlaces(h)
chequear('los enlaces conservan el filtro de semáforo', not vinculos or all(parametros(v).get('semaforo') == 'on_time' for v in vinculos), vinculos[:2])
h = pedir('/?ver=pendientes&q=PAG&pagina=3')
chequear('el Tablero no tiene solapas por estado', 'Pendientes (' not in h and 'class="tabs"' in h and '>BPs<' in h)
semaforo_links = re.findall(r'<div class="semaforo-total">(.*?)</div>', h, re.S)[0]
chequear('el semáforo total no arrastra la página', 'pagina=' not in semaforo_links)
chequear('filtrar con el formulario no manda la página', 'name="pagina"' not in h)

print('5) una lista corta no muestra navegación')
h = pedir('/?ver=todos&q=PAG0001')
chequear('un solo resultado: se dice cuántos hay y no hay enlaces de página', resumen(h) == (1, 1, 1) and not enlaces(h), (resumen(h), enlaces(h)))
h = pedir('/?ver=todos&q=NOEXISTE9999')
chequear('sin resultados: mensaje vacío y sin barra', 'No hay protocolos para mostrar.' in h and resumen(h) is None)

print('6) cada vista pagina por separado')
for ver in ('todos', 'informados', 'anulados', 'sin_cargar', 'mios'):
    recorrido, n = [], 1
    while True:
        h = pedir(f'/?ver={ver}&q=PAG&pagina={n}')
        filas = numeros(h)
        r = resumen(h)
        recorrido += filas
        if not r or r[1] >= r[2]:
            break
        n += 1
    chequear(f'ver={ver}: recorrer las páginas da cada protocolo una sola vez', len(recorrido) == len(set(recorrido)), len(recorrido))
h = pedir('/?ver=todos&q=PAG&pagina=1')
chequear('ver=todos trae los 250 sumando las páginas', resumen(h)[2] == TOTAL, resumen(h))
esperado_por_vista = {'informados': sum(1 for i in range(TOTAL) if i % PASO == 0), 'anulados': sum(1 for i in range(TOTAL) if i % 25 == 24),
                      'sin_cargar': sum(1 for i in range(TOTAL) if i % PASO == 0 and i % 4 == 0), 'pendientes': len(pendientes)}
for ver, n in esperado_por_vista.items():
    r = resumen(pedir(f'/?ver={ver}&q=PAG'))
    chequear(f'ver={ver}: el total paginado es {n}', r is not None and r[2] == n, r)

print()
print('FALLAS:', 'ninguna' if not fallas else fallas)
sys.exit(1 if fallas else 0)
