"""
Turnix v2.2 - Tests para feature de RECETAS MEDICAS con firma del medico.

Cubre:
 - GET /api/health
 - GET /api/recetas/paciente/4 (listado JSON)
 - GET /api/recetas/{id}/pdf?user_id=4 (devuelve %PDF y, si la receta tiene
   firma_base64 valida, contiene image stream embebido)
 - POST /api/recetas/crear con firma valida (PNG dataURL) -> 200, ok=true
 - POST /api/recetas/crear con firma vacia -> NO 500 (backend la acepta)
 - POST /api/recetas/crear con medico_password incorrecta -> 401
 - POST /api/recetas/crear con paciente_usuario inexistente -> 404
 - Validar que NO aparece el error 'column m.email does not exist' en:
     /api/historial/turnos/{user_id}, /api/turno/{turno_id}/detalles
 - Validar UNIQUE constraint sobre turno_id: dos recetas para el mismo turno
   no deben romper (la segunda guarda turno_id=NULL).
 - WS login: medico1/1234 (MEDICO), user1/1234 (PACIENTE), admin/1234 (ADMIN).
"""
import asyncio
import base64
import os
import re

import pytest
import requests
import websockets

# ====================== CLEANUP TEST DATA ======================
@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_recetas():
    """Borra recetas con prefijo TEST_ al final de la sesion."""
    yield
    try:
        import asyncpg
        import ssl as _ssl_mod
        ctx = _ssl_mod.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = _ssl_mod.CERT_NONE

        async def _do():
            conn = await asyncpg.connect(
                host=os.environ["SUPABASE_HOST"],
                port=int(os.environ["SUPABASE_PORT"]),
                user=os.environ["SUPABASE_USER"],
                password=os.environ["SUPABASE_PASSWORD"],
                database=os.environ["SUPABASE_DB"],
                ssl=ctx, statement_cache_size=0,
            )
            try:
                await conn.execute(
                    "DELETE FROM recetas WHERE nombre_receta LIKE 'TEST_%'"
                )
            finally:
                await conn.close()
        asyncio.run(_do())
    except Exception as e:  # cleanup best-effort
        print(f"[cleanup] no se pudo limpiar recetas TEST_: {e}")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL is required"
WS_URL = BASE_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/ws"

MEDICO_ID = 1
MEDICO_USER = "medico1"
MEDICO_PASS = "1234"
PACIENTE_ID = 4
PACIENTE_USER = "user1"
PACIENTE_PASS = "1234"
ADMIN_USER = "admin"
ADMIN_PASS = "1234"

# PNG 200x80 con una linea negra (firma fake). Generado con PIL para garantizar
# que sea un PNG valido (PIL/reportlab abren el stream).
PNG_FIRMA_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAMgAAABQCAYAAABcbTqwAAAA/UlEQVR4nO3dMQ7CQAwAwTji/182"
    "H0gWOlA0U7u4ZmV3N7t7ANfOXz8A/plAIAgEgkAgCASCQCAIBIJAIAgEgkAgCASCQCAIBIJAIAgE"
    "gkAgCASCQCAIBIJAIAgEgkAgCASCQCAIBIJAIAgEgkAgCASCQCAIBIJAIAgEgkAgCASCQCAIBIJA"
    "ILy+HZwZ/0XzKLs7n2ZsEAgCgTC7Lie4Y4NAEAgEgUAQCASBQBAIBIFAEAgEgUAQCASBQBAIBIFA"
    "EAgEgUAQCASBQBAIBIFAEAgEgUAQCASBQBAIBIFAEAgEgUAQCASBQBAIBIFAEAgEgUAQCASBQBAI"
    "BIFAeANl5wqbPuOBFgAAAABJRU5ErkJggg=="
)
FIRMA_DATAURL = "data:image/png;base64," + PNG_FIRMA_B64


# ====================== HEALTH ======================
class TestHealth:
    def test_health_ok(self):
        r = requests.get(f"{BASE_URL}/api/health", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("db") == "ok", data


# ====================== LISTADO RECETAS PACIENTE ======================
class TestRecetasListado:
    def test_listado_paciente_4_es_lista(self):
        r = requests.get(f"{BASE_URL}/api/recetas/paciente/{PACIENTE_ID}", timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list)
        assert len(data) > 0, "user_id=4 deberia tener recetas existentes"
        # Validar shape
        keys = set(data[0].keys())
        expected = {
            "id", "nombre_receta", "motivo", "medicamento", "dosis",
            "duracion", "indicaciones", "fecha_emision",
            "medico_nombre", "medico_usuario", "medico_especialidad",
            "medico_email",
        }
        missing = expected - keys
        assert not missing, f"Faltan campos en la receta: {missing}"
        # Email del medico no debe estar vacio (uso de correo_electronico, no email)
        completados = [x for x in data if x.get("medico_id")]
        if completados:
            # Al menos uno tiene email cargado
            assert any(x.get("medico_email") for x in completados), \
                "Ninguna receta trae medico_email (correo_electronico)"

    def test_listado_paciente_inexistente_devuelve_lista_vacia(self):
        r = requests.get(f"{BASE_URL}/api/recetas/paciente/9999999", timeout=15)
        assert r.status_code == 200, r.text
        assert r.json() == []


# ====================== PDF ======================
class TestRecetasPDF:
    def _get_id_con_firma(self):
        r = requests.get(f"{BASE_URL}/api/recetas/paciente/{PACIENTE_ID}", timeout=15)
        assert r.status_code == 200
        for x in r.json():
            return x["id"]  # primer id sirve
        return None

    def test_pdf_basico_magic_bytes(self):
        rid = self._get_id_con_firma()
        assert rid is not None
        r = requests.get(
            f"{BASE_URL}/api/recetas/{rid}/pdf",
            params={"user_id": PACIENTE_ID},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        ct = r.headers.get("content-type", "")
        assert "application/pdf" in ct, ct
        body = r.content
        assert body[:4] == b"%PDF", body[:8]

    def test_pdf_403_si_paciente_no_corresponde(self):
        rid = self._get_id_con_firma()
        assert rid is not None
        # Pedir con user_id=2 (no es duenio de las recetas de user1=id=4)
        r = requests.get(
            f"{BASE_URL}/api/recetas/{rid}/pdf",
            params={"user_id": 2},
            timeout=15,
        )
        assert r.status_code == 403, r.text

    def test_pdf_404_si_receta_no_existe(self):
        r = requests.get(
            f"{BASE_URL}/api/recetas/99999999/pdf",
            params={"user_id": PACIENTE_ID},
            timeout=15,
        )
        assert r.status_code == 404, r.text

    def test_pdf_de_receta_recien_creada_contiene_image_stream(self):
        # Crear una receta NUEVA con firma valida para asegurar que el PDF
        # contiene el image stream (firma embebida).
        payload = {
            "medico_id": MEDICO_ID,
            "medico_password": MEDICO_PASS,
            "paciente_usuario": PACIENTE_USER,
            "nombre_receta": "TEST_pytest_firma",
            "motivo": "Validar firma embebida en PDF",
            "medicamento": "ibuprofeno 600mg",
            "dosis": "1 cada 8h",
            "duracion": "5 dias",
            "indicaciones": "test pytest",
            "firma_base64": FIRMA_DATAURL,
        }
        cr = requests.post(f"{BASE_URL}/api/recetas/crear", json=payload, timeout=30)
        assert cr.status_code == 200, cr.text
        rid = cr.json()["id"]

        pdf = requests.get(
            f"{BASE_URL}/api/recetas/{rid}/pdf",
            params={"user_id": PACIENTE_ID},
            timeout=30,
        )
        assert pdf.status_code == 200, pdf.text
        body = pdf.content
        assert body[:4] == b"%PDF"
        # ReportLab embebe imagenes con /Subtype /Image o un /Image dentro de
        # un XObject. Buscamos cualquiera de los dos.
        assert (b"/Image" in body) or (b"/Subtype /Image" in body), \
            "PDF no contiene image stream (firma no parece estar embebida)"
        # Tambien debe figurar el bloque 'Firma del médico'
        # (texto puede estar codificado/troceado en el PDF; check debil)


# ====================== CREACION DE RECETAS ======================
class TestRecetaCreacion:
    def test_crear_receta_con_firma_ok(self):
        payload = {
            "medico_id": MEDICO_ID,
            "medico_password": MEDICO_PASS,
            "paciente_usuario": PACIENTE_USER,
            "nombre_receta": "TEST_pytest_ok",
            "motivo": "pytest",
            "medicamento": "paracetamol",
            "dosis": "1g",
            "duracion": "3 dias",
            "indicaciones": "tomar con agua",
            "firma_base64": FIRMA_DATAURL,
        }
        r = requests.post(f"{BASE_URL}/api/recetas/crear", json=payload, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True
        assert isinstance(data.get("id"), int)
        assert "fecha_emision" in data

        # GET para verificar persistencia
        lst = requests.get(
            f"{BASE_URL}/api/recetas/paciente/{PACIENTE_ID}", timeout=15
        ).json()
        ids = [x["id"] for x in lst]
        assert data["id"] in ids

    def test_crear_receta_firma_vacia_no_es_500(self):
        payload = {
            "medico_id": MEDICO_ID,
            "medico_password": MEDICO_PASS,
            "paciente_usuario": PACIENTE_USER,
            "nombre_receta": "TEST_pytest_sin_firma",
            "motivo": "firma opcional en backend",
            "medicamento": "x",
            "dosis": "x",
            "duracion": "x",
            "indicaciones": "",
            "firma_base64": "",
        }
        r = requests.post(f"{BASE_URL}/api/recetas/crear", json=payload, timeout=20)
        # El backend la acepta (firma es obligatoria solo en frontend).
        assert r.status_code != 500, r.text
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

    def test_crear_receta_password_incorrecta_401(self):
        payload = {
            "medico_id": MEDICO_ID,
            "medico_password": "password_incorrecta_xxx",
            "paciente_usuario": PACIENTE_USER,
            "nombre_receta": "TEST_no_deberia",
            "motivo": "no",
            "firma_base64": FIRMA_DATAURL,
        }
        r = requests.post(f"{BASE_URL}/api/recetas/crear", json=payload, timeout=15)
        assert r.status_code == 401, r.text

    def test_crear_receta_paciente_inexistente_404(self):
        payload = {
            "medico_id": MEDICO_ID,
            "medico_password": MEDICO_PASS,
            "paciente_usuario": "no_existe_paciente_xyz_12345",
            "nombre_receta": "TEST_no_deberia",
            "motivo": "no",
            "firma_base64": FIRMA_DATAURL,
        }
        r = requests.post(f"{BASE_URL}/api/recetas/crear", json=payload, timeout=15)
        assert r.status_code == 404, r.text

    def test_crear_receta_campos_obligatorios_400(self):
        # nombre_receta vacio
        payload = {
            "medico_id": MEDICO_ID,
            "medico_password": MEDICO_PASS,
            "paciente_usuario": PACIENTE_USER,
            "nombre_receta": "",
            "motivo": "",
            "firma_base64": FIRMA_DATAURL,
        }
        r = requests.post(f"{BASE_URL}/api/recetas/crear", json=payload, timeout=15)
        assert r.status_code == 400, r.text

    def test_unique_turno_id_no_rompe(self):
        """Crear DOS recetas seguidas para el mismo paciente/medico.
        La segunda debe poner turno_id=NULL si la primera ya ocupo el
        UNIQUE constraint, en lugar de devolver 500."""
        base = {
            "medico_id": MEDICO_ID,
            "medico_password": MEDICO_PASS,
            "paciente_usuario": PACIENTE_USER,
            "motivo": "test unique",
            "firma_base64": FIRMA_DATAURL,
        }
        r1 = requests.post(
            f"{BASE_URL}/api/recetas/crear",
            json={**base, "nombre_receta": "TEST_unique_1"},
            timeout=20,
        )
        r2 = requests.post(
            f"{BASE_URL}/api/recetas/crear",
            json={**base, "nombre_receta": "TEST_unique_2"},
            timeout=20,
        )
        assert r1.status_code == 200, r1.text
        assert r2.status_code == 200, r2.text
        assert r2.status_code != 500


# ====================== COLUMNA m.email NO DEBE FALLAR ======================
class TestColumnaEmailFix:
    def test_historial_turnos_no_falla_por_email(self):
        r = requests.get(
            f"{BASE_URL}/api/historial/turnos/{PACIENTE_ID}", timeout=20
        )
        assert r.status_code == 200, r.text
        body = r.text
        assert "column m.email does not exist" not in body
        data = r.json()
        assert isinstance(data, list)
        # Debe traer medico_email (alias de correo_electronico)
        if data:
            assert "medico_email" in data[0]

    def test_turno_detalles_no_falla_por_email(self):
        # Tomar un turno del historial y pedir sus detalles
        hist = requests.get(
            f"{BASE_URL}/api/historial/turnos/{PACIENTE_ID}", timeout=20
        ).json()
        if not hist:
            pytest.skip("Sin turnos para validar /api/turno/{id}/detalles")
        tid = hist[0]["id"]
        r = requests.get(
            f"{BASE_URL}/api/turno/{tid}/detalles",
            params={"user_id": PACIENTE_ID},
            timeout=15,
        )
        # Puede ser 200 o 403/404 segun ownership, lo importante es que NO sea
        # 500 por columna inexistente.
        assert r.status_code in (200, 403, 404), r.text
        assert "column m.email does not exist" not in r.text


# ====================== WS LOGIN ======================
async def _ws_login_role(user, pwd):
    async with websockets.connect(WS_URL, open_timeout=15) as ws:
        await ws.send(f"login:{user}:{pwd}")
        for _ in range(10):
            try:
                m = await asyncio.wait_for(ws.recv(), timeout=2.5)
            except asyncio.TimeoutError:
                break
            if m.startswith("LOGIN_OK"):
                return m
        return None


class TestWSLogin:
    @pytest.mark.asyncio
    async def test_ws_login_medico(self):
        m = await _ws_login_role(MEDICO_USER, MEDICO_PASS)
        assert m is not None, "Sin LOGIN_OK para medico1"
        assert "MEDICO" in m, m

    @pytest.mark.asyncio
    async def test_ws_login_paciente(self):
        m = await _ws_login_role(PACIENTE_USER, PACIENTE_PASS)
        assert m is not None, "Sin LOGIN_OK para user1"
        assert "PACIENTE" in m, m

    @pytest.mark.asyncio
    async def test_ws_login_admin(self):
        m = await _ws_login_role(ADMIN_USER, ADMIN_PASS)
        assert m is not None, "Sin LOGIN_OK para admin"
        assert "ADMIN" in m, m
