# Turnix - Sistema de Gestión de Turnos Médicos

## Problem Statement
Conectar la app del repo `RodrigoGarcia2004/turnixV0` (Java + MySQL local) a la base de datos
Supabase Postgres del usuario y dejarla 100% funcional en el preview de Emergent. Despues
añadir WebRTC real para videollamadas y subida real de documentos.

DB Supabase: `iqauuxgrnnjxironpyje` (host pooler `aws-1-eu-west-3.pooler.supabase.com:5432`).

## Architecture
- **Backend** (`/app/backend/server.py`): FastAPI + asyncpg.
  - WebSocket en `/api/ws` (porteado del `ServidorWeb.java`).
  - REST: `/api/health`, `/api/upload`, `/api/files/{name}`, `/api/documents/active`.
  - Uploads en `/app/uploads/` servidos como `FileResponse`.
- **Frontend**: HTML estaticos en `/app/frontend/public/` servidos por CRA.
  - `index.html` = landing, `paciente.html`, `medico.html`.
  - WebRTC: STUN de Google, signaling via WS (offer/answer/ICE/hangup).
- **DB**: Supabase Postgres via Session Pooler (IPv4). Credenciales en `/app/backend/.env`.
- **Codigo Java original**: preservado en `/app/turnix/source/Turnix/`.

## Implementado (May 2026)
### Iteracion 1 (DB connect)
- Login/Registro contra `usuarios`, pedir/llamar/finalizar turno, chat WS, valoracion estrella.
- SQL portado a Postgres (COALESCE, casts a enums, subselects en UPDATE).

### Iteracion 2 (WebRTC + Documentos)
- WebRTC peer-to-peer real con video bidireccional. El medico inicia la oferta, el paciente
  responde con su camara. Audio + video. Boton "Colgar" en ambos lados (HANGUP via WS).
- Signaling messages: `WEBRTC_OFFER`, `WEBRTC_ANSWER`, `WEBRTC_ICE`, `WEBRTC_HANGUP`.
- Subida real de documentos: paciente sube via `POST /api/upload`, archivo se guarda en
  `/app/uploads/<uuid>_<nombre>`, se inserta fila en `documentos` con `id_turno` resuelto.
- El medico recibe `DOCUMENTO_NUEVO:nombre:url:mime` y refresca el panel "Documentos del
  paciente activo" (lista descargable via GET /api/files/<...>).
- Mensajes con URLs `/api/files/...` se renderizan inline (img si es imagen, link si no).
- `LOGIN_OK` ahora incluye `id` y `usuario` para WebRTC routing y uploads.

## Test credentials
| Usuario | Password | Rol      |
|---------|----------|----------|
| admin   | 1234     | ADMIN    |
| medico1 | 1234     | MEDICO   |
| user1   | 1234     | PACIENTE |
| user2   | user2    | PACIENTE |

## Backlog
- P1: Hashear passwords (bcrypt) - hoy plaintext en DB.
- P1: Migrar uploads a Supabase Storage (cuando el usuario provea `service_role key`
  + nombre de bucket; cambiar `upload_documento()` para usar la API REST de Storage).
- P2: TURN server para WebRTC en redes con NAT estricto (hoy solo STUN).
- P2: Panel admin con metricas (tiempo medio espera, valoraciones por medico).
- P2: Foto de perfil persistente (`foto_base64` ya existe en schema).
