# Turnix - Sistema de Gestión de Turnos Médicos

Sistema integrado de salud con gestión de turnos en tiempo real, chat médico-paciente,
videollamada WebRTC peer-to-peer y subida de documentos clínicos.

## Stack
- **Backend**: FastAPI + asyncpg (Python 3.11)
- **DB**: PostgreSQL via Supabase (Session Pooler IPv4)
- **Frontend**: HTML + JavaScript vanilla servido por CRA (no React real, solo estático)
- **WebSocket**: protocolo de mensajes texto plano sobre `/api/ws`
- **WebRTC**: peer-to-peer con STUN público de Google, signaling sobre el WS

## Estructura
```
backend/
  server.py            # FastAPI: WS + REST + signaling WebRTC
  requirements.txt
  .env.example
frontend/
  public/
    index.html         # Landing page (acceso)
    paciente.html      # Portal del paciente
    medico.html        # Portal del médico
turnix/source/Turnix/  # Código Java original (referencia, no se ejecuta)
memory/
  PRD.md               # Estado del producto
  test_credentials.md  # Cuentas de prueba (NO en git)
```

## Configuración (local)
1. Copiá `backend/.env.example` a `backend/.env` y completá las credenciales
   del Session Pooler de Supabase (`Connect → Session pooler`).
2. Copiá `frontend/.env.example` a `frontend/.env` con el URL del backend.
3. Backend:
   ```
   cd backend && pip install -r requirements.txt
   uvicorn server:app --host 0.0.0.0 --port 8001 --reload
   ```
4. Frontend:
   ```
   cd frontend && yarn install && yarn start
   ```

## Esquema BD (Supabase)
Tablas: `usuarios`, `turnos`, `mensajes`, `documentos`, `historial`, `valoraciones`.
Enums: `rol_usuario` (ADMIN, PACIENTE, MEDICO), `estado_turno` (EN_ESPERA,
EN_CONSULTA, ATENDIDO, COMPLETADO, CANCELADO).

## Cuentas de prueba
| Usuario | Password | Rol      |
|---------|----------|----------|
| admin   | 1234     | ADMIN    |
| medico1 | 1234     | MEDICO   |
| user1   | 1234     | PACIENTE |

## Funcionalidades
- Login / registro de pacientes.
- Cola de turnos en tiempo real con broadcast a todos los clientes.
- Chat bidireccional médico-paciente persistido en `mensajes`.
- Videollamada WebRTC real (audio + video) iniciada por el médico.
- Subida de documentos (PDF, imágenes, TXT, DOCX) con preview inline.
- Sistema de valoración por estrellas con cálculo de media en `usuarios`.
- Atender / Finalizar consulta con escritura en `historial`.

## Notas de seguridad
- Las contraseñas en la tabla `usuarios` están en **texto plano** (legacy del proyecto
  Java original). Migrar a bcrypt antes de producción.
- Los uploads se guardan en filesystem local (`/app/uploads`). Para producción usar
  Supabase Storage (cambiar `upload_documento()` en `server.py`).
- WebRTC usa solo STUN público; en NAT estricto puede fallar. Añadir TURN si hace falta.

## Crédito
Proyecto original: [RodrigoGarcia2004/turnixV0](https://github.com/RodrigoGarcia2004/turnixV0)
(Java + WebSocket + MySQL). Esta versión portea el servidor a Python/FastAPI manteniendo
el mismo protocolo de mensajes para que el código Java original siga sirviendo de
referencia y documentación.
