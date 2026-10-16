import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos_informe

A, db, ids, admin = datos_informe.preparar()
fallas = []


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


CABECERA = "(SELECT COALESCE(MIN(CASE WHEN x.anulado=0 THEN x.id END), MIN(x.id)) FROM estudios x WHERE x.flujo_id={t}.flujo_id)"
CONSULTAS = {
    'etapas': "SELECT p.numero, f.tipo, x.etapa, x.usuario_id, x.fecha_hora FROM etapas x JOIN flujos f ON f.id=x.flujo_id JOIN protocolos p ON p.id=f.protocolo_id ORDER BY 1, 2, 3",
    'macro': "SELECT p.numero, f.tipo, x.template, x.descripcion, x.cassettes, x.decal FROM macro x JOIN flujos f ON f.id=x.flujo_id JOIN protocolos p ON p.id=f.protocolo_id ORDER BY 1, 2",
    'micro': "SELECT p.numero, f.tipo, x.template, x.descripcion, x.conclusion, x.bethesda, x.tecnicas_especiales, x.solicita_ihq FROM micro x JOIN flujos f ON f.id=x.flujo_id JOIN protocolos p ON p.id=f.protocolo_id ORDER BY 1, 2",
    'ihq': "SELECT p.numero, f.tipo, x.marcadores, x.resultado, x.pedido_en, x.pedido_por FROM ihq x JOIN flujos f ON f.id=x.flujo_id JOIN protocolos p ON p.id=f.protocolo_id ORDER BY 1, 2",
}
COLUMNAS = {'etapas': 5, 'macro': 6, 'micro': 8, 'ihq': 6}


def foto():
    salida = {}
    for t, sql in CONSULTAS.items():
        with A.app.app_context():
            salida[t] = [tuple(r[i] for i in range(COLUMNAS[t])) for r in db.q(sql)]
    with A.app.app_context():
        salida['flujos'] = [tuple(r[i] for i in range(2)) for r in db.q("SELECT p.numero, f.tipo FROM flujos f JOIN protocolos p ON p.id=f.protocolo_id ORDER BY 1, 2")]
        salida['sin_flujo'] = db.uno("SELECT COUNT(*) AS n FROM estudios WHERE flujo_id IS NULL")['n']
    return salida


def columnas(c, tabla):
    return {r['name'] for r in c.execute(f"PRAGMA table_info({tabla})")}


def volver_al_esquema_viejo(c, con_cabecera_distinta=False):
    for t in CONSULTAS:
        c.execute(f"ALTER TABLE {t} RENAME TO {t}_nueva")
    c.execute("CREATE TABLE etapas (id INTEGER PRIMARY KEY AUTOINCREMENT, estudio_id INTEGER NOT NULL REFERENCES estudios(id), etapa VARCHAR(30) NOT NULL, "
              "usuario_id INTEGER NOT NULL REFERENCES usuarios(id), fecha_hora VARCHAR(19) NOT NULL, UNIQUE (estudio_id, etapa))")
    c.execute("CREATE TABLE macro (estudio_id INTEGER PRIMARY KEY REFERENCES estudios(id), template VARCHAR(120), descripcion TEXT, cassettes INTEGER, decal INTEGER NOT NULL DEFAULT 0)")
    c.execute("CREATE TABLE micro (estudio_id INTEGER PRIMARY KEY REFERENCES estudios(id), template VARCHAR(120), descripcion TEXT, conclusion TEXT, "
              "bethesda VARCHAR(40), tecnicas_especiales VARCHAR(200), solicita_ihq INTEGER NOT NULL DEFAULT 0)")
    c.execute("CREATE TABLE ihq (estudio_id INTEGER PRIMARY KEY REFERENCES estudios(id), marcadores TEXT, resultado TEXT, pedido_en VARCHAR(19), pedido_por INTEGER)")
    c.execute("INSERT INTO etapas (estudio_id, etapa, usuario_id, fecha_hora) SELECT e.id, n.etapa, n.usuario_id, n.fecha_hora FROM etapas_nueva n JOIN estudios e ON e.flujo_id=n.flujo_id ORDER BY n.id, e.id")
    cab = CABECERA.format(t="n")
    c.execute(f"INSERT INTO macro (estudio_id, template, descripcion, cassettes, decal) SELECT {cab}, n.template, n.descripcion, n.cassettes, n.decal FROM macro_nueva n")
    c.execute(f"INSERT INTO micro (estudio_id, template, descripcion, conclusion, bethesda, tecnicas_especiales, solicita_ihq) "
              f"SELECT {cab}, n.template, n.descripcion, n.conclusion, n.bethesda, n.tecnicas_especiales, n.solicita_ihq FROM micro_nueva n")
    c.execute(f"INSERT INTO ihq (estudio_id, marcadores, resultado, pedido_en, pedido_por) SELECT {cab}, n.marcadores, n.resultado, n.pedido_en, n.pedido_por FROM ihq_nueva n")
    if con_cabecera_distinta:
        otro = db.uno("SELECT MAX(id) AS m FROM estudios WHERE flujo_id=(SELECT flujo_id FROM estudios WHERE id=?)", (ids['mix_b1'],))['m']
        c.execute("INSERT INTO macro (estudio_id, template, descripcion, cassettes, decal) VALUES (?,?,?,?,?)", (otro, None, 'TEXTO DE OTRA MUESTRA QUE NO DEBE QUEDAR', 9, 0))
    for t in CONSULTAS:
        c.execute(f"DROP TABLE {t}_nueva")
    c.execute("UPDATE estudios SET flujo_id=NULL")
    c.execute("DELETE FROM flujos")
    c.commit()


original = foto()
chequear('hay datos para comparar', len(original['etapas']) > 5 and len(original['macro']) >= 3 and len(original['flujos']) >= 6, {k: len(v) for k, v in original.items() if isinstance(v, list)})

c = db._conectar()
with A.app.app_context():
    volver_al_esquema_viejo(c, con_cabecera_distinta=True)
chequear('la base quedó con el esquema anterior (por estudio)', all('estudio_id' in columnas(c, t) and 'flujo_id' not in columnas(c, t) for t in CONSULTAS))

db.migrar_a_flujos(c)
chequear('migrada: etapas, macro, micro e IHQ quedan por flujo', all('flujo_id' in columnas(c, t) and 'estudio_id' not in columnas(c, t) for t in CONSULTAS))
chequear('no quedan tablas *_vieja', not any(columnas(c, f'{t}_vieja') for t in CONSULTAS))
despues = foto()
for t in list(CONSULTAS) + ['flujos', 'sin_flujo']:
    chequear(f'{t}: mismos datos que antes de volver al esquema viejo', despues[t] == original[t], (original[t], despues[t]))
macro_mixto = [r for r in despues['macro'] if r[0] == 'C000106']
chequear('de varias muestras del mismo flujo queda la de la cabecera', macro_mixto and 'NO DEBE QUEDAR' not in str(macro_mixto), macro_mixto)

db.migrar_a_flujos(c)
chequear('correrla de nuevo no cambia nada', foto() == despues)

with A.app.app_context():
    volver_al_esquema_viejo(c)
c.execute("CREATE TABLE ihq_vieja (x INTEGER)")
c.commit()
try:
    db.migrar_a_flujos(c)
    fallo = False
except Exception:
    fallo = True
chequear('si algo falla a mitad de camino, la migración avisa', fallo)
chequear('y no deja nada a medias: las cuatro tablas siguen como estaban', all('estudio_id' in columnas(c, t) and 'flujo_id' not in columnas(c, t) for t in CONSULTAS))
chequear('ni tablas renombradas de más', not any(columnas(c, f'{t}_vieja') for t in ('etapas', 'macro', 'micro')))
chequear('con todas sus filas', c.execute("SELECT COUNT(*) AS n FROM etapas").fetchone()['n'] > 5 and c.execute("SELECT COUNT(*) AS n FROM macro").fetchone()['n'] >= 3)
c.execute("DROP TABLE ihq_vieja")
c.commit()
db.migrar_a_flujos(c)
chequear('sacado el obstáculo, la migración se completa con los mismos datos', foto() == original)
print('FALLAS:', fallas or 'ninguna')
