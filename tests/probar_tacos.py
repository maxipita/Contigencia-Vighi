import builtins
import json
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos_informe

A, db, ids, admin = datos_informe.preparar()
from vighi.core import fechas as core_fechas
from vighi.servicios import consultas as srv_consultas
from vighi.servicios import lotes as srv_lotes
from vighi.servicios import tacos as srv_tacos
N_SEMILLA = len(json.load(open(os.path.join(datos_informe.REPO, 'seed', 'tacos_organo.json'), encoding='utf-8')))
F = datos_informe.FALSO
from vighi.herramientas import cargar_tacos
fallas = []


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


def uno(sql, params=()):
    r = F.con.execute(sql, params).fetchone()
    return dict(r) if r else None


def cliente():
    c = A.app.test_client()
    with c.session_transaction() as s:
        s['uid'] = admin
    c.get('/')
    return c


def tok(c):
    with c.session_transaction() as s:
        return s['csrf']


c = cliente()
carpeta = tempfile.mkdtemp()
semilla, faltantes = os.path.join(carpeta, 'tacos_organo.json'), os.path.join(carpeta, 'faltantes.csv')
ALIAS = cargar_tacos.RUTA_ALIAS
cargar = lambda *args: cargar_tacos.main(list(args), semilla, faltantes, ALIAS)

print('1) carga de una planilla (CSV) sobre la semilla')
valor = lambda o, l: (uno("SELECT tacos FROM tacos_organo WHERE organo=? AND tipo_lote=?", (o, l)) or {}).get('tacos')
alias = json.load(open(ALIAS, encoding='utf-8'))
nombre_alias, destinos = next(iter(alias.items()))
planilla = os.path.join(carpeta, 'planilla.csv')


def escribir(texto):
    with open(planilla, 'w', encoding='utf-8-sig') as f:
        f.write(texto)


chequear('la base arranca con la semilla', uno("SELECT COUNT(*) AS n FROM tacos_organo")['n'] == N_SEMILLA)
F.con.execute("DELETE FROM tacos_organo WHERE organo IN ('Arteria','Cuello')")
escribir(f'organo;ENDO;NO ONCO;ONCO\nCuello;;1;6\nArteria;1;2;3\nArteria;2;1;5\n{nombre_alias};1;1;1\n')
codigo = cargar(planilla, '--si')
chequear('se carga bien', codigo == 0, codigo)
chequear('con dos filas para el mismo órgano y lote gana el mayor', valor('Arteria', 'ENDO') == 2 and valor('Arteria', 'NO ONCO') == 2 and valor('Arteria', 'ONCO') == 5)
chequear('una celda vacía no guarda nada', valor('Cuello', 'ENDO') is None and valor('Cuello', 'NO ONCO') == 1 and valor('Cuello', 'ONCO') == 6)
chequear('el nombre de la planilla llega a todos los órganos del alias', all(valor(d, 'ENDO') is not None for d in destinos), destinos)
sem = json.load(open(semilla, encoding='utf-8'))
chequear('deja la semilla ordenada', sem == sorted(sem, key=lambda x: (x['organo'], x['tipo_lote'])))
chequear('no pierde lo que ya había', valor('Mama', 'ONCO') == 10 and valor('Mama', 'NO ONCO') == 4)
chequear('sin órganos sin dato no deja lista de faltantes', not os.path.exists(faltantes))

print('2) rechazos y confirmación')
F.con.execute("DELETE FROM tacos_organo WHERE organo='Cuello'")
escribir('organo;ENDO;NO ONCO;ONCO\nArteria;1;2;3\nCuello;2;mucho;3\n')
chequear('un valor que no es número se rechaza y no guarda nada', cargar(planilla, '--si') == 1 and valor('Cuello', 'ENDO') is None)
escribir('organo;ENDO;OTRO LOTE\nCuello;2;4\n')
chequear('un tipo de lote que no existe se rechaza', cargar(planilla, '--si') == 1 and valor('Cuello', 'ENDO') is None)
builtins.input = lambda *_: 'no'
escribir('organo;ENDO;NO ONCO;ONCO\nCuello;2;2;3\n')
chequear('si no se confirma, no cambia nada', cargar(planilla) == 1 and valor('Cuello', 'ENDO') is None)
escribir('organo;ENDO;NO ONCO;ONCO\nArteria;1;2;3\n')
chequear('un órgano sin dato queda en la lista de faltantes', cargar(planilla, '--si') == 0 and os.path.exists(faltantes)
         and any(l.startswith('Cuello;') for l in open(faltantes, encoding='utf-8-sig').read().splitlines()))
escribir('organo;ENDO;NO ONCO;ONCO\nCuello;2;2;3\n')
chequear('con la confirmación guarda', cargar(planilla, '--si') == 0 and valor('Cuello', 'ONCO') == 3)
total = uno("SELECT COUNT(*) AS n FROM tacos_organo")['n']
chequear('volver a cargar el mismo valor no duplica', cargar(planilla, '--si') == 0 and uno("SELECT COUNT(*) AS n FROM tacos_organo")['n'] == total)

print('3) tacos por estudio: depende del tipo de lote')
sitio = 'Mama'
combo = dict(F.con.execute("SELECT subcategoria, sitio, tipo_muestra FROM catalogo WHERE tipo='BP' AND sitio='Mama' ORDER BY tipo_muestra LIMIT 1").fetchone())
with A.app.app_context():
    onco = srv_lotes.crear_lote('ONCO', admin)['id']
    no_onco = srv_lotes.crear_lote('NO ONCO', admin)['id']
    endo = srv_lotes.crear_lote('ENDO', admin)['id']

    def protocolo(numero, frascos, lote_id, combo=combo, borrador=0):
        p = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, borrador, creado_por, creado_en) VALUES (?,?,?,?,?,?,?)",
                  (numero, db.ahora()[:10], 'T', 'T', borrador, admin, db.ahora()))
        e = db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, responsable_id, lote_id, creado_por, creado_en) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (p, 'BP', 'Biopsias', combo['subcategoria'], combo['sitio'], combo['tipo_muestra'], str(frascos), ids['med'], lote_id, admin, db.ahora()))
        return p, e

    a1, ea1 = protocolo('C000900', 3, onco)
    a2, ea2 = protocolo('C000901', 3, no_onco)
    a3, ea3 = protocolo('C000902', 3, endo)
    est = {x['id']: x for x in srv_consultas.cargar_estudios('1=1')}
    chequear('Mama x 3 frascos en ONCO = 3 x 10 = 30', est[ea1]['tacos'] == 30, est[ea1]['tacos'])
    chequear('la misma muestra en NO ONCO = 3 x 4 = 12', est[ea2]['tacos'] == 12, est[ea2]['tacos'])
    chequear('y en ENDO = 3 x 1 = 3', est[ea3]['tacos'] == 3, est[ea3]['tacos'])
    chequear('el lote suma lo que corresponde a su tipo', srv_tacos.tacos_de_lote(onco) == (30, 0) and srv_tacos.tacos_de_lote(no_onco) == (12, 0) and srv_tacos.tacos_de_lote(endo) == (3, 0))
    F.con.execute("DELETE FROM tacos_organo WHERE organo='Arteria'")
    otro = dict(F.con.execute("SELECT subcategoria, sitio, tipo_muestra FROM catalogo WHERE tipo='BP' AND sitio='Arteria' LIMIT 1").fetchone())
    s1, es1 = protocolo('C000903', 1, onco, otro)
    chequear('un órgano sin dato para ese lote cuenta 0 y se marca sin dato', srv_tacos.tacos_de_lote(onco) == (30, 1), srv_tacos.tacos_de_lote(onco))

print('4) lote lleno de 120 tacos (ONCO, Mama x 3 frascos = 30 tacos cada protocolo)')
with A.app.app_context():
    db.ex("UPDATE lotes SET cerrado=1 WHERE tipo_lote='ONCO'")
    db.ex("DELETE FROM estudios WHERE protocolo_id=?", (s1,))
    db.ex("DELETE FROM flujos WHERE protocolo_id=?", (s1,))
    db.ex("DELETE FROM protocolos WHERE id=?", (s1,))
    lote = srv_lotes.crear_lote('ONCO', admin)['id']
    ps = [protocolo(f'C0009{n}', 3, lote)[0] for n in range(10, 14)]
    chequear('cuatro protocolos de 30 tacos llenan el lote justo: 120/120', srv_tacos.tacos_de_lote(lote)[0] == 120)
    chequear('el último que entra justo no se mueve', srv_lotes.ubicar_en_lote(ps[-1], admin) is None and srv_lotes.lote_del_protocolo(ps[-1])['id'] == lote)
    p5, _ = protocolo('C000914', 3, lote)
    r = srv_lotes.ubicar_en_lote(p5, admin)
    nuevo = srv_lotes.lote_del_protocolo(p5)
    chequear('el quinto pasa a un segundo lote ONCO del mismo día', r and nuevo['id'] != lote and nuevo['tipo_lote'] == 'ONCO' and nuevo['fecha'] == core_fechas.hoy(), r)
    chequear('el aviso: se llenó con 120/120', r['ocupados'] == 120 and r['capacidad'] == 120 and r['desde'] != r['hacia'], r)
    chequear('el primero queda en 120 y el segundo en 30', srv_tacos.tacos_de_lote(lote)[0] == 120 and srv_tacos.tacos_de_lote(nuevo['id'])[0] == 30)
    p6, _ = protocolo('C000915', 3, lote)
    srv_lotes.ubicar_en_lote(p6, admin)
    chequear('el siguiente va al segundo lote (no abre un tercero)', srv_lotes.lote_del_protocolo(p6)['id'] == nuevo['id'] and srv_tacos.tacos_de_lote(nuevo['id'])[0] == 60)
    pcm, _ = protocolo('C000916', 3, lote, {'subcategoria': combo['subcategoria'], 'sitio': 'Mama', 'tipo_muestra': combo['tipo_muestra']})
    chequear('sin bloqueos colgados', db.uno("SELECT COUNT(*) AS n FROM bloqueos")['n'] == 0)

print('5) flujo real: completar protocolos que vienen de Recepción')
with A.app.app_context():
    db.ex("UPDATE lotes SET cerrado=1 WHERE tipo_lote='ONCO'")
r = c.post('/api/etiquetas/confirmar', json={'tipo': 'bp', 'inicio': 1200, 'n': 5, 'params': {'fecha': db.ahora()[:10], 'lote': 'ONCO', 'cito': ''}}, headers={'X-CSRF': tok(c)}).get_json()
chequear('se generan 5 protocolos a completar en un lote ONCO', r.get('ok'), r)
with A.app.app_context():
    filas = [dict(x) for x in db.q("SELECT p.id, p.numero, e.id AS eid, e.lote_id FROM protocolos p JOIN estudios e ON e.protocolo_id=p.id WHERE p.numero BETWEEN 'C001200' AND 'C001204' ORDER BY p.numero")]
lote_inicial = filas[0]['lote_id']
avisos = []
for f in filas:
    marca = re.search(r'name="edicion" value="([0-9a-f]+)"', c.get(f"/protocolo/{f['id']}/editar").get_data(as_text=True)).group(1)
    datos = {'_csrf': tok(c), 'edicion': marca, 'numero': f['numero'], 'apellido': 'Paciente', 'nombre': f['numero'], 'e-0-id': str(f['eid']), 'e-0-tipo': 'BP',
             'e-0-subcategoria': combo['subcategoria'], 'e-0-sitio': 'Mama', 'e-0-tipo_muestra': combo['tipo_muestra'], 'e-0-cantidad': '3',
             'e-0-responsable_id': str(ids['med']), 'e-0-lote_id': str(lote_inicial)}
    avisos.append('se llenó' in c.post(f"/protocolo/{f['id']}/editar", data=datos, follow_redirects=True).get_data(as_text=True))
with A.app.app_context():
    lotes_finales = [db.uno("SELECT lote_id FROM estudios WHERE id=?", (f['eid'],))['lote_id'] for f in filas]
chequear('los cuatro primeros quedan en el lote (4 x 30 = 120) y el quinto pasa al siguiente', lotes_finales[:4] == [lote_inicial] * 4 and lotes_finales[4] != lote_inicial, lotes_finales)
chequear('la pantalla avisó solo con el quinto', avisos == [False, False, False, False, True], avisos)

print('6) pantallas')
t = c.get('/lotes').get_data(as_text=True)
chequear('la lista de lotes muestra el contador y "Completo"', '<th>Tacos</th>' in t and '/ 120' in t and 'Completo' in t)
t = c.get(f'/lotes/{lote_inicial}').get_data(as_text=True)
chequear('el lote muestra "120 / 120 tacos", "Completo" y la columna de tacos por estudio', '120 / 120 tacos' in t and 'Completo' in t and '<th>Tacos</th>' in t and '>30<' in t.replace(' ', ''))
t = c.get(f'/lotes/{no_onco}').get_data(as_text=True)
chequear('en otro lote, la misma muestra muestra sus propios tacos (12)', '12 / 120 tacos' in t)
t = c.get(f"/protocolo/{a1}").get_data(as_text=True)
chequear('la ficha del protocolo muestra los tacos del estudio', '<th>Tacos</th>' in t and '>30<' in t.replace(' ', ''))
with A.app.app_context():
    ct = srv_lotes.crear_lote('CT', admin)['id']
t = c.get(f'/lotes/{ct}').get_data(as_text=True)
chequear('un lote de citologías no muestra contador de tacos', 'tacos</b>' not in t)

print('7) agregar a mano a un lote que se pasa avisa pero no mueve')
with A.app.app_context():
    destino = srv_lotes.crear_lote('ONCO', admin)['id']
    for k in range(4):
        protocolo(f'C00092{k}', 3, destino)
    ajeno, _ = protocolo('C000929', 3, None)
r = c.post(f'/lotes/{destino}/agregar', data={'_csrf': tok(c), 'protocolo': 'C000929'}, follow_redirects=True).get_data(as_text=True)
with A.app.app_context():
    chequear('lo agrega pero avisa que queda en 150/120', 'queda en 150/120' in r and srv_lotes.lote_del_protocolo(ajeno)['id'] == destino, r[:0])

print('8) bases nuevas arrancan con los tacos (semilla)')
chequear('el repositorio trae seed/tacos_organo.json con las combinaciones de la semilla', len(json.load(open(os.path.join(os.path.dirname(cargar_tacos.RUTA_SEMILLA), 'tacos_organo.json'), encoding='utf-8'))) == N_SEMILLA)

print(chr(10) + 'FALLAS:', fallas if fallas else 'ninguna')
