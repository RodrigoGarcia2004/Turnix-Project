# Turnix - Sistema de Gestión de Turnos Médicos

## Problem Statement
Conectar la app del repo `RodrigoGarcia2004/turnixV0` (Java + MySQL local) a la base de datos
Supabase Postgres del usuario y dejarla 100% funcional en el preview de Emergent.

DB Supabase: `iqauuxgrnnjxironpyje` (host pooler `aws-1-eu-west-3.pooler.supabase.com:5432`).

## Architecture (decidida)
El entorno de Emergent tiene `supervisord` read-only con `uvicorn` (FastAPI) en `:8001`
y `craco start` en `:3000`. No es viable correr Java directamente. Por eso el servidor
Java WebSocket se porteó fielmente a **FastAPI** preservando el mismo protocolo
de mensajes (login, registro, PEDIR_TURNO, LLAMAR_SIGUIENTE, CHAT_PRIVADO,
ENVIAR_AL_MEDICO, FINALIZAR_CONSULTA, VALORACION_MEDICO, etc.). El código Java
original queda intacto en `/app/turnix/source/Turnix/` como referencia.

- **Backend** (`/app/backend/server.py`): FastAPI + asyncpg, WS en `/api/ws`.
- **Frontend**: HTML estáticos servidos por CRA desde `/app/frontend/public/`
  (`index.html` = landing, `paciente.html`, `medico.html`).
- **DB**: Supabase Postgres via Session Pooler (IPv4). Credenciales en `/app/backend/.env`.

## Implementado (May 2026)
- Conexión a Supabase Postgres (asyncpg, ssl=require, statement_cache_size=0).
- Login/Registro contra tabla `usuarios` (passwords plaintext tal como están en la DB).
- Pedir turno (calcula MAX(numero_turno)+1, inserta en `turnos` con `id_paciente`).
- Cola en memoria + broadcast `COLA_UPDATE` y `TURNO_ASIGNADO`.
- Llamar siguiente / Iniciar consulta manual / Finalizar consulta (UPDATE estado).
- Chat médico ↔ paciente con persistencia opcional en tabla `mensajes`.
- Atender siguiente (admin) → INSERT historial + UPDATE estado='ATENDIDO'.
- Valoración médica (estrellas) → actualiza `suma_valoraciones` y `total_votos`,
  emite `VALORACION_ACTUALIZADA` al médico.
- HTML conectan al WS via `wss://${host}/api/ws` (dinámico).

## Test credentials
Usuarios existentes en la DB Supabase:
- `admin / 1234` → ADMIN
- `medico1 / 1234` → MÉDICO
- `user1 / 1234` → PACIENTE
- `user2 / user2` → PACIENTE

## Backlog / mejoras sugeridas
- P1: Hashear passwords (bcrypt) - hoy están en plaintext.
- P1: Soportar `documentos` (subida real de archivos via REST + storage).
- P2: WebRTC real para video (hoy es solo señalización).
- P2: Vista admin para ver historial completo y métricas.
- P2: Foto de perfil persistente (`foto_base64` ya existe en schema).
