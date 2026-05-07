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
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import asyncpg

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

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
                              COALESCE(suma_valoraciones,0) AS suma, COALESCE(total_votos,0) AS total
                         FROM usuarios WHERE usuario=$1 AND password=$2""",
                    username, password,
                )
            if row:
                user = dict(row)
                set_user(ws, user)
                # Si es medico/admin, enviar reputacion actual
                nombre = display_name(user)
                await safe_send(ws, f"LOGIN_OK:{user['rol']}:{nombre}:{user['id']}:{user['usuario']}")
                if user["rol"] in ("MEDICO", "ADMIN"):
                    media = 0.0
                    total = user["total"] or 0
                    if total > 0:
                        media = round(float(user["suma"]) / total * 10.0) / 10.0
                    await safe_send(ws, f"VALORACION_ACTUALIZADA:{media}:{total}")
            else:
                await safe_send(ws, "ERROR: Usuario o clave incorrectos")
        except Exception as e:
            log.exception("Login error")
            await safe_send(ws, "ERROR: Fallo en autenticacion")
        return

    # ==================== REGISTRO ====================
    if message.startswith("registro:"):
        partes = message.split(":", 3)
        if len(partes) < 4:
            await safe_send(ws, "REGISTRO_ERROR")
            return
        username, password, nombre_real = partes[1], partes[2], partes[3]
        try:
            async with pool.acquire() as conn:
                # Comprobar duplicado
                exists = await conn.fetchval(
                    "SELECT 1 FROM usuarios WHERE usuario=$1", username
                )
                if exists:
                    await safe_send(ws, "REGISTRO_ERROR")
                    return
                await conn.execute(
                    """INSERT INTO usuarios (nombre, usuario, password, rol, nombre_completo)
                       VALUES ($1,$2,$3,'PACIENTE'::rol_usuario,$4)""",
                    nombre_real, username, password, nombre_real,
                )
            await safe_send(ws, "REGISTRO_OK")
        except Exception as e:
            log.exception("Registro error")
            await safe_send(ws, "REGISTRO_ERROR")
        return

    # ==================== PEDIR TURNO ====================
    if message == "PEDIR_TURNO":
        user = get_user(ws)
        if not user:
            await safe_send(ws, "ERROR: No autenticado")
            return
        # Comprobar si ya tiene un turno en espera
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
                    """INSERT INTO turnos (numero_turno, cliente, estado, fecha, id_paciente)
                       VALUES ($1,$2,'EN_ESPERA'::estado_turno, NOW(), $3)
                       RETURNING id, numero_turno""",
                    num, nombre, user["id"],
                )
            cola_espera.append(ws)
            msg = f"TURNO_ASIGNADO: {nombre} (Turno #{row['numero_turno']})"
            for c in all_clients:
                await safe_send(c, msg)
            await actualizar_posiciones_cola()
        except Exception as e:
            log.exception("PEDIR_TURNO error")
            await safe_send(ws, "ERROR: No se pudo crear el turno")
        return

    # ==================== LLAMAR SIGUIENTE ====================
    if message == "LLAMAR_SIGUIENTE":
        if not cola_espera:
            await safe_send(ws, "ERROR: No hay pacientes en espera.")
            return
        paciente_ws = cola_espera.pop(0)
        await actualizar_posiciones_cola()
        medico = get_user(ws)
        nombre_medico = medico["usuario"] if medico else "Médico"
        if paciente_ws and paciente_ws.client_state.value == 1:  # CONNECTED
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
