import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar

A, db, ids, admin = preparar()
import fitz
from vighi.dominio import informes
from vighi.dominio.estudios import REGISTRO, pap

fallas = []


def chequear(nombre, ok, detalle=""):
    print(("  OK   " if ok else "  FALLA"), nombre, "" if ok else detalle)
    if not ok:
        fallas.append(nombre)


c = A.app.test_client()
with c.session_transaction() as s:
    s["uid"] = admin
c.get("/")
with c.session_transaction() as s:
    csrf = s["csrf"]

print("1) opciones cargadas")
with A.app.app_context():
    cuentas = {r["tipo"]: r["n"] for r in db.q("SELECT tipo, COUNT(*) AS n FROM abreviaturas_pap GROUP BY tipo")}
    sospechosos = {r["tipo"]: r["n"] for r in db.q("SELECT tipo, COUNT(*) AS n FROM abreviaturas_pap WHERE sospechoso=1 GROUP BY tipo")}
esperadas = {"flora": 20, "aspecto": 11, "otros": 4, "pavimentosas": 44, "endocervicales": 12, "metaplasicas": 9, "endometriales": 5, "resultado": 34}
chequear("cada lista trae las opciones de southernbits", cuentas == esperadas, cuentas)
chequear("solo el resultado tiene opciones sospechosas, y son 19", sospechosos == {"resultado": 19}, sospechosos)
db.inicializar()
with A.app.app_context():
    chequear("arrancar de nuevo no duplica las opciones", db.uno("SELECT COUNT(*) AS n FROM abreviaturas_pap")["n"] == sum(esperadas.values()))
    claves = {r["abreviatura"]: r["sospechoso"] for r in db.q("SELECT abreviatura, sospechoso FROM abreviaturas_pap WHERE tipo='resultado'")}
chequear("ASC-US y CIN3 son sospechosos; NEGATIVO y NO EVALUABLE no", claves["ASCUS"] == 1 and claves["CIN3"] == 1 and claves["NEG"] == 0 and claves["NOEV"] == 0)

with A.app.app_context():
    pid = db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, creado_por, creado_en) VALUES ('C000501','2026-10-14','Prueba','Pap',?,?)", (admin, db.ahora()))
    e = db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, responsable_id, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?)",
              (pid, "PAP", "Citologías", "Ginecológica", "Vagina", "Citología exocervical", "1", ids["cito"], admin, db.ahora()))
    for clave, _, _ in REGISTRO["PAP"].flujo(0):
        if clave == "microscopia":
            break
        db.ex("INSERT INTO etapas (flujo_id, etapa, usuario_id, fecha_hora) VALUES ((SELECT flujo_id FROM estudios WHERE id=?),?,?,?)", (e, clave, admin, db.ahora()))


def fila_micro(eid):
    with A.app.app_context():
        r = db.uno("SELECT * FROM micro WHERE flujo_id=(SELECT flujo_id FROM estudios WHERE id=?)", (eid,))
        return dict(r) if r else None


def malignidad(eid):
    with A.app.app_context():
        return db.uno("SELECT malignidad FROM estudios WHERE id=?", (eid,))["malignidad"]


def guardar(**datos):
    return c.post(f"/estudio/{e}/micro", data=dict(datos, _csrf=csrf), follow_redirects=True)


print("2) el formulario")
h = c.get(f"/estudio/{e}").get_data(as_text=True)
chequear("tiene Leucocitos, Hematíes y los dos bloques", all(x in h for x in ('name="leucocitos"', 'name="hematies"', "Citología hormonal", "Citología oncológica")))
chequear("leucocitos se elige con la escala [-] [+] [++] [+++]", all(x in h for x in ("[-] No se observan", "[+] Escasa cantidad", "[++] Moderada cantidad", "[+++] Abundante cantidad")))
chequear("ocho campos con cuadro de abreviatura", h.count("data-abrev-de=") == 8, h.count("data-abrev-de="))
chequear("cada opción lleva su abreviatura (MBL = Moderada cantidad de bacilos en Flora)", 'data-abrev="MBL"' in h and 'value="Moderada cantidad de bacilos"' in h)
chequear("las 19 opciones sospechosas del resultado están marcadas", h.count('data-sospechoso="1"') == 19, h.count('data-sospechoso="1"'))
chequear("ya no pide Bethesda ni la descripción", "Resultado (Bethesda)" not in h and "Descripción microscópica" not in h)
chequear("tiene Observaciones", 'name="conclusion"' in h and "Observaciones" in h)
chequear("el JS completa la opción al escribir la abreviatura y se guarda solo", "input[data-abrev-de]" in c.get("/static/app.js").get_data(as_text=True))

print("3) regla del resultado")
chequear("sin resultado no se completa la etapa", REGISTRO["PAP"].requisito("microscopia", None, {"resultado": "", "bethesda": ""}, None) == "Falta el resultado.")
chequear("con resultado sí", REGISTRO["PAP"].requisito("microscopia", None, {"resultado": "NEGATIVO", "bethesda": ""}, None) is None)
chequear("un PAP viejo con Bethesda también", REGISTRO["PAP"].requisito("microscopia", None, {"resultado": "", "bethesda": "NILM"}, None) is None)

print("4) guardar")
valores = dict(leucocitos="Moderada cantidad", hematies="No se observan", flora="Moderada cantidad de cocos", aspecto="Hipotrófico - inflamatorio", otros="",
               pavimentosas="Con leves anomalías inflamatorias", endocervicales="Aisladas y en grupos con cambios reactivos",
               metaplasicas="Maduras e inmaduras con cambios reactivos", endometriales="No se observan", resultado="NEGATIVO. INFLAMATORIO", conclusion="Se sugiere control.")
r = guardar(**valores)
m = fila_micro(e)
chequear("guarda todos los campos", m and all(m[k] == v for k, v in valores.items()), m)
chequear("y lo muestra seleccionado al volver a abrir", 'data-abrev="AGCR" selected>' in c.get(f"/estudio/{e}").get_data(as_text=True))
r = c.post(f"/estudio/{e}/micro", data=dict(valores, flora="Abundante cantidad de cocos", _csrf=csrf, autoguardar="1"), headers={"Accept": "application/json"})
chequear("el autoguardado también guarda estos campos", r.status_code == 200 and r.get_json()["ok"] and fila_micro(e)["flora"] == "Abundante cantidad de cocos")
guardar(**dict(valores, flora="Moderada cantidad de cocos"))

print("5) sospechoso")
chequear("un resultado no sospechoso no marca nada", malignidad(e) is None, malignidad(e))
guardar(**dict(valores, resultado="SIL DE ALTO GRADO (CIN2)"))
chequear("un resultado sospechoso marca el estudio como SOSPECHOSO", malignidad(e) == "SOSPECHOSO", malignidad(e))
with A.app.app_context():
    chequear("queda en el historial", any("sospechoso" in (x["detalle"] or "") for x in db.q("SELECT detalle FROM auditoria WHERE accion='malignidad' AND protocolo_id=?", (pid,))))
guardar(**dict(valores, resultado="NEGATIVO"))
chequear("si el resultado cambia a uno no sospechoso, se quita la marca", malignidad(e) is None, malignidad(e))
with A.app.app_context():
    db.ex("UPDATE estudios SET malignidad='MALIGNO' WHERE id=?", (e,))
guardar(**dict(valores, resultado="CARCINOMA ESCAMOSO"))
chequear("una malignidad ya asignada a mano no se pisa", malignidad(e) == "MALIGNO", malignidad(e))
guardar(**dict(valores, resultado="NEGATIVO"))
chequear("ni se quita sola", malignidad(e) == "MALIGNO", malignidad(e))
with A.app.app_context():
    db.ex("UPDATE estudios SET malignidad=NULL WHERE id=?", (e,))
guardar(**valores)

print("6) informe")
with A.app.app_context():
    for etapa in ("microscopia", "revision"):
        db.ex("INSERT INTO etapas (flujo_id, etapa, usuario_id, fecha_hora) VALUES ((SELECT flujo_id FROM estudios WHERE id=?),?,?,?)", (e, etapa, admin, "2026-10-14 12:00:00"))
    d = informes.armar(pid)
s = d["estudios"][0]
chequear("el diagnóstico es el resultado", s["diagnostico"] == "NEGATIVO. INFLAMATORIO" and s["detalle"] == "", (s["diagnostico"], s["detalle"]))
chequear("tres bloques: muestra, hormonal y oncológica", [b["titulo"] for b in s["hallazgos"]] == ["", "Citología hormonal", "Citología oncológica"], [b["titulo"] for b in s["hallazgos"]])
chequear("el primero lleva la técnica, leucocitos y hematíes", s["hallazgos"][0]["filas"] == [("Técnica", pap.TECNICA), ("Leucocitos", "Moderada cantidad"), ("Hematíes", "No se observan")], s["hallazgos"][0]["filas"])
chequear("Otros no sale si está vacío", [r[0] for r in s["hallazgos"][1]["filas"]] == ["Flora", "Aspecto"], s["hallazgos"][1]["filas"])
chequear("la oncológica trae sus cuatro filas", [r[0] for r in s["hallazgos"][2]["filas"]] == ["Pavimentosas", "Endocervicales", "Metaplásicas", "Endometriales"])
chequear("las observaciones van aparte y no hay microscopía", s["observaciones"] == "Se sugiere control." and s["microscopia"] == "")
with A.app.app_context():
    pdf = informes.generar_pdf(d)
doc = fitz.open(stream=pdf, filetype="pdf")
texto = "\n".join(p.get_text() for p in doc)
chequear("el PDF tiene el diagnóstico, la técnica y las lecturas", all(x in texto for x in ("DIAGNÓSTICO", "NEGATIVO. INFLAMATORIO", "Coloración de Papanicolaou", "Leucocitos", "Moderada cantidad", "Hematíes")))
chequear("y los dos bloques con sus filas", all(x in texto for x in ("CITOLOGÍA HORMONAL", "Moderada cantidad de cocos", "Hipotrófico - inflamatorio", "CITOLOGÍA ONCOLÓGICA", "Con leves anomalías inflamatorias", "Metaplásicas")))
chequear("las observaciones salen al final", "OBSERVACIONES" in texto and "Se sugiere control." in texto)
chequear("sin las marcas [+] del formulario", "[++]" not in texto and "Otros" not in texto)
vista = c.get(f"/protocolo/{pid}/informe").get_data(as_text=True)
chequear("la vista previa muestra los bloques", "Citología oncológica" in vista and "Aisladas y en grupos con cambios reactivos" in vista and "Coloración de Papanicolaou" in vista)

print("7) PAP ya cargados con Bethesda")
h = c.get(f"/estudio/{ids['pap']}").get_data(as_text=True)
chequear("el resultado anterior sigue elegido", '<option value="NILM" selected>NILM</option>' in h, "NILM" in h)
with A.app.app_context():
    v = informes.armar(ids["p_pap"])
chequear("su informe no cambia: el Bethesda es el diagnóstico y la conclusión el detalle", v["estudios"][0]["diagnostico"] == "NILM" and v["estudios"][0]["hallazgos"] == [] and "Frotis satisfactorio" in v["estudios"][0]["detalle"])
print("FALLAS:", fallas or "ninguna")
