"""Datos ficticios para probar los informes: base temporal con protocolos ya informados, uno mixto y otro pendiente."""
import io
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')


FALSO = None


def preparar():
    global FALSO
    sys.path.insert(0, REPO)
    if os.environ.get('PROBAR_PG'):
        import psycopg
        from vighi.core import pg
        os.environ['DATABASE_URL'] = os.environ['PROBAR_PG']
        with psycopg.connect(os.environ['PROBAR_PG'], autocommit=True) as cx:
            cx.execute('DROP SCHEMA public CASCADE')
            cx.execute('CREATE SCHEMA public')
        pg._con_id.clear()

        class FalsoPG:
            con = pg.Conexion(os.environ['PROBAR_PG'])
            pedidos = sentencias = fallos = max_cuerpo = 0
        FALSO = FalsoPG()
    else:
        os.environ['PROBAR_D1'] = '1'
        import fake_d1
        FALSO = fake_d1.FalsoD1()
        os.environ.update(CONTINGENCIA_D1_URL=FALSO.iniciar(), CLOUDFLARE_ACCOUNT_ID=fake_d1.CUENTA, CLOUDFLARE_D1_ID=fake_d1.BASE,
                          CLOUDFLARE_API_TOKEN=fake_d1.TOKEN, CLOUDFLARE_D1_NOMBRE='pruebas')
    os.chdir(REPO)
    import app as A
    from vighi.core import db
    from vighi.dominio.estudios import REGISTRO
    from PIL import Image, ImageDraw

    db.inicializar()
    ids = {}
    with A.app.app_context():
        img = Image.new('RGBA', (600, 220), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.line([(20, 150), (90, 40), (130, 170), (200, 60), (260, 160), (330, 70), (420, 130), (580, 90)], fill=(20, 20, 60, 255), width=7)
        buf = io.BytesIO(); img.save(buf, 'PNG')

        admin = db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, debe_cambiar_clave) VALUES ('ZZADM','Administrador','ingreso',1,1,0)")
        med = db.uno("SELECT id FROM usuarios WHERE iniciales='DM'")['id']
        db.ex("UPDATE usuarios SET nombre='Diana Miserendino', titulo='Dra.', mn='98395', mp='451876', debe_cambiar_clave=0 WHERE id=?", (med,))
        db.ex("INSERT INTO firmas (usuario_id, imagen, actualizada_en) VALUES (?,?,?)", (med, buf.getvalue(), db.ahora()))
        sin = db.uno("SELECT id FROM usuarios WHERE iniciales='AFH'")['id']      # médica sin firma ni matrícula
        db.ex("UPDATE usuarios SET nombre='Andrea Flores Herbas', titulo='Dra.' WHERE id=?", (sin,))
        # segundo médico firmante, para probar el cambio de firmante
        otro = db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, debe_cambiar_clave, titulo, mn, mp) "
                     "VALUES ('ZZOT','Otto Tester','firmante,macroscopia',0,1,0,'Dr.','111','222')")
        # citotécnico sin sector firmante (responsable de PAP/CT en el sistema real)
        cito = db.ex("INSERT INTO usuarios (iniciales, nombre, sectores, admin, activo, debe_cambiar_clave) VALUES ('ZZCT','Cito Tecnica','citotecnico',0,1,0)")
        ids.update(med=med, sin=sin, otro=otro, cito=cito, admin=admin)

        def protocolo(numero, ap, nom, medico, inst, cob, afil):
            return db.ex("INSERT INTO protocolos (numero, fecha_recoleccion, apellido, nombre, dni, cobertura, n_afiliado, medico, lugar_recoleccion, creado_por, creado_en) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (numero, '2026-10-01', ap, nom, '30111222', cob, afil, medico, inst, admin, db.ahora()))

        def estudio(pid, tipo, sitio, muestra, cant, resp):
            return db.ex("INSERT INTO estudios (protocolo_id, tipo, categoria, sitio, tipo_muestra, cantidad, responsable_id, creado_por, creado_en) VALUES (?,?,?,?,?,?,?,?,?)",
                         (pid, tipo, 'Biopsias' if tipo == 'BP' else 'Citologías', sitio, muestra, cant, resp, admin, db.ahora()))

        def completar(eid, tipo, usuario, hora='2026-10-03 10:15:00'):
            for clave, _, _ in REGISTRO[tipo].flujo(bool(db.uno("SELECT 1 FROM micro WHERE estudio_id=? AND solicita_ihq=1", (eid,)))):
                db.ex("INSERT INTO etapas (estudio_id, etapa, usuario_id, fecha_hora) VALUES (?,?,?,?)", (eid, clave, usuario, hora))

        # 1) biopsia con macroscopía, microscopía y diagnóstico
        p1 = protocolo('C000101', 'Mancini', 'Héctor Adalberto', 'Dr. Gustavo Kido', 'Sanatorio Otamendi', 'MEDICUS', '10706795003')
        e1 = estudio(p1, 'BP', 'Esófago', 'Biopsia endoscópica', '2', med)
        db.ex("INSERT INTO macro (estudio_id, descripcion, cassettes) VALUES (?,?,?)", (e1, 'Varios fragmentos irregulares, pardos claros, que miden entre 0.4 y 0.2 cm.\nSe procesa la totalidad en un cassette.', 1))
        db.ex("INSERT INTO micro (estudio_id, descripcion, conclusion) VALUES (?,?,?)", (e1,
              'Los cortes muestran fragmentos de un adenocarcinoma intramucoso moderadamente diferenciado (G2) ulcerado, originado en mucosa de Barrett con displasia epitelial de alto grado, el que infiltra la lámina propia de la mucosa, con abundantes pseudomembranas fibrinoleucocitarias y detritus. La muestra remitida no incluye muscular mucosae/submucosa. Células de 12 µm, ≥ 3 mitosis cada 10 CGA.',
              'Esófago (lengueta, cara posterior); biopsia endoscópica:\n- Adenocarcinoma intramucoso moderadamente diferenciado (G2) ulcerado (léase descripción).\n* Originado en mucosa de Barrett con displasia epitelial de alto grado.'))
        completar(e1, 'BP', med)
        ids.update(bp=e1, p_bp=p1)

        # 2) PAP con resultado Bethesda: responsable médica sin firma
        p2 = protocolo('C000102', 'Ruiz', 'Inés', 'Dra. Laura Sosa', 'Centro Médico Pueyrredón', 'OSDE', '3105522')
        e2 = estudio(p2, 'PAP', 'Vagina', 'Citología endocervical', '1/2', sin)
        db.ex("INSERT INTO micro (estudio_id, descripcion, conclusion, bethesda) VALUES (?,?,?,?)", (e2, '', 'Frotis satisfactorio con representación de zona de transformación. Flora lactobacilar.', 'NILM'))
        completar(e2, 'PAP', sin)
        ids.update(pap=e2, p_pap=p2)

        # 3) citología de líquido, solo con la descripción (sin conclusión)
        p3 = protocolo('C000103', 'Gómez', 'Luis', '', 'Hospital Italiano', '', '')
        e3 = estudio(p3, 'CT', 'Líquido pleural', 'Líquido', '3', med)
        db.ex("INSERT INTO micro (estudio_id, descripcion, conclusion) VALUES (?,?,?)", (e3, 'Extendido con escasa celularidad, linfocitos y células mesoteliales reactivas. Sin atipia.', ''))
        completar(e3, 'CT', med)
        ids.update(ct=e3, p_ct=p3)

        # 4) biopsia larga: texto extenso para forzar más de una página
        p4 = protocolo('C000104', 'Pérez', 'Ana', 'Dr. Emiliano Pastor', 'Clínica del Sol', 'GALENO', '555', )
        e4 = estudio(p4, 'BP', 'Próstata', 'Biopsia por punción (12 frascos)', '10', med)
        largo = ' '.join(['Proliferación de glándulas pequeñas con núcleos agrandados y nucléolos evidentes, dispuestas en patrón infiltrativo entre glándulas benignas.'] * 40)
        db.ex("INSERT INTO macro (estudio_id, descripcion) VALUES (?,?)", (e4, 'Doce cilindros de tejido blanquecino de 1,0 a 1,6 cm de longitud.'))
        db.ex("INSERT INTO micro (estudio_id, descripcion, conclusion, tecnicas_especiales) VALUES (?,?,?,?)", (e4, largo, 'Adenocarcinoma acinar de próstata, Gleason 3+4=7.\nCompromete 6 de 12 cilindros.', 'PAS, Giemsa'))
        completar(e4, 'BP', med)
        ids.update(largo=e4, p_largo=p4)

        # 5) estudio todavía sin informar
        p5 = protocolo('C000105', 'Sosa', 'Mía', 'Dr. X', 'Y', '', '')
        e5 = estudio(p5, 'BP', 'Mama', 'Biopsia', '1', med)
        ids.update(pendiente=e5, p_pendiente=p5)

        # 6) protocolo MIXTO ya informado: 2 biopsias (mismo flujo) + 1 citología (flujo propio)
        p6 = protocolo('C000106', 'Álvarez', 'Marta', 'Dr. Mixto', 'Clínica Central', 'SWISS', '9')
        b1 = estudio(p6, 'BP', 'Estómago', 'Biopsia endoscópica', '2', med)
        b2 = estudio(p6, 'BP', 'Duodeno', 'Biopsia endoscópica', '1', med)
        c1 = estudio(p6, 'CT', 'Líquido ascítico', 'Líquido', '1', otro)
        for b, cuerpo in ((b1, 'Gastritis crónica leve.\nSin Helicobacter.'), (b2, 'Duodenitis crónica inespecífica.')):
            db.ex("INSERT INTO macro (estudio_id, descripcion) VALUES (?,?)", (b, 'Fragmentos pardos de 0,3 cm.'))
            db.ex("INSERT INTO micro (estudio_id, descripcion, conclusion) VALUES (?,?,?)", (b, 'Mucosa con infiltrado linfoplasmocitario.', cuerpo))
        db.ex("INSERT INTO micro (estudio_id, descripcion, conclusion) VALUES (?,?,?)", (c1, 'Celularidad escasa, sin atipia.', 'Negativo para células neoplásicas.'))
        for b in (b1, b2):
            completar(b, 'BP', med, '2026-10-03 10:00:00')
        completar(c1, 'CT', cito, '2026-10-03 11:30:00')       # lo último lo cierra la citotécnica
        ids.update(mix_b1=b1, mix_b2=b2, mix_c=c1, p_mix=p6)
    return A, db, ids, admin
