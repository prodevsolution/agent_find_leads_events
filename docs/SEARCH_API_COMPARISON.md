# Web Search API — Comparativa Tavily vs SerpAPI

## Contexto

El sistema multi-agente de prospección ejecuta búsquedas web automáticas para encontrar eventos, operadores, y leads de clientes potenciales. Necesitamos al menos una API de búsqueda activa para que el sistema funcione.

---

## Proveedores Actuales

| Característica | **Tavily** (primario) | **SerpAPI** (fallback) |
|---|---|---|
| **Motor** | Propietario (optimizado para AI/LLM) | Google Search |
| **Plan gratis** | 1,000 búsquedas/mes | 100 búsquedas/mes |
| **Plan pago** | Growth: $20/mes → 5,000 búsquedas | Starter: $50/mes → 5,000 búsquedas |
| **Trial** | 7 días free | ✗ |
| **API Key** | Sí (actual) | Sí (actual) |
| **raw_content** | Sí (texto completo de página) | No (solo snippet) |
| **exclude_domains** | Sí | No |

---

## Estado Actual

| API | Estado |
|---|---|
| **Tavily** | 🔴 **Límite excedido** (error 432) — responde con `"This feature is being deprecated and can no longer be enabled."` |
| **SerpAPI** | 🟢 **Activa y funcionando** como fallback |

Actualmente el sistema cae a SerpAPI automáticamente cuando Tavily falla.

---

## Recomendación

### Opción A: Subir Tavily a Growth ($20/mes)

| Pro | Contra |
|---|---|
| raw_content (texto completo de página scraping) | Sin prueba gratuita |
| exclude_domains (filtro de sitios no deseados) | — |
| Diseñado para AI/agents | — |
| Más barato que SerpAPI | — |

### Opción B: Contratar SerpAPI Starter ($50/mes)

| Pro | Contra |
|---|---|
| Resultados reales de Google | 2.5× más caro que Tavily |
| | Sin raw_content (solo snippets) |
| | Sin exclude_domains |

### Opción C: Ambos (inversión total: $70/mes)

| Pro | Contra |
|---|---|
| Redundancia completa | Mayor costo |
| Tavily para profundidad, SerpAPI como respaldo | — |

---

## Conclusión

**Opción recomendada: Tavily Growth ($20/mes)**

- Es el plan más económico
- Tiene `raw_content` (texto completo de cada página, no solo snippet) — esto mejora la calidad del lead
- Tiene `exclude_domains` para evitar sitios como Eventbrite, Ticketmaster, etc.
- Al ser diseño para AI/LLMs, los resultados son más relevantes para nuestro caso de uso

Con $20/mes recuperamos la funcionalidad completa. SerpAPI se mantiene como respaldo gratuito (100 búsquedas/mes) para emergencias.
