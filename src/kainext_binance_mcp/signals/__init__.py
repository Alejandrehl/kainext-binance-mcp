"""Capa 4: motor de señales (read-only, PROPONE — nunca ejecuta).

Combina indicadores (capa 2) + sentiment (capa 3) + ATR en una señal transparente y
honesta. El núcleo (``engine``) es PURO: recibe valores ya calculados y devuelve un
``Signal`` con la contribución de cada factor al score. Toda ejecución es capa 1 (gate humano).
"""
