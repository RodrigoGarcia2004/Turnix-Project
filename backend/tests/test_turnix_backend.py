"""
Turnix backend tests - cubre login REST (paciente), admin login, PDF justificante,
health, y signaling WebRTC sobre WebSocket.
"""
import asyncio
import json
import os
import re

import pytest
import requests
import websockets

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL is required"
WS_URL = BASE_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/ws"


# ---------- Health ----------
def test_health_ok():
    r = requests.get(f"{BASE_URL}/api/health", timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("db") == "ok"


# ---------- Login REST (solo PACIENTE en /api/auth/login) ----------
class TestAuthLogin:
    def test_paciente_login_ok(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"usuario": "user1", "password": "1234"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["usuario"] == "user1"
        assert data["rol"] == "PACIENTE"
        assert data["id"] == 2
        assert "Usuario Uno" in (data.get("nombre_completo") or "")

    def test_medico_rest_login_rechazado(self):
        # /api/auth/login solo permite PACIENTE - debe devolver 403
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"usuario": "medico1", "password": "1234"},
            timeout=20,
        )
        assert r.status_code == 403

    def test_admin_login_endpoint_ok(self):
        # Admin tiene endpoint separado /api/admin/login
        r = requests.post(
            f"{BASE_URL}/api/admin/login",
            json={"admin_usuario": "admin", "admin_password": "1234"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

    def test_paciente_login_bad_password(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"usuario": "user1", "password": "wrong"},
            timeout=20,
        )
        assert r.status_code == 401


# ---------- PDF Justificante ----------
class TestJustificantePDF:
    def test_pdf_estructura_y_campos(self):
        r = requests.get(
            f"{BASE_URL}/api/justificante/287",
            params={"user_id": 2},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.content
        assert body[:4] == b"%PDF", "No es un PDF valido"
        assert len(body) > 100 * 1024, f"PDF muy pequeño: {len(body)} bytes"

        # Extraer texto
        import io
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(body))
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
        # Validaciones de contenido requeridas
        assert "Datos del paciente" in text
        assert "Datos de la consulta" in text
        assert "Profesional sanitario" in text
        assert "Usuario Uno Probado" in text
        assert "Otro" in text  # motivo / tipo
        assert "Moderada" in text  # prioridad
        assert "COMPLETADO" in text  # estado
        assert "Dr. Juan Pérez" in text or "Juan P" in text
        assert "Odontología" in text or "Odontolog" in text


# ---------- WebSocket WEBRTC signaling ----------
async def _ws_login(ws, usuario, password):
    await ws.send(f"login:{usuario}:{password}")
    try:
        for _ in range(10):
            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            if msg.startswith("LOGIN_OK"):
                return msg
    except asyncio.TimeoutError:
        pass
    return None


@pytest.mark.asyncio
async def test_webrtc_call_request_forwarded_to_target():
    """Medico envia WEBRTC_CALL_REQUEST:user1 -> paciente debe recibir
    WEBRTC_CALL_REQUEST:medico1"""
    async with websockets.connect(WS_URL, open_timeout=15) as ws_p, \
               websockets.connect(WS_URL, open_timeout=15) as ws_m:
        await _ws_login(ws_p, "user1", "1234")
        await _ws_login(ws_m, "medico1", "1234")
        # drenar buffer paciente
        async def drain(ws):
            try:
                while True:
                    await asyncio.wait_for(ws.recv(), timeout=0.4)
            except Exception:
                pass
        await drain(ws_p)
        await drain(ws_m)

        # medico solicita videollamada al paciente
        await ws_m.send("WEBRTC_CALL_REQUEST:user1")

        # paciente debe recibir WEBRTC_CALL_REQUEST:medico1
        received = None
        try:
            for _ in range(10):
                msg = await asyncio.wait_for(ws_p.recv(), timeout=2.5)
                if msg.startswith("WEBRTC_CALL_REQUEST:"):
                    received = msg
                    break
        except asyncio.TimeoutError:
            pass
        assert received is not None, "Paciente no recibio WEBRTC_CALL_REQUEST"
        assert "medico1" in received


@pytest.mark.asyncio
async def test_webrtc_call_accept_forwarded_back_to_medico():
    async with websockets.connect(WS_URL, open_timeout=15) as ws_p, \
               websockets.connect(WS_URL, open_timeout=15) as ws_m:
        await _ws_login(ws_p, "user1", "1234")
        await _ws_login(ws_m, "medico1", "1234")
        async def drain(ws):
            try:
                while True:
                    await asyncio.wait_for(ws.recv(), timeout=0.4)
            except Exception:
                pass
        await drain(ws_p)
        await drain(ws_m)
        # paciente acepta llamada (simulado)
        await ws_p.send("WEBRTC_CALL_ACCEPT:medico1")
        received = None
        try:
            for _ in range(10):
                msg = await asyncio.wait_for(ws_m.recv(), timeout=2.5)
                if msg.startswith("WEBRTC_CALL_ACCEPT:"):
                    received = msg
                    break
        except asyncio.TimeoutError:
            pass
        assert received is not None, "Medico no recibio WEBRTC_CALL_ACCEPT"
        assert "user1" in received


@pytest.mark.asyncio
async def test_webrtc_offer_with_json_payload_preserved():
    """El payload (SDP JSON con muchos ':') debe llegar intacto."""
    fake_sdp = json.dumps({"type": "offer", "sdp": "v=0\no=- 1:2:3 IN IP4 0.0.0.0\n"})
    async with websockets.connect(WS_URL, open_timeout=15) as ws_p, \
               websockets.connect(WS_URL, open_timeout=15) as ws_m:
        await _ws_login(ws_p, "user1", "1234")
        await _ws_login(ws_m, "medico1", "1234")
        async def drain(ws):
            try:
                while True:
                    await asyncio.wait_for(ws.recv(), timeout=0.4)
            except Exception:
                pass
        await drain(ws_p)
        await drain(ws_m)
        await ws_m.send(f"WEBRTC_OFFER:user1:{fake_sdp}")
        received = None
        try:
            for _ in range(10):
                msg = await asyncio.wait_for(ws_p.recv(), timeout=2.5)
                if msg.startswith("WEBRTC_OFFER:"):
                    received = msg
                    break
        except asyncio.TimeoutError:
            pass
        assert received is not None, "Paciente no recibio WEBRTC_OFFER"
        # formato: WEBRTC_OFFER:medico1:<json>
        assert "medico1" in received
        # El JSON con sus ':' debe permanecer intacto
        json_part = received.split(":", 2)[2]
        parsed = json.loads(json_part)
        assert parsed["type"] == "offer"
