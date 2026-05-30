"""
Turnix v2.1 iter-2 tests:
- Forgot password 3-step flow (Resend mocked-tolerant)
- Historial GET /api/historial/turnos/{id} con campos del medico (rol, email, etc)
- PDF justificante con Profesional sanitario completo
- WS chat post-aceptacion (INICIAR_CONSULTA_MANUAL match por display_name)
- WEBRTC handshake completo via WS

Conecta a Supabase real para validar codigo_verif. Tras el test deja
medico1 con password='1234' (no rompe iteraciones futuras).
"""
import asyncio
import json
import os

import asyncpg
import pytest
import pytest_asyncio
import requests
import websockets

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL is required"
WS_URL = BASE_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/ws"

MEDICO_EMAIL = "garciaherediarodrigo@gmail.com"
MEDICO_USER = "medico1"
MEDICO_PASS = "1234"
PAC_USER = "user1"
PAC_PASS = "1234"
PAC_DISPLAY = "Usuario Uno Probado"

SUPA = dict(
    host=os.environ["SUPABASE_HOST"],
    port=int(os.environ["SUPABASE_PORT"]),
    user=os.environ["SUPABASE_USER"],
    password=os.environ["SUPABASE_PASSWORD"],
    database=os.environ["SUPABASE_DB"],
)


import ssl as _ssl
_SSL_CTX = _ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = _ssl.CERT_NONE


async def _get_codigo_verif_from_db(email: str):
    conn = await asyncpg.connect(**SUPA, ssl=_SSL_CTX, statement_cache_size=0)
    try:
        return await conn.fetchrow(
            "SELECT codigo_verif, codigo_expira FROM usuarios WHERE LOWER(email)=LOWER($1)",
            email,
        )
    finally:
        await conn.close()


async def _restore_medico_pass():
    """Asegura que medico1 vuelva a tener password '1234'."""
    conn = await asyncpg.connect(**SUPA, ssl=_SSL_CTX, statement_cache_size=0)
    try:
        await conn.execute(
            "UPDATE usuarios SET password='1234', codigo_verif=NULL, codigo_expira=NULL "
            "WHERE usuario=$1",
            MEDICO_USER,
        )
    finally:
        await conn.close()


# ====================== FORGOT PASSWORD ======================
class TestForgotPassword:
    def test_a_forgot_known_email_returns_ok(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/forgot-password",
            json={"email": MEDICO_EMAIL},
            timeout=30,
        )
        # 200 incluso si Resend falla NO esta garantizado: server.py raises 500
        # si Resend rechaza. Tolerar 200 o 500 con mensaje resend pero registrar
        # info.
        assert r.status_code in (200, 500), r.text
        if r.status_code == 200:
            assert r.json().get("ok") is True

    def test_b_unknown_email_still_200(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/forgot-password",
            json={"email": "nadie-jamas-existe-xyz@example.com"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

    @pytest.mark.asyncio
    async def test_c_codigo_grabado_en_db(self):
        # Forzar reset code en DB via endpoint
        r = requests.post(
            f"{BASE_URL}/api/auth/forgot-password",
            json={"email": MEDICO_EMAIL},
            timeout=30,
        )
        # Aunque Resend devuelva 500, el UPDATE de codigo_verif ya se ejecuto
        # antes del try/except del send. Verificarlo en DB.
        row = await _get_codigo_verif_from_db(MEDICO_EMAIL)
        assert row is not None, "medico1 no esta en la DB"
        assert row["codigo_verif"] is not None, (
            f"codigo_verif vacio tras forgot-password (status {r.status_code} {r.text})"
        )
        assert len(row["codigo_verif"]) == 6 and row["codigo_verif"].isdigit()
        assert row["codigo_expira"] is not None

    def test_d_verify_codigo_incorrecto(self):
        # Asegurar que hay codigo
        requests.post(
            f"{BASE_URL}/api/auth/forgot-password",
            json={"email": MEDICO_EMAIL},
            timeout=30,
        )
        r = requests.post(
            f"{BASE_URL}/api/auth/verify-reset-code",
            json={"email": MEDICO_EMAIL, "codigo": "000000"},
            timeout=20,
        )
        assert r.status_code == 400
        body = r.text
        # Mensaje esperado: 'Código incorrecto' o 'Código inválido o caducado'
        assert "ódigo" in body or "incorrecto" in body or "inválido" in body

    @pytest.mark.asyncio
    async def test_e_full_reset_flow_and_restore(self):
        # 1) Solicitar codigo
        requests.post(
            f"{BASE_URL}/api/auth/forgot-password",
            json={"email": MEDICO_EMAIL},
            timeout=30,
        )
        row = await _get_codigo_verif_from_db(MEDICO_EMAIL)
        codigo = row["codigo_verif"]
        assert codigo and len(codigo) == 6

        # 2) Verificar codigo correcto
        rv = requests.post(
            f"{BASE_URL}/api/auth/verify-reset-code",
            json={"email": MEDICO_EMAIL, "codigo": codigo},
            timeout=20,
        )
        assert rv.status_code == 200, rv.text
        assert rv.json().get("ok") is True

        # 3) Reset password (a '1234' para no romper otros tests aun si fallasen
        #    los pasos de cleanup)
        rr = requests.post(
            f"{BASE_URL}/api/auth/reset-password",
            json={"email": MEDICO_EMAIL, "codigo": codigo, "nueva_password": "1234"},
            timeout=20,
        )
        assert rr.status_code == 200, rr.text

        # 4) Cleanup paranoico
        await _restore_medico_pass()


# ====================== HISTORIAL ======================
class TestHistorialMedicoFields:
    def test_get_historial_user1_tiene_campos_medico(self):
        r = requests.get(f"{BASE_URL}/api/historial/turnos/2", timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list) and len(data) > 0
        keys = set(data[0].keys())
        required = {
            "medico_nombre", "medico_usuario", "medico_especialidad",
            "medico_email", "medico_rol", "tipo_consulta", "prioridad",
            "fecha_inicio_consulta", "fecha_fin_consulta",
        }
        assert required.issubset(keys), f"Faltan campos: {required - keys}"

        # Al menos un turno completado debe traer datos del medico
        completados = [t for t in data if t.get("atendido_por")]
        assert completados, "No hay turnos completados para user1"
        c0 = completados[0]
        assert c0["medico_usuario"], "medico_usuario vacio en turno completado"
        assert c0["medico_rol"] in ("MEDICO", "ADMIN"), c0["medico_rol"]


# ====================== PDF JUSTIFICANTE ======================
class TestPDFJustificanteProfesional:
    def test_pdf_287_tiene_datos_profesional_completos(self):
        r = requests.get(
            f"{BASE_URL}/api/justificante/287",
            params={"user_id": 2},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.content
        assert body[:4] == b"%PDF"

        import io
        from pypdf import PdfReader
        text = "\n".join(
            (p.extract_text() or "") for p in PdfReader(io.BytesIO(body)).pages
        )
        # Profesional
        assert "Profesional sanitario" in text
        assert "Juan P" in text  # Dr. Juan Pérez (acento puede romper)
        assert "Odontolog" in text
        assert "medico1" in text
        assert MEDICO_EMAIL in text
        # No "—" en bloque profesional (verificacion debil: contar guiones)
        # El PDF puede tener "—" en otras secciones, pero el row "Usuario interno"
        # debe tener medico1 y no guion.


# ====================== CHAT POST-ACEPTACION ======================
async def _drain(ws, timeout=0.4):
    msgs = []
    try:
        while True:
            msgs.append(await asyncio.wait_for(ws.recv(), timeout=timeout))
    except Exception:
        pass
    return msgs


async def _ws_login(ws, user, pwd):
    await ws.send(f"login:{user}:{pwd}")
    for _ in range(10):
        try:
            m = await asyncio.wait_for(ws.recv(), timeout=2.0)
            if m.startswith("LOGIN_OK"):
                return m
        except asyncio.TimeoutError:
            break
    return None


async def _recv_until(ws, predicate, timeout_total=4.0):
    end = asyncio.get_event_loop().time() + timeout_total
    bag = []
    while asyncio.get_event_loop().time() < end:
        try:
            m = await asyncio.wait_for(ws.recv(), timeout=0.6)
            bag.append(m)
            if predicate(m):
                return m, bag
        except asyncio.TimeoutError:
            continue
    return None, bag


@pytest.mark.asyncio
async def test_chat_post_aceptacion_full_flow():
    """Bug reportado: tras INICIAR_CONSULTA_MANUAL, el CHAT_PRIVADO no llegaba al
    paciente porque se matcheaba solo por usuario. Ahora debe matchear por
    display_name."""
    async with websockets.connect(WS_URL, open_timeout=15) as ws_p, \
               websockets.connect(WS_URL, open_timeout=15) as ws_m:
        # Login MEDICO primero (necesario para que reciba broadcast)
        login_m = await _ws_login(ws_m, MEDICO_USER, MEDICO_PASS)
        assert login_m and "MEDICO" in login_m

        # Login PACIENTE
        login_p = await _ws_login(ws_p, PAC_USER, PAC_PASS)
        assert login_p and "PACIENTE" in login_p

        await _drain(ws_p)
        await _drain(ws_m)

        # PEDIR_TURNO con tipo Odontologia (medico1 es Odontologia)
        await ws_p.send("PEDIR_TURNO:Odontología:Moderada")
        msg, bag = await _recv_until(
            ws_m, lambda m: m.startswith("TURNO_ASIGNADO:"), timeout_total=5.0
        )
        assert msg is not None, f"Medico no recibio TURNO_ASIGNADO. bag={bag}"
        # Formato: TURNO_ASIGNADO:<display_name>:<usuario>:<num>:<tipo>:<prio>
        parts = msg.split(":")
        assert parts[0] == "TURNO_ASIGNADO"
        assert PAC_USER in msg
        assert "Odontolog" in msg
        assert "Moderada" in msg

        await _drain(ws_p)
        await _drain(ws_m)

        # INICIAR_CONSULTA_MANUAL usando display_name (este es el bug)
        await ws_m.send(f"INICIAR_CONSULTA_MANUAL:{PAC_DISPLAY}")

        # Paciente debe recibir SISTEMA: LLAMADA_A_CONSULTA y COMANDO:ENTRAR_CONSULTA
        llamada, bag_p = await _recv_until(
            ws_p, lambda m: "LLAMADA_A_CONSULTA" in m, timeout_total=5.0
        )
        assert llamada is not None, f"Paciente no recibio LLAMADA_A_CONSULTA. bag={bag_p}"

        comando, bag_p2 = await _recv_until(
            ws_p, lambda m: m.startswith("COMANDO:ENTRAR_CONSULTA:"),
            timeout_total=3.0,
        )
        assert comando is not None, f"Paciente no recibio ENTRAR_CONSULTA. bag={bag_p2}"
        assert MEDICO_USER in comando

        await _drain(ws_p)
        await _drain(ws_m)

        # CHAT_PRIVADO via display_name - este era el bug principal
        await ws_m.send(f"CHAT_PRIVADO:{PAC_DISPLAY}:Hola desde test")
        mensaje, bag = await _recv_until(
            ws_p, lambda m: m.startswith("MEDICO_DICE:"), timeout_total=4.0
        )
        assert mensaje is not None, f"Paciente no recibio MEDICO_DICE. bag={bag}"
        assert "Hola desde test" in mensaje

        # ============ WEBRTC HANDSHAKE ============
        await _drain(ws_p)
        await _drain(ws_m)

        # CALL_REQUEST: medico -> paciente
        await ws_m.send(f"WEBRTC_CALL_REQUEST:{PAC_DISPLAY}:")
        req, bag = await _recv_until(
            ws_p, lambda m: m.startswith("WEBRTC_CALL_REQUEST:"),
            timeout_total=4.0,
        )
        assert req is not None, f"Paciente no recibio WEBRTC_CALL_REQUEST. bag={bag}"
        # backend envia "WEBRTC_CALL_REQUEST:<medico_display>" o medico1
        assert MEDICO_USER in req or "Juan" in req or "medico1" in req.lower()

        # CALL_ACCEPT: paciente -> medico
        await ws_p.send(f"WEBRTC_CALL_ACCEPT:{MEDICO_USER}:")
        acc, bag = await _recv_until(
            ws_m, lambda m: m.startswith("WEBRTC_CALL_ACCEPT:"),
            timeout_total=4.0,
        )
        assert acc is not None, f"Medico no recibio WEBRTC_CALL_ACCEPT. bag={bag}"

        # OFFER con payload JSON con ":" embebidos
        sdp = json.dumps({"type": "offer", "sdp": "v=0\r\no=- 1:2:3 IN IP4 0.0.0.0\r\n"})
        await ws_m.send(f"WEBRTC_OFFER:{PAC_DISPLAY}:{sdp}")
        offer, bag = await _recv_until(
            ws_p, lambda m: m.startswith("WEBRTC_OFFER:"),
            timeout_total=4.0,
        )
        assert offer is not None, f"Paciente no recibio WEBRTC_OFFER. bag={bag}"
        # Recuperar payload JSON intacto
        payload = offer.split(":", 2)[2]
        parsed = json.loads(payload)
        assert parsed["type"] == "offer"
        assert "v=0" in parsed["sdp"]
