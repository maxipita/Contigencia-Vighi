import threading, time
import datos_informe
A, db, ids, admin = datos_informe.preparar()
dentro = [0]; maximo = [0]; hechos = [0]; fallos = []
def trabajo():
    try:
        with A.app.app_context():
            with db.bloqueo('prueba'):
                dentro[0] += 1; maximo[0] = max(maximo[0], dentro[0])
                time.sleep(0.05)
                dentro[0] -= 1
            hechos[0] += 1
            for _ in range(5):
                db.uno('SELECT COUNT(*) AS n FROM usuarios')
    except Exception as e:
        fallos.append(repr(e))
hs = [threading.Thread(target=trabajo) for _ in range(12)]
[h.start() for h in hs]; [h.join() for h in hs]
print('hechos', hechos[0], 'maximo simultaneo', maximo[0], 'fallos', fallos[:3])
