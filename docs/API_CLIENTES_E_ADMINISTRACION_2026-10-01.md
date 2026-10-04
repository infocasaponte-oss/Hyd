# Informe: acceso de CeltIA e Nova AI a HYDRA

Copyright (c) 2026 Luis Manuel Cousido Hermida. Todos los derechos reservados.

Data: 1 de outubro de 2026.

## Cambios realizados

- Eliminouse CELTIA_ADMIN_TOKEN do .env de HYDRA.
- Configurouse HYDRA_ADMIN_TOKEN local, separado das claves dos clientes.
- Creáronse claves individuais para celtia e nova-ai, cun límite de 30 peticións
  por minuto por cliente e proceso, limitado tamén polo máximo global configurado.
- O rexistro data/keys/api-clients.json garda só o identificador público da
  clave e un hash scrypt con sal propia (formato da credencial:
  `hydra.<key_id>.<segredo>`). Lese en cada autenticación: a revogación e a
  rotación aplícanse sen reiniciar.
- As claves permiten POST /v1/chat/completions, POST /v1/responses e GET /v1/models.
  Bloquéanse tarefas, WebSocket de tarefas, ferramentas directas e administración.
- Un token descoñecido ou revogado non pode aproveitar o acceso local sen clave.
- Mantense a clave xeral HYDRA_API_KEY para compatibilidade co operador.
- Reconstruíuse hydra-sandbox:py312-v3 e verificouse nun contedor sen rede:
  Python 3.12.14, pytest 9.1.1, pytest-asyncio 1.4.0, UID 65532.

## Credenciais e conexión

As credenciais están en ficheiros ignorados por Git:

- D:\HYDRA\data\secrets\client-credentials\celtia.env
- D:\HYDRA\data\secrets\client-credentials\nova-ai.env

Cada ficheiro contén HYDRA_BASE_URL e HYDRA_API_KEY. Deben cargarse no backend
da aplicación correspondente, nunca no JavaScript público do navegador.
O token administrativo non se comparte con esas aplicacións.

URL local prevista: http://127.0.0.1:18088/v1. Hai que reiniciar o gateway
para cargar o código novo e o token administrativo; este cambio non reinicia
Studio automaticamente nin modifica os repositorios de CeltIA ou Nova AI.
Un servidor externo non pode usar 127.0.0.1 para chegar a este equipo.

Configuración do rexistro: HYDRA_CLIENT_KEYS_FILE, por defecto
data/keys/api-clients.json. Nun servidor cómpre montar un directorio privado
persistente e restrinxir os permisos dos ficheiros mediante ACL do sistema.
As credenciais de entrega están en texto claro; os hashes do rexistro non.

Revogar unha clave:

```powershell
.venv/Scripts/python.exe -m scripts.manage_client_keys celtia --revoke
```

Reemitir a clave dun cliente (mesmo ID, límite e alcance; a credencial anterior
deixa de valer ao momento):

```powershell
.venv/Scripts/python.exe -m scripts.manage_client_keys celtia --rotate
```

## Migración desde o formato SHA-256 (2026-10-01)

O gateway xa non acepta as filas antigas (`sha256` sen sal). Despois de
despregar este cambio, reemítense os dous clientes e entrégaselles o novo
ficheiro `.env`:

```powershell
.venv/Scripts/python.exe -m scripts.manage_client_keys celtia --rotate
.venv/Scripts/python.exe -m scripts.manage_client_keys nova-ai --rotate
```

Non se debe executar a rotación antes de reiniciar o gateway co código novo:
un gateway antigo non sabe ler as filas novas.

## Validación e límites

Os tests de claves e seguridade tamén comproban o bloqueo desde o gateway.
Illouse a configuración de credenciais dos tests para non cargar o .env real.
Ruff non detectou erros nos ficheiros
revisados. Non se probou aínda unha chamada de CeltIA ou Nova AI contra un
gateway reiniciado. Tampouco se publicou unha API remota.

O límite é por proceso: non hai cota diaria, facturación nin contador persistente
de consumo por cliente. Esta implementación restrinxe rutas, pero non ofrece
illamento multi-tenant da memoria do motor. Para atender terceiros en produción
faltan HTTPS, illamento de datos/contexto por cliente, métricas de consumo e
limitador compartido se hai varias réplicas. Non debe anunciarse como servizo
multi-tenant certificado.

O rexistro de clientes admite administración local mediante a ferramenta CLI.
Non hai endpoints públicos para emitir claves. A publicación remota require
identificar o destino e instalar alí o token administrativo e o rexistro.
