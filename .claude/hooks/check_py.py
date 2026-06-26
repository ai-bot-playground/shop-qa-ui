#!/usr/bin/env python3
"""Hook PostToolUse: szybka kontrola składni Pythona po Edit/Write.

Czyta payload hooka (JSON na stdin), a jeśli edytowany plik to `.py`, kompiluje go
w pamięci (bez zapisu `.pyc`). Niezerowy kod wyjścia + komunikat na stderr informuje
Claude o błędzie składni (akcja edycji już się wykonała — to feedback, nie blokada).

Wymaga jedynie `python` na PATH. Pliki inne niż `.py` są ignorowane (exit 0).
"""
import json
import sys


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0  # brak/niepoprawny payload — nic nie robimy

    path = (data.get("tool_input") or {}).get("file_path", "")
    if not path.endswith(".py"):
        return 0

    try:
        with open(path, encoding="utf-8") as f:
            source = f.read()
        compile(source, path, "exec")  # bez doraise/py_compile → nie tworzy __pycache__
    except SyntaxError as exc:
        print(f"[hook] Błąd składni w {path}: {exc}", file=sys.stderr)
        return 2
    except OSError:
        return 0  # plik zniknął/nieczytelny — pomijamy

    return 0


if __name__ == "__main__":
    sys.exit(main())
