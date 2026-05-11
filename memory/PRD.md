# Turnix - Sistema de Gestión de Turnos Médicos

## Iteración 4 (May 2026) - Sistema completo de gestión

### Schema migrations (Supabase)
- `usuarios`: añadidas `email_verificado BOOL`, `codigo_verif VARCHAR`, `codigo_expira TIMESTAMPTZ`.
- `turnos`: añadidas `tipo_consulta VARCHAR(100)`, `prioridad VARCHAR(20)`.
- Tabla nueva `solicitudes_especialidad` (medico_id, especialidad_actual, especialidad_nueva, motivo, estado, fecha_solicitud, fecha_resolucion, resuelto_por).
- Admin actualizado: `admin/1234` con email `admin@gmail.com`.

### Resend (verificación de email)
- POST `/api/auth/register-init`: crea cuenta `email_verificado=FALSE`, manda código 6 dígitos vía Resend.
- POST `/api/auth/register-confirm`: valida código (15min de validez).
- POST `/api/auth/resend-code`: reenvía si caducó.
- Login WS bloquea PACIENTE no verificado → emite `NEEDS_VERIFICATION:user_id` → frontend abre modal.
- **Limitación sandbox Resend free**: solo envía a `garciaherediarodrigo@gmail.com` (el de la cuenta). Verificar dominio para producción.

### Filtrado por especialidad + prioridad
- Paciente al pedir turno elige `tipo_consulta` (Medicina General, Pediatría, Traumatología, Cardiología, Dermatología, Ginecología, Neurología, Psiquiatría, Oftalmología, ORL, Endocrinología, Urología, Oncología, Reumatología, Nutrición, Psicología, Odontología, Otro) y `prioridad` (Urgente/Moderada/Leve con colores rojo/amarillo/verde).
- Broadcast `TURNO_ASIGNADO:<nombre>:<usuario>:<numero>:<tipo>:<prioridad>` filtrado: solo médicos con esa especialidad lo ven. `Otro` → todos.
- `LLAMAR_SIGUIENTE` filtra la cola por la especialidad del médico que llama.

### Modo offline médico
- POST `/api/medico/toggle-offline` actualiza set in-memory `medicos_offline`.
- Médicos offline no reciben broadcasts ni pueden llamar siguientes.
- Pueden seguir atendiendo al paciente activo que ya tenían.

### Cambio de especialidad con aprobación admin
- Médico solicita: POST `/api/medico/solicitar-especialidad` (con password actual).
- Admin ve bandeja: POST `/api/admin/specialty-requests`.
- Admin aprueba/rechaza: POST `/api/admin/specialty-action`. La aprobación actualiza `usuarios.especialidad`.

### Portal Admin (admin.html)
- Tema oscuro cyan, dos tabs: Usuarios y Solicitudes.
- Lista de usuarios con badges de rol (ADMIN/MEDICO/PACIENTE).
- Botón borrar (excepto ADMINs) con modal de re-autenticación.
- Borrado en cascada de mensajes/documentos/historial/valoraciones/turnos/solicitudes.

### Fix bug histórico
- `/api/historial/paciente/{usuario}` ahora busca por `usuario`, `nombre_completo` o `nombre`.

## Test credentials
| Usuario       | Pass    | Rol      | Email                   |
|---------------|---------|----------|--------------------------|
| admin         | 1234    | ADMIN    | admin@gmail.com         |
| medico1       | 1234    | MEDICO   | medico1@                |
| user1         | 1234    | PACIENTE |                          |
| user2         | user2   | PACIENTE |                          |
| rodrigo       | rodrigo | PACIENTE |                          |

## Endpoints REST (resumen)
- /api/auth/login, /register-init, /register-confirm, /resend-code
- /api/admin/login, /users, /delete-user, /specialty-requests, /specialty-action
- /api/medico/solicitar-especialidad, /toggle-offline
- /api/especialidades
- /api/profile/photo (GET/POST), /api/historial/turnos/{id}, /paciente/{usuario}, /chat/activa
- /api/justificante/{turno_id}?user_id=
- /api/upload, /files/{name}, /documents/active
- WS /api/ws (protocolo texto)
