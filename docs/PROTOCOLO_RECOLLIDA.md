<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# Protocolo de recollida e etiquetaxe (v1, 5 de outubro de 2026)

**Obxectivo:** que Hyd xeneralice a persoas que non viu. A auditoría do 5 de outubro mostrou o problema:
- cunha persoa xa vista no adestramento, o modelo acerta o 77–84 %;
- cunha persoa nova, o 52–73 %.

Faltan **persoas distintas** e **criterios iguais**, non máis preguntas das mesmas persoas.

## Fase 1 — tres persoas novas (empeza agora)

Cada persoa nova fai, por esta orde:

1. **Le a guía** (`docs/GUIA_ETIQUETAXE.md`), uns 15 minutos.
2. **Etiqueta o conxunto común:** 150 preguntas xa escritas, nunha folla Excel, cunha lista despregable de rutas. Uns 60–75 minutos.
   - Non se consulta con ninguén nin se miran as etiquetas doutras persoas.
3. **Escribe 250 preguntas propias**, 25 por ruta, na app de Hyd. Unhas 4–5 horas, en varias sesións.
   - Coa cota fixa, ningunha persoa enche o corpus só con dous ou tres tipos de pregunta.
   - Se a pregunta conta cunha imaxe ou captura, empeza por `[con captura]` (ou `[con foto]`, `[con documento]`), ou marca o campo da app cando exista.
   - Variedade: temas da súa vida e traballo, lonxitudes e tons distintos. Non copiar modelos, non numerar, non comezar todas igual.
   - Datos persoais sempre inventados.
4. **Consentimento:** o mesmo da app, "gardar neste sistema e usar para adestrar e avaliar Hyd". **Non** autoriza a publicar.

**Perfís:** o máis distintos posible entre si e respecto de Juan, Belén e Lois. Idade, profesión, nivel técnico e, se pode ser, unha persoa que escriba en galego.

## Fase 1 — persoas actuais

| Persoa | Tarefa | Tempo |
|---|---|---|
| Belén | `revision-pantalla-belen.xlsx`: 776 preguntas de pantalla coa regra nova. Confirma ou cambia a suxestión automática | ~3–4 h |
| Belén, Juan, Lois | Conxunto común (150), igual que as persoas novas | ~1 h cada unha |

A etiqueta orixinal nunca se borra. Cada cambio garda quen o fixo, a data, o motivo e a versión da guía.

## Que se mide con isto

- **Teito humano:** coas seis persoas no conxunto común sae a concordancia por clase e por parella (kappa de Fleiss e de Cohen).
  - Se as persoas coinciden nun 80 %, ese é o teito realista do modelo.
  - As clases con pouca concordancia indican que a guía está mal explicada.
- **Efecto da regra de pantalla:** comparar o LOPO antes e despois da revisión de Belén.
- **Efecto das persoas novas:** LOPO con 6 persoas. Cando cheguen, unha das novas queda reservada como test cego e non se usa para escoller nada.

## Cambio recomendado na app (Lovable)

Engadir ao formulario de pregunta un campo obrigatorio:

> **¿A pregunta viría cun adxunto?** ○ Non ○ Imaxe ou captura de pantalla ○ Documento ou PDF ○ Outro

e gardalo en `meta.attachment` (`none` | `image` | `document` | `other`). Sen app nova, abonda co prefixo
`[con captura]` no texto: o importador convérteo no mesmo campo.

## Ficheiros (privados, fóra de git)

`D:\HYDRA\data\private\hyd-anotacion-2026-10-05\`
- `conxunto-comun-150.xlsx`: para todas as persoas, sen etiquetas.
- `clave-conxunto-comun.json`: etiquetas orixinais (non se reparte).
- `revision-pantalla-belen.xlsx`: só para Belén.
