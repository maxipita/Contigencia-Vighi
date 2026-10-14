import datos_informe
A, db, ids, admin = datos_informe.preparar()
r = A.app.test_client().get('/salud')
print('salud', r.status_code, r.get_data(as_text=True))
