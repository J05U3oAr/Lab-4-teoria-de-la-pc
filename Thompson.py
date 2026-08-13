import copy
import itertools
import re
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field

EPSILON = "epsilon"
EPSILON_SYMBOLS = {"epsilon", "eps", "\u03b5"}  # "epsilon", "eps", "ε"
CONCAT = "CONCAT"


# ---------------------------------------------------------------------------
# 1. FRONT-END (reutilizado de regex_ast.py): regex -> AST basico
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Token:
    tipo: str
    valor: object
    texto: str
    posicion: int


@dataclass(frozen=True)
class Nodo:
    tipo: str
    valor: object = None
    hijos: tuple = ()


PRECEDENCIA = {"|": 1, CONCAT: 2}


def es_operador_binario(token):
    return token.tipo in {"UNION", "CONCAT"}


def puede_terminar_operando(token):
    return token.tipo in {"LITERAL", "CLASE", "EPSILON", "RPAREN", "STAR", "PLUS", "QUESTION", "REPEAT"}


def puede_iniciar_operando(token):
    return token.tipo in {"LITERAL", "CLASE", "EPSILON", "LPAREN"}


def formato_tokens(tokens):
    return " ".join(token.texto for token in tokens) if tokens else "(vacio)"


def escapar_literal(char):
    especiales = {"\\", "|", "*", "+", "?", "(", ")", "[", "]", "{", "}", " "}
    return "\\" + char if char in especiales else char


def leer_clase(expresion, inicio):
    profundidad = 0
    i = inicio
    while i < len(expresion):
        char = expresion[i]
        if char == "\\":
            if i + 1 >= len(expresion):
                raise ValueError(f"Caracter de escape incompleto dentro de clase en posicion {i}")
            i += 2
            continue
        if char == "[":
            profundidad += 1
        elif char == "]":
            profundidad -= 1
            if profundidad == 0:
                return expresion[inicio : i + 1], i + 1
        i += 1
    raise ValueError(f"Clase de caracteres sin cierre desde posicion {inicio}")


def leer_repeticion(expresion, inicio):
    fin = expresion.find("}", inicio + 1)
    if fin == -1:
        raise ValueError(f"Repeticion sin cierre desde posicion {inicio}")

    contenido = expresion[inicio + 1 : fin].replace(" ", "")
    if not contenido:
        raise ValueError(f"Repeticion vacia en posicion {inicio}")

    if "," in contenido:
        partes = contenido.split(",")
        if len(partes) != 2:
            raise ValueError(f"Repeticion invalida en posicion {inicio}: {{{contenido}}}")
        minimo_txt, maximo_txt = partes
        if minimo_txt == "":
            raise ValueError(f"La repeticion debe tener minimo en posicion {inicio}")
        if not minimo_txt.isdigit() or (maximo_txt and not maximo_txt.isdigit()):
            raise ValueError(f"Repeticion invalida en posicion {inicio}: {{{contenido}}}")
        minimo = int(minimo_txt)
        maximo = int(maximo_txt) if maximo_txt else None
    else:
        if not contenido.isdigit():
            raise ValueError(f"Repeticion invalida en posicion {inicio}: {{{contenido}}}")
        minimo = int(contenido)
        maximo = minimo

    if maximo is not None and minimo > maximo:
        raise ValueError(f"Repeticion invalida en posicion {inicio}: minimo mayor que maximo")

    return (minimo, maximo), expresion[inicio : fin + 1], fin + 1


def leer_palabra(expresion, inicio):
    i = inicio
    while i < len(expresion) and (expresion[i].isalpha() or expresion[i] == "_"):
        i += 1
    return expresion[inicio:i], i


def tokenizar(expresion):
    tokens = []
    pasos = []
    i = 0

    while i < len(expresion):
        char = expresion[i]

        if char.isspace():
            i += 1
            continue

        if char == "\\":
            if i + 1 >= len(expresion):
                raise ValueError(f"Caracter de escape incompleto en posicion {i}")
            literal = expresion[i + 1]
            token = Token("LITERAL", literal, escapar_literal(literal), i)
            tokens.append(token)
            pasos.append(f"pos {i}: '\\{literal}' se toma como literal escapado")
            i += 2
            continue

        if char == "[":
            texto, nuevo_i = leer_clase(expresion, i)
            tokens.append(Token("CLASE", texto, texto, i))
            pasos.append(f"pos {i}: clase de caracteres {texto} se toma como operando")
            i = nuevo_i
            continue

        if char == "{":
            repeticion, texto, nuevo_i = leer_repeticion(expresion, i)
            tokens.append(Token("REPEAT", repeticion, texto, i))
            pasos.append(f"pos {i}: extension {texto} validada como repeticion")
            i = nuevo_i
            continue

        if char == "^":
            j = i + 1
            while j < len(expresion) and expresion[j].isspace():
                j += 1
            if j < len(expresion) and expresion[j] == "{":
                pasos.append(f"pos {i}: '^' se reconoce como marcador de repeticion")
                i += 1
                continue

        if char == "\u03b5":  # "ε"
            tokens.append(Token("EPSILON", EPSILON, EPSILON, i))
            pasos.append(f"pos {i}: epsilon se toma como operando")
            i += 1
            continue

        if char.isalpha():
            palabra, nuevo_i = leer_palabra(expresion, i)
            if palabra.lower() in EPSILON_SYMBOLS:
                tokens.append(Token("EPSILON", EPSILON, EPSILON, i))
                pasos.append(f"pos {i}: {palabra} se toma como epsilon")
                i = nuevo_i
                continue

        if char == "(":
            tokens.append(Token("LPAREN", char, char, i))
        elif char == ")":
            tokens.append(Token("RPAREN", char, char, i))
        elif char == "|":
            tokens.append(Token("UNION", char, char, i))
        elif char == "*":
            tokens.append(Token("STAR", char, char, i))
        elif char == "+":
            tokens.append(Token("PLUS", char, char, i))
        elif char == "?":
            tokens.append(Token("QUESTION", char, char, i))
        elif char in {"]", "}"}:
            raise ValueError(f"Caracter de cierre inesperado '{char}' en posicion {i}")
        else:
            tokens.append(Token("LITERAL", char, escapar_literal(char), i))

        i += 1

    return tokens, pasos


def insertar_concatenacion(tokens):
    resultado = []
    pasos = []

    for token in tokens:
        if resultado and puede_terminar_operando(resultado[-1]) and puede_iniciar_operando(token):
            concat = Token("CONCAT", CONCAT, CONCAT, token.posicion)
            resultado.append(concat)
            pasos.append(
                f"antes de pos {token.posicion}: se inserta {CONCAT} entre "
                f"'{resultado[-2].texto}' y '{token.texto}'"
            )
        resultado.append(token)

    return resultado, pasos


def validar_sintaxis(tokens):
    espera_operando = True
    balance = 0

    for token in tokens:
        if token.tipo in {"LITERAL", "CLASE", "EPSILON"}:
            if not espera_operando:
                raise ValueError(f"Falta operador antes de '{token.texto}' en posicion {token.posicion}")
            espera_operando = False
        elif token.tipo == "LPAREN":
            if not espera_operando:
                raise ValueError(f"Falta operador antes de '(' en posicion {token.posicion}")
            balance += 1
            espera_operando = True
        elif token.tipo == "RPAREN":
            if espera_operando:
                raise ValueError(f"Grupo vacio o operador incompleto antes de ')' en posicion {token.posicion}")
            balance -= 1
            if balance < 0:
                raise ValueError(f"Parentesis de cierre sin apertura en posicion {token.posicion}")
            espera_operando = False
        elif token.tipo in {"STAR", "PLUS", "QUESTION", "REPEAT"}:
            if espera_operando:
                raise ValueError(f"Extension '{token.texto}' sin operando en posicion {token.posicion}")
            espera_operando = False
        elif es_operador_binario(token):
            if espera_operando:
                raise ValueError(f"Operador '{token.texto}' sin operando izquierdo en posicion {token.posicion}")
            espera_operando = True

    if balance > 0:
        raise ValueError("Hay parentesis de apertura sin cerrar")
    if espera_operando and tokens:
        raise ValueError("La expresion termina con un operador incompleto")


def a_postfix(tokens):
    salida = []
    pila = []
    pasos = []

    for token in tokens:
        if token.tipo in {"LITERAL", "CLASE", "EPSILON"}:
            salida.append(token)
            pasos.append(f"leer {token.texto}: va a salida -> {formato_tokens(salida)}")
        elif token.tipo in {"STAR", "PLUS", "QUESTION", "REPEAT"}:
            salida.append(token)
            pasos.append(f"leer {token.texto}: operador postfix, va a salida -> {formato_tokens(salida)}")
        elif token.tipo == "LPAREN":
            pila.append(token)
            pasos.append(f"leer (: push en pila -> {formato_tokens(pila)}")
        elif token.tipo == "RPAREN":
            pasos.append("leer ): desapilar hasta encontrar (")
            while pila and pila[-1].tipo != "LPAREN":
                salida.append(pila.pop())
                pasos.append(f"  pop a salida -> {formato_tokens(salida)}")
            if not pila:
                raise ValueError("Parentesis desbalanceados durante Shunting Yard")
            pila.pop()
            pasos.append(f"  se descarta ( -> pila {formato_tokens(pila)}")
        elif es_operador_binario(token):
            while (
                pila
                and es_operador_binario(pila[-1])
                and PRECEDENCIA[pila[-1].valor] >= PRECEDENCIA[token.valor]
            ):
                salida.append(pila.pop())
                pasos.append(f"leer {token.texto}: pop por precedencia -> {formato_tokens(salida)}")
            pila.append(token)
            pasos.append(f"leer {token.texto}: push en pila -> {formato_tokens(pila)}")

    while pila:
        if pila[-1].tipo == "LPAREN":
            raise ValueError("Parentesis de apertura sin cierre durante Shunting Yard")
        salida.append(pila.pop())
        pasos.append(f"fin: pop restante -> {formato_tokens(salida)}")

    return salida, pasos


def construir_ast(postfix):
    pila = []

    for token in postfix:
        if token.tipo in {"LITERAL", "CLASE"}:
            pila.append(Nodo(token.tipo, token.texto))
        elif token.tipo == "EPSILON":
            pila.append(Nodo("EPSILON"))
        elif token.tipo == "STAR":
            pila.append(Nodo("STAR", hijos=(pila.pop(),)))
        elif token.tipo == "PLUS":
            pila.append(Nodo("PLUS", hijos=(pila.pop(),)))
        elif token.tipo == "QUESTION":
            pila.append(Nodo("QUESTION", hijos=(pila.pop(),)))
        elif token.tipo == "REPEAT":
            pila.append(Nodo("REPEAT", token.valor, (pila.pop(),)))
        elif token.tipo == "CONCAT":
            derecho = pila.pop()
            izquierdo = pila.pop()
            pila.append(Nodo("CONCAT", hijos=(izquierdo, derecho)))
        elif token.tipo == "UNION":
            derecho = pila.pop()
            izquierdo = pila.pop()
            pila.append(Nodo("UNION", hijos=(izquierdo, derecho)))

    if len(pila) != 1:
        raise ValueError("No se pudo construir un arbol valido desde el postfix")
    return pila[0]


def concatenar(nodos):
    if not nodos:
        return Nodo("EPSILON")
    actual = nodos[0]
    for nodo in nodos[1:]:
        actual = Nodo("CONCAT", hijos=(actual, nodo))
    return actual


def expandir_extensiones(nodo):
    if nodo.tipo in {"LITERAL", "CLASE", "EPSILON"}:
        return nodo
    if nodo.tipo == "STAR":
        return Nodo("STAR", hijos=(expandir_extensiones(nodo.hijos[0]),))
    if nodo.tipo == "CONCAT":
        return Nodo("CONCAT", hijos=(expandir_extensiones(nodo.hijos[0]), expandir_extensiones(nodo.hijos[1])))
    if nodo.tipo == "UNION":
        return Nodo("UNION", hijos=(expandir_extensiones(nodo.hijos[0]), expandir_extensiones(nodo.hijos[1])))
    if nodo.tipo == "PLUS":
        base = expandir_extensiones(nodo.hijos[0])
        return Nodo("CONCAT", hijos=(copy.deepcopy(base), Nodo("STAR", hijos=(copy.deepcopy(base),))))
    if nodo.tipo == "QUESTION":
        base = expandir_extensiones(nodo.hijos[0])
        return Nodo("UNION", hijos=(base, Nodo("EPSILON")))
    if nodo.tipo == "REPEAT":
        minimo, maximo = nodo.valor
        base = expandir_extensiones(nodo.hijos[0])
        partes = [copy.deepcopy(base) for _ in range(minimo)]
        if maximo is None:
            partes.append(Nodo("STAR", hijos=(copy.deepcopy(base),)))
        else:
            for _ in range(maximo - minimo):
                partes.append(Nodo("UNION", hijos=(copy.deepcopy(base), Nodo("EPSILON"))))
        return concatenar(partes)
    raise ValueError(f"Tipo de nodo no reconocido: {nodo.tipo}")


def etiqueta_nodo(nodo):
    etiquetas = {"EPSILON": "\u03b5", "STAR": "*", "CONCAT": ".", "UNION": "|"}
    return str(nodo.valor) if nodo.tipo in {"LITERAL", "CLASE"} else etiquetas[nodo.tipo]


def construir_ast_basico(expresion):
    """Aplica todo el front-end del laboratorio anterior y regresa el AST
    basico (solo LITERAL, CLASE, EPSILON, STAR, CONCAT, UNION), que es el
    "arbol construido" sobre el que se aplica el algoritmo de Thompson."""
    tokens, _ = tokenizar(expresion)
    tokens_cc, _ = insertar_concatenacion(tokens)
    validar_sintaxis(tokens_cc)
    postfix_extendido, _ = a_postfix(tokens_cc)
    ast_extendido = construir_ast(postfix_extendido)
    return expandir_extensiones(ast_extendido)


# ---------------------------------------------------------------------------
# 2. ALGORITMO DE THOMPSON: AST basico -> AFN
# ---------------------------------------------------------------------------

def expandir_clase(texto_clase):
    """Convierte una clase '[abc]' o '[a-z0-9]' (sin negacion) en la lista
    de simbolos individuales que representa."""
    contenido = texto_clase[1:-1]
    if contenido.startswith("^"):
        raise ValueError("Las clases negadas no estan soportadas: se requiere un alfabeto explicito")
    simbolos = []
    i = 0
    while i < len(contenido):
        if contenido[i] == "\\" and i + 1 < len(contenido):
            simbolos.append(contenido[i + 1])
            i += 2
            continue
        if i + 2 < len(contenido) and contenido[i + 1] == "-":
            for codigo in range(ord(contenido[i]), ord(contenido[i + 2]) + 1):
                simbolos.append(chr(codigo))
            i += 3
            continue
        simbolos.append(contenido[i])
        i += 1
    return simbolos


@dataclass
class AFN:
    """AFN representado con estados enteros y una lista de adyacencia.
    En transiciones[estado] hay tuplas (simbolo, destino); simbolo=None
    representa una transicion epsilon."""

    inicial: int
    aceptacion: int
    estados: set
    transiciones: dict

    def clausura_epsilon(self, conjunto):
        pila = list(conjunto)
        clausura = set(conjunto)
        while pila:
            estado = pila.pop()
            for simbolo, destino in self.transiciones.get(estado, []):
                if simbolo is None and destino not in clausura:
                    clausura.add(destino)
                    pila.append(destino)
        return clausura

    def mover(self, conjunto, simbolo):
        destinos = set()
        for estado in conjunto:
            for sim, destino in self.transiciones.get(estado, []):
                if sim == simbolo:
                    destinos.add(destino)
        return destinos

    def acepta(self, cadena):
        """Simula el AFN sobre la cadena w y regresa True si w in L(r)."""
        actual = self.clausura_epsilon({self.inicial})
        for caracter in cadena:
            actual = self.clausura_epsilon(self.mover(actual, caracter))
            if not actual:
                return False
        return self.aceptacion in actual


def _construir_fragmento(nodo, contador, transiciones):
    """Construye recursivamente el fragmento de AFN correspondiente a `nodo`
    siguiendo las reglas clasicas de Thompson. Regresa (estado_inicio, estado_fin)."""

    tipo = nodo.tipo

    if tipo == "LITERAL":
        s0, s1 = next(contador), next(contador)
        transiciones[s0].append((nodo.valor, s1))
        return s0, s1

    if tipo == "CLASE":
        s0, s1 = next(contador), next(contador)
        for simbolo in expandir_clase(nodo.valor):
            transiciones[s0].append((simbolo, s1))
        return s0, s1

    if tipo == "EPSILON":
        s0, s1 = next(contador), next(contador)
        transiciones[s0].append((None, s1))
        return s0, s1

    if tipo == "CONCAT":
        i1, a1 = _construir_fragmento(nodo.hijos[0], contador, transiciones)
        i2, a2 = _construir_fragmento(nodo.hijos[1], contador, transiciones)
        transiciones[a1].append((None, i2))
        return i1, a2

    if tipo == "UNION":
        i1, a1 = _construir_fragmento(nodo.hijos[0], contador, transiciones)
        i2, a2 = _construir_fragmento(nodo.hijos[1], contador, transiciones)
        s0, s1 = next(contador), next(contador)
        transiciones[s0].append((None, i1))
        transiciones[s0].append((None, i2))
        transiciones[a1].append((None, s1))
        transiciones[a2].append((None, s1))
        return s0, s1

    if tipo == "STAR":
        i1, a1 = _construir_fragmento(nodo.hijos[0], contador, transiciones)
        s0, s1 = next(contador), next(contador)
        transiciones[s0].append((None, i1))
        transiciones[s0].append((None, s1))
        transiciones[a1].append((None, i1))
        transiciones[a1].append((None, s1))
        return s0, s1

    raise ValueError(f"Tipo de nodo no soportado por Thompson: {tipo}")


def construir_afn(ast_basico):
    """Punto de entrada del algoritmo de Thompson: recibe el AST basico
    (arbol construido en la seccion anterior) y regresa un objeto AFN."""
    contador = itertools.count()
    transiciones = defaultdict(list)
    inicio, fin = _construir_fragmento(ast_basico, contador, transiciones)
    # Los estados no siempre son consecutivos en un solo tramo (se crean por
    # recursion), asi que se recolectan explicitamente a partir de las
    # transiciones generadas:
    estados = set()
    for origen, lista in transiciones.items():
        estados.add(origen)
        for _, destino in lista:
            estados.add(destino)
    estados.add(inicio)
    estados.add(fin)
    return AFN(inicio, fin, estados, dict(transiciones))


# ---------------------------------------------------------------------------
# 3. DIBUJO DEL AFN (ventana con Tkinter, mismo estilo que el laboratorio
#    anterior de arboles sintacticos)
# ---------------------------------------------------------------------------

def calcular_niveles(afn):
    """BFS desde el estado inicial para asignar un 'nivel' (columna) a cada
    estado. Como el AFN de Thompson puede tener ciclos (por el operador *),
    un estado solo recibe nivel la primera vez que se visita."""
    niveles = {afn.inicial: 0}
    orden = [afn.inicial]
    cola = deque([afn.inicial])
    visitados = {afn.inicial}
    while cola:
        u = cola.popleft()
        for _, v in afn.transiciones.get(u, []):
            if v not in visitados:
                visitados.add(v)
                niveles[v] = niveles[u] + 1
                orden.append(v)
                cola.append(v)
    for estado in afn.estados:
        if estado not in niveles:
            niveles[estado] = 0
            orden.append(estado)
    return niveles, orden


def calcular_posiciones(afn, espacio_x=150, espacio_y=100, margen=70):
    niveles, orden = calcular_niveles(afn)
    por_nivel = defaultdict(list)
    for estado in orden:
        por_nivel[niveles[estado]].append(estado)

    max_en_nivel = max(len(v) for v in por_nivel.values())
    posiciones = {}
    for nivel, estados_nivel in por_nivel.items():
        x = margen + nivel * espacio_x
        n = len(estados_nivel)
        offset_y = margen + (max_en_nivel - n) * espacio_y / 2
        for indice, estado in enumerate(estados_nivel):
            y = offset_y + indice * espacio_y
            posiciones[estado] = (x, y)

    ancho = margen * 2 + max(niveles.values()) * espacio_x + 60
    alto = margen * 2 + (max_en_nivel - 1) * espacio_y + 40
    return posiciones, ancho, alto


class DibujadorAFN:
    """Dibuja uno o mas AFNs (con su cadena de prueba y resultado) en una
    sola ventana desplazable, igual que DibujadorArbol del laboratorio
    anterior."""

    def __init__(self, resultados):
        # resultados: lista de tuplas (expresion, cadena, afn, acepta)
        self.resultados = resultados
        self.radio = 24
        self.espacio_x = 150
        self.espacio_y = 100
        self.margen = 70

    def dibujar_estado(self, canvas, x, y, nombre, es_inicial, es_aceptacion):
        r = self.radio
        canvas.create_oval(x - r, y - r, x + r, y + r, fill="#f8fafc", outline="#1f2937", width=2)
        if es_aceptacion:
            canvas.create_oval(x - r + 5, y - r + 5, x + r - 5, y + r - 5, outline="#1f2937", width=2)
        canvas.create_text(x, y, text=f"q{nombre}", font=("Segoe UI", 10, "bold"), fill="#111827")
        if es_inicial:
            canvas.create_line(x - r - 34, y, x - r - 2, y, fill="#1f2937", width=2, arrow="last")
            canvas.create_text(x - r - 38, y, anchor="e", text="inicio", font=("Segoe UI", 9), fill="#374151")

    def dibujar_arista(self, canvas, origen, destino, etiqueta):
        x1, y1 = origen
        x2, y2 = destino
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        dx, dy = x2 - x1, y2 - y1
        longitud = max((dx ** 2 + dy ** 2) ** 0.5, 1)
        nx, ny = -dy / longitud, dx / longitud
        # Las aristas "hacia atras" (o dentro del mismo nivel) se curvan mas
        # para no encimarse con el resto del grafo (ej. el lazo de A*).
        curvatura = 34 if dx <= 0 else 16
        # Alterna el lado de la curva usando el signo de (x1+y1) para separar
        # aristas que comparten el mismo tramo horizontal.
        lado = 1 if (int(x1 + y1) % 2 == 0) else -1
        cx, cy = mx + nx * curvatura * lado, my + ny * curvatura * lado

        canvas.create_line(
            x1, y1, cx, cy, x2, y2,
            smooth=True, splinesteps=24,
            fill="#596174", width=2, arrow="last",
        )
        canvas.create_rectangle(cx - 10, cy - 10, cx + 10, cy + 10, fill="#ffffff", outline="")
        canvas.create_text(cx, cy, text=etiqueta, font=("Consolas", 10, "bold"), fill="#7c3aed")

    def dibujar_uno(self, canvas, afn, offset_x, offset_y, expresion, cadena, acepta):
        posiciones, ancho, alto = calcular_posiciones(afn, self.espacio_x, self.espacio_y, self.margen)
        pos = {estado: (x + offset_x + 60, y + offset_y + 46) for estado, (x, y) in posiciones.items()}

        resultado_txt = "si" if acepta else "no"
        color_resultado = "#15803d" if acepta else "#b91c1c"
        canvas.create_text(
            offset_x + 10, offset_y + 16, anchor="w",
            text=f"r = {expresion}", fill="#111827", font=("Segoe UI", 12, "bold"),
        )
        canvas.create_text(
            offset_x + 10, offset_y + 36, anchor="w",
            text=f"w = '{cadena}'   ->   ¿w \u2208 L(r)?", fill="#374151", font=("Consolas", 10),
        )
        canvas.create_text(
            offset_x + 260, offset_y + 36, anchor="w",
            text=resultado_txt, fill=color_resultado, font=("Segoe UI", 11, "bold"),
        )

        # Agrupar transiciones que van del mismo estado al mismo estado
        # (por ejemplo, una clase de caracteres genera varios simbolos
        # entre el mismo par de estados) para dibujar una sola arista.
        etiquetas_arista = defaultdict(list)
        for u, lista in afn.transiciones.items():
            for simbolo, v in lista:
                etiquetas_arista[(u, v)].append("\u03b5" if simbolo is None else simbolo)

        for (u, v), simbolos in etiquetas_arista.items():
            etiqueta = ",".join(dict.fromkeys(simbolos))  # unicos, en orden
            self.dibujar_arista(canvas, pos[u], pos[v], etiqueta)

        for estado in afn.estados:
            x, y = pos[estado]
            self.dibujar_estado(canvas, x, y, estado, estado == afn.inicial, estado == afn.aceptacion)

        return ancho + 60, alto + 60

    def mostrar(self):
        import tkinter as tk

        if not self.resultados:
            return

        ventana = tk.Tk()
        ventana.title("AFNs generados con el algoritmo de Thompson")
        ventana.geometry("1200x760")

        marco = tk.Frame(ventana)
        marco.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(marco, bg="#ffffff")
        scroll_y = tk.Scrollbar(marco, orient=tk.VERTICAL, command=canvas.yview)
        scroll_x = tk.Scrollbar(ventana, orient=tk.HORIZONTAL, command=canvas.xview)
        canvas.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll_x.pack(side=tk.BOTTOM, fill=tk.X)

        offset_y = 0
        ancho_total = 1200
        for expresion, cadena, afn, acepta in self.resultados:
            ancho, alto = self.dibujar_uno(canvas, afn, 20, offset_y, expresion, cadena, acepta)
            ancho_total = max(ancho_total, ancho)
            offset_y += alto
            canvas.create_line(10, offset_y - 20, ancho_total - 10, offset_y - 20, fill="#e5e7eb")

        canvas.configure(scrollregion=(0, 0, ancho_total, offset_y))
        ventana.mainloop()


# ---------------------------------------------------------------------------
# 4. LECTURA DE ARCHIVO Y PROGRAMA PRINCIPAL
# ---------------------------------------------------------------------------

def leer_lineas(ruta):
    try:
        with open(ruta, "r", encoding="utf-8") as archivo:
            return [linea.rstrip("\n") for linea in archivo]
    except FileNotFoundError:
        print(f"Error: no se encontro el archivo '{ruta}'")
        sys.exit(1)


def configurar_salida_utf8():
    """Permite imprimir simbolos como epsilon en consolas Windows."""
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(encoding="utf-8")


def limpiar_linea(linea):
    linea = linea.strip()
    # Por si el archivo trae numeracion tipo "(a) (a*|b*)+", se descarta el prefijo.
    return re.sub(r"^\([A-Za-z0-9]+\)\s+", "", linea)


def procesar(ruta_expresiones, ruta_cadenas=None):
    lineas = [limpiar_linea(l) for l in leer_lineas(ruta_expresiones)]
    expresiones = [l for l in lineas if l and not l.startswith("#")]

    cadenas = None
    if ruta_cadenas:
        cadenas = [l.strip() for l in leer_lineas(ruta_cadenas)]

    resultados = []
    for indice, expresion in enumerate(expresiones):
        print("=" * 80)
        print(f"Expresion regular: {expresion}")

        try:
            ast_basico = construir_ast_basico(expresion)
        except ValueError as error:
            print(f"  ERROR al construir el arbol: {error}")
            continue

        try:
            afn = construir_afn(ast_basico)
        except ValueError as error:
            print(f"  ERROR al aplicar Thompson: {error}")
            continue

        num_transiciones = sum(len(v) for v in afn.transiciones.values())
        print(f"  AFN construido: {len(afn.estados)} estados, {num_transiciones} transiciones")
        print(f"  estado inicial: q{afn.inicial}    estado de aceptacion: q{afn.aceptacion}")

        if cadenas is not None:
            cadena = cadenas[indice] if indice < len(cadenas) else ""
        else:
            cadena = input(f"  Ingrese la cadena w a evaluar para '{expresion}': ")

        acepta = afn.acepta(cadena)
        print(f"  w = '{cadena}'  ->  {'si' if acepta else 'no'} pertenece a L(r)")

        resultados.append((expresion, cadena, afn, acepta))

    print("=" * 80)
    return resultados


def main():
    configurar_salida_utf8()

    if len(sys.argv) < 2:
        print("Uso: python thompson_afn.py <expresiones.txt> [cadenas.txt] [--no-gui]")
        sys.exit(1)

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    no_gui = "--no-gui" in sys.argv

    ruta_expresiones = args[0]
    ruta_cadenas = args[1] if len(args) > 1 else None

    resultados = procesar(ruta_expresiones, ruta_cadenas)

    if resultados and not no_gui:
        DibujadorAFN(resultados).mostrar()


if __name__ == "__main__":
    main()
