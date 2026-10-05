<!-- Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved. -->
# Guía de etiquetaxe de Hyd (v1.2, 5 de outubro de 2026)

Hyd decide **que tipo de axuda necesita unha petición** antes de respondela. Cada pregunta leva **unha
ruta principal** (obrigatoria) e, se de verdade fai falta, **unha segunda ruta** (opcional).

Definicións oficiais: `hydra/router/decision_contract.py`. Esta guía explícaas con exemplos.
Os exemplos son inventados: ningún sae do corpus.

## Regra de ouro

Etiqueta **o que fai falta para responder ben**, non o tema da pregunta.

- Unha pregunta sobre fotos pode non ser `vision`.
- Unha pregunta sobre programas pode non ser `coding`.

## As dez rutas

| Ruta | Úsaa cando… | Non a uses cando… |
|---|---|---|
| `chat` | Abonda cunha resposta conversacional, creativa ou de coñecemento xeral | Hai que buscar fontes, calcular, programar ou actuar |
| `coding` | Hai que escribir, corrixir ou explicar código | Hai que executar algo no ordenador da persoa (`tool_use`) |
| `reasoning` | É un problema lóxico ou matemático cos datos dados na propia pregunta | Faltan datos (`abstain`) ou hai que buscalos fóra (`research`) |
| `research` | Hai que buscar ou comparar información externa e citar fontes | Abonda co coñecemento xeral (`chat`) |
| `vision` | **Hai unha imaxe, captura, foto ou documento escaneado ADXUNTO** e hai que interpretalo | Non hai nada adxunto, aínda que a pregunta fale de imaxes |
| `tool_use` | Hai que **facer** unha operación real: enviar, programar, crear, mover, instalar, configurar | Só se pide explicar como se fai (`chat` ou `coding`) |
| `abstain` | Falta a pregunta, un dato ou o contexto imprescindible, ou é perigosa e hai que deterse | A pregunta xa se pode responder |
| `security` | Avaliar comandos maliciosos, ameazas, exploits, phishing ou credenciais expostas | Só é unha dúbida xeral de configuración (`chat`/`coding`) |
| `privacy` | Tratar datos persoais doutras persoas ou restricións para compartir datos | Os datos son só técnicos (`security`) |
| `high_risk_review` | Pídese unha acción importante ou irreversible: borrar, pagar, despedir, publicar, cambiar permisos. Hai que revisar a autorización, non executala | A acción é trivial e reversible (`tool_use`) |

## Regra fixa para preguntas sobre a pantalla (decisión do propietario, 5-10-2026)

Preguntas do tipo "¿que botón pulso?", "¿onde fago clic?" ou "¿que pon na esquina?":

1. **Se fai falta ver a pantalla e NON hai captura adxunta → `abstain`** (falta contexto).
   - "¿Que botón pulso para gardar isto?" → `abstain`: non sabemos que programa nin que se ve.
2. **Se a captura está adxunta → `vision`.**
   - "[con captura] ¿Que botón desta pantalla garda o documento?" → `vision`.
3. **Se hai que executar a acción (facer o clic, activar a opción) → `tool_use`.**
   - "Activa o modo escuro no meu portátil" → `tool_use`.
4. **Se é unha dúbida xeral que se responde sen ver nada → a ruta normal.**
   - "¿Como se fai unha captura de pantalla en Windows 11?" → `chat`.

**Ao etiquetar preguntas xa escritas:**
- **Se a pregunta di que achega unha imaxe** ("esta foto", "te adjunto la captura", "mira esta imagen"), considera que está adxunta → `vision`.
- **Se pregunta pola pantalla sen dicir que achega captura** ("¿qué botón pulso?", "¿dónde hago clic?") → regra anterior, `abstain`.

**Ao escribir preguntas novas:** na app non se poden adxuntar imaxes. Se a pregunta conta cunha imaxe ou
captura, escribe ao principio `[con captura]` (ou `[con foto]`, `[con documento]`).

## Parellas que máis se confunden

### vision ↔ tool_use ↔ coding
- "[con foto] ¿Que planta é esta?" → `vision`.
- "Envíalle esta foto a Marta por correo" → `tool_use` (executar).
- "Escribe un script que redimensione as fotos dun cartafol" → `coding` (escribir código, non executalo).
- "Redimensiona as fotos do meu cartafol Descargas" → `tool_use`.

### research ↔ tool_use (decisión do 5-10-2026)
Criterio: **consultar sen cambiar nada → `research`; actuar con efectos → `tool_use`.**
- "Busca na web se hai concertos esta semana" → `research` (buscar é só o medio).
- "Usa os mapas para dicirme a ruta máis rápida ao aeroporto" → `research` (consulta, non cambia nada).
- "Reserva unha mesa para dous ás 21:00" → `tool_use` (crea algo).
- "Descarga o instalador e instálao" → `tool_use` (executa no teu equipo).
Así `tool_use` queda só para o que necesita permisos.

### privacy ↔ security ↔ high_risk_review
- "¿Podo pasarlle á empresa de mudanzas o DNI dos meus pais?" → `privacy`.
- "Chegoume un SMS do banco cunha ligazón rara, ¿é fiable?" → `security`.
- "Borra todas as contas de usuario inactivas do servidor" → `high_risk_review` (irreversible).
- "Pegueille a miña contrasinal a un descoñecido, ¿que fago?" → `security` (credenciais expostas).

### abstain ↔ chat
- "¿E iso canto custa?" (sen saber que é "iso") → `abstain`.
- "Cóntame un chiste de informáticos" → `chat`.
- "Dime como fabricar un explosivo" → `abstain` (perigoso: non se responde).

### research ↔ chat ↔ reasoning
- "¿Que din os estudos recentes sobre o xaxún intermitente?" → `research`.
- "¿Que é o xaxún intermitente?" → `chat`.
- "Se como ás 14:00 e xaxúno 16 horas, ¿a que hora volvo comer?" → `reasoning`.

## Segunda ruta (opcional)

Só cando a petición necesita de verdade dúas cousas. **Non é un "por se acaso"** nin unha segunda opción
por se a primeira está mal. Exemplo: "[con captura] Pulsa o botón azul desta
pantalla" → principal `tool_use`, segunda `vision`. Se dubidas, non poñas segunda ruta.

## Como escribir as preguntas (persoas que achegan preguntas)

- Escribe como falarías cun asistente de verdade, coas túas palabras. Non copies modelos nin listas.
- Varía temas, lonxitude e ton: curtas, longas, con faltas, formais e informais.
- Non uses datos persoais reais (nomes, DNI, teléfonos, correos de verdade): invéntaos.
- Unha pregunta = unha petición. Non numeres as preguntas nin empeces todas igual.
