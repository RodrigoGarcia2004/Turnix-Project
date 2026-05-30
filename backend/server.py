"""
Turnix - Servidor WebSocket en FastAPI
Porteado fielmente desde el ServidorWeb.java original (proyecto Java de Rodrigo Garcia)
para poder ejecutarse en el entorno de Emergent (FastAPI/uvicorn en puerto 8001).
La conexion a la BD se realiza a Supabase Postgres mediante el connection pooler (IPv4).
El codigo Java original queda preservado en /app/turnix/source/Turnix como referencia.
"""
import os
import logging
import asyncio
import uuid
import mimetypes
import io
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import asyncpg

# ReportLab para generar PDFs
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage

import resend
import random
import string

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# Carpeta del frontend estatico (paciente.html, medico.html, index.html...)
FRONTEND_DIR = Path(os.environ.get(
    "FRONTEND_DIR",
    str(ROOT_DIR.parent / "frontend" / "public")
))

# Resend (envio de emails de verificacion)
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")
if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY

# Especialidades por defecto disponibles para los medicos
ESPECIALIDADES_BASE = [
    "Medicina General", "Pediatría", "Traumatología", "Cardiología",
    "Dermatología", "Ginecología", "Neurología", "Psiquiatría",
    "Oftalmología", "Otorrinolaringología", "Endocrinología",
    "Urología", "Oncología", "Reumatología", "Nutrición",
    "Psicología", "Odontología", "Otro",
]

# Medicos en modo desconectado (in-memory). user_id -> True
medicos_offline: set = set()


def _gen_codigo() -> str:
    return "".join(random.choices(string.digits, k=6))


async def enviar_codigo_email(destinatario: str, codigo: str, nombre: str):
    """Envia codigo de 6 digitos via Resend. No bloquea el event loop."""
    if not RESEND_API_KEY:
        log.warning("RESEND_API_KEY no configurado, no se envia email a %s", destinatario)
        return None
    html = f"""
    <table style="font-family: Arial, sans-serif; max-width: 520px; margin: auto; border: 1px solid #e2e8f0; border-radius: 12px; padding: 30px;">
      <tr><td style="text-align:center;">
        <h1 style="color: #0d9488; margin: 0 0 10px;">Turnix Salud</h1>
        <p style="color: #475569; margin: 0 0 24px;">Confirmación de cuenta</p>
        <p style="color: #1e293b; font-size: 15px;">Hola <b>{nombre or destinatario}</b>,</p>
        <p style="color: #1e293b; font-size: 15px;">Tu código de verificación es:</p>
        <div style="background: #0d9488; color: white; font-size: 32px; letter-spacing: 8px; font-weight: bold;
                    padding: 18px; border-radius: 12px; margin: 18px 0;">{codigo}</div>
        <p style="color: #64748b; font-size: 12px;">El código caduca en 15 minutos. Si no creaste esta cuenta, ignora este mensaje.</p>
      </td></tr>
    </table>"""
    params = {
        "from": SENDER_EMAIL,
        "to": [destinatario],
        "subject": "Turnix · Tu código de verificación",
        "html": html,
    }
    try:
        return await asyncio.to_thread(resend.Emails.send, params)
    except Exception as e:
        log.exception("Resend send falló: %s", e)
        raise HTTPException(500, f"No se pudo enviar el email: {e}")

UPLOADS_DIR = Path(os.environ.get("UPLOADS_DIR", "/app/uploads"))
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("turnix")

# ----------------------------------------------------------------------
# Conexion a Supabase Postgres (Session Pooler - IPv4)
# ----------------------------------------------------------------------
SUPABASE_HOST = os.environ["SUPABASE_HOST"]
SUPABASE_PORT = int(os.environ["SUPABASE_PORT"])
SUPABASE_DB = os.environ["SUPABASE_DB"]
SUPABASE_USER = os.environ["SUPABASE_USER"]
SUPABASE_PASSWORD = os.environ["SUPABASE_PASSWORD"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Conectando a Supabase Postgres en %s:%s ...", SUPABASE_HOST, SUPABASE_PORT)
    app.state.pool = await asyncpg.create_pool(
        host=SUPABASE_HOST,
        port=SUPABASE_PORT,
        user=SUPABASE_USER,
        password=SUPABASE_PASSWORD,
        database=SUPABASE_DB,
        min_size=1,
        max_size=5,
        # Supavisor session pooler emite SET commands; statement_cache_size=0 evita
        # 'prepared statement already exists' al reusar conexiones.
        statement_cache_size=0,
        ssl="require",
    )
    # Tabla de recetas medicas (creada idempotente). Vincula con turnos+usuarios.
    async with app.state.pool.acquire() as _conn:
        await _conn.execute("""
            CREATE TABLE IF NOT EXISTS recetas (
                id              SERIAL PRIMARY KEY,
                turno_id        INTEGER REFERENCES turnos(id) ON DELETE SET NULL,
                medico_id       INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                paciente_id     INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                nombre_receta   TEXT NOT NULL,
                motivo          TEXT NOT NULL,
                medicamento     TEXT,
                dosis           TEXT,
                duracion        TEXT,
                indicaciones    TEXT,
                firma_base64    TEXT,
                fecha_emision   TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await _conn.execute("CREATE INDEX IF NOT EXISTS idx_recetas_paciente ON recetas(paciente_id)")
        await _conn.execute("CREATE INDEX IF NOT EXISTS idx_recetas_medico ON recetas(medico_id)")
        # Sesiones de conexion (uptime de medicos / admins).
        await _conn.execute("""
            CREATE TABLE IF NOT EXISTS sesiones_conexion (
                id              SERIAL PRIMARY KEY,
                usuario_id      INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                rol             TEXT NOT NULL,
                fecha_inicio    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                fecha_fin       TIMESTAMPTZ,
                duracion_seg    INTEGER
            )
        """)
        await _conn.execute("CREATE INDEX IF NOT EXISTS idx_sesconex_usuario ON sesiones_conexion(usuario_id)")
        await _conn.execute("CREATE INDEX IF NOT EXISTS idx_sesconex_inicio ON sesiones_conexion(fecha_inicio DESC)")
        # Cerrar de forma defensiva cualquier sesion abierta (caso reinicio).
        await _conn.execute("""
            UPDATE sesiones_conexion
               SET fecha_fin = NOW(),
                   duracion_seg = GREATEST(0, EXTRACT(EPOCH FROM (NOW() - fecha_inicio))::INT)
             WHERE fecha_fin IS NULL
        """)
    log.info("Conexion a la BD lista. App Turnix iniciada.")
    yield
    await app.state.pool.close()
    log.info("Conexion a la BD cerrada.")


app = FastAPI(lifespan=lifespan)
api = APIRouter(prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------------
# Anti-cache para HTML/JS/CSS (evita que el navegador sirva versiones
# obsoletas de paciente.html / acceso.html al volver de aviso-legal, etc.)
# ----------------------------------------------------------------------
from starlette.middleware.base import BaseHTTPMiddleware

class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.endswith(".html") or path == "/" or \
           path.endswith(".js") or path.endswith(".css"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

app.add_middleware(NoCacheStaticMiddleware)


# ----------------------------------------------------------------------
# Estado en memoria (equivale a colaEspera + getConnections() de Java)
# ----------------------------------------------------------------------
all_clients: List[WebSocket] = []
cola_espera: List[WebSocket] = []
ws_users: Dict[int, Dict[str, Any]] = {}


def get_user(ws: WebSocket) -> Optional[Dict[str, Any]]:
    return ws_users.get(id(ws))


def set_user(ws: WebSocket, user: Optional[Dict[str, Any]]):
    if user is None:
        ws_users.pop(id(ws), None)
    else:
        ws_users[id(ws)] = user


def display_name(user: Dict[str, Any]) -> str:
    nc = user.get("nombre_completo")
    if nc and nc != "null" and str(nc).strip():
        return str(nc)
    return user["usuario"]


# Mapeo id(ws) -> sesion_id en BD para cerrar al desconectar
ws_session_ids: Dict[int, int] = {}

async def session_open(ws: WebSocket, user: Dict[str, Any]):
    """Inserta una fila en sesiones_conexion y la asocia al ws."""
    if not user or user.get("rol") not in ("MEDICO", "ADMIN"):
        return
    try:
        async with app.state.pool.acquire() as conn:
            sid = await conn.fetchval(
                """INSERT INTO sesiones_conexion (usuario_id, rol)
                   VALUES ($1, $2) RETURNING id""",
                user["id"], user["rol"],
            )
        ws_session_ids[id(ws)] = sid
        log.info("Sesion %s abierta para usuario %s (%s)", sid, user["usuario"], user["rol"])
    except Exception:
        log.exception("session_open fallo")


async def session_close(ws: WebSocket):
    sid = ws_session_ids.pop(id(ws), None)
    if not sid:
        return
    try:
        async with app.state.pool.acquire() as conn:
            await conn.execute(
                """UPDATE sesiones_conexion
                      SET fecha_fin = NOW(),
                          duracion_seg = GREATEST(0, EXTRACT(EPOCH FROM (NOW() - fecha_inicio))::INT)
                    WHERE id = $1 AND fecha_fin IS NULL""",
                sid,
            )
        log.info("Sesion %s cerrada", sid)
    except Exception:
        log.exception("session_close fallo")


async def safe_send(ws: WebSocket, msg: str):
    try:
        await ws.send_text(msg)
    except Exception:
        pass


async def actualizar_posiciones_cola():
    pos = 1
    total = len(cola_espera)
    for ws in cola_espera:
        await safe_send(ws, f"COLA_UPDATE:{pos}:{total}")
        pos += 1


# ----------------------------------------------------------------------
# Endpoints HTTP basicos
# ----------------------------------------------------------------------
@api.get("/")
async def root():
    return {"status": "ok", "service": "Turnix WebSocket Server", "protocol": "ws"}


@api.get("/health")
async def health():
    try:
        async with app.state.pool.acquire() as conn:
            v = await conn.fetchval("SELECT 1")
        return {"db": "ok", "value": v}
    except Exception as e:
        return {"db": "error", "detail": str(e)}


# ----------------------------------------------------------------------
# Documentos: upload + listado + descarga
# Almacenamiento local en /app/uploads. La tabla `documentos` guarda la
# ruta servible: /api/files/{filename}. Si despues quieres usar Supabase
# Storage, basta con cambiar la implementacion de upload_documento().
# ----------------------------------------------------------------------
ALLOWED_MIME = {
    "image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/plain",
}
MAX_BYTES = 10 * 1024 * 1024  # 10 MB


@api.post("/upload")
async def upload_documento(
    user_id: int = Form(...),
    file: UploadFile = File(...),
):
    """Subida de documento del paciente. Vincula al turno EN_ESPERA/EN_CONSULTA mas reciente."""
    contenido = await file.read()
    if len(contenido) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Archivo demasiado grande (max 10MB)")
    mime = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    if mime not in ALLOWED_MIME:
        raise HTTPException(status_code=415, detail=f"Tipo no permitido: {mime}")

    safe_name = (file.filename or "archivo").replace("/", "_").replace("\\", "_")
    fname = f"{uuid.uuid4().hex}_{safe_name}"
    dest = UPLOADS_DIR / fname
    dest.write_bytes(contenido)

    url = f"/api/files/{fname}"

    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO documentos (id_turno, nombre_archivo, ruta_archivo, tipo_mime, subido_en)
               VALUES (
                 (SELECT id FROM turnos
                   WHERE id_paciente=$1 AND estado IN ('EN_ESPERA','EN_CONSULTA')
                   ORDER BY id DESC LIMIT 1),
                 $2, $3, $4, NOW())
               RETURNING id, id_turno""",
            user_id, safe_name, url, mime,
        )

    # Notificar al medico via WS
    for c in all_clients:
        u = get_user(c)
        if u and u["rol"] in ("MEDICO", "ADMIN"):
            await safe_send(c, f"DOCUMENTO_NUEVO:{safe_name}:{url}:{mime}")

    return {"id": row["id"], "id_turno": row["id_turno"], "url": url, "nombre": safe_name, "mime": mime}


@api.get("/files/{fname}")
async def get_file(fname: str):
    safe = Path(fname).name  # impide path traversal
    p = UPLOADS_DIR / safe
    if not p.exists():
        raise HTTPException(status_code=404)
    mime = mimetypes.guess_type(safe)[0] or "application/octet-stream"
    return FileResponse(p, media_type=mime, filename=safe.split("_", 1)[-1] if "_" in safe else safe)


@api.get("/documents/active")
async def docs_active():
    """Documentos del turno EN_ESPERA/EN_CONSULTA mas antiguo (para el medico)."""
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT d.id, d.nombre_archivo, d.ruta_archivo, d.tipo_mime, d.subido_en, d.id_turno,
                      t.cliente
                 FROM documentos d
                 JOIN turnos t ON t.id = d.id_turno
                WHERE t.estado IN ('EN_ESPERA','EN_CONSULTA')
                ORDER BY d.subido_en DESC"""
        )
    return [dict(r) for r in rows]


# ----------------------------------------------------------------------
# Auth REST (para el portal "Historial seguro" en acceso.html)
# ----------------------------------------------------------------------
class LoginIn(BaseModel):
    usuario: str
    password: str


@api.post("/auth/login")
async def auth_login(body: LoginIn):
    """Login REST para el portal del paciente (PDF historial). Solo PACIENTE."""
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, nombre, usuario, rol::text AS rol, correo_electronico AS email, nombre_completo,
                      foto_base64
                 FROM usuarios WHERE usuario=$1 AND contraseña=$2""",
            body.usuario, body.password,
        )
    if not row:
        raise HTTPException(status_code=401, detail="Credenciales no validas")
    if row["rol"] != "PACIENTE":
        raise HTTPException(status_code=403, detail="Acceso solo para pacientes")
    return {
        "id": row["id"], "usuario": row["usuario"], "rol": row["rol"],
        "nombre": row["nombre"], "nombre_completo": row["nombre_completo"],
        "email": row["email"], "foto_base64": row["foto_base64"],
    }


# ----------------------------------------------------------------------
# Foto de perfil persistente en `usuarios.foto_base64`
# ----------------------------------------------------------------------
class PhotoIn(BaseModel):
    user_id: int
    password: str
    foto_base64: Optional[str] = None
    nombre: Optional[str] = None
    nueva_password: Optional[str] = None


@api.post("/profile/photo")
async def save_profile(body: PhotoIn):
    """Guarda foto y/o nombre/password del usuario. Requiere su password actual."""
    async with app.state.pool.acquire() as conn:
        actual = await conn.fetchval(
            "SELECT contraseña FROM usuarios WHERE id=$1", body.user_id
        )
        if actual is None:
            raise HTTPException(404, "Usuario no encontrado")
        if actual != body.password:
            raise HTTPException(401, "Password actual incorrecta")
        sets = []
        params: List[Any] = []
        i = 1
        if body.foto_base64 is not None:
            sets.append(f"foto_base64=${i}"); params.append(body.foto_base64); i += 1
        if body.nombre:
            sets.append(f"nombre_completo=${i}"); params.append(body.nombre); i += 1
        if body.nueva_password:
            sets.append(f"contraseña=${i}"); params.append(body.nueva_password); i += 1
        if not sets:
            return {"ok": True, "changed": 0}
        params.append(body.user_id)
        sql = f"UPDATE usuarios SET {', '.join(sets)} WHERE id=${i}"
        await conn.execute(sql, *params)
    return {"ok": True, "changed": len(sets)}


@api.get("/profile/photo/{user_id}")
async def get_profile(user_id: int):
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, usuario, nombre, nombre_completo, correo_electronico AS email, foto_base64,
                      especialidad, rol::text AS rol
                 FROM usuarios WHERE id=$1""", user_id,
        )
    if not row:
        raise HTTPException(404, "Usuario no encontrado")
    return dict(row)


# ----------------------------------------------------------------------
# Historial: turnos del paciente, chat de la consulta activa, historial completo
# ----------------------------------------------------------------------
@api.get("/historial/turnos/{user_id}")
async def historial_turnos(user_id: int):
    """Lista turnos del paciente (mas recientes primero)."""
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT t.id, t.numero_turno, t.cliente, t.estado::text AS estado,
                      t.fecha, t.fecha_inicio_consulta, t.fecha_fin_consulta,
                      t.notas_medico, t.atendido_por, t.tipo_consulta, t.prioridad,
                      m.nombre_completo AS medico_nombre,
                      m.usuario AS medico_usuario,
                      m.especialidad AS medico_especialidad,
                      m.email AS medico_email,
                      m.rol::text AS medico_rol
                 FROM turnos t
                 LEFT JOIN usuarios m ON m.id = t.atendido_por
                WHERE t.id_paciente=$1
                ORDER BY t.fecha DESC NULLS LAST, t.id DESC""",
            user_id,
        )
    return [dict(r) for r in rows]


@api.get("/historial/chat/activa")
async def historial_chat_activa():
    """Mensajes del turno activo (EN_ESPERA o EN_CONSULTA mas antiguo)."""
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT m.id, m.contenido, m.fecha_envio, m.emisor_id,
                      u.usuario AS emisor_usuario, u.rol::text AS emisor_rol,
                      u.nombre_completo AS emisor_nombre
                 FROM mensajes m
                 LEFT JOIN usuarios u ON u.id = m.emisor_id
                WHERE m.id_turno = (SELECT id FROM turnos
                                     WHERE estado IN ('EN_ESPERA','EN_CONSULTA')
                                     ORDER BY id ASC LIMIT 1)
                ORDER BY m.fecha_envio ASC"""
        )
    return [dict(r) for r in rows]


@api.get("/historial/paciente/{usuario}")
async def historial_paciente(usuario: str):
    """Para el medico: historial completo de un paciente (turnos, mensajes, docs).
    Acepta tanto 'usuario' como 'nombre_completo' como identificador."""
    async with app.state.pool.acquire() as conn:
        u = await conn.fetchrow(
            """SELECT id, usuario, nombre_completo FROM usuarios
                WHERE usuario=$1 OR nombre_completo=$1 OR nombre=$1
                ORDER BY (usuario=$1) DESC LIMIT 1""",
            usuario,
        )
        if not u:
            return {"usuario": usuario, "turnos": [], "mensajes": [], "documentos": []}
        turnos = await conn.fetch(
            """SELECT id, numero_turno, estado::text AS estado, fecha,
                      fecha_inicio_consulta, fecha_fin_consulta, notas_medico
                 FROM turnos WHERE id_paciente=$1
                 ORDER BY id DESC LIMIT 30""", u["id"]
        )
        mensajes = await conn.fetch(
            """SELECT m.id, m.id_turno, m.contenido, m.fecha_envio,
                      us.usuario AS emisor_usuario, us.rol::text AS emisor_rol
                 FROM mensajes m LEFT JOIN usuarios us ON us.id=m.emisor_id
                 JOIN turnos t ON t.id=m.id_turno
                 WHERE t.id_paciente=$1
                 ORDER BY m.fecha_envio DESC LIMIT 200""", u["id"]
        )
        docs = await conn.fetch(
            """SELECT d.id, d.id_turno, d.nombre_archivo, d.ruta_archivo, d.tipo_mime, d.subido_en
                 FROM documentos d
                 JOIN turnos t ON t.id=d.id_turno
                WHERE t.id_paciente=$1
                ORDER BY d.subido_en DESC LIMIT 100""", u["id"]
        )
    return {
        "usuario": dict(u),
        "turnos": [dict(r) for r in turnos],
        "mensajes": [dict(r) for r in mensajes],
        "documentos": [dict(r) for r in docs],
    }


# ----------------------------------------------------------------------
# Justificante PDF de un turno
# ----------------------------------------------------------------------
@api.get("/justificante/{turno_id}")
async def justificante_pdf(turno_id: int, user_id: int):
    async with app.state.pool.acquire() as conn:
        turno = await conn.fetchrow(
            """SELECT t.id, t.numero_turno, t.cliente, t.estado::text AS estado,
                      t.fecha, t.fecha_inicio_consulta, t.fecha_fin_consulta,
                      t.notas_medico, t.id_paciente, t.tipo_consulta, t.prioridad,
                      p.nombre_completo AS paciente_nombre, p.usuario AS paciente_usuario,
                      p.email AS paciente_email,
                      m.nombre_completo AS medico_nombre, m.usuario AS medico_usuario,
                      m.especialidad AS medico_especialidad, m.email AS medico_email
                 FROM turnos t
                 LEFT JOIN usuarios p ON p.id = t.id_paciente
                 LEFT JOIN usuarios m ON m.id = t.atendido_por
                WHERE t.id = $1""", turno_id,
        )

    if not turno:
        raise HTTPException(404, "Turno no encontrado")
    if turno["id_paciente"] != user_id:
        raise HTTPException(403, "Este justificante no pertenece a tu cuenta")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)

    styles = getSampleStyleSheet()

    titulo = ParagraphStyle("titulo", parent=styles["Heading1"],
                            textColor=colors.HexColor("#0d9488"),
                            alignment=1, fontSize=26, spaceAfter=4, fontName="Helvetica-Bold",
                            leading=30)

    subtitulo = ParagraphStyle("subtitulo", parent=styles["Normal"],
                               textColor=colors.HexColor("#64748b"),
                               alignment=1, fontSize=12, spaceAfter=18)

    section = ParagraphStyle("section", parent=styles["Heading3"],
                             textColor=colors.HexColor("#0f4c5c"),
                             fontSize=13, spaceBefore=18, spaceAfter=8,
                             fontName="Helvetica-Bold")

    story = []

    # ---------- Cabecera con logo ----------
    logo_path = Path(FRONTEND_DIR) / "turnix-logo.png"
    if logo_path.exists():
        try:
            logo = RLImage(str(logo_path), width=3.2*cm, height=3.2*cm)
            logo.hAlign = "CENTER"
            story.append(logo)
            story.append(Spacer(1, 6))
        except Exception:
            pass

    story.append(Paragraph("TURNIX SALUD", titulo))
    story.append(Paragraph("Justificante oficial de consulta médica", subtitulo))

    def fmt(dt):
        if not dt: return "—"
        if isinstance(dt, str): return dt
        return dt.strftime("%d/%m/%Y %H:%M")

    prio = turno["prioridad"] or "—"
    motivo = turno["tipo_consulta"] or "Consulta general"
    medico_nombre = turno["medico_nombre"] or turno["medico_usuario"] or "Sin asignar"
    especialidad = turno["medico_especialidad"] or "—"
    paciente_nombre = turno["paciente_nombre"] or turno["paciente_usuario"] or "—"

    # ---------- Bloque: Datos del paciente ----------
    story.append(Paragraph("Datos del paciente", section))
    paciente_data = [
        ["Nombre completo", paciente_nombre],
        ["Usuario",         turno["paciente_usuario"] or "—"],
        ["Correo electrónico", turno["paciente_email"] or "—"],
    ]
    story.append(_build_pdf_table(paciente_data))

    # ---------- Bloque: Datos de la consulta ----------
    story.append(Paragraph("Datos de la consulta", section))
    consulta_data = [
        ["Número de turno", f"#{turno['numero_turno']}"],
        ["Motivo / Tipo de consulta", motivo],
        ["Prioridad", prio],
        ["Estado", turno["estado"]],
        ["Fecha de solicitud", fmt(turno["fecha"])],
        ["Inicio de consulta", fmt(turno["fecha_inicio_consulta"])],
        ["Fin de consulta", fmt(turno["fecha_fin_consulta"])],
    ]
    story.append(_build_pdf_table(consulta_data))

    # ---------- Bloque: Profesional que le atendio ----------
    story.append(Paragraph("Profesional sanitario", section))
    medico_data = [
        ["Médico", medico_nombre],
        ["Especialidad / Rama", especialidad],
        ["Usuario interno", turno["medico_usuario"] or "—"],
        ["Correo profesional", turno["medico_email"] or "—"],
    ]
    story.append(_build_pdf_table(medico_data))

    # ---------- Observaciones ----------
    if turno["notas_medico"]:
        story.append(Paragraph("Observaciones del médico", section))
        story.append(Paragraph(turno["notas_medico"].replace("\n", "<br/>"), styles["Normal"]))

    # ---------- Pie con verificacion ----------
    story.append(Spacer(1, 24))
    pie = ParagraphStyle("pie", parent=styles["Normal"],
                         textColor=colors.HexColor("#64748b"),
                         fontSize=9, alignment=1, leading=14)

    story.append(Paragraph(
        f"Documento generado el {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}<br/>"
        f"Turnix Salud · Verificación: TURNIX-{turno['id']:08d}<br/>"
        f"Este documento acredita la asistencia médica del paciente en la fecha indicada.",
        pie))

    doc.build(story)
    buf.seek(0)

    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="justificante_turno_{turno["numero_turno"]}.pdf"'},
    )


def _build_pdf_table(data):
    t = Table(data, colWidths=[5.5*cm, 11*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E0F2F1")),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#0F4C5C")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10.5),
        ("ROWBACKGROUNDS", (1, 0), (1, -1), [colors.white, colors.HexColor("#F8FAFB")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.6, colors.HexColor("#CBD5E1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    return t


# ======================================================================
# Lookup ligero de usuario por nombre (utilizado por medico.html al abrir chat)
# ======================================================================
@api.get("/usuarios")
async def buscar_usuario(nombre: str):
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, usuario, nombre_completo, rol::text AS rol, correo_electronico AS email
                 FROM usuarios
                WHERE usuario=$1 OR nombre_completo=$1 OR nombre=$1
                ORDER BY (usuario=$1) DESC LIMIT 1""",
            nombre,
        )
    if not row:
        raise HTTPException(404, "Usuario no encontrado")
    return dict(row)


# ======================================================================
# RECETAS MEDICAS - creacion (medico), listado (paciente) y PDF
# ======================================================================
class RecetaCreate(BaseModel):
    medico_id: int
    medico_password: str
    paciente_usuario: str          # nombre_completo o usuario tal cual lo ve el medico
    nombre_receta: str
    motivo: str
    medicamento: Optional[str] = ""
    dosis: Optional[str] = ""
    duracion: Optional[str] = ""
    indicaciones: Optional[str] = ""
    firma_base64: Optional[str] = ""   # data URL PNG de la firma


@api.post("/recetas/crear")
async def recetas_crear(body: RecetaCreate):
    if not body.nombre_receta.strip() or not body.motivo.strip():
        raise HTTPException(400, "Nombre de la receta y motivo son obligatorios")
    async with app.state.pool.acquire() as conn:
        medico = await conn.fetchrow(
            """SELECT id, contraseña AS password, rol::text AS rol FROM usuarios WHERE id=$1""",
            body.medico_id,
        )
        if not medico or medico["rol"] != "MEDICO":
            raise HTTPException(403, "Solo médicos pueden emitir recetas")
        if medico["password"] != body.medico_password:
            raise HTTPException(401, "Contraseña del médico incorrecta")
        paciente = await conn.fetchrow(
            """SELECT id FROM usuarios
                WHERE rol='PACIENTE'
                  AND (usuario=$1 OR nombre_completo=$1 OR nombre=$1)
                ORDER BY (usuario=$1) DESC LIMIT 1""",
            body.paciente_usuario,
        )
        if not paciente:
            raise HTTPException(404, f"Paciente '{body.paciente_usuario}' no encontrado")
        turno_id = await conn.fetchval(
            """SELECT id FROM turnos
                WHERE id_paciente=$1 AND atendido_por=$2
                  AND estado IN ('EN_CONSULTA','EN_ESPERA','COMPLETADO')
                ORDER BY id DESC LIMIT 1""",
            paciente["id"], body.medico_id,
        )
        row = await conn.fetchrow(
            """INSERT INTO recetas
                (turno_id, medico_id, paciente_id, nombre_receta, motivo,
                 medicamento, dosis, duracion, indicaciones, firma_base64)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
               RETURNING id, fecha_emision""",
            turno_id, body.medico_id, paciente["id"],
            body.nombre_receta.strip(), body.motivo.strip(),
            (body.medicamento or "").strip(), (body.dosis or "").strip(),
            (body.duracion or "").strip(), (body.indicaciones or "").strip(),
            body.firma_base64 or None,
        )
    # Notificar al paciente conectado (si esta en WS)
    for c in all_clients:
        u = get_user(c)
        if u and u["id"] == paciente["id"]:
            await safe_send(c, f"RECETA_NUEVA:{body.nombre_receta.strip()}")
    return {"ok": True, "id": row["id"], "fecha_emision": row["fecha_emision"].isoformat()}


@api.get("/recetas/paciente/{user_id}")
async def recetas_listar_paciente(user_id: int):
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT r.id, r.nombre_receta, r.motivo, r.medicamento, r.dosis,
                      r.duracion, r.indicaciones, r.fecha_emision, r.turno_id,
                      m.id AS medico_id, m.nombre_completo AS medico_nombre,
                      m.usuario AS medico_usuario, m.especialidad AS medico_especialidad,
                      m.email AS medico_email
                 FROM recetas r
                 LEFT JOIN usuarios m ON m.id = r.medico_id
                WHERE r.paciente_id = $1
                ORDER BY r.fecha_emision DESC""",
            user_id,
        )
    return [dict(r) for r in rows]


@api.get("/recetas/{receta_id}/pdf")
async def recetas_pdf(receta_id: int, user_id: int):
    async with app.state.pool.acquire() as conn:
        r = await conn.fetchrow(
            """SELECT r.id, r.nombre_receta, r.motivo, r.medicamento, r.dosis,
                      r.duracion, r.indicaciones, r.firma_base64, r.fecha_emision,
                      r.turno_id, r.paciente_id,
                      p.nombre_completo AS paciente_nombre, p.usuario AS paciente_usuario,
                      p.email AS paciente_email,
                      m.nombre_completo AS medico_nombre, m.usuario AS medico_usuario,
                      m.especialidad AS medico_especialidad, m.email AS medico_email,
                      t.numero_turno
                 FROM recetas r
                 LEFT JOIN usuarios p ON p.id = r.paciente_id
                 LEFT JOIN usuarios m ON m.id = r.medico_id
                 LEFT JOIN turnos   t ON t.id = r.turno_id
                WHERE r.id = $1""",
            receta_id,
        )
    if not r:
        raise HTTPException(404, "Receta no encontrada")
    if r["paciente_id"] != user_id:
        raise HTTPException(403, "Esta receta no pertenece a tu cuenta")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)
    styles = getSampleStyleSheet()
    titulo = ParagraphStyle("titulo", parent=styles["Heading1"],
                            textColor=colors.HexColor("#0d9488"),
                            alignment=1, fontSize=26, spaceAfter=4,
                            fontName="Helvetica-Bold", leading=30)
    subtitulo = ParagraphStyle("subtitulo", parent=styles["Normal"],
                               textColor=colors.HexColor("#64748b"),
                               alignment=1, fontSize=12, spaceAfter=18)
    section = ParagraphStyle("section", parent=styles["Heading3"],
                             textColor=colors.HexColor("#0f4c5c"),
                             fontSize=13, spaceBefore=18, spaceAfter=8,
                             fontName="Helvetica-Bold")
    story = []

    logo_path = Path(FRONTEND_DIR) / "turnix-logo.png"
    if logo_path.exists():
        try:
            logo = RLImage(str(logo_path), width=3.2*cm, height=3.2*cm)
            logo.hAlign = "CENTER"
            story.append(logo)
            story.append(Spacer(1, 6))
        except Exception:
            pass

    story.append(Paragraph("TURNIX SALUD", titulo))
    story.append(Paragraph("Receta médica oficial", subtitulo))

    def fmt(dt):
        if not dt: return "—"
        if isinstance(dt, str): return dt
        return dt.strftime("%d/%m/%Y %H:%M")

    paciente_nombre = r["paciente_nombre"] or r["paciente_usuario"] or "—"
    medico_nombre = r["medico_nombre"] or r["medico_usuario"] or "Sin asignar"

    story.append(Paragraph("Datos del paciente", section))
    story.append(_build_pdf_table([
        ["Nombre completo", paciente_nombre],
        ["Usuario", r["paciente_usuario"] or "—"],
        ["Correo electrónico", r["paciente_email"] or "—"],
    ]))

    story.append(Paragraph("Detalles de la receta", section))
    detalles = [
        ["Nombre de la receta", r["nombre_receta"]],
        ["Motivo", r["motivo"]],
    ]
    if r["medicamento"]: detalles.append(["Medicamento", r["medicamento"]])
    if r["dosis"]:       detalles.append(["Dosis", r["dosis"]])
    if r["duracion"]:    detalles.append(["Duración del tratamiento", r["duracion"]])
    detalles.append(["Fecha de emisión", fmt(r["fecha_emision"])])
    if r["numero_turno"] is not None:
        detalles.append(["Turno asociado", f"#{r['numero_turno']}"])
    story.append(_build_pdf_table(detalles))

    if r["indicaciones"]:
        story.append(Paragraph("Indicaciones adicionales", section))
        story.append(Paragraph(
            r["indicaciones"].replace("\n", "<br/>"), styles["Normal"]
        ))

    story.append(Paragraph("Profesional sanitario", section))
    story.append(_build_pdf_table([
        ["Médico", medico_nombre],
        ["Especialidad / Rama", r["medico_especialidad"] or "—"],
        ["Usuario interno", r["medico_usuario"] or "—"],
        ["Correo profesional", r["medico_email"] or "—"],
    ]))

    # Firma del medico (data URL PNG -> embed)
    firma = r["firma_base64"] or ""
    if firma.startswith("data:image"):
        try:
            import base64 as _b64
            head, b64data = firma.split(",", 1)
            firma_bytes = _b64.b64decode(b64data)
            firma_io = io.BytesIO(firma_bytes)
            story.append(Spacer(1, 14))
            story.append(Paragraph("Firma del médico:", section))
            firma_img = RLImage(firma_io, width=7*cm, height=3.2*cm)
            firma_img.hAlign = "LEFT"
            story.append(firma_img)
        except Exception:
            log.exception("No se pudo embedir la firma en el PDF")

    story.append(Spacer(1, 24))
    pie = ParagraphStyle("pie", parent=styles["Normal"],
                         textColor=colors.HexColor("#64748b"),
                         fontSize=9, alignment=1, leading=14)
    story.append(Paragraph(
        f"Documento generado el {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}<br/>"
        f"Turnix Salud · Receta verificable: RX-{r['id']:08d}<br/>"
        f"Solo válida acompañada de la firma del profesional sanitario.",
        pie))

    doc.build(story)
    buf.seek(0)
    safe_name = "".join(c for c in r["nombre_receta"] if c.isalnum() or c in " -_").strip().replace(" ", "_") or "receta"
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="receta_{r["id"]}_{safe_name}.pdf"'},
    )





# ======================================================================
# REGISTRO CON VERIFICACION DE EMAIL (Resend)
# ======================================================================
class RegisterInit(BaseModel):
    usuario: str
    password: str
    nombre_completo: str
    email: str


@api.post("/auth/register-init")
async def auth_register_init(body: RegisterInit):
    """Crea cuenta con email_verificado=FALSE, genera codigo y lo envia por email."""
    codigo = _gen_codigo()
    async with app.state.pool.acquire() as conn:
        existe = await conn.fetchval("SELECT 1 FROM usuarios WHERE usuario=$1", body.usuario)
        if existe:
            raise HTTPException(409, "Ese usuario ya existe")
        row = await conn.fetchrow(
            """INSERT INTO usuarios
                (nombre, usuario, contraseña, rol, nombre_completo, correo_electronico,
                 email_verificado, codigo_verif, codigo_expira)
               VALUES ($1, $2, $3, 'PACIENTE'::rol_usuario, $4, $5,
                       FALSE, $6, NOW() + INTERVAL '15 minutes')
               RETURNING id""",
            body.nombre_completo, body.usuario, body.password,
            body.nombre_completo, body.email, codigo,
        )
    try:
        await enviar_codigo_email(body.email, codigo, body.nombre_completo)
    except Exception as e:
        log.warning(f"No se pudo enviar email de verificación: {e}")
    # No borramos el usuario ni devolvemos error.
    # El usuario se crea igual (para que puedas probar)
    return {"user_id": row["id"], "email": body.email, "ok": True}


class RegisterConfirm(BaseModel):
    user_id: int
    codigo: str


@api.post("/auth/register-confirm")
async def auth_register_confirm(body: RegisterConfirm):
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT codigo_verif, codigo_expira, email_verificado
                 FROM usuarios WHERE id=$1""", body.user_id,
        )
        if not row:
            raise HTTPException(404, "Usuario no encontrado")
        if row["email_verificado"]:
            return {"ok": True, "already": True}
        if row["codigo_verif"] != body.codigo.strip():
            raise HTTPException(400, "Código incorrecto")
        if row["codigo_expira"] and row["codigo_expira"] < datetime.now(timezone.utc):
            raise HTTPException(400, "Código caducado, solicita uno nuevo")
        await conn.execute(
            """UPDATE usuarios SET email_verificado=TRUE,
                                   codigo_verif=NULL, codigo_expira=NULL
                WHERE id=$1""", body.user_id,
        )
    return {"ok": True}


class ResendCode(BaseModel):
    usuario: str


@api.post("/auth/resend-code")
async def auth_resend(body: ResendCode):
    codigo = _gen_codigo()
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE usuarios SET codigo_verif=$1,
                                   codigo_expira=NOW() + INTERVAL '15 minutes'
                WHERE usuario=$2 AND email_verificado=FALSE
                RETURNING id, correo_electronico AS email, nombre_completo""",
            codigo, body.usuario,
        )
    if not row:
        raise HTTPException(404, "No hay verificación pendiente para ese usuario")
    await enviar_codigo_email(row["email"], codigo, row["nombre_completo"])
    return {"ok": True, "user_id": row["id"]}


# ======================================================================
# Recuperacion de contrasena (forgot password)
# ======================================================================
class ForgotInit(BaseModel):
    email: str

class ForgotVerify(BaseModel):
    email: str
    codigo: str

class ForgotReset(BaseModel):
    email: str
    codigo: str
    nueva_password: str


async def enviar_codigo_reset(destinatario: str, codigo: str, nombre: str):
    if not RESEND_API_KEY:
        log.warning("RESEND_API_KEY no configurado, no se envia email de reset a %s", destinatario)
        return None
    html = f"""
    <table style="font-family: Arial, sans-serif; max-width: 520px; margin: auto; border: 1px solid #e2e8f0; border-radius: 12px; padding: 30px;">
      <tr><td style="text-align:center;">
        <h1 style="color: #0d9488; margin: 0 0 10px;">Turnix Salud</h1>
        <p style="color: #475569; margin: 0 0 24px;">Recuperación de contraseña</p>
        <p style="color: #1e293b; font-size: 15px;">Hola <b>{nombre or destinatario}</b>,</p>
        <p style="color: #1e293b; font-size: 15px;">Recibimos una solicitud para reestablecer tu contraseña. Tu código es:</p>
        <div style="background: #0d9488; color: white; font-size: 32px; letter-spacing: 8px; font-weight: bold;
                    padding: 18px; border-radius: 12px; margin: 18px 0;">{codigo}</div>
        <p style="color: #64748b; font-size: 12px;">Caduca en 15 minutos. Si no fuiste tú, ignora este mensaje y tu contraseña seguirá intacta.</p>
      </td></tr>
    </table>"""
    params = {"from": SENDER_EMAIL, "to": [destinatario],
              "subject": "Turnix · Recuperar contraseña", "html": html}
    try:
        return await asyncio.to_thread(resend.Emails.send, params)
    except Exception as e:
        log.exception("Resend reset fallo: %s", e)
        raise HTTPException(500, f"No se pudo enviar el email: {e}")


@api.post("/auth/forgot-password")
async def auth_forgot(body: ForgotInit):
    email = body.email.strip().lower()
    if not email:
        raise HTTPException(400, "Email requerido")
    codigo = _gen_codigo()
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE usuarios
                  SET codigo_verif = $1,
                      codigo_expira = NOW() + INTERVAL '15 minutes'
                WHERE LOWER(correo_electronico) = $2
                RETURNING id, correo_electronico, nombre_completo, usuario""",
            codigo, email,
        )
    if not row:
        # No exponer si el email existe (anti enumeracion). Devolvemos OK igualmente.
        log.info("Forgot-password para email desconocido: %s", email)
        return {"ok": True}
    await enviar_codigo_reset(row["correo_electronico"], codigo, row["nombre_completo"] or row["usuario"])
    return {"ok": True}


@api.post("/auth/verify-reset-code")
async def auth_verify_reset(body: ForgotVerify):
    email = body.email.strip().lower()
    codigo = body.codigo.strip()
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT codigo_verif, codigo_expira FROM usuarios
                WHERE LOWER(correo_electronico) = $1""",
            email,
        )
    if not row or not row["codigo_verif"]:
        raise HTTPException(400, "Código inválido o caducado")
    if row["codigo_verif"] != codigo:
        raise HTTPException(400, "Código incorrecto")
    if row["codigo_expira"] and row["codigo_expira"] < datetime.now(timezone.utc):
        raise HTTPException(400, "Código caducado")
    return {"ok": True}


@api.post("/auth/reset-password")
async def auth_reset_password(body: ForgotReset):
    email = body.email.strip().lower()
    codigo = body.codigo.strip()
    nueva = body.nueva_password
    if len(nueva) < 4:
        raise HTTPException(400, "La contraseña debe tener al menos 4 caracteres")
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT codigo_verif, codigo_expira FROM usuarios
                WHERE LOWER(correo_electronico) = $1""", email,
        )
        if not row or row["codigo_verif"] != codigo:
            raise HTTPException(400, "Código incorrecto")
        if row["codigo_expira"] and row["codigo_expira"] < datetime.now(timezone.utc):
            raise HTTPException(400, "Código caducado")
        # Actualizamos password en plano para mantener consistencia con el resto
        # del sistema (admin/medico1/user1 estan en plano).
        await conn.execute(
            """UPDATE usuarios
                  SET contraseña = $1,
                      codigo_verif = NULL,
                      codigo_expira = NULL
                WHERE LOWER(correo_electronico) = $2""",
            nueva, email,
        )
    return {"ok": True}


# ======================================================================
# Especialidades disponibles
# ======================================================================
@api.get("/especialidades")
async def especialidades():
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT DISTINCT especialidad FROM usuarios
                WHERE especialidad IS NOT NULL AND especialidad <> ''"""
        )
    extras = [r["especialidad"] for r in rows if r["especialidad"] not in ESPECIALIDADES_BASE]
    return {"base": ESPECIALIDADES_BASE, "extras": extras}


# ======================================================================
# Solicitudes de cambio de especialidad
# ======================================================================
class EspecialidadReq(BaseModel):
    medico_id: int
    password: str
    especialidad_nueva: str
    motivo: Optional[str] = ""


@api.post("/medico/solicitar-especialidad")
async def solicitar_especialidad(body: EspecialidadReq):
    async with app.state.pool.acquire() as conn:
        m = await conn.fetchrow(
            """SELECT id, especialidad, contraseña AS password, rol::text AS rol
                 FROM usuarios WHERE id=$1""", body.medico_id,
        )
        if not m or m["rol"] != "MEDICO":
            raise HTTPException(403, "Solo médicos pueden solicitar cambio")
        if m["password"] != body.password:
            raise HTTPException(401, "Contraseña incorrecta")
        await conn.execute(
            """UPDATE solicitudes_especialidad SET estado='CANCELADA'
                WHERE medico_id=$1 AND estado='PENDIENTE'""", body.medico_id,
        )
        await conn.execute(
            """INSERT INTO solicitudes_especialidad
                (medico_id, especialidad_actual, especialidad_nueva, motivo)
               VALUES ($1, $2, $3, $4)""",
            body.medico_id, m["especialidad"], body.especialidad_nueva, body.motivo or "",
        )
    return {"ok": True}


# ======================================================================
# ADMIN: requiere usuario+password en cada request
# ======================================================================
async def _check_admin(usuario: str, password: str) -> int:
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id FROM usuarios
                WHERE usuario=$1 AND contraseña=$2 AND rol='ADMIN'""",
            usuario, password,
        )
    if not row:
        raise HTTPException(403, "Credenciales de administrador no válidas")
    return row["id"]


class AdminCreds(BaseModel):
    admin_usuario: str
    admin_password: str


@api.post("/admin/login")
async def admin_login(body: AdminCreds):
    await _check_admin(body.admin_usuario, body.admin_password)
    return {"ok": True}


@api.post("/admin/users")
async def admin_users(body: AdminCreds):
    await _check_admin(body.admin_usuario, body.admin_password)
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, usuario, nombre, nombre_completo, correo_electronico AS email,
                      rol::text AS rol, especialidad, email_verificado,
                      total_votos, suma_valoraciones, fecha_creacion
                 FROM usuarios ORDER BY id ASC"""
        )
    return [dict(r) for r in rows]


class AdminDelete(BaseModel):
    admin_usuario: str
    admin_password: str
    target_user_id: int


@api.post("/admin/delete-user")
async def admin_delete(body: AdminDelete):
    admin_id = await _check_admin(body.admin_usuario, body.admin_password)
    if body.target_user_id == admin_id:
        raise HTTPException(400, "No puedes borrar tu propia cuenta")
    async with app.state.pool.acquire() as conn:
        await conn.execute("DELETE FROM mensajes WHERE emisor_id=$1", body.target_user_id)
        await conn.execute(
            "DELETE FROM recetas WHERE medico_id=$1 OR paciente_id=$1",
            body.target_user_id,
        )
        await conn.execute(
            """DELETE FROM documentos WHERE id_turno IN
                (SELECT id FROM turnos WHERE id_paciente=$1 OR atendido_por=$1)""",
            body.target_user_id,
        )
        await conn.execute(
            """DELETE FROM historial WHERE id_turno IN
                (SELECT id FROM turnos WHERE id_paciente=$1 OR atendido_por=$1)""",
            body.target_user_id,
        )
        await conn.execute(
            """DELETE FROM valoraciones WHERE turno_id IN
                (SELECT id FROM turnos WHERE id_paciente=$1 OR atendido_por=$1)""",
            body.target_user_id,
        )
        await conn.execute(
            "DELETE FROM turnos WHERE id_paciente=$1 OR atendido_por=$1",
            body.target_user_id,
        )
        await conn.execute("DELETE FROM solicitudes_especialidad WHERE medico_id=$1", body.target_user_id)
        await conn.execute("DELETE FROM usuarios WHERE id=$1", body.target_user_id)
    return {"ok": True}


class AdminEditUser(BaseModel):
    admin_usuario: str
    admin_password: str
    target_user_id: int
    usuario: Optional[str] = None
    nombre: Optional[str] = None
    nombre_completo: Optional[str] = None
    email: Optional[str] = None
    rol: Optional[str] = None              # 'ADMIN' | 'MEDICO' | 'PACIENTE'
    especialidad: Optional[str] = None
    password: Optional[str] = None
    email_verificado: Optional[bool] = None


@api.post("/admin/edit-user")
async def admin_edit(body: AdminEditUser):
    admin_id = await _check_admin(body.admin_usuario, body.admin_password)
    # Reglas minimas
    if body.rol is not None and body.rol not in ("ADMIN", "MEDICO", "PACIENTE"):
        raise HTTPException(400, "Rol invalido")
    if body.target_user_id == admin_id and body.rol and body.rol != "ADMIN":
        raise HTTPException(400, "No puedes cambiar tu propio rol")
    sets, params, i = [], [], 1
    def add(col, val, cast=""):
        nonlocal i
        sets.append(f"{col}=${i}{cast}")
        params.append(val); i += 1
    if body.usuario is not None:          add("usuario", body.usuario.strip())
    if body.nombre is not None:           add("nombre", body.nombre.strip())
    if body.nombre_completo is not None:  add("nombre_completo", body.nombre_completo.strip())
    if body.email is not None:            add("correo_electronico", body.email.strip())
    if body.rol is not None:              add("rol", body.rol, "::rol_usuario")
    if body.especialidad is not None:     add("especialidad", body.especialidad.strip() or None)
    if body.password:                     add("contraseña", body.password)
    if body.email_verificado is not None: add("email_verificado", body.email_verificado)
    if not sets:
        return {"ok": True, "changed": 0}
    params.append(body.target_user_id)
    sql = f"UPDATE usuarios SET {', '.join(sets)} WHERE id=${i} RETURNING id"
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(sql, *params)
    if not row:
        raise HTTPException(404, "Usuario no encontrado")
    return {"ok": True, "changed": len(sets), "id": row["id"]}


# ======================================================================
# Historial de conexiones (uptime medicos / admins) - para panel admin
# ======================================================================
class AdminConnHistoryReq(BaseModel):
    admin_usuario: str
    admin_password: str
    range: Optional[str] = "month"   # 'week' | 'month' | 'all' | 'custom'
    desde: Optional[str] = None      # ISO "YYYY-MM-DD"
    hasta: Optional[str] = None      # ISO "YYYY-MM-DD"
    usuario_id: Optional[int] = None # filtrar por medico concreto


@api.post("/admin/conn-history")
async def admin_conn_history(body: AdminConnHistoryReq):
    await _check_admin(body.admin_usuario, body.admin_password)
    where = ["1=1"]
    params: List[Any] = []
    i = 1

    if body.usuario_id:
        where.append(f"s.usuario_id = ${i}")
        params.append(body.usuario_id); i += 1

    if body.range == "custom" and (body.desde or body.hasta):
        if body.desde:
            where.append(f"s.fecha_inicio >= ${i}::date")
            params.append(body.desde); i += 1
        if body.hasta:
            where.append(f"s.fecha_inicio < (${i}::date + INTERVAL '1 day')")
            params.append(body.hasta); i += 1
    elif body.range == "week":
        where.append("s.fecha_inicio >= NOW() - INTERVAL '7 days'")
    elif body.range == "all":
        pass
    else:  # 'month' por defecto
        where.append("s.fecha_inicio >= NOW() - INTERVAL '30 days'")

    sql = f"""
        SELECT s.id, s.usuario_id, s.rol,
               s.fecha_inicio, s.fecha_fin, s.duracion_seg,
               u.usuario, u.nombre_completo, u.rol::text AS rol, u.especialidad,
               (s.fecha_fin IS NULL) AS activa
          FROM sesiones_conexion s
          JOIN usuarios u ON u.id = s.usuario_id
         WHERE {' AND '.join(where)}
         ORDER BY s.fecha_inicio DESC
         LIMIT 1000
    """
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
        # Resumen agregado por usuario (sólo dentro del filtro)
        agg = await conn.fetch(
            f"""SELECT s.usuario_id, u.usuario, u.nombre_completo, u.rol::text AS rol,
                       COUNT(*)::INT AS total_sesiones,
                       COALESCE(SUM(
                         CASE WHEN s.duracion_seg IS NOT NULL THEN s.duracion_seg
                              ELSE EXTRACT(EPOCH FROM (NOW() - s.fecha_inicio))::INT END
                       ), 0)::INT AS total_seg,
                       BOOL_OR(s.fecha_fin IS NULL) AS activa
                  FROM sesiones_conexion s
                  JOIN usuarios u ON u.id = s.usuario_id
                 WHERE {' AND '.join(where)}
              GROUP BY s.usuario_id, u.usuario, u.nombre_completo, u.rol
              ORDER BY total_seg DESC""",
            *params,
        )

    # Calcular duracion en vivo si esta activa
    def session_dict(r):
        d = dict(r)
        if d["activa"] and d["fecha_fin"] is None:
            delta = (datetime.now(timezone.utc) - d["fecha_inicio"]).total_seconds()
            d["duracion_seg"] = int(max(0, delta))
        return d

    return {
        "ok": True,
        "filtro": body.range,
        "sesiones": [session_dict(r) for r in rows],
        "resumen": [dict(r) for r in agg],
    }


@api.post("/admin/specialty-requests")
async def admin_spec_list(body: AdminCreds):
    await _check_admin(body.admin_usuario, body.admin_password)
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT s.id, s.medico_id, s.especialidad_actual, s.especialidad_nueva,
                      s.motivo, s.estado, s.fecha_solicitud, s.fecha_resolucion,
                      u.usuario AS medico_usuario, u.nombre_completo AS medico_nombre,
                      u.email AS medico_email
                 FROM solicitudes_especialidad s
                 JOIN usuarios u ON u.id = s.medico_id
                ORDER BY (s.estado='PENDIENTE') DESC, s.fecha_solicitud DESC"""
        )
    return [dict(r) for r in rows]


class AdminSpecAction(BaseModel):
    admin_usuario: str
    admin_password: str
    request_id: int
    action: str  # 'APROBADA' o 'RECHAZADA'


@api.post("/admin/specialty-action")
async def admin_spec_action(body: AdminSpecAction):
    admin_id = await _check_admin(body.admin_usuario, body.admin_password)
    if body.action not in ("APROBADA", "RECHAZADA"):
        raise HTTPException(400, "Acción inválida")
    async with app.state.pool.acquire() as conn:
        req = await conn.fetchrow(
            "SELECT medico_id, especialidad_nueva FROM solicitudes_especialidad WHERE id=$1 AND estado='PENDIENTE'",
            body.request_id,
        )
        if not req:
            raise HTTPException(404, "Solicitud no encontrada o ya resuelta")
        await conn.execute(
            """UPDATE solicitudes_especialidad
                  SET estado=$1, fecha_resolucion=NOW(), resuelto_por=$2
                WHERE id=$3""", body.action, admin_id, body.request_id,
        )
        if body.action == "APROBADA":
            await conn.execute(
                "UPDATE usuarios SET especialidad=$1 WHERE id=$2",
                req["especialidad_nueva"], req["medico_id"],
            )
    return {"ok": True}


# ======================================================================
# Doctor online/offline toggle (in-memory)
# ======================================================================
class ToggleOffline(BaseModel):
    medico_id: int
    offline: bool


@api.post("/medico/toggle-offline")
async def toggle_offline(body: ToggleOffline):
    if body.offline:
        medicos_offline.add(body.medico_id)
        # Cerrar cualquier sesion activa de este medico
        try:
            async with app.state.pool.acquire() as conn:
                await conn.execute(
                    """UPDATE sesiones_conexion
                          SET fecha_fin = NOW(),
                              duracion_seg = GREATEST(0, EXTRACT(EPOCH FROM (NOW() - fecha_inicio))::INT)
                        WHERE usuario_id = $1 AND fecha_fin IS NULL""",
                    body.medico_id,
                )
            # Quitar la asociacion ws->session para que el disconnect no cierre nada
            for ws_id, sid in list(ws_session_ids.items()):
                # No conocemos el medico_id desde el id(ws); recargamos por consulta
                pass
            # Limpieza del mapping: cualquier ws cuyo user.id == medico_id pierde su session_id
            for c in all_clients:
                u = get_user(c)
                if u and u.get("id") == body.medico_id:
                    ws_session_ids.pop(id(c), None)
        except Exception:
            log.exception("Cerrando sesion al ir offline fallo")
    else:
        medicos_offline.discard(body.medico_id)
        # Reabrir sesion (solo si hay ws activo de ese medico y no tiene una abierta)
        try:
            async with app.state.pool.acquire() as conn:
                ya = await conn.fetchval(
                    "SELECT id FROM sesiones_conexion WHERE usuario_id=$1 AND fecha_fin IS NULL LIMIT 1",
                    body.medico_id,
                )
            if not ya:
                target_ws = None
                for c in all_clients:
                    u = get_user(c)
                    if u and u.get("id") == body.medico_id:
                        target_ws = c
                        break
                if target_ws:
                    await session_open(target_ws, get_user(target_ws))
        except Exception:
            log.exception("Reabriendo sesion al ir online fallo")
    return {"ok": True, "offline": body.offline}



# ----------------------------------------------------------------------
# WebSocket - protocolo replicado del ServidorWeb.java
# ----------------------------------------------------------------------
@api.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    all_clients.append(ws)
    log.info("Nueva conexion WS desde %s", ws.client)
    try:
        while True:
            message = await ws.receive_text()
            log.info("Mensaje: %s", message[:120])
            await handle_message(ws, message)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.exception("Error en WS: %s", e)
    finally:
        # Cerrar sesion de tiempo conectado (MEDICO/ADMIN)
        await session_close(ws)
        # Avisar a los medicos si el que se va era paciente
        u_out = get_user(ws)
        if u_out and u_out.get("rol") == "PACIENTE":
            disp = display_name(u_out)
            for c in all_clients:
                u2 = get_user(c)
                if u2 and u2["rol"] in ("MEDICO", "ADMIN"):
                    await safe_send(c, f"SISTEMA_PACIENTE_DESCONECTADO:{u_out['usuario']}:{disp}")
        if ws in cola_espera:
            cola_espera.remove(ws)
        if ws in all_clients:
            all_clients.remove(ws)
        set_user(ws, None)
        await actualizar_posiciones_cola()


async def handle_message(ws: WebSocket, message: str):
    pool: asyncpg.Pool = app.state.pool

    # ==================== LOGIN ====================
    if message.startswith("login:"):
        partes = message.split(":")
        if len(partes) < 3:
            await safe_send(ws, "ERROR: formato login")
            return
        username, password = partes[1], partes[2]
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT id, nombre, usuario, rol::text AS rol, correo_electronico AS email, nombre_completo,
                              especialidad,
                              COALESCE(suma_valoraciones,0) AS suma, COALESCE(total_votos,0) AS total
                         FROM usuarios WHERE usuario=$1 AND contraseña=$2""",
                    username, password,
                )
            if row:
                user = dict(row)
                # Bloquear si email no verificado (solo PACIENTE)
                if user["rol"] == "PACIENTE":
                    async with pool.acquire() as conn:
                        ver = await conn.fetchval("SELECT email_verificado FROM usuarios WHERE id=$1", user["id"])
                    if not ver:
                        await safe_send(ws, f"NEEDS_VERIFICATION:{user['id']}")
                        return
                set_user(ws, user)
                await session_open(ws, user)
                nombre = display_name(user)
                await safe_send(ws, f"LOGIN_OK:{user['rol']}:{nombre}:{user['id']}:{user['usuario']}")
                if user["rol"] in ("MEDICO", "ADMIN"):
                    media = 0.0
                    total = user["total"] or 0
                    if total > 0:
                        media = round(float(user["suma"]) / total * 10.0) / 10.0
                    await safe_send(ws, f"VALORACION_ACTUALIZADA:{media}:{total}")
                # Broadcast a medicos: paciente conectado
                if user["rol"] == "PACIENTE":
                    for c in all_clients:
                        u2 = get_user(c)
                        if u2 and u2["rol"] in ("MEDICO", "ADMIN"):
                            await safe_send(c, f"SISTEMA_PACIENTE_CONECTADO:{user['usuario']}:{nombre}")
            else:
                await safe_send(ws, "ERROR: Usuario o clave incorrectos")
        except Exception as e:
            log.exception("Login error")
            await safe_send(ws, "ERROR: Fallo en autenticacion")
        return

    # ==================== REGISTRO (legacy, mantenido para compat) ====================
    if message.startswith("registro:"):
        # El flujo nuevo es REST /api/auth/register-init + /register-confirm.
        # Aquí solo devolvemos un error para forzar al cliente a usar el modal nuevo.
        await safe_send(ws, "REGISTRO_LEGACY_DEPRECATED")
        return

    # ==================== PEDIR TURNO ====================
    if message.startswith("PEDIR_TURNO"):
        user = get_user(ws)
        if not user:
            await safe_send(ws, "ERROR: No autenticado")
            return
        # Formato: PEDIR_TURNO:<tipo>:<prioridad>   (opcional, default Otro/Moderada)
        tipo = "Otro"
        prioridad = "Moderada"
        if ":" in message:
            partes = message.split(":", 2)
            if len(partes) >= 2 and partes[1]:
                tipo = partes[1]
            if len(partes) >= 3 and partes[2]:
                prioridad = partes[2]
        # Comprobar si ya tiene turno en espera
        for w in cola_espera:
            u = get_user(w)
            if u and u["id"] == user["id"]:
                await safe_send(ws, "ERROR: Ya tienes un turno en espera.")
                return
        nombre = display_name(user)
        try:
            async with pool.acquire() as conn:
                num = await conn.fetchval(
                    "SELECT COALESCE(MAX(numero_turno),0)+1 FROM turnos"
                )
                row = await conn.fetchrow(
                    """INSERT INTO turnos
                        (numero_turno, cliente, estado, fecha, id_paciente, tipo_consulta, prioridad)
                       VALUES ($1,$2,'EN_ESPERA'::estado_turno, NOW(), $3, $4, $5)
                       RETURNING id, numero_turno""",
                    num, nombre, user["id"], tipo, prioridad,
                )
            # Marcar el WS con el turno en cola (con tipo+prioridad embebidos)
            ws.turno_tipo = tipo
            ws.turno_prioridad = prioridad
            ws.turno_usuario = user["usuario"]
            cola_espera.append(ws)
            # Broadcast filtrado: solo medicos con esa especialidad (o todos si 'Otro')
            # y que no estén offline
            msg = f"TURNO_ASIGNADO:{nombre}:{user['usuario']}:{row['numero_turno']}:{tipo}:{prioridad}"
            for c in all_clients:
                u2 = get_user(c)
                if not u2: continue
                if u2["rol"] not in ("MEDICO", "ADMIN"): 
                    # Otros pacientes también reciben el broadcast genérico para feedback
                    await safe_send(c, msg); continue
                if u2["id"] in medicos_offline: continue
                # Filtro por especialidad
                if tipo != "Otro" and u2["rol"] == "MEDICO":
                    esp = (u2.get("especialidad") or "").strip()
                    if esp and esp != tipo:
                        continue
                await safe_send(c, msg)
            await actualizar_posiciones_cola()
        except Exception as e:
            log.exception("PEDIR_TURNO error")
            await safe_send(ws, "ERROR: No se pudo crear el turno")
        return


    # ==================== LLAMAR SIGUIENTE ====================
    if message == "LLAMAR_SIGUIENTE":
        medico = get_user(ws)
        if not medico:
            await safe_send(ws, "ERROR: No autenticado"); return
        if medico["id"] in medicos_offline:
            await safe_send(ws, "ERROR: Estás en modo desconectado. Vuelve a conectarte para atender pacientes.")
            return
        esp_medico = (medico.get("especialidad") or "").strip()
        # Buscar el primer paciente en cola cuyo tipo encaje con la especialidad
        # (o tipo='Otro' que es para cualquiera, o si el medico no tiene especialidad asignada)
        paciente_ws = None
        for w in list(cola_espera):
            tipo = getattr(w, "turno_tipo", "Otro") or "Otro"
            if tipo == "Otro" or not esp_medico or esp_medico == tipo:
                paciente_ws = w
                cola_espera.remove(w)
                break
        if paciente_ws is None:
            await safe_send(ws, "ERROR: No hay pacientes en cola que coincidan con tu especialidad.")
            return
        await actualizar_posiciones_cola()
        nombre_medico = medico["usuario"]
        if paciente_ws and paciente_ws.client_state.value == 1:
            paciente_user = get_user(paciente_ws)
            nombre_paciente = paciente_user["usuario"] if paciente_user else "Paciente"
            await safe_send(paciente_ws, "SISTEMA: LLAMADA_A_CONSULTA")
            await safe_send(paciente_ws, f"COMANDO:ENTRAR_CONSULTA:{nombre_medico}")
            await safe_send(ws, f"COMANDO:ABRIR_CHAT:{nombre_paciente}")
        return

    # ==================== INICIAR CONSULTA MANUAL (desde boton "Atender") ====================
    if message.startswith("INICIAR_CONSULTA_MANUAL:"):
        nombre_paciente = message[len("INICIAR_CONSULTA_MANUAL:"):].strip()
        medico = get_user(ws)
        nombre_medico = medico["usuario"] if medico else "Médico"
        if medico:
            async with pool.acquire() as conn:
                await conn.execute(
                    """UPDATE turnos
                          SET atendido_por = $1,
                              estado = 'EN_CONSULTA'::estado_turno,
                              fecha_inicio_consulta = NOW()
                        WHERE id = (
                            SELECT t2.id FROM turnos t2
                              JOIN usuarios up ON up.id = t2.id_paciente
                             WHERE (up.usuario = $2 OR up.nombre_completo = $2 OR up.nombre = $2)
                               AND t2.estado IN ('EN_ESPERA', 'EN_CONSULTA')
                             ORDER BY t2.id DESC LIMIT 1
                        )""",
                    medico["id"], nombre_paciente
                )

        for c in all_clients:
            u = get_user(c)
            if u and (u["usuario"] == nombre_paciente
                      or display_name(u) == nombre_paciente
                      or (u.get("nombre_completo") or "") == nombre_paciente):
                await safe_send(c, "SISTEMA: LLAMADA_A_CONSULTA")
                await safe_send(c, f"COMANDO:ENTRAR_CONSULTA:{nombre_medico}")
                if c in cola_espera:
                    cola_espera.remove(c)
                    await actualizar_posiciones_cola()
                break

        await safe_send(ws, f"CHAT_DE_PACIENTE: 🟢 Has iniciado la consulta con {nombre_paciente}")
        return

    # ==================== CHAT PRIVADO (medico -> paciente) ====================
    if message.startswith("CHAT_PRIVADO:"):
        partes = message.split(":", 2)
        if len(partes) >= 3:
            destino, texto = partes[1], partes[2]
            for c in all_clients:
                u = get_user(c)
                if u:
                    n = display_name(u)
                    if n == destino or u["usuario"] == destino:
                        await safe_send(c, f"MEDICO_DICE:{texto}")
                        break
        return

    # ==================== ENVIAR AL MEDICO (paciente -> medico) ====================
    if message.startswith("ENVIAR_AL_MEDICO:"):
        texto = message[len("ENVIAR_AL_MEDICO:"):].strip()
        emisor = get_user(ws)
        # Persistir mensaje vinculado al turno EN_ESPERA del paciente
        if emisor and emisor["rol"] == "PACIENTE":
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO mensajes (id_turno, emisor_id, contenido, fecha_envio)
                           VALUES (
                             (SELECT id FROM turnos
                                WHERE id_paciente=$1 AND estado IN ('EN_ESPERA','EN_CONSULTA')
                                ORDER BY id DESC LIMIT 1),
                             $1, $2, NOW())""",
                        emisor["id"], texto,
                    )
            except Exception:
                log.exception("Persist mensaje fallo (no critico)")
        # Reenviar a todos los medicos conectados
        for c in all_clients:
            u = get_user(c)
            if u and u["rol"] in ("MEDICO", "ADMIN"):
                await safe_send(c, f"CHAT_DE_PACIENTE:{texto}")
        return

    # ==================== FINALIZAR CONSULTA ====================
    if message.startswith("FINALIZAR_CONSULTA:") or message == "FINALIZAR_CONSULTA":
        if message.startswith("FINALIZAR_CONSULTA:"):
            nombre_paciente = message[len("FINALIZAR_CONSULTA:"):].strip()
        else:
            nombre_paciente = ""
        medico = get_user(ws)
        nombre_medico = medico["usuario"] if medico else "Médico"
        # Marcar como COMPLETADO el turno mas antiguo EN_ESPERA o EN_CONSULTA
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """UPDATE turnos SET estado='COMPLETADO'::estado_turno,
                                          fecha_fin_consulta=NOW()
                       WHERE id = (SELECT id FROM turnos
                                    WHERE estado IN ('EN_ESPERA','EN_CONSULTA')
                                    ORDER BY id ASC LIMIT 1)"""
                )
        except Exception:
            log.exception("Finalizar consulta fallo")
        for c in all_clients:
            await safe_send(c, "SISTEMA: El médico ha finalizado la consulta.")
            await safe_send(c, f"COMANDO:CONSULTA_FINALIZADA:{nombre_medico}")
        return

    # ==================== ATENDER SIGUIENTE (admin) ====================
    if message == "ATENDER_SIGUIENTE":
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        """SELECT id, numero_turno FROM turnos
                            WHERE estado='EN_ESPERA'::estado_turno
                            ORDER BY numero_turno ASC LIMIT 1"""
                    )
                    if row:
                        await conn.execute(
                            "INSERT INTO historial (id_turno, fecha_atendido) VALUES ($1, NOW())",
                            row["id"],
                        )
                        await conn.execute(
                            "UPDATE turnos SET estado='ATENDIDO'::estado_turno WHERE id=$1",
                            row["id"],
                        )
                        await safe_send(ws, "Paciente atendido y movido a historial.")
                    else:
                        await safe_send(ws, "No hay pacientes pendientes.")
        except Exception:
            log.exception("ATENDER_SIGUIENTE fallo")
            await safe_send(ws, "ERROR al atender")
        return

    # ==================== VALORACION (estrellas) ====================
    if message.startswith("VALORACION_MEDICO:"):
        partes = message.split(":")
        if len(partes) >= 3:
            try:
                nota = float(partes[1])
                nombre_medico = partes[2].strip()
                if not nombre_medico or nombre_medico == "undefined":
                    return
                async with pool.acquire() as conn:
                    await conn.execute(
                        """UPDATE usuarios
                              SET suma_valoraciones = COALESCE(suma_valoraciones,0) + $1,
                                  total_votos      = COALESCE(total_votos,0) + 1
                            WHERE usuario=$2 OR nombre_completo=$2 OR nombre=$2""",
                        nota, nombre_medico,
                    )
                    row = await conn.fetchrow(
                        """SELECT COALESCE(suma_valoraciones,0) AS suma,
                                  COALESCE(total_votos,0) AS total
                             FROM usuarios
                            WHERE usuario=$1 OR nombre_completo=$1 OR nombre=$1""",
                        nombre_medico,
                    )
                if row and row["total"] and row["total"] > 0:
                    media = round(float(row["suma"]) / row["total"] * 10.0) / 10.0
                    total = int(row["total"])
                    for c in all_clients:
                        u = get_user(c)
                        if u and (u["usuario"].lower() == nombre_medico.lower()
                                  or (u.get("nombre_completo") or "").lower() == nombre_medico.lower()):
                            await safe_send(c, f"VALORACION_ACTUALIZADA:{media}:{total}")
                            break
            except Exception:
                log.exception("VALORACION_MEDICO error")
        return

    # ==================== VIDEO / SISTEMA flags ====================
    if message == "VIDEO_LLAMADA_INICIADA":
        for c in all_clients:
            u = get_user(c)
            if u and u["rol"] == "PACIENTE":
                await safe_send(c, "VIDEO_LLAMADA_INICIADA")
        return

    if message == "NOTIFICAR_VIDEO_PACIENTE":
        for c in all_clients:
            u = get_user(c)
            if u and u["rol"] in ("MEDICO", "ADMIN"):
                await safe_send(c, "NOTIFICAR_VIDEO_PACIENTE")
        return

    if message == "CONFIRMAR_ASISTENCIA":
        u = get_user(ws)
        if u and u["rol"] == "PACIENTE":
            disp = display_name(u)
            for c in all_clients:
                u2 = get_user(c)
                if u2 and u2["rol"] in ("MEDICO", "ADMIN"):
                    await safe_send(c, f"SISTEMA_PACIENTE_ACEPTO:{u['usuario']}:{disp}")
        return

    # ==================== WEBRTC SIGNALING ====================
    # Formatos:
    #   WEBRTC_CALL_REQUEST:targetUser           (medico pide iniciar videollamada)
    #   WEBRTC_CALL_ACCEPT:targetUser            (paciente acepta)
    #   WEBRTC_CALL_REJECT:targetUser            (paciente rechaza)
    #   WEBRTC_OFFER:targetUser:<json sdp>
    #   WEBRTC_ANSWER:targetUser:<json sdp>
    #   WEBRTC_ICE:targetUser:<json candidate>
    #   WEBRTC_HANGUP:targetUser
    # El servidor reenvia al WS con username == targetUser anteponiendo el sender.
    for kind in ("WEBRTC_CALL_REQUEST", "WEBRTC_CALL_ACCEPT", "WEBRTC_CALL_REJECT",
                 "WEBRTC_OFFER", "WEBRTC_ANSWER", "WEBRTC_ICE", "WEBRTC_HANGUP"):
        prefix = kind + ":"
        if message.startswith(prefix):
            partes = message.split(":", 2)
            target = partes[1] if len(partes) >= 2 else ""
            payload = partes[2] if len(partes) >= 3 else ""
            sender = get_user(ws)
            sender_name = sender["usuario"] if sender else "anon"
            forwarded = f"{kind}:{sender_name}" + (f":{payload}" if payload else "")
            for c in all_clients:
                u = get_user(c)
                if not u:
                    continue
                if (u["usuario"] == target
                        or (u.get("nombre_completo") or "") == target
                        or u["usuario"].lower() == target.lower()):
                    await safe_send(c, forwarded)
                    break
            return

    log.info("Comando no reconocido: %s", message[:60])


app.include_router(api)

# Montaje del frontend estatico (paciente.html, medico.html, etc).
# IMPORTANTE: va al final, despues del router /api, para no robar /api/*.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
    log.info("Frontend estatico servido desde %s", FRONTEND_DIR)
else:
    log.warning("FRONTEND_DIR no existe: %s (la API funcionara sin frontend)", FRONTEND_DIR)
