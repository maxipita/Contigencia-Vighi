import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datos_informe
from werkzeug.datastructures import MultiDict

A, db, ids, admin = datos_informe.preparar()
from vighi.servicios.protocolos import dni_valido, protocolos_del_paciente

fallas = []


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


c = A.app.test_client()
with c.session_transaction() as s:
    s['uid'] = admin
c.get('/')
with c.session_transaction() as s:
    csrf = s['csrf']


def post(url, datos):
    return c.post(url, data=MultiDict([('_csrf', csrf)] + list(datos.items())), follow_redirects=True).get_data(as_text=True)


print('1) qué cuenta como DNI')
for valor, esperado in (('30111222', True), ('30.111.222', True), ('0', False), ('00', False), ('0000000', False), ('', False), (None, False), (' 0 ', False), ('10', True)):
    chequear(f'{valor!r} -> {esperado}', dni_valido(valor) is esperado)


def protocolo(numero, dni, apellido='Gomez', nombre='Ana', nacimiento='1980-05-05', cobertura='OSDE'):
    return db.ex("INSERT INTO protocolos (numero, dni, apellido, nombre, fecha_nacimiento, cobertura, borrador, creado_por, creado_en) VALUES (?,?,?,?,?,?,0,?,?)",
                 (numero, dni, apellido, nombre, nacimiento, cobertura, admin, db.ahora()))


with A.app.app_context():
    a, b, d = protocolo('ZD1', '0'), protocolo('ZD2', '0'), protocolo('ZD3', '')
    x, y = protocolo('ZD4', '40111222', 'Perez', 'Luis'), protocolo('ZD5', '40111222', 'Perez', 'Luis')
    base = lambda pid: db.uno("SELECT * FROM protocolos WHERE id=?", (pid,))
    sin_dni = [p['id'] for p in protocolos_del_paciente(base(a))]
    vacio = [p['id'] for p in protocolos_del_paciente(base(d))]
    con_dni = sorted(p['id'] for p in protocolos_del_paciente(base(x)))

print('2) no se juntan los pacientes sin DNI')
chequear('con DNI 0 no junta aunque coincidan nombre y nacimiento', sin_dni == [a], sin_dni)
chequear('con DNI vacío tampoco', vacio == [d], vacio)
chequear('con DNI válido sí junta', con_dni == sorted([x, y]), con_dni)
h = c.get(f'/paciente/{a}').get_data(as_text=True)
chequear('la ficha muestra solo ese protocolo', 'ZD1' in h and 'ZD2' not in h and 'ZD3' not in h and '1 protocolo(s)' in h.replace('\n', ' '))

print('3) editar uno no toca al otro')
h = post(f'/paciente/{a}/datos', {'dni': '0', 'apellido': 'Gomez', 'nombre': 'Ana Maria', 'fecha_nacimiento': '1980-05-05', 'cobertura': 'PAMI'})
with A.app.app_context():
    nuevo_a, nuevo_b = base(a), base(b)
chequear('cambia el protocolo editado', nuevo_a['nombre'] == 'Ana Maria' and nuevo_a['cobertura'] == 'PAMI')
chequear('y no el otro con DNI 0', nuevo_b['nombre'] == 'Ana' and nuevo_b['cobertura'] == 'OSDE', dict(nuevo_b))
h = post(f'/paciente/{x}/datos', {'dni': '40111222', 'apellido': 'Perez', 'nombre': 'Luis', 'fecha_nacimiento': '', 'cobertura': 'PAMI'})
with A.app.app_context():
    otro = base(y)
chequear('con DNI válido el cambio sí llega a los demás', otro['cobertura'] == 'PAMI', otro['cobertura'])
h = post(f'/paciente/{b}/datos', {'dni': '0', 'apellido': 'Gomez', 'nombre': 'Ana', 'fecha_nacimiento': '1980-05-05', 'cobertura': 'OSDE'})
chequear('guardar un paciente con DNI 0 no lo toma por repetido', 'Ya hay otro paciente' not in h)

print('4) la edición rápida no se propaga')
h = post(f'/protocolo/{a}/datos', {'apellido': 'Gomez', 'nombre': 'Ana Maria', 'cobertura': 'SWISS'})
with A.app.app_context():
    nuevo_b = base(b)
chequear('la edición rápida de uno no cambia al otro', nuevo_b['cobertura'] == 'OSDE', nuevo_b['cobertura'])

print()
print('FALLAS:', 'ninguna' if not fallas else fallas)
sys.exit(1 if fallas else 0)
