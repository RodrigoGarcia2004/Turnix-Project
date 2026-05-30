# Turnix Salud — PRD

## Problem Statement
Repositorio: `RodrigoGarcia2004/Turnix-Project` (rama `cambios`).
Se requería que al generar una receta, el médico pudiese **firmar con el ratón** y enviar la firma con el formulario, y que el paciente pudiera **ver y descargar la receta en PDF** desde su panel. Adicionalmente, dejar la app lista para presentar / desplegar en Render.

## Stack
- Backend: FastAPI + asyncpg (Supabase Postgres, schema `usuarios`/`turnos`/`recetas` con enums).
- Frontend: HTML estático + JS vanilla servido vía `python3 -m http.server` (no React).
- PDF: reportlab + PIL (Pillow) para validar firma PNG.
- Emails: Resend (verificación de cuenta).
- Tiempo real: WebSockets (`/ws/PACIENTE`, `/ws/MEDICO`, `/ws/ADMIN`).

## Personas
- **Paciente** — registra cuenta, pide turnos, chatea con el médico, consulta historial y descarga recetas.
- **Médico** — gestiona pacientes en consulta, genera recetas firmadas, accede a historial.
- **Admin** — gestiona usuarios y solicitudes de cambio de especialidad.

## Core Requirements
- Login WS por rol con contraseña hasheada/plain (legacy).
- Generación de recetas con datos médicos + firma manuscrita digital del médico.
- Firma del médico **obligatoria** (validada en frontend, almacenada como dataURL PNG en columna `firma_base64`).
- Listado de recetas por paciente + descarga en **PDF con firma embebida**.
- Validación robusta del PDF (fallback si firma corrupta).
- App lista para deploy en Render (ya hay `render.yaml`).

## What's been implemented (30/05/2026)

### Fix 1 — Frontend médico (`/app/frontend/public/medico.html`)
- Añadida lógica completa de canvas para dibujo de firma con **ratón + touch** (events: mousedown/move/up/leave + touchstart/move/end).
- Validación: el formulario no permite enviar la receta sin firma; muestra alerta y resalta el hint.
- Reset del canvas al abrir/cerrar modal y tras envío correcto.
- Captura `firmaCanvas.toDataURL('image/png')` y lo envía en `firma_base64`.

### Fix 2 — Frontend paciente (`/app/frontend/public/paciente.html`)
- Añadida sección **"Mis Recetas"** con listado dinámico (`#recetas-list`).
- Tarjetas con nombre, médico, especialidad, fecha, código RX-xxxxxxxx, motivo + botón **"Descargar PDF"**.
- Función `cargarRecetasPaciente()` invocada al hacer LOGIN_OK y por refresco manual.
- Handler WS para `RECETA_NUEVA:` y `SISTEMA:RECETA_GENERADA:` que refresca la lista en vivo.
- Función `descargarRecetaPDF(id)` que descarga `application/pdf` con nombre `receta_{id}.pdf`.

### Fix 3 — Backend bugs (`/app/backend/server.py`)
- Corregido `column m.email does not exist` → reemplazado por `m.correo_electronico AS medico_email` (y `p.correo_electronico AS paciente_email`) en 4 queries (historial, recetas paciente, PDF, solicitudes especialidad).
- Corregido `UniqueViolation` en `recetas.turno_id` → si ya hay receta para ese turno, se inserta con `turno_id=NULL` permitiendo múltiples recetas por consulta.
- Hardening de PDF: validación PIL `verify()` previa al embebido; si la firma está corrupta se muestra "(no disponible)" en lugar de devolver 500. Doble red de seguridad con try/except envolviendo `doc.build()`.

## Testing
- Testing agent: **18/18 tests pasados** (backend). Cubre listado, PDF con image stream, creación con/sin firma, autorización, password incorrecta, paciente inexistente, UNIQUE turno_id, fix de columna, login WS para los 3 roles.
- E2E manual (Playwright): login médico → modal receta → dibujo firma → submit → password → confirmación. Login paciente → 9 recetas visibles → descarga PDF (200 OK, ~115 KB con image embebida).
- Tests automatizados creados por testing agent: `/app/backend/tests/test_recetas.py`.

## Deployment
- `render.yaml` ya configurado (web service: backend + static site frontend).
- Variables: `SUPABASE_HOST`, `SUPABASE_PORT`, `SUPABASE_DB`, `SUPABASE_USER`, `SUPABASE_PASSWORD`, `RESEND_API_KEY`, `CORS_ORIGINS=*`, `UPLOADS_DIR=/tmp/turnix_uploads`, `FRONTEND_DIR=/opt/render/project/src/frontend/public` (ya existentes en el dashboard del usuario).
- Para activar el cambio en Render: el usuario debe usar la opción **"Save to Github"** del chat para hacer push a la rama `cambios`; Render auto-desplegará.

## Backlog / P1
- Endpoint para descargar firma original (PNG) por separado.
- Dividir `server.py` (1927 LOC) en módulos (auth, recetas, turnos, admin).
- Persistir firma del médico en su perfil para reusarla por defecto.

## Backlog / P2
- Validar firma_base64 obligatoria también en backend (actualmente solo en frontend).
- Compresión/optimización del PNG de la firma antes de guardar.
- Auditoría: registrar IP + user agent al firmar receta.
