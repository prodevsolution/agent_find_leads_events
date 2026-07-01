# SLMs para Ollama — Structured JSON Output

## Problema

El scraper usa `with_structured_output()` (vía `_invoke_structured` en `graph.py`) para extraer leads en JSON.
Modelos muy pequeños (<5B params, ej: `qwen3.5:4b`) no generan JSON válido incluso con `format="json"`.

## SLMs recomendados (Junio 2026)

### Tabla comparativa

| Modelo | Params | Download | Context | RAM mín | JSON mode | Tool calling |
|--------|--------|----------|---------|---------|-----------|--------------|
| `llama3.1:8b` | 8B | 4.7 GB | 128K | 8 GB | Excelente | Excelente |
| `qwen3:8b` | 8B | 5.2 GB | 40K | 8 GB | Excelente | Buena |
| `dolphin3:8b` | 8B | 4.9 GB | 128K | 8 GB | Excelente | Excelente |
| `phi4:14b` | 14B | 9.1 GB | 16K | 12 GB | Excelente | Buena |
| `qwen3.5:9b` | 9B | 5.8 GB | 128K | 8 GB | Buena | Buena |
| `gemma4:26b` | 26B MoE | 18 GB | 256K | 24 GB | Excelente | Excelente |

### Recomendación principal: `llama3.1:8b`

Es el modelo más probado para structured JSON output. Meta lo diseñó con tool calling nativo, y Ollama lo soporta al 100% con `format="json"`. Es el que usan los benchmarks de referencia.

### Alternativa rápida: `dolphin3:8b`

Fine-tune de Llama 3.1 8B especializado en **agentic/function calling**. Misma RAM, misma confiabilidad, ligeramente mejor en tareas de extracción estructurada.

## Cómo cambiar

Solo actualiza el `.env`:

```env
LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.1:8b
```

Luego descarga el modelo:

```powershell
ollama pull llama3.1:8b
```

## Por qué estos modelos sí funcionan

1. **`format="json"`** — Ollama fuerza la generación a JSON a nivel de tokens (Grammar-Constrained). El modelo no puede emitir texto no-JSON.
2. **Tamaño suficiente (≥7B)** — Modelos ≥7B params tienen la capacidad de seguir schemas complejos como `ExtractedLeads` (8+ campos anidados). Modelos de 4B no.
3. **Tool calling nativo** — Llama 3.1+ y Qwen 3+ fueron entrenados con tool calling. `with_structured_output()` usa esto internamente para modelos ≥7B.

## Matriz de decisión

| Tu RAM | Mejor opción | Cómo |
|--------|-------------|------|
| 8 GB | `llama3.1:8b` | `ollama pull llama3.1:8b` |
| 12 GB | `phi4:14b` | `ollama pull phi4:14b` |
| 16 GB | `qwen3-coder:30b` | `ollama pull qwen3-coder:30b` |
| 24 GB+ | `gemma4:26b` | `ollama pull gemma4:26b` |
