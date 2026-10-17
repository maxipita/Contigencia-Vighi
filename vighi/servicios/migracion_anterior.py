import re

from vighi.core import db
from vighi.dominio.anterior import clave, fecha_hora_comentario, separar_practicas
from vighi.dominio.estudios import REGISTRO
from vighi.dominio.estudios.base import Variante
from vighi.servicios.validacion import PACIENTE_PROVISORIO

INICIALES_SISTEMA = "ANT"
NOMBRE_SISTEMA = "Sistema anterior"
RE_LOTE = re.compile(r"^(.+)-(\d{2})(\d{2})\.(\d+)$")
RE_TITULO_PERSONA = re.compile(r"^(dr|dra|lic|ct)\.?\s+", re.I)
CAMPOS_PAP = ("leucocitos", "hematies", "flora", "aspecto", "otros", "pavimentosas", "endocervicales", "metaplasicas", "endometriales", "resultado")


def usuario_sistema(ensayo=False):
    fila = db.uno("SELECT id FROM usuarios WHERE iniciales=?", (INICIALES_SISTEMA,))
    if fila:
        return fila["id"]
    if ensayo:
        return 0
    return db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, debe_cambiar_clave) VALUES (?,?,'',0,0,1)", (INICIALES_SISTEMA, NOMBRE_SISTEMA))


class Contexto:
    def __init__(self, ensayo=False):
        self.ensayo = ensayo
        self.usuarios = {u["iniciales"]: u["id"] for u in db.q("SELECT id, iniciales FROM usuarios")}
        self.personas = [(clave(u["nombre"]), u["id"]) for u in db.q("SELECT id, nombre FROM usuarios WHERE nombre IS NOT NULL AND nombre<>''")]
        self.ubicaciones = {u["abreviatura"] for u in db.q("SELECT abreviatura FROM ubicaciones")}
        self.medicos = {clave(m["nombre"]): m["nombre"] for m in db.q("SELECT nombre FROM medicos")}
        self.coberturas = [c["valor"] for c in db.q("SELECT valor FROM listas WHERE nombre='cobertura' ORDER BY orden")]
        self.lotes = {l["codigo"]: l["id"] for l in db.q("SELECT id, codigo FROM lotes")}
        self.tecnicas = {clave(t["valor"]) for t in db.q("SELECT valor FROM listas WHERE nombre='tecnicas_especiales'")}
        self.nuevos = {"usuarios": [], "ubicaciones": [], "medicos": [], "lotes": [], "coberturas": [], "sin_firmante": []}
        self.sistema = usuario_sistema(ensayo)
        self.usuarios.setdefault(INICIALES_SISTEMA, self.sistema)

    def usuario(self, iniciales):
        iniciales = (iniciales or "").strip()[:10]
        if not iniciales:
            return self.sistema
        if iniciales not in self.usuarios:
            self.nuevos["usuarios"].append(iniciales)
            self.usuarios[iniciales] = 0 if self.ensayo else db.ex(
                "INSERT INTO usuarios (iniciales, sectores, admin, activo, debe_cambiar_clave) VALUES (?,'',0,1,1)", (iniciales,))
        return self.usuarios[iniciales]

    def persona(self, nombre):
        buscado = clave(RE_TITULO_PERSONA.sub("", nombre or ""))
        if not buscado:
            return None
        hallados = [i for c, i in self.personas if c == buscado]
        if not hallados:
            hallados = [i for c, i in self.personas if set(buscado.split()) <= set(c.split())]
        if len(hallados) != 1 and nombre and nombre not in self.nuevos["sin_firmante"]:
            self.nuevos["sin_firmante"].append(nombre)
        return hallados[0] if len(hallados) == 1 else None

    def ubicacion(self, abreviatura):
        if not abreviatura or abreviatura in self.ubicaciones:
            return abreviatura or None
        self.nuevos["ubicaciones"].append(abreviatura)
        self.ubicaciones.add(abreviatura)
        if not self.ensayo:
            db.ex("INSERT INTO ubicaciones (abreviatura) VALUES (?)", (abreviatura,))
        return abreviatura

    def medico(self, nombre):
        if not nombre:
            return None
        hallado = self.medicos.get(clave(nombre))
        if hallado:
            return hallado
        self.nuevos["medicos"].append(nombre)
        self.medicos[clave(nombre)] = nombre
        if not self.ensayo:
            db.ex("INSERT INTO medicos (nombre) VALUES (?)", (nombre,))
        return nombre

    def cobertura(self, nombre):
        if not nombre:
            return None
        buscado = clave(nombre)
        for c in self.coberturas:
            if clave(c) == buscado or clave(re.sub(r".*\((.*)\)\s*$", r"\1", c)) == buscado:
                return c
        if nombre not in self.nuevos["coberturas"]:
            self.nuevos["coberturas"].append(nombre)
        return nombre

    def lote(self, codigo, tipo_lote, anio, usuario):
        if not codigo:
            return None
        if codigo in self.lotes:
            return self.lotes[codigo]
        m = RE_LOTE.match(codigo)
        if not m:
            return None
        self.nuevos["lotes"].append(codigo)
        if self.ensayo:
            self.lotes[codigo] = 0
            return 0
        fecha = f"{anio}-{m.group(2)}-{m.group(3)}"
        try:
            self.lotes[codigo] = db.ex("INSERT INTO lotes (codigo, tipo_lote, fecha, numero, cerrado, creado_por, creado_en) VALUES (?,?,?,?,0,?,?)",
                                       (codigo, m.group(1), fecha, int(m.group(4)), usuario, db.ahora()))
        except db.IntegrityError:
            fila = db.uno("SELECT id FROM lotes WHERE codigo=?", (codigo,))
            self.lotes[codigo] = fila["id"] if fila else None
        return self.lotes[codigo]


def existentes(numeros):
    salida = set()
    for i in range(0, len(numeros), 80):
        trozo = numeros[i:i + 80]
        salida |= {r["numero"] for r in db.q(f"SELECT numero FROM protocolos WHERE numero IN ({','.join('?' * len(trozo))})", tuple(trozo))}
    return salida


def etapas_validas(flujo):
    variante = Variante(ihq=flujo["ihq"], decal=bool(flujo["macro"] and flujo["macro"]["decal"]))
    return {k for k, _, _ in REGISTRO[flujo["tipo"]].flujo(variante)}


def sentencias_protocolo(r, ctx):
    ingreso = ctx.usuario((r["ingreso"] or {}).get("usuario"))
    creado = (r["ingreso"] or {}).get("fecha_hora") or db.ahora()
    campos = ("numero", "fecha_recoleccion", "dni", "cobertura", "plan", "n_afiliado", "nombre", "apellido", "sexo", "exento", "email", "telefono", "medico",
              "lugar_recoleccion", "lugar_entrega", "observaciones")
    provisorio = r.get("provisorio")
    valores = dict(r, apellido=PACIENTE_PROVISORIO[0] if provisorio else r["apellido"], nombre=PACIENTE_PROVISORIO[1] if provisorio else r["nombre"],
                   medico=ctx.medico(r["medico"]), lugar_recoleccion=ctx.ubicacion(r["lugar_recoleccion"]), lugar_entrega=ctx.ubicacion(r["lugar_entrega"]),
                   cobertura=ctx.cobertura(r["cobertura"]))
    sql = (f"INSERT INTO protocolos ({', '.join(campos)}, protocolo_sistema, cargado_sistema, borrador, pendiente_validacion, origen, creado_por, creado_en) "
           f"VALUES ({','.join('?' * len(campos))},?,1,0,?,'anterior',?,?)")
    pendiente = 1 if provisorio or not r["validado"] else 0
    return [(sql, [valores[c] for c in campos] + [r["numero"], pendiente, ingreso, creado])], ingreso, creado


def sentencia_flujo(r, f, creado):
    return ("INSERT INTO flujos (protocolo_id, tipo, creado_en) SELECT id, ?, ? FROM protocolos WHERE numero=?", (f["tipo"], creado, r["numero"]))


def sentencias_estudios(r, f, ctx, tecnicas_txt, lote_id, ingreso, creado):
    cito = ctx.usuarios.get((f.get("lote") or "").split("-")[0]) if f["tipo"] == "PAP" else None
    responsable = ctx.persona(f.get("asignado")) or cito or ctx.persona(f.get("firmante"))
    salida = []
    for i, e in enumerate(f["estudios"]):
        salida.append(("INSERT INTO estudios (protocolo_id, flujo_id, tipo, categoria, subcategoria, sitio, tipo_muestra, cantidad, observaciones, responsable_id, lote_id, "
                       "tecnicas_especiales, creado_por, creado_en) SELECT p.id, fl.id, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ? FROM protocolos p "
                       "JOIN flujos fl ON fl.protocolo_id=p.id AND fl.tipo=? WHERE p.numero=?",
                       (f["tipo"], e["categoria"], e["subcategoria"], e["sitio"], e["tipo_muestra"], "1", e["observaciones"], responsable, lote_id or None,
                        tecnicas_txt if i == 0 else None, ingreso, creado, f["tipo"], r["numero"])))
    return salida


def sentencias_tecnicas(r, f, ingreso, creado):
    salida = []
    for i, e in enumerate(f["estudios"]):
        t = e.get("tecnica")
        if t:
            salida.append(("INSERT INTO tecnicas (estudio_id, numero, fragmentos, inclusion, tacos, cassettes, usuario_id, creado_en) VALUES "
                           "((SELECT e.id FROM estudios e JOIN protocolos p ON p.id=e.protocolo_id WHERE p.numero=? AND e.tipo=? ORDER BY e.id LIMIT 1 OFFSET ?),?,?,?,?,?,?,?)",
                           (r["numero"], f["tipo"], i, t["numero"], t["fragmentos"], t["inclusion"], t["tacos"], t["cassettes"], ingreso, creado)))
    return salida


def insert_flujo(tabla, columnas, valores, r, f):
    marcas = ",".join("?" * len(valores))
    return (f"INSERT INTO {tabla} (flujo_id, {', '.join(columnas)}) SELECT fl.id, {marcas} FROM flujos fl JOIN protocolos p ON p.id=fl.protocolo_id "
            "WHERE p.numero=? AND fl.tipo=?", list(valores) + [r["numero"], f["tipo"]])


def sentencias_secciones(r, f, marcadores, ingreso, creado):
    salida = []
    if f["macro"]:
        m = f["macro"]
        salida.append(insert_flujo("macro", ("descripcion", "cassettes", "decal"), (m["descripcion"], m["cassettes"], m["decal"]), r, f))
    micro = f["micro"]
    if micro and micro.get("pap"):
        p = micro["pap"]
        salida.append(insert_flujo("micro", CAMPOS_PAP + ("conclusion",), [p[k] or None for k in CAMPOS_PAP] + [p["conclusion"] or None], r, f))
    elif micro or f["ihq"]:
        d = micro or {}
        texto = "\n".join(x for x in (d.get("conclusion"), d.get("observaciones")) if x) or None
        salida.append(insert_flujo("micro", ("descripcion", "conclusion", "solicita_ihq"), (d.get("descripcion"), texto, 1 if f["ihq"] else 0), r, f))
    if f["ihq"]:
        salida.append(insert_flujo("ihq", ("marcadores", "pedido_en", "pedido_por"), ("; ".join(marcadores) or None, creado, ingreso), r, f))
    return salida


def sentencias_etapas(r, f, ctx):
    validas = etapas_validas(f)
    return [insert_flujo("etapas", ("etapa", "usuario_id", "fecha_hora"), (e["etapa"], ctx.usuario(e["usuario"]), e["fecha_hora"]), r, f)
            for e in f["etapas"] if e["etapa"] in validas]


def sentencias_comentarios(r, ctx, anio):
    salida = []
    for c in r.get("comentarios") or []:
        fecha = fecha_hora_comentario(c.get("fecha"), anio) or db.ahora()
        salida.append(("INSERT INTO comentarios (protocolo_id, usuario_id, fecha_hora, texto) SELECT id, ?, ?, ? FROM protocolos WHERE numero=?",
                       (ctx.sistema, fecha, f"[{c.get('autor') or '?'} · sistema anterior] {c['texto']}", r["numero"])))
    return salida


def sentencias_de(r, ctx):
    anio = (r.get("fecha_recoleccion") or db.ahora())[:4]
    sentencias, ingreso, creado = sentencias_protocolo(r, ctx)
    for f in r["flujos"]:
        tecnicas, marcadores, _ = separar_practicas(f["practicas"], f["ihq"], ctx.tecnicas)
        lote = ctx.lote(f["lote"], f["lote_tipo"], anio, ingreso)
        sentencias.append(sentencia_flujo(r, f, creado))
        sentencias += sentencias_estudios(r, f, ctx, "; ".join(tecnicas) or None, lote, ingreso, creado)
        sentencias += sentencias_tecnicas(r, f, ingreso, creado)
        sentencias += sentencias_secciones(r, f, marcadores, ingreso, creado)
        sentencias += sentencias_etapas(r, f, ctx)
    sentencias += sentencias_comentarios(r, ctx, anio)
    sentencias.append(("INSERT INTO auditoria (fecha_hora, usuario_id, protocolo_id, accion, detalle) SELECT ?, ?, id, 'importar_anterior', ? FROM protocolos WHERE numero=?",
                       (db.ahora(), ctx.sistema, f"Importado del sistema anterior ({r['numero']}): " + ", ".join(f"{f['tipo']} {len(f['estudios'])} muestra(s)" for f in r["flujos"]), r["numero"])))
    return sentencias


def importar(registros, ensayo=False, ctx=None):
    ctx = ctx or Contexto(ensayo)
    ya = existentes([r["numero"] for r in registros])
    resultado = {"importados": 0, "existentes": 0, "errores": []}
    for r in registros:
        if r["numero"] in ya:
            resultado["existentes"] += 1
            continue
        try:
            sentencias = sentencias_de(r, ctx)
            if not ensayo:
                db.lote_ex(sentencias)
            resultado["importados"] += 1
        except Exception as e:
            resultado["errores"].append(f"{r['numero']}: {e}")
    resultado["nuevos"] = ctx.nuevos
    return resultado
