# PRD - Turnix Salud

## Problema original
Gestión de turnos médicos con chat médico-paciente en tiempo real, justificantes en PDF
y videollamada P2P. El cliente pidió:
1. Logo Turnix en splash de carga en TODAS las pantallas con animación.
2. Toggle de modo oscuro arriba a la derecha, con animación del logo girando durante el cambio.
3. Persistir preferencia de tema en localStorage.
4. PDF de justificante con datos completos (motivo, prioridad, rama del médico) + logo.
5. Videollamada WebRTC funcional con flujo "1-click": médico llama → al paciente
   le aparece modal "Aceptar / Rechazar" → al aceptar se conecta automáticamente.
   Con botones de mute/cam/colgar en ambos lados.
6. Depurar el proyecto y dejarlo presentable.

## Stack
- Backend: FastAPI + asyncpg, Python 3.11. WebSocket + REST en :8001.
- DB: Postgres en Supabase (Session Pooler IPv4).
- Frontend: HTML/CSS/JS vanilla en `/app/frontend/public`, servido por `python -m http.server` en :3000.
- WebRTC: P2P con STUN público (stun.l.google.com), signaling sobre WS.
- PDF: ReportLab.
- Email: Resend (verificación de cuentas).

## Personas
- Paciente: pide turno, chatea con el médico, descarga justificantes, acepta videollamadas.
- Médico: atiende turnos, chat, sube documentos, llama por video, deja notas.
- Admin: gestiona usuarios y solicitudes de especialidad.

## Cambios en esta sesión (25/05/2026)
- Limpieza del proyecto: eliminados `frontend/src`, `node_modules`, `craco`, `tailwind`,
  carpeta legacy `turnix/` (Java) y `package.json` simplificado a solo `python -m http.server`.
- Arreglado bug crítico: el bloque `<style>` del dark mode no se cerraba en
  `index.html`, `acceso.html`, `admin.html`, `medico.html`, `paciente.html`,
  `privacidad.html` → todo el HTML del body quedaba dentro del `<style>`.
- Creados `turnix-theme.css` y `turnix-theme.js` compartidos.
- Splash inicial con logo girando: se muestra en todas las páginas, fade-out al cargar.
- Toggle dark mode flotante (id=`turnix-dark-toggle`) con overlay de logo girando
  en la transición; preferencia persistida en localStorage (`turnix-theme`).
- Logo Turnix inyectado en `index.html` (cabecera) y en el PDF de justificante.
- PDF rediseñado en 3 secciones: Datos del paciente, Datos de la consulta
  (con motivo, prioridad, estado, fechas), Profesional sanitario (médico + rama).
- WebRTC arreglado:
  - JS `split(":", 3)` reemplazado por `turnixSplit3()` (mantiene `:` del payload JSON).
  - Backend amplió tipos de mensaje a `WEBRTC_CALL_REQUEST/ACCEPT/REJECT/OFFER/ANSWER/ICE/HANGUP`.
  - Flujo 1-click: médico → `WEBRTC_CALL_REQUEST` → modal `turnix-video-incoming` en paciente
    → `WEBRTC_CALL_ACCEPT` → médico crea oferta → handshake estándar SDP/ICE.
- Botones mute / cam / colgar en ambos lados con cambio de icono al togglear.

## Testing
- 9/9 backend tests OK (`/app/backend/tests/test_turnix_backend.py`).
- UI flows: login, splash, dark mode, PDF, signaling WebRTC y modal de incoming call verificados.
- Sin issues críticos pendientes.

## Backlog (futuro, no bloqueante)
- P2: Login REST unificado (medico/admin actualmente vía WS / `/api/admin/login`).
- P2: Refactor `server.py` (>1300 líneas) en submódulos.
- P2: TURN server (solo STUN ahora; NAT estricto puede impedir conexión P2P en algunas redes).
- P3: Incluir DNI/centro en BD para reflejarlos en el PDF (hoy no existen esas columnas).

## Cambios 2026-05-27 (fork actual)

### Recetas (acceso.html) — bugs corregidos
- `cargarMisRecetas` estaba anidada dentro de sí misma → ahora es una sola función.
- URLs ahora usan prefijo `/api/recetas/...` correctamente.
- Respuesta backend = array plano (antes esperaba `data.recetas`).
- Mapeo de campos: `nombre_receta`, `medico_nombre`, `medico_especialidad`, `medico_email`.
- PDF download incluye `?user_id=` (requerido por backend).

### Admin "Editar usuario"
- Nuevo botón "✏️ Editar" naranja al lado de "🗑 Borrar" en cada fila.
- Modal con todos los campos editables: usuario, nombre, nombre_completo, email, rol, especialidad, password (opcional), email_verificado.
- Requiere contraseña de admin para confirmar.
- Backend: `POST /api/admin/edit-user` (validación admin + UPDATE dinámico).

### Backend nuevo
- `GET /api/usuarios?nombre=X` — lookup de usuario por nombre completo/usuario (usado por medico.html).
- `POST /api/admin/edit-user` — edición masiva con validación admin.
- DELETE cascade en `recetas` cuando admin borra usuario (medico o paciente).

## Cambios 2026-05-27 v2 (uptime + cache + UI global)

### Fix cache obsoleto al volver de aviso-legal/privacidad
- Middleware `NoCacheStaticMiddleware` en FastAPI: cabeceras `Cache-Control: no-store, no-cache, must-revalidate` + `Pragma: no-cache` para todo `.html`, `.js`, `.css` y `/`.
- Verificado con `curl -I /acceso.html`.

### Botón "← Inicio" global
- Inyectado por `turnix-theme.js` (función `ensureHomeBtn`) en TODAS las páginas excepto `index.html`.
- No duplica con enlaces existentes (`.btn-volver`, textos "Volver al inicio" o "Volver a Turnix").
- Estilo flotante pastilla blanca arriba-izquierda + soporte dark mode.

### Dark mode toggle
- Ya estaba presente en `turnix-theme.js` (auto-inject) en todas las páginas. Confirmado funcional.

### Contador "Conectado desde hace"
- En `medico.html`: nuevo `<p id="uptime-text">⏱ Conectado desde hace <b>0m</b></p>` debajo del estado.
- Función `iniciarContadorConexion()` ejecuta cada 1s, formato `Xd Yh Zm`/`Xh Ym`/`Xm Ys`/`Xs`.
- Se arranca al recibir `LOGIN_OK:MEDICO|ADMIN`.

### Tabla `sesiones_conexion` (tracking de uptime)
- Schema: id, usuario_id, rol, fecha_inicio, fecha_fin, duracion_seg.
- `session_open(ws, user)` se llama al login WS para MEDICO/ADMIN.
- `session_close(ws)` se llama en el `finally` del endpoint WS.
- Al startup se cierran defensivamente sesiones que quedaron abiertas (reinicios).

### Admin: Tab "Historial de conexiones"
- Posición: tercera pestaña a la derecha de "Solicitudes de especialidad".
- Filtros: Última semana / Último mes (30d) / Todo / Mes específico (12 últimos meses).
- Dos tablas: Resumen agregado por usuario (sesiones, tiempo total, activa) + lista cronológica.
- Endpoint: `POST /api/admin/conn-history` (acepta `range`, `desde`, `hasta`, `usuario_id`).
