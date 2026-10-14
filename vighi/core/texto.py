import unicodedata


def sin_acentos(texto):
    t = unicodedata.normalize("NFD", texto or "")
    return " ".join("".join(c for c in t if unicodedata.category(c) != "Mn").lower().split())
