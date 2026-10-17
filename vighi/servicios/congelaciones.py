import io
import re
from datetime import date, datetime, timedelta

from flask import abort
from werkzeug.datastructures import MultiDict

from vighi.core import db, permisos
from vighi.core.config import CONGELACION_ALERTA_HORAS
from vighi.servicios.consultas import listas
from vighi.servicios.protocolos import dni_valido

TIPOS = ("GI", "QR", "PUN")
ESTADOS = {"agendada": "Agendada", "confirmada": "Confirmada", "eliminada": "Eliminada"}
ESTADOS_ALTA = {"agendada": "A confirmar", "confirmada": "Confirmada"}
ACTIVIDADES = {"alerta": "Alerta: sin confirmar", "confirmar": "A confirmar", "vincular": "Falta vincular el protocolo", "realizar": "Por realizar", "vinculada": "Vinculada", "eliminada": "Eliminada"}
PENDIENTES = ("alerta", "confirmar", "vincular", "realizar")
HORAS = [f"{h:02d}:{m}" for h in range(6, 24) for m in ("00", "30")]
HORA_DESDE, HORA_HASTA = "08:00", "20:00"
DIAS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")
MESES = ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre")
LIMITE_TABLERO = 300
CAMPOS = ("fecha", "hora", "tipo", "ubicacion", "patologo_id", "medico", "material", "cobertura", "dni", "apellido", "nombre", "observaciones")
CAMPOS_DE_AGENDA = ("fecha", "hora", "ubicacion", "patologo_id")

SQL_CONGELACIONES = """SELECT c.*, p.iniciales AS pat_iniciales, p.nombre AS pat_nombre, r.numero AS protocolo_numero
                       FROM congelaciones c LEFT JOIN usuarios p ON p.id=c.patologo_id LEFT JOIN protocolos r ON r.id=c.protocolo_id"""
SQL_PATOLOGOS = """SELECT u.id, u.iniciales, u.nombre, u.sectores, u.admin, u.permisos_mas, u.permisos_menos, p.permisos AS perfil_permisos
                   FROM usuarios u LEFT JOIN perfiles p ON p.id=u.perfil_id WHERE u.activo=1 ORDER BY u.iniciales"""
SQL_PATOLOGOS_USADOS = "SELECT DISTINCT patologo_id FROM congelaciones WHERE patologo_id IS NOT NULL"
SQL_UBICACION_EXISTE = "SELECT abreviatura FROM ubicaciones WHERE abreviatura=?"
SQL_UBICACIONES_USADAS = "SELECT DISTINCT ubicacion FROM congelaciones ORDER BY ubicacion"
SQL_MEDICOS_USADOS = "SELECT DISTINCT medico FROM congelaciones WHERE COALESCE(medico, '')<>'' ORDER BY medico"
SQL_MEDICOS_DE_UBICACION = "SELECT DISTINCT medico FROM congelaciones WHERE COALESCE(medico, '')<>'' AND ubicacion=? ORDER BY medico"
SQL_COBERTURAS_USADAS = "SELECT DISTINCT cobertura FROM congelaciones WHERE COALESCE(cobertura, '')<>'' ORDER BY cobertura"


def consultas_de_pantalla():
    return [(SQL_PATOLOGOS, ()), (SQL_PATOLOGOS_USADOS, ()), (SQL_UBICACIONES_USADAS, ()), (SQL_MEDICOS_USADOS, ()), (SQL_COBERTURAS_USADAS, ())]


def medicos_usados(ubicacion):
    filas = db.q(SQL_MEDICOS_DE_UBICACION, (ubicacion,)) if ubicacion else db.q(SQL_MEDICOS_USADOS)
    return [r["medico"] for r in filas]


def turno(hora):
    minutos = int(hora[:2]) * 60 + int(hora[3:5])
    if minutos <= 12 * 60:
        return "Mañana"
    if minutos <= 16 * 60:
        return "Mediodía"
    if minutos <= 20 * 60:
        return "Tarde"
    return "Noche"


def en_horario(fecha, hora, feriados):
    dia = date.fromisoformat(fecha)
    return dia.weekday() < 5 and dia not in feriados and HORA_DESDE <= hora < HORA_HASTA


def fecha_de(texto):
    try:
        return date.fromisoformat((texto or "").strip())
    except ValueError:
        return None


def lunes_de(dia):
    return dia - timedelta(days=dia.weekday())


def semanas_del_mes(anio, mes):
    ultimo = date(anio + (mes == 12), mes % 12 + 1, 1) - timedelta(days=1)
    lunes, semanas = lunes_de(date(anio, mes, 1)), []
    while lunes <= ultimo:
        semanas.append(lunes)
        lunes += timedelta(days=7)
    return semanas


def patologos(incluir=()):
    return [u for u in db.q(SQL_PATOLOGOS) if "firmante" in (u["sectores"] or "").split(",")
            and ("congelaciones_realiza" in permisos.efectivos(u, u["perfil_permisos"]) or u["id"] in incluir)]


def patologos_usados():
    return {r["patologo_id"] for r in db.q(SQL_PATOLOGOS_USADOS)}


def paciente_texto(c):
    return ", ".join(x for x in (c["apellido"], c["nombre"]) if x) or "Sin paciente"


def limite_alerta(ahora=None):
    return ((ahora or datetime.now()) + timedelta(hours=CONGELACION_ALERTA_HORAS)).strftime("%Y-%m-%d %H:%M")


def en_alerta(c, limite):
    return c["estado"] == "agendada" and f"{c['fecha']} {c['hora']}" < limite


def actividad_de(c, ahora, limite):
    if c["estado"] == "eliminada":
        return "eliminada"
    if c["protocolo_id"]:
        return "vinculada"
    if c["estado"] == "agendada":
        return "alerta" if en_alerta(c, limite) else "confirmar"
    return "vincular" if f"{c['fecha']} {c['hora']}" <= ahora else "realizar"


def texto_de_alerta(c, ahora):
    faltan = datetime.strptime(f"{c['fecha']} {c['hora']}", "%Y-%m-%d %H:%M") - ahora
    if faltan <= timedelta(0):
        return "Ya pasó la hora y no se confirmó"
    horas = int(faltan.total_seconds() // 3600)
    return f"Sin confirmar: faltan {horas} h" if horas else "Sin confirmar: falta menos de 1 h"


def cuando(fecha):
    dia = date.fromisoformat(fecha)
    return f"{DIAS[dia.weekday()]} {dia.day} de {MESES[dia.month - 1].lower()}"


def decorar(filas, feriados=None):
    ahora = datetime.now()
    texto_ahora, limite = ahora.strftime("%Y-%m-%d %H:%M"), limite_alerta(ahora)
    feriados = db.feriados() if feriados is None else feriados
    return [{**dict(c), "turno": turno(c["hora"]), "actividad": actividad_de(c, texto_ahora, limite), "paciente": paciente_texto(c), "cuando": cuando(c["fecha"]),
             "en_horario": en_horario(c["fecha"], c["hora"], feriados), "alerta": en_alerta(c, limite),
             "alerta_texto": texto_de_alerta(c, ahora) if en_alerta(c, limite) else ""} for c in filas]


def filtros_de(args):
    return {"ubicacion": args.get("ubicacion", "").strip(), "patologo": args.get("patologo", "").strip(), "medico": args.get("medico", "").strip(),
            "cobertura": args.get("cobertura", "").strip(),
            "vinculadas": args.get("vinculadas") if args.get("vinculadas") in ("si", "no") else "",
            "tipos": [t for t in TIPOS if t in args.getlist("tipo")],
            "horario": args.get("horario") if args.get("horario") in ("en", "fuera") else "",
            "estado": args.get("estado") if args.get("estado") in (*ESTADOS, "alerta") else ""}


def filtros_vacios():
    return filtros_de(MultiDict())


def listar(f, desde=None, hasta=None, con_eliminadas=False):
    condiciones, params = [], []
    if desde:
        condiciones.append("c.fecha>=?")
        params.append(desde)
    if hasta:
        condiciones.append("c.fecha<=?")
        params.append(hasta)
    if f["estado"] == "alerta":
        condiciones.append("c.estado='agendada' AND (c.fecha || ' ' || c.hora)<?")
        params.append(limite_alerta())
    elif not f["estado"] and not con_eliminadas:
        condiciones.append("c.estado<>'eliminada'")
    for columna, clave in (("c.ubicacion", "ubicacion"), ("c.medico", "medico"), ("c.cobertura", "cobertura")) + ((("c.estado", "estado"),) if f["estado"] != "alerta" else ()):
        if f[clave]:
            condiciones.append(f"{columna}=?")
            params.append(f[clave])
    if f["patologo"] == "sin":
        condiciones.append("c.patologo_id IS NULL")
    elif f["patologo"].isdigit():
        condiciones.append("c.patologo_id=?")
        params.append(int(f["patologo"]))
    if f["vinculadas"]:
        condiciones.append("c.protocolo_id IS " + ("NOT NULL" if f["vinculadas"] == "si" else "NULL"))
    if f["tipos"]:
        condiciones.append(f"c.tipo IN ({','.join('?' * len(f['tipos']))})")
        params += f["tipos"]
    donde = (" WHERE " + " AND ".join(condiciones)) if condiciones else ""
    filas = decorar(db.q(f"{SQL_CONGELACIONES}{donde} ORDER BY c.fecha, c.hora, c.id", params))
    if f["horario"]:
        filas = [c for c in filas if c["en_horario"] == (f["horario"] == "en")]
    return filas


def agenda_semanal(f, lunes):
    filas = listar(f, lunes.isoformat(), (lunes + timedelta(days=6)).isoformat())
    return [{"fecha": lunes + timedelta(days=i), "dia": DIAS[i], "tarjetas": [c for c in filas if c["fecha"] == (lunes + timedelta(days=i)).isoformat()]} for i in range(7)]


def firmantes_de(protocolos):
    protocolos = list(dict.fromkeys(p for p in protocolos if p))
    firmantes = {}
    for i in range(0, len(protocolos), 80):
        grupo = protocolos[i:i + 80]
        for r in db.q("SELECT e.protocolo_id, u.iniciales FROM estudios e JOIN usuarios u ON u.id=e.responsable_id WHERE e.anulado=0 AND (',' || u.sectores || ',') LIKE ? "
                      f"AND e.protocolo_id IN ({','.join('?' * len(grupo))}) ORDER BY e.id", ("%,firmante,%", *grupo)):
            firmantes.setdefault(r["protocolo_id"], r["iniciales"])
    return firmantes


def tablero(f, actividad):
    filas = listar(f, con_eliminadas=actividad in ("todas", "eliminada"))
    if actividad == "pendientes":
        filas = [c for c in filas if c["actividad"] in PENDIENTES]
    elif actividad in ACTIVIDADES:
        filas = [c for c in filas if c["actividad"] == actividad]
    orden = list(ACTIVIDADES)
    filas.sort(key=lambda c: (orden.index(c["actividad"]), c["fecha"], c["hora"], c["id"]))
    total = len(filas)
    filas = filas[:LIMITE_TABLERO]
    firmantes = firmantes_de(c["protocolo_id"] for c in filas)
    return [{**c, "mf": firmantes.get(c["protocolo_id"], "")} for c in filas], total


def dashboard(f, anio, contar):
    estados = ("confirmada",) if contar == "confirmadas" else ("confirmada", "agendada")
    por, nombres = {}, {}
    for c in listar(f, f"{anio}-01-01", f"{anio}-12-31"):
        if c["estado"] not in estados:
            continue
        clave = c["patologo_id"] or 0
        nombres[clave] = c["pat_nombre"] or c["pat_iniciales"] or "Sin asignar"
        por.setdefault(clave, [0] * 12)[int(c["fecha"][5:7]) - 1] += 1
    filas = [{"patologo": nombres[k], "meses": por[k], "total": sum(por[k])} for k in sorted(por, key=lambda k: db.clave_nombre(nombres[k]))]
    meses = [sum(x["meses"][i] for x in filas) for i in range(12)]
    return filas, meses, sum(meses)


def agenda_patologo(patologo, estado, ubicacion, pasadas):
    hoy = db.ahora()[:10]
    datos = [c for c in listar({**filtros_vacios(), "patologo": str(patologo)}) if pasadas or c["fecha"] >= hoy or c["alerta"]]
    por_estado = {k: sum(1 for c in datos if c["estado"] == k) for k in ("agendada", "confirmada")}
    base = [c for c in datos if not estado or c["estado"] == estado]
    por_ubicacion = {u: sum(1 for c in base if c["ubicacion"] == u) for u in sorted({c["ubicacion"] for c in datos}, key=db.clave_nombre)}
    return [c for c in base if not ubicacion or c["ubicacion"] == ubicacion], por_estado, por_ubicacion, len(base)


def congelacion_o_404(cid):
    return db.uno(f"{SQL_CONGELACIONES} WHERE c.id=?", (cid,)) or abort(404)


def limpiar_dni(texto):
    return re.sub(r"[.\s-]", "", texto or "")


def paciente_por_dni(dni):
    dni = limpiar_dni(dni)
    if not dni_valido(dni):
        return None
    fila = db.uno("SELECT apellido, nombre, cobertura, medico FROM protocolos WHERE dni=? AND borrador=0 ORDER BY id DESC LIMIT 1", (dni,)) \
        or db.uno("SELECT apellido, nombre, cobertura, medico FROM congelaciones WHERE dni=? ORDER BY id DESC LIMIT 1", (dni,))
    return {k: fila[k] or "" for k in ("apellido", "nombre", "cobertura", "medico")} if fila else None


def numero_o_none(valor, validos):
    if not valor:
        return None, None
    return (int(valor), None) if valor.isdigit() and int(valor) in validos else (None, "Elegí el valor de la lista.")


def validar(form, actual=None):
    d = {k: " ".join(form.get(k, "").split()) for k in ("ubicacion", "medico", "material", "apellido", "nombre", "cobertura")}
    d.update(fecha=form.get("fecha", "").strip(), hora=form.get("hora", "").strip(), tipo=form.get("tipo", "").strip(), dni=limpiar_dni(form.get("dni", "")),
             observaciones=form.get("observaciones", "").strip(), estado=form.get("estado", "agendada") if form.get("estado") in ESTADOS_ALTA else "agendada")
    permitidos = {u["id"] for u in patologos()} | ({actual["patologo_id"]} if actual and actual["patologo_id"] else set())
    d["patologo_id"], error_patologo = numero_o_none(form.get("patologo_id", ""), permitidos)
    if not fecha_de(d["fecha"]):
        return d, "Elegí la fecha de la congelación."
    if d["hora"] not in HORAS:
        return d, "Elegí la hora de la lista."
    if d["tipo"] not in TIPOS:
        return d, "Elegí el tipo de congelación."
    if not d["ubicacion"] or not db.uno(SQL_UBICACION_EXISTE, (d["ubicacion"],)):
        return d, "Elegí la ubicación de la lista que se despliega al escribir."
    if error_patologo:
        return d, "Elegí el patólogo de la lista."
    if d["cobertura"] and d["cobertura"] not in listas().get("cobertura", []):
        return d, "Elegí la cobertura de la lista."
    if d["dni"] and not (d["dni"].isdigit() and dni_valido(d["dni"])):
        return d, "El DNI tiene que ser solo números."
    if not d["apellido"]:
        return d, "Falta el apellido del paciente."
    if len(d["medico"]) > 150 or len(d["material"]) > 200 or len(d["observaciones"]) > 1000 or len(d["apellido"]) > 80 or len(d["nombre"]) > 80:
        return d, "Alguno de los textos es demasiado largo."
    return d, None


def choque(d, cid=None):
    if not d["patologo_id"] or d["estado"] == "eliminada":
        return None
    otra = db.uno("SELECT id FROM congelaciones WHERE patologo_id=? AND fecha=? AND hora=? AND estado<>'eliminada' AND id<>?", (d["patologo_id"], d["fecha"], d["hora"], cid or 0))
    return f"El patólogo ya tiene la congelación #{otra['id']} a esa hora." if otra else None


def resumen(d):
    return f"{d['fecha']} {d['hora']} {d['tipo']} en {d['ubicacion']}, {d['apellido']}"


def crear(d, yo):
    with db.bloqueo("congelaciones"):
        error = choque(d)
        if error:
            return None, error
        cid = db.ex(f"INSERT INTO congelaciones ({', '.join(CAMPOS)}, estado, creado_por, creado_en) VALUES ({','.join('?' * (len(CAMPOS) + 3))})",
                    (*(d[k] or None for k in CAMPOS), d["estado"], yo, db.ahora()))
    db.auditar(yo, None, "congelacion", f"Congelación #{cid}: alta {resumen(d)} ({ESTADOS[d['estado']]})")
    return cid, None


def editar(c, d, yo):
    reprogramada = c["estado"] == "confirmada" and any((c[k] or None) != (d[k] or None) for k in CAMPOS_DE_AGENDA)
    estado = "agendada" if reprogramada else c["estado"]
    with db.bloqueo("congelaciones"):
        error = choque({**d, "estado": estado}, c["id"])
        if error:
            return None, error
        db.ex(f"UPDATE congelaciones SET {', '.join(k + '=?' for k in CAMPOS)}, estado=?, actualizado_por=?, actualizado_en=? WHERE id=?",
              (*(d[k] or None for k in CAMPOS), estado, yo, db.ahora(), c["id"]))
    db.auditar(yo, c["protocolo_id"], "congelacion", f"Congelación #{c['id']}: edición {resumen(d)}" + (" (reprogramada: vuelve a A confirmar)" if reprogramada else ""))
    return reprogramada, None


TRANSICIONES = {"confirmar": ("agendada", "confirmada"), "eliminar": (("agendada", "confirmada"), "eliminada"), "restaurar": ("eliminada", "agendada")}
VERBOS = {"confirmar": "confirmada", "eliminar": "eliminada", "restaurar": "restaurada (vuelve a Agendada)"}


def cambiar_estado(c, accion, yo):
    desde, hasta = TRANSICIONES[accion]
    if c["estado"] not in ((desde,) if isinstance(desde, str) else desde):
        return f"La congelación está {ESTADOS[c['estado']].lower()}: no se puede pasar a {ESTADOS[hasta].lower()}."
    if accion == "restaurar":
        error = choque({"patologo_id": c["patologo_id"], "fecha": c["fecha"], "hora": c["hora"], "estado": hasta}, c["id"])
        if error:
            return error
    db.ex("UPDATE congelaciones SET estado=?, actualizado_por=?, actualizado_en=? WHERE id=?", (hasta, yo, db.ahora(), c["id"]))
    db.auditar(yo, c["protocolo_id"], "congelacion", f"Congelación #{c['id']}: {VERBOS[accion]} ({c['fecha']} {c['hora']}, {c['ubicacion']})")
    return None


def vincular(c, numero, yo):
    numero = numero.strip()
    if numero and c["estado"] == "eliminada":
        return "Está eliminada: restaurala antes de vincularla a un protocolo."
    if not numero:
        db.ex("UPDATE congelaciones SET protocolo_id=NULL, actualizado_por=?, actualizado_en=? WHERE id=?", (yo, db.ahora(), c["id"]))
        db.auditar(yo, c["protocolo_id"], "congelacion", f"Congelación #{c['id']}: se desvinculó del protocolo {c['protocolo_numero']}")
        return None
    p = db.uno("SELECT id, numero, dni FROM protocolos WHERE UPPER(numero)=UPPER(?) AND borrador=0", (numero,))
    if not p:
        return f"No encontré el protocolo «{numero}»."
    if c["dni"] and p["dni"] and dni_valido(p["dni"]) and limpiar_dni(p["dni"]) != c["dni"]:
        return f"El DNI del protocolo {p['numero']} no coincide con el de la congelación."
    db.ex("UPDATE congelaciones SET protocolo_id=?, actualizado_por=?, actualizado_en=? WHERE id=?", (p["id"], yo, db.ahora(), c["id"]))
    db.auditar(yo, p["id"], "congelacion", f"Congelación #{c['id']}: se vinculó al protocolo {p['numero']}")
    return None


def historial(cid):
    return db.q("SELECT a.fecha_hora, a.detalle, u.iniciales FROM auditoria a LEFT JOIN usuarios u ON u.id=a.usuario_id WHERE a.accion='congelacion' AND a.detalle LIKE ? "
                "ORDER BY a.id DESC LIMIT 30", (f"Congelación #{cid}:%",))


def protocolos_de_paciente(dni):
    return db.q("SELECT id, numero FROM protocolos WHERE dni=? AND borrador=0 ORDER BY id DESC LIMIT 5", (dni,)) if dni else []


def libro_excel(filas):
    import openpyxl
    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.title = "Congelaciones"
    hoja.append(["Fecha", "Hora", "Turno", "Horario", "Estado", "Tipo", "Ubicación", "Patólogo", "Médico tratante", "Material", "Cobertura", "DNI", "Apellido",
                 "Nombre", "Protocolo", "Observaciones"])
    for c in filas:
        hoja.append([c["fecha"], c["hora"], c["turno"], "En horario" if c["en_horario"] else "Fuera de horario", ESTADOS[c["estado"]], c["tipo"], c["ubicacion"],
                     c["pat_nombre"] or c["pat_iniciales"] or "", c["medico"] or "", c["material"] or "", c["cobertura"] or "",
                     c["dni"] or "", c["apellido"] or "", c["nombre"] or "", c["protocolo_numero"] or "", c["observaciones"] or ""])
    for columna, ancho in zip("ABCDEFGHIJKLMNOP", (11, 7, 10, 16, 12, 6, 30, 24, 28, 30, 22, 12, 18, 18, 12, 40)):
        hoja.column_dimensions[columna].width = ancho
    salida = io.BytesIO()
    libro.save(salida)
    salida.seek(0)
    return salida
