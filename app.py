from vighi import crear_app

app = crear_app()

if __name__ == "__main__":
    from vighi.servidor import ejecutar
    ejecutar(app)
