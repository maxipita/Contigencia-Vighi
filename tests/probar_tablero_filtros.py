import os
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
c.get('/')

BP1, PAP, BP2, BP3, CT = 'C000101', 'C000102', 'C000104', 'C000105', 'C000103'
TODOS = (BP1, PAP, BP2, BP3, CT)
with A.app.app_context():
    def flujo(numero, tipo):
        return db.uno("SELECT f.id FROM flujos f JOIN protocolos p ON p.id=f.protocolo_id WHERE p.numero=? AND f.tipo=?", (numero, tipo))['id']

    for numero, zona in ((BP1, 'Digestiva'), (BP2, 'Urológica'), (BP3, 'Dermatológica'), (PAP, 'Ginecológica')):
        db.ex("UPDATE estudios SET subcategoria=? WHERE protocolo_id=(SELECT id FROM protocolos WHERE numero=?)", (zona, numero))
    db.ex("UPDATE protocolos SET plan='PLAN 210' WHERE numero=?", (BP1,))
    db.ex("UPDATE estudios SET malignidad='MALIGNO' WHERE protocolo_id=(SELECT id FROM protocolos WHERE numero=?)", (BP1,))
    db.ex("UPDATE estudios SET malignidad='NMA' WHERE protocolo_id=(SELECT id FROM protocolos WHERE numero=?)", (BP2,))
    f1, f2 = flujo(BP1, 'BP'), flujo(BP2, 'BP')
    db.ex("DELETE FROM etapas WHERE flujo_id IN (?, ?) AND etapa='microscopia'", (f1, f2))
    db.ex("INSERT INTO etapas (flujo_id, etapa, usuario_id, fecha_hora) VALUES (?, 'microscopia', ?, '2026-10-10 10:00:00')", (f1, admin))
    db.ex("DELETE FROM micro WHERE flujo_id=?", (f2,))
    db.ex("INSERT INTO micro (flujo_id, conclusion) VALUES (?, 'Adenocarcinoma acinar de próstata')", (f2,))
    db.ex("INSERT INTO lotes (codigo, tipo_lote, fecha, numero) VALUES ('FILTRO-1010.1', 'FILTRO', '2026-10-10', 1)")
    lote = db.uno("SELECT id FROM lotes WHERE codigo='FILTRO-1010.1'")['id']
    db.ex("UPDATE estudios SET lote_id=? WHERE protocolo_id=(SELECT id FROM protocolos WHERE numero=?)", (lote, BP3))


def ver(q):
    h = c.get('/?ver=todos&' + q).get_data(as_text=True)
    return h, {n for n in TODOS if n in h}


h, vistos = ver('')
chequear('la pantalla ofrece todos los filtros del sistema anterior',
         all(f'name="{k}"' in h for k in ('dia', 'mes', 'anio', 'ubicacion', 'lote', 'etapa', 'medico', 'mf', 'cobertura', 'plan', 'biopsia', 'zona', 'diagnostico', 'organo', 'kwd')))
chequear('los rótulos son los del sistema anterior', all(x in h for x in ('[ Procedencia: todas ]', '[ Lote: todos ]', '[ Actividad: todas ]', '[ cobertura ]', '[ plan ]',
                                                                       '[ Tipo de biopsia ]', '[ zona del cuerpo ]', '[ Diagnóstico: todos ]', '[ Órgano: todos ]', 'Diagnóstico contiene')))
chequear('la actividad se ofrece como sector: actividad', 'LABORATORIO: Taco &gt; Cortar' in h and 'DIAGNÓSTICOS: Micro &gt; Informar' in h and 'TRASLADOS: Cito &gt; Informar' in h)
chequear('sin filtros se ven todos y no hay «Quitar filtros»', set(TODOS) <= vistos and 'Quitar filtros' not in h, vistos)

h, vistos = ver('cobertura=OSDE')
chequear('cobertura deja solo esa', vistos == {PAP} and 'Quitar filtros' in h, vistos)
h, vistos = ver('cobertura=MEDICUS')
chequear('el plan de otra cobertura se ofrece cuando corresponde', 'value="PLAN 210"' in h)
h, vistos = ver('cobertura=GALENO')
chequear('los planes se acotan a la cobertura elegida', 'value="PLAN 210"' not in h)
h, vistos = ver('plan=PLAN+210')
chequear('el plan deja solo ese', vistos == {BP1}, vistos)
h, vistos = ver('medico=kido')
chequear('el médico solicitante se busca por parte del nombre, sin distinguir mayúsculas', vistos == {BP1}, vistos)
h, vistos = ver('medico=zzz')
chequear('un médico que no existe no deja ninguno', not vistos)

h, vistos = ver('zona=Digestiva')
chequear('zona del cuerpo', vistos == {BP1}, vistos)
chequear('la zona elegida queda marcada', '<option value="Digestiva" selected>' in h)
h, vistos = ver('organo=Próstata')
chequear('órgano', vistos == {BP2}, vistos)
h, vistos = ver('zona=Urológica')
chequear('los órganos se acotan a la zona elegida', 'value="Próstata"' in h and 'value="Esófago"' not in h)
h, vistos = ver('zona=Urológica&organo=Esófago')
chequear('zona y órgano que no coinciden no dejan ninguno', not vistos, vistos)

h, vistos = ver('biopsia=Dermatológicas')
chequear('tipo de biopsia: dermatológicas', vistos == {BP3}, vistos)
h, vistos = ver('biopsia=Ginecológicas')
chequear('tipo de biopsia: ginecológicas', vistos == {PAP}, vistos)
h, vistos = ver('biopsia=Quirúrgicas')
chequear('tipo de biopsia: quirúrgicas son las demás zonas', {BP1, BP2} <= vistos and not ({PAP, BP3} & vistos), vistos)

h, vistos = ver('diagnostico=MALIGNO')
chequear('diagnóstico: maligno', vistos == {BP1}, vistos)
h, vistos = ver('diagnostico=NMA')
chequear('diagnóstico: no maligno', vistos == {BP2}, vistos)
h, vistos = ver('diagnostico=con')
chequear('con diagnóstico: los que ya tienen la microscopía', BP1 in vistos and BP2 not in vistos, vistos)
h, vistos = ver('diagnostico=sin')
chequear('sin diagnóstico: los que todavía no', BP2 in vistos and BP1 not in vistos, vistos)

h, vistos = ver('kwd=ACINAR')
chequear('diagnóstico contiene busca en la conclusión sin distinguir mayúsculas', vistos == {BP2}, vistos)
h, vistos = ver('kwd=zzzz')
chequear('un texto que no está no deja ninguno', not vistos)
h, vistos = ver('kwd=%25')
chequear('los comodines del texto no devuelven todo ni rompen', set(TODOS) <= vistos, vistos)
h, vistos = ver("kwd='%3B+DROP+TABLE+micro%3B--")
chequear('un texto raro no rompe la consulta', not vistos and c.get('/?kwd=%27').status_code == 200)

h, vistos = ver('lote=FILTRO')
chequear('tipo de lote', vistos == {BP3}, vistos)
chequear('los tipos de lote salen de los lotes que hay', 'value="FILTRO"' in h)

h, vistos = ver('zona=Digestiva&cobertura=OSDE')
chequear('los filtros se combinan', not vistos, vistos)
h, vistos = ver('tipo=BP&biopsia=Quirúrgicas&diagnostico=con')
chequear('varios filtros a la vez', vistos == {BP1}, vistos)
paginas = c.get('/?ver=todos&zona=Digestiva&pagina=1').get_data(as_text=True)
chequear('quitar filtros vuelve a la lista completa', 'Quitar filtros' in paginas and 'href="/"' in paginas)
for basura in ('dia=0', 'mes=13', 'anio=abc', 'zona=%FF', 'diagnostico=otro', 'lote=%25', 'plan=%27'):
    chequear('un valor raro (' + basura + ') no rompe la pantalla', c.get('/?' + basura).status_code == 200)

print('FALLAS:', ', '.join(fallas) if fallas else 'ninguna')
