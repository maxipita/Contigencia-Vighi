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


c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
h = c.get('/').get_data(as_text=True)
barra = h[h.index('id="menuPrincipal"'):h.index('</nav>')]
titulos = re.findall(r'<a class="it[^"]*" href="[^"]*" title="([^"]+)"', barra)

print('1) orden de la barra de arriba')
esperado = ['Dashboards', 'Lotes', 'Estudios', 'Tareas', 'Congelaciones', 'Facturación']
chequear('el administrador ve los ítems en el orden de trabajo', titulos == esperado, titulos)
chequear('«Tablero» ya no aparece en el menú', 'title="Tablero"' not in barra and '>Tablero<' not in barra)
chequear('«Ingresar» y «Más» siguen al final', barra.index('Ingresar') > barra.index('title="Facturación"') and barra.index('Configuraciones') > barra.index('Ingresar'))

ingresar = barra[barra.index('Ingresar'):barra.index('Configuraciones')]
items = re.findall(r'<a class="[^"]*" href="([^"]*)" title="([^"]+)"', ingresar)
chequear('«Ingresar» reúne Nuevo protocolo, Etiquetas y Por completar', items == [('/protocolo/nuevo', 'Nuevo protocolo'), ('/etiquetas', 'Etiquetas'), ('/completar', 'Por completar')], items)
chequear('ya no hay un alta por tipo de estudio', 'Con biopsia' not in barra and 'Con PAP' not in barra and 'Con citología' not in barra)
chequear('el alta sin tipo ofrece los tres estudios', all(x in c.get('/protocolo/nuevo').get_data(as_text=True) for x in ('+ PAP', '+ Biopsia', '+ Citología')))
chequear('en «Nuevo protocolo» queda marcado ese ítem', 'class="activo" href="/protocolo/nuevo"' in c.get('/protocolo/nuevo').get_data(as_text=True))

print('2) la pantalla se llama Estudios')
chequear('título y encabezado de la consulta', '<title>Estudios' in h and '<h1>Estudios</h1>' in h, h[h.index('<title>'):h.index('<title>') + 60])
chequear('el ítem queda marcado en la consulta', re.search(r'<a class="it activo" href="/" title="Estudios"', barra) is not None)

print('3) cada uno ve los ítems que le corresponden')
with A.app.app_context():
    db.ex("UPDATE usuarios SET permisos_mas='', permisos_menos='' WHERE id=?", (ids['cito'],))
    db.olvidar_cache()
d = A.app.test_client()
with d.session_transaction() as s:
    s['uid'] = ids['cito']
h = d.get('/').get_data(as_text=True)
barra = h[h.index('id="menuPrincipal"'):h.index('</nav>')]
titulos = re.findall(r'<a class="it[^"]*" href="[^"]*" title="([^"]+)"', barra)
chequear('sin permisos de dashboards ni facturación no los ve y mantiene el orden', 'Facturación' not in titulos and titulos.index('Lotes') < titulos.index('Estudios') < titulos.index('Tareas'), titulos)

print()
print('FALLAS:', fallas if fallas else 'ninguna')
sys.exit(1 if fallas else 0)
