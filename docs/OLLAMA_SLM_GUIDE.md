# SLMs para Ollama — Structured JSON Output

## Problema

El scraper usa `with_structured_output()` (vía `_invoke_structured` en `graph.py`) para extraer leads en JSON.
Modelos muy pequeños (<3B params, ej: `qwen3.5:4b`) no generan JSON válido incluso con `format="json"`.

## SLMs recomendados (Julio 2026)

### Tabla comparativa

| Modelo | Params | Download | Context | RAM real¹ | JSON mode | Tool calling |
|--------|--------|----------|---------|-----------|-----------|--------------|
| `llama3.2:3b` | 3.2B | 2.0 GB | 128K | **8 GB** ✅ | Excelente | Excelente |
| `llama3.1:8b` | 8B | 4.7 GB | 128K | 16 GB | Excelente | Excelente |
| `qwen3:8b` | 8B | 5.2 GB | 40K | 16 GB | Excelente | Buena |
| `dolphin3:8b` | 8B | 4.9 GB | 128K | 16 GB | Excelente | Excelente |
| `phi4:14b` | 14B | 9.1 GB | 16K | 24 GB | Excelente | Buena |
| `qwen3.5:9b` | 9B | 5.8 GB | 128K | 16 GB | Buena | Buena |
| `gemma4:26b` | 26B MoE | 18 GB | 256K | 32 GB | Excelente | Excelente |

> ¹ RAM real = memoria total del servidor requerida para operación estable con el modelo + app Python + scraping simultáneos. Los modelos 8B cargan ~5.4 GB solo en parámetros, dejando <2 GB para el resto en un servidor de 8 GB, causando swapping severo y cuelgues.

### Recomendación principal: `llama3.2:3b`

Es la mejor opción para servidores con **8 GB de RAM**. A diferencia de `qwen3.5:4b` (que falla generando JSON), `llama3.2:3b`:

- Usa solo **~2 GB** de RAM, dejando 6 GB libres para Python + scraping.
- Soporta `format="json"` (Grammar-Constrained Decoding) correctamente.
- Fue entrenado con **tool calling nativo** (como `llama3.1:8b` pero en formato pequeño).
- Genera JSON estructurado confiable para `ExtractedLeads` (8+ campos).

En servidores de 8 GB, `llama3.2:3b` **rinde mejor que `llama3.1:8b`**, porque:
- `llama3.1:8b` consume ~70% de la RAM y fuerza swapping → inferencia 10× más lenta.
- `llama3.2:3b` deja RAM suficiente para que el scraper y el extractor operen sin contención.

### Alternativa para más RAM: `llama3.1:8b` o `dolphin3:8b`

Si tu servidor tiene **≥16 GB RAM**, prefiere `llama3.1:8b` (el estándar de la industria para JSON estructurado) o `dolphin3:8b` (fine-tune especializado en agentic/function calling).

## Cómo cambiar

Solo actualiza el `.env`:

```env
LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.2:3b
```

Luego descarga el modelo:

```bash
ollama pull llama3.2:3b
```

Reemplaza el modelo anterior para liberar espacio:

```bash
ollama rm llama3.1:8b
```

## Por qué estos modelos sí funcionan

1. **`format="json"`** — Ollama fuerza la generación a JSON a nivel de tokens (Grammar-Constrained). El modelo no puede emitir texto no-JSON.
2. **Tool calling nativo** — Llama 3.2+ y Llama 3.1+ fueron entrenados con tool calling. `with_structured_output()` usa esto internamente.
3. **Tamaño suficiente (≥3B)** — A diferencia de modelos de 4B con mal soporte JSON, `llama3.2:3b` fue entrenado específicamente para seguir schemas estructurados.

## Matriz de decisión

| RAM del servidor | Mejor opción | Alternativa |
|-----------------|-------------|-------------|
| 8 GB | `llama3.2:3b` | — |
| 12 GB | `phi4:14b` | `llama3.1:8b` |
| 16 GB | `llama3.1:8b` | `qwen3:8b` |
| 24 GB+ | `gemma4:26b` | `phi4:14b` |
