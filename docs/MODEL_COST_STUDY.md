# Estudio de Modelos — Costos y Recomendación para Prospección de Leads

## Proyecto: Sistema Multi-Agente de Prospección de Eventos

### Perfil de uso típico
- **Requests por workflow**: 25–35 llamadas al LLM
- **Tokens por request**: ~5K–10K input, ~500–1K output (con SCRAPER_CONTENT_LIMIT=2000)
- **Tokens totales por ejecución**: ~150K–350K input, ~15K–35K output
- **Ejecuciones por mes**: ~120 (4/día × 30 días, automático + manuales)
- **Tokens mensuales**: ~18M–42M input, ~1.8M–4.2M output

---

## 1. Modelos Local (SLM) — vía Ollama

### Costo: $0 (solo electricidad/hardware)

| Modelo | Params | RAM req | Contexto | JSON mode | Tool calling | Rendimiento |
|--------|--------|---------|----------|-----------|--------------|-------------|
| **llama3.1:8b** | 8B | 8 GB | 128K | Excelente | Excelente | Alto |
| **dolphin3:8b** | 8B | 8 GB | 128K | Excelente | Excelente (fine-tune) | Alto |
| **phi4:14b** | 14B | 12 GB | 16K | Excelente | Buena | Muy alto |
| **qwen3:8b** | 8B | 8 GB | 40K | Excelente | Buena | Alto |
| **gemma4:26b** | 26B MoE | 24 GB | 256K | Excelente | Excelente | Máximo |

**Ventajas**: Sin cuotas, sin 429/503, sin filtraciones de datos, sin costos operativos mensuales.

---

## 2. Modelos Frontera (API)— Costo por 1M tokens

### Gemini (Google)

| Modelo | Input | Output | Contexto | Free tier | Notas |
|--------|-------|--------|----------|-----------|-------|
| **gemini-2.5-flash** | $0.30 | $2.50 | 1M | 20 req/día, 250K TPM | Activo hasta Oct 2026 |
| **gemini-2.5-flash-lite** | $0.10 | $0.40 | 1M | mismo límite | Más barato, menos capaz |
| **gemini-3.5-flash** | $1.50 | $9.00 | 1M | mismo límite | Alta demanda (503s frecuentes) |

### OpenAI

| Modelo | Input | Output | Contexto | Free tier | Notas |
|--------|-------|--------|----------|-----------|-------|
| **gpt-4o-mini** | $0.15 | $0.60 | 128K | Trial $5 | Ideal relación calidad/precio |
| **gpt-4o** | $2.50 | $10.00 | 128K | Trial $5 | Legacy pero confiable |
| **gpt-4.1-mini** | $0.40 | $1.60 | 1M | Trial $5 | Nuevo, mejor contexto |
| | | | | |
| ***Modelos ChatGPT web (API)*** | | | | |
| **gpt-4.1** | $2.00 | $8.00 | 1M | Trial $5 | Recomendado reemplazo de gpt-4o |
| **gpt-5.4** | $2.50 | $15.00 | 400K | Trial $5 | Calidad ChatGPT web en API |
| **gpt-5.5** | $5.00 | $30.00 | 400K | Trial $5 | Frontier, misma calidad que ChatGPT |
| **gpt-5.6 Luna** | $1.00 | $6.00 | — | Trial $5 | Nueva familia, balance |
| **gpt-5.6 Terra** | $2.50 | $15.00 | — | Trial $5 | Equivalente a gpt-5.4 |
| **gpt-5.6 Sol** | $5.00 | $30.00 | — | Trial $5 | Flagship, mejor de OpenAI |

### Claude (Anthropic)

| Modelo | Input | Output | Contexto | Free tier | Notas |
|--------|-------|--------|----------|-----------|-------|
| **claude-haiku-4.5** | $1.00 | $5.00 | 200K | Créditos trial | Rápido, económico |
| **claude-sonnet-4.6** | $3.00 | $15.00 | 1M | Créditos trial | Mejor balance |
| **claude-opus-4.8** | $5.00 | $25.00 | 1M | Créditos trial | Lo mejor de Anthropic |

### Qwen (Alibaba — API Cloud)

| Modelo | Input | Output | Contexto | Free tier | Notas |
|--------|-------|--------|----------|-----------|-------|
| **qwen-flash** | $0.05 | $0.40 | 1M | 1M tokens único | Más barato del mercado |
| **qwen-plus** | $0.40 | $1.20 | 1M | 1M tokens único | Buen balance |
| **qwen3.7-max** | $2.50 | $7.50 | 1M | 1M tokens único | Flagship |

---

## 3. Costo mensual estimado por modelo

(120 ejecuciones/mes, ~250K input + 25K output por ejecución = ~30M input + 3M output/mes)

| Modelo | Costo input | Costo output | **Total mes** |
|--------|------------|-------------|--------------|
| **Ollama (llama3.1:8b)** | $0 | $0 | **$0** |
| **gemini-2.5-flash** (free) | $0 (20 req/día) | $0 | **$0** (pero limitado) |
| **gemini-2.5-flash-lite** (pago) | $3.00 | $1.20 | **~$4.20** |
| **gpt-4o-mini** | $4.50 | $1.80 | **~$6.30** |
| **gpt-4.1-mini** | $12.00 | $4.80 | **~$16.80** |
| **claude-haiku-4.5** | $30.00 | $15.00 | **~$45.00** |
| **qwen-flash** | $1.50 | $1.20 | **~$2.70** |
| **gemini-2.5-flash** (pago) | $9.00 | $7.50 | **~$16.50** |
| **gpt-4o** | $75.00 | $30.00 | **~$105.00** |
| **claude-sonnet-4.6** | $90.00 | $45.00 | **~$135.00** |
| | | | |
| ***ChatGPT web via API*** | | | |
| **gpt-4.1** | $60.00 | $24.00 | **~$84.00** |
| **gpt-5.4** | $75.00 | $45.00 | **~$120.00** |
| **gpt-5.5** | $150.00 | $90.00 | **~$240.00** |
| **gpt-5.6 Luna** | $30.00 | $18.00 | **~$48.00** |
| **gpt-5.6 Terra** | $75.00 | $45.00 | **~$120.00** |
| **gpt-5.6 Sol** | $150.00 | $90.00 | **~$240.00** |

---

## 4. Problemas encontrados con cada proveedor

| Proveedor | Problema |
|-----------|----------|
| **OpenAI** | Key sin créditos (429 insufficient_quota) |
| **Gemini** | 20 req/día free tier (429), 503s en modelos nuevos |
| **Claude** | Costoso, sin free tier significativo |
| **Qwen** | Free tier limitado a 1M tokens único, requiere tarjeta |

---

## 5. Recomendación final

### Para producción ahora (Julio 2026):

| Prioridad | Opción | Costo/mes | Riesgo |
|-----------|--------|-----------|--------|
| 🥇 | **Ollama + llama3.1:8b** | **$0** | Ninguno |
| 🥈 | **Qwen-flash API** ($0.05/$0.40) | ~$2.70 | Bajo |
| 🥉 | **gpt-4o-mini** ($0.15/$0.60) | ~$6.30 | Medio (créditos) |
| 4 | **gemini-2.5-flash-lite pago** | ~$4.20 | Bajo (con pago) |

### Decisión estratégica:

**Ollama con `llama3.1:8b` es la opción óptima** para este proyecto porque:
1. **Costo $0** — sin límites de requests, sin 429, sin 503
2. **`format="json"`** forza JSON válido (Grammar-Constrained Decoding)
3. **8B params** es suficiente para extracción estructurada de leads
4. **No requiere internet** ni depende de servidores externos
5. **Sin riesgo de filtración de datos** de clientes

Si se quiere redundancia, agregar **gpt-4o-mini** como fallback por ~$6.30/mes. Esto ya está implementado en la lógica de `_invoke_structured()` en `graph.py`.
