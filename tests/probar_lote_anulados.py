import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar
from werkzeug.datastructures import MultiDict

A, db, ids, admin = preparar()
fallas = []


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


with A.app.app_context():
    ahora = db.ahora()
    lote = db.ex("INSERT INTO lotes (codigo, tipo_lote, fecha, numero) VALUES ('ENDO-ANU.1','ENDO','2026-10-15',1)")
    vacio = db.ex("INSERT INTO lotes (codigo, tipo_lote, fecha, numero) VALUES ('ENDO-ANU.2','ENDO','2026-10-15',2)")
    pid = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, borrador, creado_por, creado_en) VALUES ('C000777','2026-10-15','Lote','Anulados',0,?,?)", (admin, ahora))
    vivo = db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, lote_id, anulado, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,0,?,?)",
                 (pid, 'BP', 'Biopsias', 'Digestiva', 'Estómago', 'Biopsia', '1', lote, admin, ahora))
    anulado = db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, lote_id, anulado, motivo_anulacion, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,1,'Duplicado',?,?)",
                    (pid, 'BP', 'Biopsias', 'Digestiva', 'Duodeno', 'Biopsia', '1', lote, admin, ahora))
    pid2 = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, borrador, creado_por, creado_en) VALUES ('C000778','2026-10-15','Solo','Anulado',0,?,?)", (admin, ahora))
    db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, lote_id, anulado, motivo_anulacion, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,1,'Duplicado',?,?)",
          (pid2, 'BP', 'Biopsias', 'Digestiva', 'Colon', 'Biopsia', '1', vacio, admin, ahora))

c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
c.get('/')
with c.session_transaction() as s:
    csrf = s['csrf']

h = c.get(f'/lotes/{lote}').get_data(as_text=True)
chequear('el lote muestra el estudio vigente', 'Estómago' in h and 'C000777' in h)
chequear('no muestra el anulado', 'Duodeno' not in h and 'Duplicado' not in h)
chequear('cuenta solo los vigentes', '1 estudio(s)' in h)

h = c.get(f'/lotes/{vacio}').get_data(as_text=True)
chequear('un lote con solo anulados figura vacío y se puede eliminar', 'todavía no tiene estudios' in h and 'Eliminar' in h)
r = c.post(f'/lotes/{vacio}/eliminar', data=MultiDict([('_csrf', csrf)]), follow_redirects=True)
with A.app.app_context():
    existe = db.uno("SELECT 1 FROM lotes WHERE id=?", (vacio,))
    huerfano = db.uno("SELECT lote_id FROM estudios WHERE protocolo_id=?", (pid2,))
chequear('se elimina y el estudio anulado queda sin lote', existe is None and huerfano['lote_id'] is None)
r = c.post(f'/lotes/{lote}/eliminar', data=MultiDict([('_csrf', csrf)]), follow_redirects=True)
chequear('un lote con estudios vigentes no se elimina', 'Solo se puede eliminar un lote vacío' in r.get_data(as_text=True))

print()
print('FALLAS:', 'ninguna' if not fallas else fallas)
sys.exit(1 if fallas else 0)
