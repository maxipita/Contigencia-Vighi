from vighi.core import db, permisos


def perfiles_con_permisos():
    return [{**dict(f), "set": permisos.lista(f["permisos"])} for f in db.q(
        """SELECT p.*, (SELECT COUNT(*) FROM usuarios u WHERE u.perfil_id=p.id AND u.activo=1) AS usuarios
           FROM perfiles p ORDER BY p.nombre""")]
