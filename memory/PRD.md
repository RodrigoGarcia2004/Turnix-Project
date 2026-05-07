# Turnix - Sistema de Gestión de Turnos Médicos

## Iteración 3 (May 2026) - Mejoras solicitadas
- **Foto perfil persistente**: tabla `usuarios.foto_base64` se actualiza vía
  `POST /api/profile/photo` con verificación de password actual. Carga en login.
- **Notificaciones de sistema en chat médico**: SISTEMA_PACIENTE_CONECTADO,
  SISTEMA_PACIENTE_DESCONECTADO, SISTEMA_PACIENTE_ACEPTO con estilos verde/rojo.
- **Botón "Documentos / Historial del paciente"** sobre "Ver Mis Valoraciones",
  abre modal con 3 tabs: Documentos, Chat de la consulta, Turnos previos. Datos
  desde `GET /api/historial/paciente/{usuario}`.
- **"Historial Seguro" en acceso.html**: modal de login solo para PACIENTE
  (`POST /api/auth/login`), lista de turnos (`GET /api/historial/turnos/{user_id}`),
  descarga de justificante en PDF (`GET /api/justificante/{turno_id}?user_id=`)
  generado con ReportLab (cabecera Turnix, tabla con datos del turno, médico,
  notas, firma de verificación).
- **WebRTC bidireccional** ya operativo desde iteración 2.

## Iteraciones previas
- Iter 1: conexión Supabase Postgres via Session Pooler IPv4. Login/registro,
  cola de turnos, chat WS, valoración estrella.
- Iter 2: WebRTC P2P con STUN, upload real de documentos (POST /api/upload),
  serving estático integrado (FastAPI mount para frontend/public).

## Stack
- FastAPI + asyncpg + reportlab.
- Frontend HTML estático (no React real).
- Despliegue: Render (blueprint `render.yaml` o servicio web manual).

## Test credentials (ver test_credentials.md)
