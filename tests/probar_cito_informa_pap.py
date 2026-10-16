import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datos_informe import preparar

A, db, ids, admin = preparar()
from vighi.dominio.estudios import REGISTRO, sector_marca
from vighi.servicios.fichas import motivo_no_listo

fallas = []


def chequear(n, ok, det=''):
    print(('  OK   ' if ok else '  FALLA'), n, '' if ok else det)
    if not ok:
        fallas.append(n)


cito, medico = ['citotecnico'], ['firmante']
chequear('un citotécnico marca la microscopía de un PAP', sector_marca(cito, 'PAP', 'microscopia', 'firmante'))
chequear('no la de una biopsia', not sector_marca(cito, 'BP', 'microscopia', 'firmante'))
chequear('ni otras etapas del PAP que no son suyas', not sector_marca(cito, 'PAP', 'coloreado', 'laboratorio'))
chequear('el médico firmante sigue marcándola en PAP y BP', sector_marca(medico, 'PAP', 'microscopia', 'firmante') and sector_marca(medico, 'BP', 'microscopia', 'firmante'))
chequear('quien no es de ninguno de los dos no puede', not sector_marca(['laboratorio'], 'PAP', 'microscopia', 'firmante'))

pasos = REGISTRO['PAP'].estado({'coloreado', 'citotecnicos'}, False)[1]
yo = {'admin': 0, 'sectores': 'citotecnico'}
micro = {'resultado': 'Negativo'}
chequear('al marcar la etapa, el servidor no la rechaza por sector al citotécnico', motivo_no_listo(yo, 'PAP', 'microscopia', pasos, False, None, micro, None, set()) is None,
         motivo_no_listo(yo, 'PAP', 'microscopia', pasos, False, None, micro, None, set()))
chequear('el de otro sector sí se rechaza', 'la marca el sector' in (motivo_no_listo({'admin': 0, 'sectores': 'laboratorio'}, 'PAP', 'microscopia', pasos, False, None, micro, None, set()) or ''))
print('FALLAS:', fallas or 'ninguna')
