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
            """SELECT id, nombre, usuario, rol::text AS rol, email, nombre_completo,
                      foto_base64
                 FROM usuarios WHERE usuario=$1 AND password=$2""",
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
            "SELECT password FROM usuarios WHERE id=$1", body.user_id
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
            sets.append(f"password=${i}"); params.append(body.nueva_password); i += 1
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
            """SELECT id, usuario, nombre, nombre_completo, email, foto_base64,
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
                      t.notas_medico, t.atendido_por,
                      m.nombre_completo AS medico_nombre,
                      m.usuario AS medico_usuario,
                      m.especialidad AS medico_especialidad
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
    """Genera un PDF justificante. Solo el dueno del turno puede descargarlo."""
    async with app.state.pool.acquire() as conn:
        turno = await conn.fetchrow(
            """SELECT t.id, t.numero_turno, t.cliente, t.estado::text AS estado,
                      t.fecha, t.fecha_inicio_consulta, t.fecha_fin_consulta,
                      t.notas_medico, t.id_paciente,
                      p.nombre_completo AS paciente_nombre, p.usuario AS paciente_usuario,
                      p.email AS paciente_email,
                      m.nombre_completo AS medico_nombre, m.usuario AS medico_usuario,
                      m.especialidad AS medico_especialidad
                 FROM turnos t
                 LEFT JOIN usuarios p ON p.id=t.id_paciente
                 LEFT JOIN usuarios m ON m.id=t.atendido_por
                WHERE t.id=$1""", turno_id,
        )
    if not turno:
        raise HTTPException(404, "Turno no encontrado")
    if turno["id_paciente"] != user_id:
        raise HTTPException(403, "Este justificante no pertenece a tu cuenta")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=colors.HexColor("#1E88E5"),
                        alignment=1, fontSize=22, spaceAfter=6)
    sub = ParagraphStyle("sub", parent=styles["Normal"], alignment=1, textColor=colors.grey,
                         fontSize=10, spaceAfter=18)
    story: List[Any] = []
    story.append(Paragraph("🏥 TURNIX SALUD", h1))
    story.append(Paragraph("Justificante oficial de consulta médica", sub))

    def fmt(dt):
        if not dt: return "—"
        if isinstance(dt, str): return dt
        return dt.strftime("%d/%m/%Y %H:%M")

    data = [
        ["Número de turno", f"#{turno['numero_turno']}"],
        ["Paciente", turno["paciente_nombre"] or turno["paciente_usuario"] or turno["cliente"]],
        ["Usuario", turno["paciente_usuario"] or "—"],
        ["Email", turno["paciente_email"] or "—"],
        ["Fecha de solicitud", fmt(turno["fecha"])],
        ["Inicio de consulta", fmt(turno["fecha_inicio_consulta"])],
        ["Fin de consulta", fmt(turno["fecha_fin_consulta"])],
        ["Estado", turno["estado"]],
        ["Médico", turno["medico_nombre"] or turno["medico_usuario"] or "Sin asignar"],
        ["Especialidad", turno["medico_especialidad"] or "—"],
    ]
    t = Table(data, colWidths=[5.5*cm, 10.5*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#E0F2F1")),
        ("TEXTCOLOR", (0,0), (0,-1), colors.HexColor("#0F4C5C")),
        ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
        ("FONTNAME", (1,0), (1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 10),
        ("ROWBACKGROUNDS", (1,0), (1,-1), [colors.white, colors.HexColor("#F8FAFB")]),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LINEBELOW", (0,0), (-1,-1), 0.3, colors.lightgrey),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
    ]))
    story.append(t)

    if turno["notas_medico"]:
        story.append(Spacer(1, 18))
        story.append(Paragraph("<b>Observaciones del médico</b>", styles["Heading3"]))
        story.append(Paragraph(turno["notas_medico"], styles["BodyText"]))

    story.append(Spacer(1, 30))
    pie = ParagraphStyle("pie", parent=styles["Normal"], textColor=colors.grey,
                         fontSize=8, alignment=1)
    story.append(Paragraph(
        f"Documento generado automáticamente el {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}<br/>"
        f"Sistema Turnix Salud · Verificación: TURNIX-{turno['id']:08d}", pie))

    doc.build(story)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="justificante_turno_{turno["numero_turno"]}.pdf"'},
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
                (nombre, usuario, password, rol, nombre_completo, email,
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
                RETURNING id, email, nombre_completo""",
            codigo, body.usuario,
        )
    if not row:
        raise HTTPException(404, "No hay verificación pendiente para ese usuario")
    await enviar_codigo_email(row["email"], codigo, row["nombre_completo"])
    return {"ok": True, "user_id": row["id"]}


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
            """SELECT id, especialidad, password, rol::text AS rol
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
                WHERE usuario=$1 AND password=$2 AND rol='ADMIN'""",
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
            """SELECT id, usuario, nombre, nombre_completo, email,
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
    else:
        medicos_offline.discard(body.medico_id)
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
                    """SELECT id, nombre, usuario, rol::text AS rol, email, nombre_completo,
                              especialidad,
                              COALESCE(suma_valoraciones,0) AS suma, COALESCE(total_votos,0) AS total
                         FROM usuarios WHERE usuario=$1 AND password=$2""",
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
        for c in all_clients:
            u = get_user(c)
            if u and u["usuario"] == nombre_paciente:
                await safe_send(c, "SISTEMA: LLAMADA_A_CONSULTA")
                await safe_send(c, f"COMANDO:ENTRAR_CONSULTA:{nombre_medico}")
                # Sacar al paciente de la cola si estaba
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
    #   WEBRTC_OFFER:targetUser:<json sdp>
    #   WEBRTC_ANSWER:targetUser:<json sdp>
    #   WEBRTC_ICE:targetUser:<json candidate>
    #   WEBRTC_HANGUP:targetUser
    # El servidor reenvia al WS con username == targetUser anteponiendo el sender.
    for kind in ("WEBRTC_OFFER", "WEBRTC_ANSWER", "WEBRTC_ICE", "WEBRTC_HANGUP"):
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
