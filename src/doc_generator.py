"""Documentation generation (Mandatory M3) + module overview (bonus).

Calls Claude via llm_complete() to generate structured docs per function
and 2-3 sentence module summaries.
"""
from __future__ import annotations

import json
import re

from src.contracts import CodeChunk, FunctionDoc, ModuleOverview


def generate_docs(chunk: CodeChunk) -> FunctionDoc:
    """Generate purpose/parameters/returns/gotchas for a function chunk (M3)."""
    from src.agent import llm_complete
    import os

    if chunk.kind != "function":
        raise ValueError(f"generate_docs expects a function, got kind={chunk.kind!r}")

    model = os.environ.get("LLM_MODEL_FAST", "claude-haiku-4-5-20251001")
    user_prompt = f"""Analyze this Python function and respond with ONLY a JSON object:

```python
{chunk.source}
```

JSON schema:
{{
  "purpose": "one sentence: what this function does",
  "parameters": "comma-separated parameter descriptions with types/roles",
  "returns": "what is returned and its shape/type",
  "gotchas": "surprising behaviour, side effects, or edge cases (empty string if none)"
}}

Respond in the same language as the code comments (Polish if comments are Polish, otherwise English).
Return ONLY the JSON object, no other text.
"""
    try:
        raw = llm_complete("You are a code documentation expert.", user_prompt, model=model)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            raise ValueError("No JSON in response")
        data = json.loads(m.group(0))
        return FunctionDoc(
            file=chunk.file,
            symbol=chunk.symbol,
            purpose=data.get("purpose", ""),
            parameters=data.get("parameters", ""),
            returns=data.get("returns", ""),
            gotchas=data.get("gotchas", ""),
        )
    except Exception as e:
        return FunctionDoc(
            file=chunk.file,
            symbol=chunk.symbol,
            purpose=f"(doc generation failed: {e})",
            parameters="—",
            returns="—",
            gotchas="",
        )


def generate_module_overview(file: str, chunks: list[CodeChunk]) -> ModuleOverview:
    """Generate a 2-3 sentence NL summary for a file (bonus) + coverage counters."""
    from src.agent import llm_complete
    import os

    in_file = [c for c in chunks if c.file == file]
    funcs = [c for c in in_file if c.kind == "function"]
    constants = [c for c in in_file if c.kind == "constant"]
    documented = len(funcs)  # all functions are documented in this run

    if not in_file:
        return ModuleOverview(file=file, summary=f"Moduł {file.split('/')[-1]}.",
                              function_count=0, documented_count=0)

    sources = "\n\n".join(
        f"# {c.symbol} ({c.kind})\n{c.source[:300]}" for c in in_file[:10]
    )
    const_names = [c.symbol for c in constants]
    model = os.environ.get("LLM_MODEL_FAST", "claude-haiku-4-5-20251001")
    user_prompt = f"""Given these code units from file '{file}':

{sources}

Write a 2-3 sentence summary of what this module does, its role in the system,
and any important constants or behaviors ({', '.join(const_names) if const_names else 'no module constants'}).
Respond in Polish. Return ONLY the summary text, no JSON.
"""
    try:
        summary = llm_complete("You are a code documentation expert.", user_prompt, model=model).strip()
    except Exception as e:
        summary = f"Moduł {file.split('/')[-1]}. (overview generation failed: {e})"

    return ModuleOverview(
        file=file,
        summary=summary,
        function_count=len(funcs),
        documented_count=documented,
    )
