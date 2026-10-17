import os, sys
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
with A.app.app_context():
    med = db.uno("SELECT iniciales, nombre FROM usuarios WHERE id=?", (ids['med'],))
    nums = [r['numero'] for r in db.q("SELECT p.numero FROM protocolos p JOIN estudios e ON e.protocolo_id=p.id WHERE e.responsable_id=? AND e.tipo='BP' AND p.borrador=0", (ids['med'],))]
h = c.get('/?ver=todos').get_data(as_text=True)
chequear('el tablero ofrece el filtro por médico firmante', 'name="mf"' in h and '[ médico firmante ]' in h and med['iniciales'] in h)
h = c.get(f"/?ver=todos&mf={med['iniciales']}").get_data(as_text=True)
chequear('filtrar por un firmante deja sus protocolos', bool(nums) and all(n in h for n in nums), nums)
h = c.get('/?ver=todos&mf=NOEXISTE').get_data(as_text=True)
chequear('un firmante sin casos no deja ninguno', not any(n in h for n in nums))
print('FALLAS:', fallas or 'ninguna')
