from vighi.core import db
from vighi.dominio import facturacion
from vighi.servicios.consultas import listas


def lista_coberturas():
    return listas().get("cobertura", [])


def limpiar_cobertura(texto):
    return " ".join((texto or "").split())[:80]


def error_cobertura(nombre):
    if not nombre:
        return "Falta el nombre de la cobertura."
    clave = db.clave_nombre(nombre)
    if any(db.clave_nombre(c) == clave for c in lista_coberturas()):
        return f"Ya existe una cobertura llamada «{nombre}» (se comparan sin tildes ni mayúsculas)."
    return None


def crear_cobertura(nombre):
    orden = (db.uno("SELECT MAX(orden) AS m FROM listas WHERE nombre='cobertura'")["m"] or 0) + 1
    db.ex("INSERT INTO listas (nombre, orden, valor) VALUES ('cobertura', ?, ?)", (orden, nombre))


def usos_de_cobertura(nombre):
    protocolos = db.uno("SELECT COUNT(*) AS n FROM protocolos WHERE cobertura=?", (nombre,))["n"]
    facturas = db.uno("SELECT COUNT(*) AS n FROM facturas WHERE cobertura=?", (nombre,))["n"]
    return protocolos, facturas


def error_eliminar(nombre):
    protocolos, facturas = usos_de_cobertura(nombre)
    if protocolos or facturas:
        return f"No se puede eliminar «{nombre}»: la usan {protocolos} protocolo(s) y {facturas} factura(s)."
    return None


def eliminar_cobertura(nombre):
    db.lote_ex([("DELETE FROM listas WHERE nombre='cobertura' AND valor=?", (nombre,)),
                ("DELETE FROM tarifario_coberturas WHERE cobertura=?", (nombre,)),
                ("DELETE FROM cobertura_pago WHERE cobertura=?", (nombre,))])


def tarifa_general():
    filas = db.q("SELECT id, nombre, iva FROM tarifarios ORDER BY id")
    return next((t for t in filas if t["nombre"] == facturacion.GENERAL), filas[0] if filas else None)


def datos_de_coberturas():
    tarifas = {t["id"]: t for t in db.q("SELECT id, nombre, iva FROM tarifarios")}
    general = tarifa_general()
    asignadas = {}
    planes = {}
    for r in db.q("SELECT cobertura, plan, tarifario_id FROM tarifario_coberturas"):
        if r["plan"]:
            planes.setdefault(r["cobertura"], []).append({"plan": r["plan"], "tarifa_id": r["tarifario_id"]})
        else:
            asignadas[r["cobertura"]] = r["tarifario_id"]
    importes = {r["tarifario_id"]: (r["n"], r["ceros"]) for r in db.q(
        "SELECT tarifario_id, COUNT(*) AS n, SUM(CASE WHEN importe=0 THEN 1 ELSE 0 END) AS ceros FROM tarifario_valores GROUP BY tarifario_id")}
    usos = {}
    for tid in list(asignadas.values()):
        usos[tid] = usos.get(tid, 0) + 1
    pago = {r["cobertura"]: r["dias"] for r in db.q("SELECT cobertura, dias FROM cobertura_pago")}
    salida = []
    for c in lista_coberturas():
        tid = asignadas.get(c)
        tarifa = tarifas.get(tid) if tid else general
        n, ceros = importes.get(tarifa["id"], (0, 0)) if tarifa else (0, 0)
        salida.append({"nombre": c, "propia": tid is not None, "tarifa": tarifa, "iva": tarifa["iva"] if tarifa else "exento", "dias": pago.get(c),
                       "planes": [{**p, "nombre": tarifas[p["tarifa_id"]]["nombre"], "importes": importes.get(p["tarifa_id"], (0, 0))[0]}
                                  for p in sorted(planes.get(c, []), key=lambda x: x["plan"])],
                       "compartida": (usos.get(tid, 0) - 1) if tid else 0,
                       "importes": n if tid else 0, "ceros": int(ceros or 0) if tid else 0})
    return salida


def dato_de_cobertura(cobertura):
    return next((d for d in datos_de_coberturas() if d["nombre"] == cobertura), None)


def nombre_unico(base):
    nombre, n = base, 2
    while db.uno("SELECT 1 FROM tarifarios WHERE nombre=?", (nombre,)):
        nombre, n = f"{base} ({n})", n + 1
    return nombre


def crear_tarifa_propia(cobertura, iva):
    nombre = nombre_unico(cobertura.upper()[:80])
    tid = db.ex("INSERT INTO tarifarios (nombre, iva) VALUES (?,?)", (nombre, iva))
    db.lote_ex([("DELETE FROM tarifario_coberturas WHERE cobertura=? AND plan=''", (cobertura,)),
                ("INSERT INTO tarifario_coberturas (cobertura, plan, tarifario_id) VALUES (?,?,?)", (cobertura, "", tid))])
    return tid, nombre


def guardar_cobertura(cobertura, iva, dias, tarifa_id):
    general = tarifa_general()
    mensajes = []
    actual = dato_de_cobertura(cobertura)
    if tarifa_id is not None and general and tarifa_id != (actual["tarifa"]["id"] if actual and actual["propia"] else general["id"]):
        if tarifa_id == general["id"]:
            db.ex("DELETE FROM tarifario_coberturas WHERE cobertura=? AND plan=''", (cobertura,))
            mensajes.append("Usa la tarifa general.")
        elif db.uno("SELECT 1 FROM tarifarios WHERE id=?", (tarifa_id,)):
            db.lote_ex([("DELETE FROM tarifario_coberturas WHERE cobertura=? AND plan=''", (cobertura,)),
                        ("INSERT INTO tarifario_coberturas (cobertura, plan, tarifario_id) VALUES (?,?,?)", (cobertura, "", tarifa_id))])
            mensajes.append("Tarifa cambiada.")
    actual = dato_de_cobertura(cobertura)
    if iva in facturacion.TIPOS_IVA and actual and iva != actual["iva"]:
        if actual["propia"]:
            db.ex("UPDATE tarifarios SET iva=? WHERE id=?", (iva, actual["tarifa"]["id"]))
            mensajes.append("IVA guardado.")
        else:
            _, nombre = crear_tarifa_propia(cobertura, iva)
            mensajes.append(f"Se creó la tarifa propia {nombre} para cambiar el IVA.")
    if dias is None:
        db.ex("DELETE FROM cobertura_pago WHERE cobertura=?", (cobertura,))
    else:
        db.lote_ex([("DELETE FROM cobertura_pago WHERE cobertura=?", (cobertura,)),
                    ("INSERT INTO cobertura_pago (cobertura, dias) VALUES (?,?)", (cobertura, dias))])
    return mensajes


def agregar_plan(cobertura, plan):
    plan = " ".join((plan or "").split())[:60].upper()
    if not plan:
        return None, "Indicá el nombre del plan."
    actual = dato_de_cobertura(cobertura)
    existente = db.uno("SELECT tarifario_id FROM tarifario_coberturas WHERE cobertura=? AND plan=?", (cobertura, plan))
    if existente:
        return None, f"La cobertura ya tiene el plan {plan}."
    iva = actual["iva"] if actual else "gravado"
    nombre = nombre_unico(f"{cobertura.upper()} · {plan}"[:80])
    tid = db.ex("INSERT INTO tarifarios (nombre, iva) VALUES (?,?)", (nombre, iva))
    db.ex("INSERT INTO tarifario_coberturas (cobertura, plan, tarifario_id) VALUES (?,?,?)", (cobertura, plan, tid))
    return tid, plan


def quitar_plan(cobertura, plan):
    usados = db.uno("SELECT COUNT(*) AS n FROM protocolos WHERE cobertura=? AND plan=?", (cobertura, plan))["n"]
    if usados:
        return f"No se puede quitar el plan {plan}: lo tienen {usados} protocolo(s)."
    db.ex("DELETE FROM tarifario_coberturas WHERE cobertura=? AND plan=?", (cobertura, plan))
    return None


def contexto_cobertura(nombre):
    if not nombre or nombre not in lista_coberturas():
        return None
    d = dato_de_cobertura(nombre)
    opciones = [{"id": d["tarifa"]["id"], "rotulo": "Tarifa de la cobertura" if d["propia"] else "Tarifa general (sin tarifa propia)", "plan": ""}]
    opciones += [{"id": p["tarifa_id"], "rotulo": f"Plan {p['plan']}", "plan": p["plan"]} for p in d["planes"]]
    return {"cob": d, "opciones": opciones, "ids": {o["id"] for o in opciones}}
