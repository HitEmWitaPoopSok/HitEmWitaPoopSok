"""Arithmetic and unit/currency conversion without asking a model to guess."""
import ast
import math
import operator

import httpx

import toolkit

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
        ast.FloorDiv: operator.floordiv}
_FUNCS = {"sqrt": math.sqrt, "abs": abs, "round": round, "sin": math.sin, "cos": math.cos,
          "tan": math.tan, "log": math.log, "log10": math.log10, "ln": math.log,
          "floor": math.floor, "ceil": math.ceil}
_CONST = {"pi": math.pi, "e": math.e}


def evaluate(expr: str) -> float:
    text = str(expr).lower().replace("×", "*").replace("÷", "/").replace("^", "**").replace(",", "")
    # "18% of 2340" and "18 percent of 2340"
    import re
    text = re.sub(r"(\d+(?:\.\d+)?)\s*(?:%|percent)\s*of\s*", r"(\1/100)*", text)
    text = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", text)
    if len(text) > 200:
        raise ValueError("That's too long")

    def walk(n):
        if isinstance(n, ast.Expression):
            return walk(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            a, b = walk(n.left), walk(n.right)
            if isinstance(n.op, ast.Pow) and (abs(b) > 100 or abs(a) > 1e9):
                raise ValueError("That power is too large")
            return _OPS[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            return -walk(n.operand) if isinstance(n.op, ast.USub) else walk(n.operand)
        if isinstance(n, ast.Name) and n.id in _CONST:
            return _CONST[n.id]
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS \
                and not n.keywords and len(n.args) <= 2:
            return _FUNCS[n.func.id](*[walk(a) for a in n.args])
        raise ValueError("I can only do arithmetic")

    try:
        return walk(ast.parse(text.strip(), mode="eval"))
    except (SyntaxError, ZeroDivisionError, OverflowError):
        raise ValueError("That doesn't work out")


def fmt(x: float) -> str:
    if isinstance(x, float) and x.is_integer() and abs(x) < 1e15:
        return str(int(x))
    return f"{x:.6g}" if abs(x) >= 1e-4 or x == 0 else f"{x:.3e}"


# unit -> (dimension, factor to the base unit)
_UNITS = {
    "mm": ("len", 0.001), "cm": ("len", 0.01), "m": ("len", 1), "km": ("len", 1000),
    "in": ("len", 0.0254), "inch": ("len", 0.0254), "inches": ("len", 0.0254),
    "ft": ("len", 0.3048), "foot": ("len", 0.3048), "feet": ("len", 0.3048),
    "yd": ("len", 0.9144), "mi": ("len", 1609.344), "mile": ("len", 1609.344), "miles": ("len", 1609.344),
    "g": ("mass", 1), "kg": ("mass", 1000), "mg": ("mass", 0.001), "lb": ("mass", 453.592),
    "lbs": ("mass", 453.592), "pound": ("mass", 453.592), "pounds": ("mass", 453.592),
    "oz": ("mass", 28.3495), "ounce": ("mass", 28.3495), "ounces": ("mass", 28.3495),
    "ml": ("vol", 1), "l": ("vol", 1000), "litre": ("vol", 1000), "liter": ("vol", 1000),
    "litres": ("vol", 1000), "liters": ("vol", 1000), "tsp": ("vol", 4.92892),
    "tbsp": ("vol", 14.7868), "cup": ("vol", 236.588), "cups": ("vol", 236.588),
    "pint": ("vol", 473.176), "pints": ("vol", 473.176), "gallon": ("vol", 3785.41),
    "gallons": ("vol", 3785.41), "floz": ("vol", 29.5735),
    "b": ("data", 1), "kb": ("data", 1e3), "mb": ("data", 1e6), "gb": ("data", 1e9), "tb": ("data", 1e12),
    "s": ("time", 1), "sec": ("time", 1), "min": ("time", 60), "mins": ("time", 60),
    "minutes": ("time", 60), "h": ("time", 3600), "hr": ("time", 3600), "hours": ("time", 3600),
    "day": ("time", 86400), "days": ("time", 86400), "week": ("time", 604800), "weeks": ("time", 604800),
    "mph": ("speed", 0.44704), "kph": ("speed", 0.277778), "kmh": ("speed", 0.277778), "mps": ("speed", 1),
}
_TEMP = {"c", "f", "k", "celsius", "fahrenheit", "kelvin"}


def convert_units(value: float, a: str, b: str) -> float:
    a, b = a.lower().strip().rstrip("."), b.lower().strip().rstrip(".")
    if a in _TEMP and b in _TEMP:
        a, b = a[0], b[0]
        c = value if a == "c" else (value - 32) * 5 / 9 if a == "f" else value - 273.15
        return c if b == "c" else c * 9 / 5 + 32 if b == "f" else c + 273.15
    if a not in _UNITS or b not in _UNITS:
        raise KeyError
    (da, fa), (db, fb) = _UNITS[a], _UNITS[b]
    if da != db:
        raise ValueError(f"I can't convert {da} to {db}")
    return value * fa / fb


async def handler(args: dict) -> str:
    if args.get("expression"):
        try:
            return f"{fmt(evaluate(args['expression']))}, sir."
        except ValueError as e:
            return f"{e}, sir."
    try:
        value = float(args.get("value"))
    except (TypeError, ValueError):
        return "Give me an expression, or a value and two units, sir."
    a, b = str(args.get("from") or ""), str(args.get("to") or "")
    try:
        return f"{fmt(convert_units(value, a, b))} {toolkit.clean(b, 20)}, sir."
    except KeyError:
        pass
    except ValueError as e:
        return f"{e}, sir."
    ca, cb = a.upper().strip(), b.upper().strip()
    if len(ca) == 3 and len(cb) == 3 and ca.isalpha() and cb.isalpha():
        try:
            async with httpx.AsyncClient(timeout=6.0) as http:
                r = await http.get("https://api.frankfurter.app/latest",
                                   params={"amount": value, "from": ca, "to": cb})
            rate = r.json()["rates"][cb]
            return f"{fmt(rate)} {cb} at today's rate, sir."
        except Exception:
            return "I couldn't get an exchange rate just now, sir."
    return "I don't know those units, sir."


toolkit.register(toolkit.Tool(
    name="calculate",
    description=("Exact arithmetic and conversion — never do sums in your head. "
                 "`expression` like '18% of 2340' or '(4+5)*3'; or `value`, `from`, "
                 "`to` for units (km, miles, kg, lb, cups, C/F, GB, minutes...) or "
                 "currencies (USD, EUR, GBP...)."),
    schema={"type": "object", "properties": {
        "expression": {"type": "string"}, "value": {"type": "number"},
        "from": {"type": "string"}, "to": {"type": "string"}}},
    handler=handler,
    exempt="it computes from numbers the user gave; a rate from the exchange API is a number"))
