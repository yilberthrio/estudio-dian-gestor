"""Revisa un archivo JSON de preguntas antes de importarlo: detecta pistas por longitud y otros patrones.

Uso: python revisar_preguntas.py preguntas/importar/archivo.json
"""
import json
import re
import sys
from collections import Counter

from db import LETRAS, sesgo_longitud

ABSOLUTOS = re.compile(r"\b(siempre|nunca|únicamente|solamente|exclusivamente|en ningún caso|todas? las anteriores|ninguna de las anteriores)\b", re.I)


def revisar(ruta):
    datos = json.load(open(ruta, encoding="utf-8"))
    preguntas = datos["preguntas"] if isinstance(datos, dict) else datos
    n = len(preguntas)
    mas_larga = mas_corta = 0
    letras = Counter()
    problemas = []
    for i, p in enumerate(preguntas, 1):
        ops = p["opciones"] if isinstance(p["opciones"], dict) else dict(zip(LETRAS, p["opciones"]))
        c = p["correcta"].upper()
        letras[c] += 1
        largos = {l: len(ops[l]) for l in LETRAS}
        if largos[c] == max(largos.values()):
            mas_larga += 1
        if largos[c] == min(largos.values()):
            mas_corta += 1
        if sesgo_longitud(ops, c):
            problemas.append(f"#{i} [{p.get('sesion', datos.get('sesion'))}] correcta {largos[c]} car. vs otras {[v for l, v in largos.items() if l != c]}: {p['enunciado'][:70]}")
        abs_en_distractores = [l for l in LETRAS if l != c and ABSOLUTOS.search(ops[l])]
        if len(abs_en_distractores) == 3 and not ABSOLUTOS.search(ops[c]):
            problemas.append(f"#{i} todos los distractores usan absolutos y la correcta no: {p['enunciado'][:70]}")
    print(f"{n} preguntas · correcta es la más larga: {mas_larga} ({100 * mas_larga / n:.0f}%, ideal ≤25%) · "
          f"la más corta: {mas_corta} ({100 * mas_corta / n:.0f}%)")
    print("Distribución de letras correctas:", dict(sorted(letras.items())))
    if problemas:
        print(f"\n{len(problemas)} con posible pista:")
        print("\n".join("  " + x for x in problemas))
    else:
        print("Sin pistas evidentes por longitud. ✔")
    return not problemas and mas_larga / n <= 0.3


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    ok = all([revisar(r) for r in sys.argv[1:]])
    sys.exit(0 if ok else 1)
