import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from datos_informe import preparar

A, db, ids, admin = preparar()
from vighi.dominio import informes
import fitz
SC = __import__("tempfile").gettempdir()
fallas = []


def chequear(nombre, ok, detalle=''):
    print(('  OK   ' if ok else '  FALLA'), nombre, '' if ok else detalle)
    if not ok:
        fallas.append(nombre)


with A.app.app_context():
    print('fuente usada:', informes.FUENTE)
    mixto = informes.armar(ids['p_mix'])
    materiales = {s['tipo']: s['material'].splitlines() for s in mixto['estudios']}
    chequear('mixto: varias muestras de un flujo salen enumeradas a), b)', materiales['BP'] == ['a) Estómago · Biopsia endoscópica', 'b) Duodeno · Biopsia endoscópica'], materiales)
    chequear('mixto: el título previo al diagnóstico es solo el tipo (Biopsia / Citología)', [s['titulo'] for s in mixto['estudios']] == ['Biopsia', 'Citología'], [s['titulo'] for s in mixto['estudios']])
    lineas_mixto = [l.strip() for p in fitz.open(stream=informes.generar_pdf(mixto), filetype='pdf') for l in p.get_text().splitlines()]
    chequear('mixto: el PDF titula BIOPSIA y CITOLOGÍA sin los sitios', 'BIOPSIA' in lineas_mixto and 'CITOLOGÍA' in lineas_mixto and not any(l.startswith(('BIOPSIA ·', 'CITOLOGÍA ·')) for l in lineas_mixto), lineas_mixto[:30])
    chequear('mixto: una sola muestra no lleva letra', materiales['CT'] == ['Líquido ascítico · Líquido'], materiales)
    for clave in ('bp', 'pap', 'ct', 'largo'):
        d = informes.armar(ids[clave], comentario='Se sugiere correlación clínico-imagenológica.' if clave == 'bp' else '')
        pdf = informes.generar_pdf(d)
        ruta = os.path.join(SC, f'informe_{clave}.pdf')
        open(ruta, 'wb').write(pdf)
        doc = fitz.open(ruta)
        texto = '\n'.join(p.get_text() for p in doc)
        print(f'\n[{clave}] {len(pdf)//1024} KB, {len(doc)} página(s), avisos: {d["avisos"]}')
        for i, p in enumerate(doc):
            p.get_pixmap(dpi=80).save(os.path.join(SC, f'informe_{clave}_{i + 1}.png'))
        chequear(f'{clave}: es un PDF', pdf[:4] == b'%PDF')
        chequear(f'{clave}: tiene el número de protocolo y el título', d['numero'] in texto and d['titulo'] in texto)
        chequear(f'{clave}: el paciente en mayúsculas', d['paciente'] in texto)
        chequear(f'{clave}: dice "Página 1 de {len(doc)}"', f'1 de {len(doc)}' in texto, texto[:300])
        chequear(f'{clave}: pie de secreto médico', 'SECRETO MÉDICO' in texto and 'Concepción Arenal 3732' in texto)
        if clave == 'bp':
            chequear('bp: material, macro, micro y diagnóstico', all(x in texto for x in ('Esófago', 'MACROSCOPÍA', 'Varios fragmentos', 'MICROSCOPÍA', 'DIAGNÓSTICO', 'Adenocarcinoma intramucoso')))
            chequear('bp: símbolos µ y ≥ se ven (fuente Unicode)', 'µ' in texto and '≥' in texto)
            chequear('bp: comentario opcional', 'COMENTARIO' in texto and 'correlación clínico' in texto)
            chequear('bp: médica con título, matrícula y firma', 'Dra. Diana Miserendino' in texto and 'MN 98395' in texto and 'MP 451876' in texto and len(doc[0].get_images()) >= 2)
            chequear('bp: sin avisos', d['avisos'] == [])
        if clave == 'pap':
            chequear('pap: título citológico y Bethesda como diagnóstico', 'INFORME CITOLÓGICO' in texto and 'NILM' in texto)
            chequear('pap: el material no lleva la cantidad de vidrios', 'vidrios' not in texto and 'Vagina' in texto)
            chequear('pap: avisa que a la médica le falta firma y matrícula', len(d['avisos']) == 2, d['avisos'])
            chequear('pap: sin firma no hay imagen de firma (solo el logo)', len(doc[0].get_images()) == 1)
        if clave == 'ct':
            chequear('ct: con solo la descripción dice "Ver descripción"', 'Ver descripción microscópica' in texto and 'DESCRIPCIÓN' in texto)
        if clave == 'largo':
            chequear('largo: pasa de una página y cada página tiene su pie', len(doc) >= 2 and all('SECRETO MÉDICO' in p.get_text() for p in doc), len(doc))
            chequear('largo: la firma no queda sola en otra página', 'Dra. Diana Miserendino' in doc[-1].get_text() and len(doc[-1].get_text()) > 400)

    print()
    for clave, motivo in (('pendiente', 'pendiente'),):
        try:
            informes.armar(ids[clave]); chequear('estudio sin informar se rechaza', False)
        except informes.InformeError as err:
            chequear('estudio sin informar se rechaza', 'pendiente' in str(err), str(err)); print('     →', err)

print('\nFALLAS:', fallas if fallas else 'ninguna')
