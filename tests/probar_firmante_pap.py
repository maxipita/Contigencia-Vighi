import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar

A, db, ids, admin = preparar()
from vighi.dominio import informes

fallas = []


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


with A.app.app_context():
    andrea = db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, debe_cambiar_clave) VALUES ('ZZAP','Andrea Paparatto','firmante',0,1,0)")
    cierre = {"usuario_id": ids["cito"]}
    p = {"firmante_id": ids["cito"]}
    pap = [{"tipo": "PAP", "responsable_id": ids["cito"]}]
    bp = [{"tipo": "BP", "responsable_id": ids["med"]}]
    u, _ = informes._firmante(p, pap, cierre)
    chequear('un protocolo solo de PAP sale a nombre de Andrea Paparatto', u["id"] == andrea, dict(u))
    u, _ = informes._firmante({"firmante_id": ids["med"]}, pap, cierre)
    chequear('aunque alguien haya pasado la firma a su nombre', u["id"] == andrea)
    u, _ = informes._firmante({"firmante_id": None}, bp, cierre)
    chequear('una biopsia sigue con su médico responsable', u["id"] == ids["med"], dict(u))
    u, _ = informes._firmante({"firmante_id": None}, pap + bp, cierre)
    chequear('con biopsia y PAP no cambia la regla de siempre', u["id"] != andrea)
print('FALLAS:', fallas or 'ninguna')
