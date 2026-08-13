# Lab 4 - Algoritmo de Thompson

Este programa toma expresiones regulares y construye un AFN usando el algoritmo de Thompson. En palabras mas tranquilas: le das una regex, el programa arma el automata correspondiente y luego prueba si una cadena pertenece o no al lenguaje de esa expresion.

Tambien puede dibujar los AFN en una ventana usando Tkinter, para que no todo se quede solo en texto de consola. Bastante util cuando uno quiere ver que esta pasando con los estados, las transiciones epsilon y todo ese relajo bonito de teoria de la computacion.

## Que hace

- Lee expresiones regulares desde un archivo `.txt`.
- Convierte cada expresion a un arbol sintactico basico.
- Aplica el algoritmo de Thompson para construir el AFN.
- Evalua cadenas de prueba para decir si pertenecen a la expresion regular.
- Opcionalmente muestra una interfaz grafica con el automata dibujado.

## Archivos principales

- `Thompson.py`: contiene todo el programa.
- `expresiones.txt`: archivo con las expresiones regulares a procesar.
- `cadenas_ejemplo.txt`: cadenas que se prueban contra cada expresion.

## Como usarlo

Para correrlo con interfaz grafica:

```bash
python Thompson.py expresiones.txt cadenas_ejemplo.txt
```

Para correrlo solo en consola, sin abrir la ventana:

```bash
python Thompson.py expresiones.txt cadenas_ejemplo.txt --no-gui
```

Si no mandas un archivo de cadenas, el programa te va preguntando manualmente que cadena quieres probar para cada expresion.

## Ejemplo de entrada

En `expresiones.txt` puedes tener cosas como:

```txt
(a*|b*)+
((epsilon|a)|b*)*
(a|b)*abb(a|b)*
0?(1?)?0*
```

Y en `cadenas_ejemplo.txt`:

```txt
aab
bb
aabba
101
```

## Video

Aqui esta el video de YouTube relacionado con el programa:

[https://youtu.be/7UMGgMGlxoc](https://youtu.be/7UMGgMGlxoc)

## Nota rapida

El programa soporta operadores comunes como union `|`, concatenacion implicita, estrella `*`, mas `+`, opcional `?`, repeticiones con `{}` y epsilon escrito como `epsilon`, `eps` o el simbolo griego epsilon.

La idea general es que este lab sirva para conectar la teoria con algo que si se pueda ejecutar, probar y visualizar sin tener que imaginarse todos los estados en la cabeza.
