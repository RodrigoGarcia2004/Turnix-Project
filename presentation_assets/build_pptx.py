"""
Genera Turnix_Presentacion.pptx con la estructura completa de la defensa tecnica
del proyecto Turnix Salud (15 min, audiencia tecnica).

Esquema cromatico Turnix:
    --primary-bg #F0F8FF (azul claro)
    --secondary-bg #E0F2F1 (verde aqua claro)
    --dark-blue #2C3E50 (titulares)
    --medico-blue #1E88E5 (acentos azules)
    --medico-teal / --paciente-teal #00897B / #009688 (acentos verdes)
    --paciente-green #2ECC71 (botones positivos)
"""
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from copy import deepcopy
import os

# ===== Paleta Turnix =====
DARK_BLUE   = RGBColor(0x2C, 0x3E, 0x50)
MEDICO_BLUE = RGBColor(0x1E, 0x88, 0xE5)
TEAL        = RGBColor(0x00, 0x89, 0x7B)
GREEN       = RGBColor(0x2E, 0xCC, 0x71)
PRIMARY_BG  = RGBColor(0xF0, 0xF8, 0xFF)
SECOND_BG   = RGBColor(0xE0, 0xF2, 0xF1)
WHITE       = RGBColor(0xFF, 0xFF, 0xFF)
MUTED       = RGBColor(0x5B, 0x6B, 0x7A)
SLATE       = RGBColor(0x47, 0x55, 0x69)
ACCENT_AMB  = RGBColor(0xD9, 0x77, 0x06)
DANGER      = RGBColor(0xDC, 0x26, 0x26)

ASSETS = "/app/presentation_assets"

prs = Presentation()
prs.slide_width  = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]

# ===== Helpers =====
def add_solid_bg(slide, color):
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    bg.line.fill.background()
    bg.fill.solid(); bg.fill.fore_color.rgb = color
    slide.shapes._spTree.remove(bg._element); slide.shapes._spTree.insert(2, bg._element)
    return bg

def add_gradient_band(slide, top, height, c1, c2):
    """Banda horizontal con degradado (XML directo porque python-pptx no expone bien grad fills)."""
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, top, prs.slide_width, height)
    shape.line.fill.background()
    sp = shape.fill._xPr
    spPr = sp.find(qn('a:solidFill'))
    if spPr is not None: sp.remove(spPr)
    grad_xml = (
        '<a:gradFill rotWithShape="1" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:gsLst>'
        f'<a:gs pos="0"><a:srgbClr val="{c1[0]:02X}{c1[1]:02X}{c1[2]:02X}"/></a:gs>'
        f'<a:gs pos="100000"><a:srgbClr val="{c2[0]:02X}{c2[1]:02X}{c2[2]:02X}"/></a:gs>'
        '</a:gsLst>'
        '<a:lin ang="0" scaled="0"/>'
        '</a:gradFill>'
    )
    from lxml import etree
    sp.append(etree.fromstring(grad_xml))
    return shape

def add_text(slide, left, top, width, height, text, *,
             size=18, bold=False, color=DARK_BLUE, align=PP_ALIGN.LEFT,
             font="Calibri", anchor=MSO_ANCHOR.TOP, line_spacing=1.15):
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Emu(0)
    tf.margin_top = tf.margin_bottom = Emu(0)
    tf.vertical_anchor = anchor
    if isinstance(text, str):
        text = [text]
    for i, line in enumerate(text):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = line_spacing
        r = p.add_run()
        r.text = line
        r.font.name = font
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = color
    return tb

def add_bullets(slide, left, top, width, height, items, *, size=16, color=DARK_BLUE,
                bold_first_word=False, font="Calibri"):
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = Emu(0); tf.margin_right = Emu(0)
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        p.line_spacing = 1.25
        p.space_after = Pt(6)
        r = p.add_run(); r.text = "•  "
        r.font.name = font; r.font.size = Pt(size); r.font.color.rgb = TEAL; r.font.bold = True
        if bold_first_word and ":" in item:
            head, tail = item.split(":", 1)
            rb = p.add_run(); rb.text = head + ":"
            rb.font.name = font; rb.font.size = Pt(size); rb.font.color.rgb = color; rb.font.bold = True
            rt = p.add_run(); rt.text = tail
            rt.font.name = font; rt.font.size = Pt(size); rt.font.color.rgb = color
        else:
            r2 = p.add_run(); r2.text = item
            r2.font.name = font; r2.font.size = Pt(size); r2.font.color.rgb = color
    return tb

def add_rect(slide, left, top, width, height, fill=WHITE, line=None, shadow=True, radius=False):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE, left, top, width, height)
    shp.fill.solid(); shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line; shp.line.width = Pt(0.75)
    # apaga shadow por defecto
    if not shadow:
        sppr = shp._element.spPr
        for el in sppr.findall(qn('a:effectLst')):
            sppr.remove(el)
        from lxml import etree
        sppr.append(etree.fromstring('<a:effectLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"/>'))
    return shp

def add_footer(slide, num, total):
    add_text(slide, Inches(0.4), Inches(7.05), Inches(6), Inches(0.35),
             "Turnix Salud · Defensa técnica · Rodrigo García", size=10, color=MUTED)
    add_text(slide, Inches(11.5), Inches(7.05), Inches(1.5), Inches(0.35),
             f"{num} / {total}", size=10, color=MUTED, align=PP_ALIGN.RIGHT)

def add_pill(slide, left, top, text, fill, color=WHITE, w=Inches(1.6), h=Inches(0.35), size=11):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, w, h)
    shp.adjustments[0] = 0.5
    shp.fill.solid(); shp.fill.fore_color.rgb = fill
    shp.line.fill.background()
    tf = shp.text_frame; tf.margin_left = tf.margin_right = Emu(45720)
    tf.margin_top = tf.margin_bottom = Emu(0)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = text
    r.font.name = "Calibri"; r.font.size = Pt(size); r.font.color.rgb = color; r.font.bold = True

# ===== TOTAL para footer =====
TOTAL = 19

# ====================================================================
# SLIDE 1 — Portada
# ====================================================================
def slide_portada():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, PRIMARY_BG)
    add_gradient_band(s, 0, Inches(7.5), SECOND_BG, PRIMARY_BG)

    # Bloque visual a la izquierda (tarjeta blanca grande)
    add_rect(s, Inches(0.7), Inches(0.9), Inches(7.4), Inches(5.7), fill=WHITE, radius=True)

    # Logo (texto) y mini stripe teal
    add_rect(s, Inches(0.7), Inches(0.9), Inches(0.18), Inches(5.7), fill=TEAL)

    add_text(s, Inches(1.1), Inches(1.3), Inches(7), Inches(0.7),
             "TURNIX SALUD", size=42, bold=True, color=DARK_BLUE)
    add_text(s, Inches(1.1), Inches(2.05), Inches(7), Inches(0.5),
             "Sistema Integrado de Salud", size=22, color=MEDICO_BLUE)

    # Linea fina decorativa
    add_rect(s, Inches(1.1), Inches(2.7), Inches(2.5), Inches(0.04), fill=GREEN)

    add_text(s, Inches(1.1), Inches(2.95), Inches(7), Inches(1.4),
             ["Plataforma multi-rol (Paciente · Médico · Admin)",
              "con turnos en tiempo real, recetas firmadas",
              "digitalmente y arquitectura cloud-ready."],
             size=15, color=SLATE, line_spacing=1.4)

    # pills tech
    add_pill(s, Inches(1.1), Inches(5.2), "FastAPI",         MEDICO_BLUE)
    add_pill(s, Inches(2.8), Inches(5.2), "Spring Gateway",  TEAL)
    add_pill(s, Inches(4.5), Inches(5.2), "Supabase",        DARK_BLUE)
    add_pill(s, Inches(6.2), Inches(5.2), "Docker · Render", GREEN)

    add_text(s, Inches(1.1), Inches(5.85), Inches(7), Inches(0.4),
             "Defensa técnica · 15 min", size=12, color=MUTED, bold=True)

    # Bloque a la derecha (datos del autor)
    add_rect(s, Inches(8.7), Inches(0.9), Inches(4), Inches(5.7), fill=DARK_BLUE, radius=True)
    add_text(s, Inches(9), Inches(1.5), Inches(3.5), Inches(0.5),
             "Autor", size=12, color=RGBColor(0x9C, 0xAF, 0xC0), bold=True)
    add_text(s, Inches(9), Inches(1.9), Inches(3.5), Inches(0.7),
             "Rodrigo García", size=24, bold=True, color=WHITE)
    add_text(s, Inches(9), Inches(2.6), Inches(3.5), Inches(0.4),
             "Proyecto Fin de Ciclo", size=13, color=RGBColor(0x9C, 0xAF, 0xC0))

    add_rect(s, Inches(9), Inches(3.25), Inches(3.4), Inches(0.03), fill=GREEN)

    add_text(s, Inches(9), Inches(3.45), Inches(3.5), Inches(0.4),
             "Repositorio", size=11, color=RGBColor(0x9C, 0xAF, 0xC0), bold=True)
    add_text(s, Inches(9), Inches(3.75), Inches(3.5), Inches(0.4),
             "RodrigoGarcia2004 / Turnix-Project", size=12, color=WHITE)

    add_text(s, Inches(9), Inches(4.4), Inches(3.5), Inches(0.4),
             "Producción", size=11, color=RGBColor(0x9C, 0xAF, 0xC0), bold=True)
    add_text(s, Inches(9), Inches(4.7), Inches(3.5), Inches(0.4),
             "turnix-project.onrender.com", size=12, color=WHITE)
    add_text(s, Inches(9), Inches(5.05), Inches(3.5), Inches(0.4),
             "turnix-gateway.onrender.com", size=12, color=WHITE)

    add_text(s, Inches(9), Inches(5.85), Inches(3.5), Inches(0.4),
             "Año", size=11, color=RGBColor(0x9C, 0xAF, 0xC0), bold=True)
    add_text(s, Inches(9), Inches(6.15), Inches(3.5), Inches(0.4),
             "2026", size=12, color=WHITE)

# ====================================================================
# SLIDE 2 — Índice
# ====================================================================
def slide_indice():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_rect(s, 0, 0, prs.slide_width, Inches(1.1), fill=DARK_BLUE)
    add_text(s, Inches(0.6), Inches(0.3), Inches(10), Inches(0.7),
             "Índice de la defensa", size=28, bold=True, color=WHITE)
    add_text(s, Inches(0.6), Inches(0.78), Inches(10), Inches(0.4),
             "15 min · audiencia técnica · demo en vivo incluida", size=13, color=RGBColor(0xB0,0xC4,0xD9))

    items = [
        ("01", "Problema y motivación",         "¿Por qué Turnix?"),
        ("02", "Visión y alcance",              "Roles, casos de uso, KPIs"),
        ("03", "Arquitectura del sistema",      "3 capas + gateway"),
        ("04", "Stack tecnológico",             "Decisiones y por qué"),
        ("05", "Modelo de datos",               "Esquema Supabase Postgres"),
        ("06", "Flujo: Paciente",               "Registro, turno, chat, recetas"),
        ("07", "Flujo: Médico",                 "Consulta + receta firmada"),
        ("08", "Flujo: Admin",                  "Gobierno de la plataforma"),
        ("09", "Tiempo real con WebSockets",    "Chat y notificaciones"),
        ("10", "Firma digital manuscrita",      "Canvas → PDF embedido"),
        ("11", "Gateway Java + Worker",         "Spring Cloud + métricas"),
        ("12", "Seguridad y RGPD",              "Re-auth, password, datos"),
        ("13", "Despliegue (Render + CI/CD)",   "Docker, render.yaml"),
        ("14", "Demo en vivo",                  "Guion paso a paso"),
        ("15", "Roadmap y conclusiones",        "Lo aprendido"),
    ]
    cols = 3
    rows = 5
    col_w = Inches(4.1)
    row_h = Inches(1.05)
    x0 = Inches(0.6)
    y0 = Inches(1.55)
    for idx, (num, title, sub) in enumerate(items):
        r = idx // cols; c = idx % cols
        x = x0 + col_w*c + Inches(0.1*c)
        y = y0 + row_h*r + Inches(0.1*r)
        add_rect(s, x, y, col_w, row_h, fill=PRIMARY_BG, radius=True)
        add_rect(s, x, y, Inches(0.12), row_h, fill=TEAL)
        add_text(s, x+Inches(0.3), y+Inches(0.08), Inches(0.7), Inches(0.4),
                 num, size=22, bold=True, color=TEAL)
        add_text(s, x+Inches(1), y+Inches(0.12), col_w-Inches(1.2), Inches(0.4),
                 title, size=14, bold=True, color=DARK_BLUE)
        add_text(s, x+Inches(1), y+Inches(0.55), col_w-Inches(1.2), Inches(0.4),
                 sub, size=11, color=MUTED)
    add_footer(s, 2, TOTAL)

# ====================================================================
# SLIDE 3 — Problema
# ====================================================================
def slide_problema():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_rect(s, 0, 0, Inches(0.18), prs.slide_height, fill=TEAL)
    add_text(s, Inches(0.6), Inches(0.5), Inches(10), Inches(0.7),
             "01 · Problema y motivación", size=28, bold=True, color=DARK_BLUE)
    add_rect(s, Inches(0.6), Inches(1.3), Inches(1.5), Inches(0.04), fill=GREEN)

    add_text(s, Inches(0.6), Inches(1.55), Inches(12), Inches(0.5),
             "Tres dolores reales del circuito asistencial digital",
             size=18, color=MEDICO_BLUE)

    # 3 columnas
    blocks = [
        ("⏱", "Salas de espera ciegas",
         "El paciente llega sin saber su turno real; "
         "el médico no controla el flujo de pacientes en cola."),
        ("📋", "Recetas en papel",
         "El médico imprime, firma a mano y entrega físicamente. "
         "El paciente puede perder la receta y no hay trazabilidad."),
        ("🔌", "Sistemas desconectados",
         "Agenda, chat, historial y prescripción son herramientas "
         "distintas → fricción para todos los roles."),
    ]
    bx = Inches(0.6); by = Inches(2.4); bw = Inches(3.95); bh = Inches(4.0)
    for i,(ic, ttl, body) in enumerate(blocks):
        x = bx + (bw + Inches(0.2))*i
        add_rect(s, x, by, bw, bh, fill=PRIMARY_BG, radius=True)
        add_rect(s, x, by, bw, Inches(0.7), fill=DARK_BLUE, radius=True)
        add_text(s, x+Inches(0.3), by+Inches(0.18), Inches(0.6), Inches(0.4),
                 ic, size=20, color=WHITE)
        add_text(s, x+Inches(1), by+Inches(0.2), bw-Inches(1.2), Inches(0.4),
                 ttl, size=15, bold=True, color=WHITE)
        add_text(s, x+Inches(0.35), by+Inches(0.95), bw-Inches(0.7), bh-Inches(1),
                 body, size=13, color=SLATE, line_spacing=1.35)

    add_text(s, Inches(0.6), Inches(6.65), Inches(12), Inches(0.5),
             "Turnix unifica turno + consulta + receta digital en una sola plataforma.",
             size=14, bold=True, color=TEAL)
    add_footer(s, 3, TOTAL)

# ====================================================================
# SLIDE 4 — Visión y alcance
# ====================================================================
def slide_vision():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_rect(s, 0, 0, Inches(0.18), prs.slide_height, fill=TEAL)
    add_text(s, Inches(0.6), Inches(0.5), Inches(10), Inches(0.7),
             "02 · Visión y alcance", size=28, bold=True, color=DARK_BLUE)
    add_rect(s, Inches(0.6), Inches(1.3), Inches(1.5), Inches(0.04), fill=GREEN)

    # Mockup a la derecha
    s.shapes.add_picture(f"{ASSETS}/01_acceso_home.jpeg",
                         Inches(7.2), Inches(1.6), width=Inches(5.8))

    add_text(s, Inches(0.6), Inches(1.55), Inches(6.4), Inches(0.5),
             "Una sola puerta de entrada · 3 perfiles · 1 base de datos",
             size=15, color=MEDICO_BLUE, bold=True)

    add_bullets(s, Inches(0.6), Inches(2.2), Inches(6.4), Inches(4.5), [
        "Paciente: registro con verificación de email, solicitud de turno por especialidad, chat con el médico y descarga de recetas en PDF.",
        "Médico: panel con pacientes en espera, valoración del médico, generación de recetas con firma manuscrita digital.",
        "Admin: alta/edición/borrado de usuarios, gestión de solicitudes de cambio de especialidad, historial de conexiones.",
        "Tiempo real: turnos, chats y nuevas recetas se propagan por WebSocket sin recargar.",
        "Cloud-ready: despliegue automático en Render desde GitHub, gateway en contenedor Docker.",
    ], size=13)

    add_footer(s, 4, TOTAL)

# ====================================================================
# SLIDE 5 — Arquitectura
# ====================================================================
def slide_arquitectura():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_rect(s, 0, 0, Inches(0.18), prs.slide_height, fill=TEAL)
    add_text(s, Inches(0.6), Inches(0.5), Inches(10), Inches(0.7),
             "03 · Arquitectura del sistema", size=28, bold=True, color=DARK_BLUE)
    add_rect(s, Inches(0.6), Inches(1.3), Inches(1.5), Inches(0.04), fill=GREEN)

    add_text(s, Inches(0.6), Inches(1.55), Inches(12), Inches(0.5),
             "Cliente  →  Gateway Java  →  Backend FastAPI  →  Supabase (Postgres)",
             size=15, color=MEDICO_BLUE, bold=True)

    # 4 columnas: Cliente | Gateway | Backend | DB
    cols = [
        ("🖥", "Cliente",   "HTML5 + JS vanilla",
         ["acceso.html (entry)", "paciente.html", "medico.html", "admin.html",
          "WebSocket nativo", "fetch / multipart"]),
        ("🌐", "Gateway",   "Spring Cloud Gateway",
         ["Java 21 + Spring Boot 3.3", "Routes: /api /ws /**", "Worker @Scheduled",
          "Métricas /worker/stats", "Docker Alpine"]),
        ("⚙",  "Backend",  "FastAPI + asyncpg",
         ["Python 3.11", "WebSockets /ws/{rol}", "REST /api/**",
          "PDFs con ReportLab", "Resend (mails)"]),
        ("🗄", "Datos",    "Supabase Postgres",
         ["pooler IPv4", "usuarios · turnos", "recetas · valoraciones",
          "ENUMs rol/estado", "firma como TEXT b64"]),
    ]
    cw = Inches(2.9); ch = Inches(4.5)
    x0 = Inches(0.6); y0 = Inches(2.2)
    palette = [MEDICO_BLUE, TEAL, DARK_BLUE, GREEN]
    for i,(ic, ttl, sub, items) in enumerate(cols):
        x = x0 + (cw + Inches(0.18))*i
        add_rect(s, x, y0, cw, ch, fill=PRIMARY_BG, radius=True)
        add_rect(s, x, y0, cw, Inches(0.9), fill=palette[i], radius=True)
        add_text(s, x+Inches(0.25), y0+Inches(0.13), Inches(0.6), Inches(0.5),
                 ic, size=22, color=WHITE)
        add_text(s, x+Inches(0.85), y0+Inches(0.15), cw-Inches(1), Inches(0.4),
                 ttl, size=16, bold=True, color=WHITE)
        add_text(s, x+Inches(0.85), y0+Inches(0.5), cw-Inches(1), Inches(0.4),
                 sub, size=10, color=RGBColor(0xE2, 0xE8, 0xF0))
        add_bullets(s, x+Inches(0.2), y0+Inches(1.05), cw-Inches(0.4), ch-Inches(1.2),
                    items, size=11)
        # flecha entre columnas
        if i < len(cols)-1:
            arrow = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW,
                                       x + cw - Inches(0.05), y0+Inches(2),
                                       Inches(0.32), Inches(0.5))
            arrow.fill.solid(); arrow.fill.fore_color.rgb = MUTED
            arrow.line.fill.background()

    add_text(s, Inches(0.6), Inches(6.9), Inches(12), Inches(0.4),
             "Beneficio: el gateway centraliza routing, CORS y observabilidad sin tocar el core de negocio.",
             size=12, color=MUTED)
    add_footer(s, 5, TOTAL)

# ====================================================================
# SLIDE 6 — Stack tecnológico
# ====================================================================
def slide_stack():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_rect(s, 0, 0, Inches(0.18), prs.slide_height, fill=TEAL)
    add_text(s, Inches(0.6), Inches(0.5), Inches(10), Inches(0.7),
             "04 · Stack tecnológico y por qué", size=28, bold=True, color=DARK_BLUE)
    add_rect(s, Inches(0.6), Inches(1.3), Inches(1.5), Inches(0.04), fill=GREEN)

    rows = [
        ("Frontend",  "HTML5 + CSS3 + JS vanilla",
         "Cero build-step, tiempo de carga mínimo, sin lock-in de framework."),
        ("Backend",   "FastAPI 0.115 (Python 3.11) + asyncpg",
         "API async, OpenAPI auto, ideal para WebSockets y endpoints REST."),
        ("PDF",       "ReportLab 4 + Pillow",
         "Generación on-the-fly de la receta con la firma manuscrita embebida."),
        ("Gateway",   "Spring Cloud Gateway 2023.0.3 (Java 21)",
         "Reactive, expresivo en routes, ecosistema enterprise para presentar."),
        ("BD",        "Supabase Postgres (pooler IPv4)",
         "PostgreSQL gestionado, free-tier, backups automáticos."),
        ("Mensajería",  "WebSockets nativos + Resend para email",
         "Chat y notificaciones sin polling; Resend cubre el doble opt-in."),
        ("CI/CD",     "Render + GitHub (auto-deploy desde rama)",
         "Push a cambios → deploy automático del backend y del gateway."),
        ("Tests",     "Pytest async + httpx + Playwright (manual)",
         "Cobertura sobre las rutas críticas: auth, recetas y PDF."),
    ]
    x = Inches(0.6); y = Inches(1.6); w = Inches(12.1); h = Inches(0.62)
    for i,(cat, tech, why) in enumerate(rows):
        yy = y + (h + Inches(0.06))*i
        bg = PRIMARY_BG if i%2==0 else WHITE
        add_rect(s, x, yy, w, h, fill=bg, radius=True)
        add_text(s, x+Inches(0.25), yy+Inches(0.17), Inches(1.8), Inches(0.3),
                 cat, size=12, bold=True, color=TEAL)
        add_text(s, x+Inches(2.1), yy+Inches(0.17), Inches(4.5), Inches(0.3),
                 tech, size=12, bold=True, color=DARK_BLUE)
        add_text(s, x+Inches(6.6), yy+Inches(0.17), Inches(5.5), Inches(0.3),
                 why, size=11, color=SLATE)
    add_footer(s, 6, TOTAL)

# ====================================================================
# SLIDE 7 — Modelo de datos
# ====================================================================
def slide_modelo_datos():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_rect(s, 0, 0, Inches(0.18), prs.slide_height, fill=TEAL)
    add_text(s, Inches(0.6), Inches(0.5), Inches(10), Inches(0.7),
             "05 · Modelo de datos (Supabase Postgres)", size=24, bold=True, color=DARK_BLUE)
    add_rect(s, Inches(0.6), Inches(1.25), Inches(1.5), Inches(0.04), fill=GREEN)

    # Tablas
    tables = [
        ("usuarios", MEDICO_BLUE, Inches(0.6), Inches(1.55), [
            "id  SERIAL PK",
            "usuario  TEXT UNIQUE",
            "contraseña  TEXT",
            "rol  ENUM rol_t",
            "nombre_completo",
            "correo_electronico",
            "especialidad",
            "email_verificado BOOL",
            "foto_perfil BYTEA",
        ]),
        ("turnos", TEAL, Inches(4.7), Inches(1.55), [
            "id  SERIAL PK",
            "id_paciente → usuarios.id",
            "especialidad",
            "atendido_por → usuarios.id",
            "numero_turno",
            "estado  ENUM estado_t",
            "fecha · fecha_fin",
            "puntuacion · valoracion",
        ]),
        ("recetas", DARK_BLUE, Inches(8.8), Inches(1.55), [
            "id  SERIAL PK",
            "paciente_id → usuarios.id",
            "medico_id → usuarios.id",
            "turno_id → turnos.id (UQ nullable)",
            "nombre_receta · motivo",
            "medicamento · dosis · duracion",
            "indicaciones",
            "firma_base64  TEXT (PNG dataURL)",
            "fecha_emision  TIMESTAMP",
        ]),
    ]
    for name, color, x, y, fields in tables:
        add_rect(s, x, y, Inches(4), Inches(4.5), fill=PRIMARY_BG, radius=True)
        add_rect(s, x, y, Inches(4), Inches(0.55), fill=color, radius=True)
        add_text(s, x+Inches(0.25), y+Inches(0.08), Inches(3.5), Inches(0.4),
                 name, size=15, bold=True, color=WHITE)
        for j,f in enumerate(fields):
            add_text(s, x+Inches(0.25), y+Inches(0.7)+Inches(0.4)*j, Inches(3.6), Inches(0.4),
                     "• " + f, size=11, color=DARK_BLUE)

    add_text(s, Inches(0.6), Inches(6.3), Inches(12), Inches(0.4),
             "ENUMs: rol_t (PACIENTE · MEDICO · ADMIN), estado_t (EN_ESPERA · EN_CONSULTA · COMPLETADO · CANCELADO)",
             size=11, color=MUTED)
    add_text(s, Inches(0.6), Inches(6.65), Inches(12), Inches(0.4),
             "Decisión clave: firma se almacena como dataURL PNG en TEXT, simple de embeber luego en ReportLab.",
             size=11, color=MUTED, bold=True)
    add_footer(s, 7, TOTAL)

# ====================================================================
# SLIDE 8 — Flujo Paciente
# ====================================================================
def slide_flujo_paciente():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_rect(s, 0, 0, Inches(0.18), prs.slide_height, fill=TEAL)
    add_text(s, Inches(0.6), Inches(0.5), Inches(10), Inches(0.7),
             "06 · Flujo: Paciente", size=28, bold=True, color=DARK_BLUE)
    add_rect(s, Inches(0.6), Inches(1.3), Inches(1.5), Inches(0.04), fill=GREEN)

    s.shapes.add_picture(f"{ASSETS}/05_paciente_recetas.jpeg",
                         Inches(7.4), Inches(1.5), width=Inches(5.6))

    add_bullets(s, Inches(0.6), Inches(1.6), Inches(6.6), Inches(5), [
        "Registro con email (Resend envía código de verificación de 6 dígitos).",
        "Login WS: LOGIN:user:pass → backend devuelve LOGIN_OK:PACIENTE:nombre:id.",
        "Solicitud de turno: el paciente elige especialidad y entra en cola.",
        "Chat médico-paciente en tiempo real durante la consulta.",
        "Sección «Mis Recetas» (nuevo en esta entrega) → lista todas sus prescripciones con código RX-xxxxxxxx.",
        "Descarga PDF: GET /api/recetas/{id}/pdf?user_id={uid} ⇒ PDF con firma embebida.",
        "Notificación push WS: RECETA_NUEVA:{nombre} refresca la lista al instante.",
    ], size=13)
    add_footer(s, 8, TOTAL)

# ====================================================================
# SLIDE 9 — Flujo Médico
# ====================================================================
def slide_flujo_medico():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_rect(s, 0, 0, Inches(0.18), prs.slide_height, fill=TEAL)
    add_text(s, Inches(0.6), Inches(0.5), Inches(10), Inches(0.7),
             "07 · Flujo: Médico", size=28, bold=True, color=DARK_BLUE)
    add_rect(s, Inches(0.6), Inches(1.3), Inches(1.5), Inches(0.04), fill=GREEN)

    s.shapes.add_picture(f"{ASSETS}/04_medico_firma_modal.jpeg",
                         Inches(7), Inches(1.5), width=Inches(6.1))

    add_bullets(s, Inches(0.6), Inches(1.6), Inches(6.2), Inches(5), [
        "Login dedicado (medico.html) con verificación de rol MEDICO en servidor.",
        "Panel con valoración 4.4/5 + lista de pacientes en espera en vivo.",
        "Al llamar a un turno: chat WS, acceso al historial del paciente, ver documentos.",
        "Generación de receta con modal:",
        "    – Datos clínicos (medicamento, dosis, duración, motivo, indicaciones).",
        "    – Canvas HTML5 para firmar con el ratón o trackpad (toda la lógica en JS vanilla).",
        "    – Confirmación con re-autenticación de password del propio médico.",
        "El backend valida password, persiste la receta en Postgres y notifica al paciente por WS.",
    ], size=13)
    add_footer(s, 9, TOTAL)

# ====================================================================
# SLIDE 10 — Flujo Admin
# ====================================================================
def slide_flujo_admin():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_rect(s, 0, 0, Inches(0.18), prs.slide_height, fill=TEAL)
    add_text(s, Inches(0.6), Inches(0.5), Inches(10), Inches(0.7),
             "08 · Flujo: Admin (modo claro + oscuro)", size=26, bold=True, color=DARK_BLUE)
    add_rect(s, Inches(0.6), Inches(1.3), Inches(1.5), Inches(0.04), fill=GREEN)

    # Dos capturas lado a lado
    s.shapes.add_picture(f"{ASSETS}/06_admin_light.jpeg",
                         Inches(0.6), Inches(1.55), width=Inches(6.1))
    s.shapes.add_picture(f"{ASSETS}/07_admin_dark.jpeg",
                         Inches(6.85), Inches(1.55), width=Inches(6.1))

    add_pill(s, Inches(0.6), Inches(5.05), "🌞 Tema claro", MEDICO_BLUE, w=Inches(1.5))
    add_pill(s, Inches(6.85), Inches(5.05), "🌙 Tema oscuro", DARK_BLUE, w=Inches(1.5))

    add_bullets(s, Inches(0.6), Inches(5.6), Inches(12.1), Inches(1.5), [
        "Lista de usuarios con badge de rol, especialidad y verificación de email.",
        "Acciones críticas (editar/borrar/aprobar especialidad) requieren reautenticación con la password del admin.",
        "Toggle de tema persiste en localStorage; las variables CSS se intercambian sin recargar.",
    ], size=12)
    add_footer(s, 10, TOTAL)

# ====================================================================
# SLIDE 11 — Tiempo real
# ====================================================================
def slide_websockets():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_rect(s, 0, 0, Inches(0.18), prs.slide_height, fill=TEAL)
    add_text(s, Inches(0.6), Inches(0.5), Inches(10), Inches(0.7),
             "09 · Tiempo real con WebSockets", size=28, bold=True, color=DARK_BLUE)
    add_rect(s, Inches(0.6), Inches(1.3), Inches(1.5), Inches(0.04), fill=GREEN)

    add_text(s, Inches(0.6), Inches(1.55), Inches(12), Inches(0.5),
             "FastAPI gestiona 3 endpoints WS, uno por rol, con su propio pool de conexiones.",
             size=14, color=MEDICO_BLUE)

    # Diagrama: 3 cajas roles + WS centro + backend
    add_rect(s, Inches(0.6), Inches(2.3), Inches(2.7), Inches(3.6), fill=PRIMARY_BG, radius=True)
    add_text(s, Inches(0.6), Inches(2.45), Inches(2.7), Inches(0.4),
             "Endpoints WS", size=14, bold=True, color=DARK_BLUE, align=PP_ALIGN.CENTER)
    rutas = ["/ws/PACIENTE", "/ws/MEDICO", "/ws/ADMIN"]
    for i,r in enumerate(rutas):
        add_rect(s, Inches(0.85), Inches(3.0)+Inches(0.85)*i, Inches(2.2), Inches(0.65),
                 fill=WHITE, radius=True)
        add_text(s, Inches(0.85), Inches(3.16)+Inches(0.85)*i, Inches(2.2), Inches(0.4),
                 r, size=13, bold=True, color=TEAL, align=PP_ALIGN.CENTER)

    # Tipos de mensaje
    msgs = [
        ("LOGIN_OK:rol:nombre:id",   MEDICO_BLUE, "Sesión establecida"),
        ("NEW_TURNO:numero:user",    TEAL,        "Médico ve nuevo paciente"),
        ("CHAT:remitente:mensaje",   DARK_BLUE,   "Chat 1-a-1"),
        ("RECETA_NUEVA:nombre",      GREEN,       "Push al paciente"),
        ("CONFIRMAR_ASISTENCIA",     ACCENT_AMB,  "Paciente confirma turno"),
        ("ESPECIALIDAD_OK / KO",     RGBColor(0x6D,0x28,0xD9), "Admin notifica decisión"),
    ]
    x = Inches(3.7); y = Inches(2.3); w = Inches(9.05); h = Inches(0.6)
    add_text(s, x, y, Inches(7), Inches(0.4),
             "Vocabulario de mensajes", size=14, bold=True, color=DARK_BLUE)
    for i,(m, c, desc) in enumerate(msgs):
        yy = y + Inches(0.5) + (h + Inches(0.1))*i
        add_rect(s, x, yy, w, h, fill=PRIMARY_BG, radius=True)
        add_rect(s, x, yy, Inches(0.18), h, fill=c)
        add_text(s, x+Inches(0.35), yy+Inches(0.15), Inches(4), Inches(0.4),
                 m, size=12, bold=True, color=DARK_BLUE, font="Consolas")
        add_text(s, x+Inches(5), yy+Inches(0.15), Inches(4), Inches(0.4),
                 desc, size=12, color=SLATE)
    add_footer(s, 11, TOTAL)

# ====================================================================
# SLIDE 12 — Firma digital manuscrita
# ====================================================================
def slide_firma():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_rect(s, 0, 0, Inches(0.18), prs.slide_height, fill=TEAL)
    add_text(s, Inches(0.6), Inches(0.5), Inches(10), Inches(0.7),
             "10 · Firma digital manuscrita", size=28, bold=True, color=DARK_BLUE)
    add_rect(s, Inches(0.6), Inches(1.3), Inches(1.5), Inches(0.04), fill=GREEN)

    s.shapes.add_picture(f"{ASSETS}/08_receta_pdf.png",
                         Inches(9), Inches(1.5), height=Inches(5.4))

    add_text(s, Inches(0.6), Inches(1.55), Inches(8.2), Inches(0.5),
             "Del canvas del navegador al PDF en la BD",
             size=15, bold=True, color=MEDICO_BLUE)

    # Pipeline pasos
    steps = [
        ("1", "Canvas HTML5",
         "El médico dibuja con mouse/touch. Listeners mousedown/move/up + touchstart/move/end."),
        ("2", "toDataURL('image/png')",
         "Se exporta como PNG codificado en base64 (`data:image/png;base64,...`)."),
        ("3", "Validación frontend",
         "Si firmaTieneTrazo == false → no se permite enviar. Mensaje rojo en el modal."),
        ("4", "POST /api/recetas/crear",
         "Body JSON incluye firma_base64. El backend re-autentica al médico antes de insertar."),
        ("5", "ReportLab + Pillow",
         "Al pedir el PDF: PIL.verify() defensivo y RLImage embebe la firma a 7 × 3.2 cm."),
    ]
    x = Inches(0.6); y = Inches(2.15); w = Inches(8.1); h = Inches(0.85)
    for i,(num, ttl, desc) in enumerate(steps):
        yy = y + (h + Inches(0.08))*i
        add_rect(s, x, yy, w, h, fill=PRIMARY_BG, radius=True)
        add_rect(s, x, yy, Inches(0.65), h, fill=TEAL)
        add_text(s, x, yy+Inches(0.2), Inches(0.65), Inches(0.5),
                 num, size=22, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        add_text(s, x+Inches(0.85), yy+Inches(0.08), Inches(7.2), Inches(0.35),
                 ttl, size=12, bold=True, color=DARK_BLUE)
        add_text(s, x+Inches(0.85), yy+Inches(0.4), Inches(7.2), Inches(0.45),
                 desc, size=11, color=SLATE)
    add_footer(s, 12, TOTAL)

# ====================================================================
# SLIDE 13 — Gateway Java + Worker
# ====================================================================
def slide_gateway():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_rect(s, 0, 0, Inches(0.18), prs.slide_height, fill=TEAL)
    add_text(s, Inches(0.6), Inches(0.5), Inches(11), Inches(0.7),
             "11 · Gateway Java + Worker programado", size=26, bold=True, color=DARK_BLUE)
    add_rect(s, Inches(0.6), Inches(1.3), Inches(1.5), Inches(0.04), fill=GREEN)

    # Caja gateway grande
    add_rect(s, Inches(0.6), Inches(1.55), Inches(12.1), Inches(2.4),
             fill=PRIMARY_BG, radius=True)
    add_text(s, Inches(0.85), Inches(1.7), Inches(8), Inches(0.45),
             "Spring Cloud Gateway · Java 21 · Docker Alpine",
             size=15, bold=True, color=DARK_BLUE)

    add_bullets(s, Inches(0.85), Inches(2.2), Inches(11.5), Inches(2), [
        "Routes declarativas en application.yml: /api/** → backend, /ws/** → backend WS, /** → frontend estático.",
        "RequestCountingFilter (GlobalFilter) cuenta peticiones por ruta y status code.",
        "Worker @Scheduled cada 15 s ⇒ ping a /api/health del backend, almacena latencia y estado.",
        "Endpoint /worker/stats expone JSON con uptime, rutas más usadas, p50/p95 y salud del backend.",
        "Header X-Powered-By: Turnix-Gateway añadido globalmente para trazabilidad.",
    ], size=12)

    # Caja JSON de ejemplo
    add_rect(s, Inches(0.6), Inches(4.15), Inches(7.4), Inches(2.85),
             fill=DARK_BLUE, radius=True)
    add_text(s, Inches(0.85), Inches(4.25), Inches(7), Inches(0.4),
             "GET /worker/stats   →   200 OK", size=12, bold=True,
             color=RGBColor(0x67, 0xE8, 0xF9), font="Consolas")
    code = (
        '{\n'
        '  "uptime_seconds": 1432,\n'
        '  "total_requests": 318,\n'
        '  "requests_by_route": { "/api": 217, "/ws": 84, "other": 17 },\n'
        '  "responses_by_status_class": { "2xx": 295, "4xx": 18, "5xx": 5 },\n'
        '  "backend": {\n'
        '    "status": "UP",\n'
        '    "last_latency_ms": 64,\n'
        '    "checks_ok": 96,\n'
        '    "checks_fail": 1\n'
        '  }\n'
        '}'
    )
    tb = add_text(s, Inches(0.85), Inches(4.65), Inches(7), Inches(2.25),
                  code, size=10, color=WHITE, font="Consolas", line_spacing=1.2)

    # Caja diagrama worker
    add_rect(s, Inches(8.15), Inches(4.15), Inches(4.55), Inches(2.85),
             fill=WHITE, radius=True, line=RGBColor(0xCB,0xD5,0xE1))
    add_text(s, Inches(8.35), Inches(4.25), Inches(4.2), Inches(0.4),
             "Componentes Java", size=12, bold=True, color=DARK_BLUE)
    comps = [
        ("HealthCheckWorker", "@Scheduled · pinguea /api/health"),
        ("RequestCountingFilter", "GlobalFilter · cuenta tráfico"),
        ("MetricsStore",     "ConcurrentHashMap + LongAdder"),
        ("WorkerStatsController", "GET /worker/stats → JSON"),
    ]
    for i,(name, desc) in enumerate(comps):
        yy = Inches(4.7) + Inches(0.55)*i
        add_text(s, Inches(8.35), yy, Inches(4.2), Inches(0.25),
                 "• " + name, size=11, bold=True, color=TEAL)
        add_text(s, Inches(8.5), yy+Inches(0.25), Inches(4.05), Inches(0.25),
                 desc, size=10, color=SLATE)

    add_footer(s, 13, TOTAL)

# ====================================================================
# SLIDE 14 — Seguridad
# ====================================================================
def slide_seguridad():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_rect(s, 0, 0, Inches(0.18), prs.slide_height, fill=TEAL)
    add_text(s, Inches(0.6), Inches(0.5), Inches(10), Inches(0.7),
             "12 · Seguridad y privacidad", size=28, bold=True, color=DARK_BLUE)
    add_rect(s, Inches(0.6), Inches(1.3), Inches(1.5), Inches(0.04), fill=GREEN)

    items = [
        ("Reautenticación en acciones críticas",
         "Cualquier acción admin (alta/baja/edición) y la firma de receta exigen volver a introducir la password.",
         MEDICO_BLUE),
        ("Comprobación de rol en servidor",
         "Cada endpoint REST verifica el rol del usuario (PACIENTE/MEDICO/ADMIN) → un paciente no puede llamar /api/admin/**.",
         TEAL),
        ("Aislamiento de recetas",
         "GET /api/recetas/{id}/pdf rechaza con 403 si el user_id no es el paciente dueño ni el médico que la emitió.",
         DARK_BLUE),
        ("CORS controlado en gateway",
         "El gateway aplica una política única; el backend confía en él. Reduce superficie y centraliza configuración.",
         GREEN),
        ("Datos sensibles",
         "Email verificado vía Resend con código de 6 dígitos antes de poder operar (cumple RGPD para datos médicos).",
         ACCENT_AMB),
        ("Limpieza de logs",
         "No se loguean contraseñas; los mensajes de auth fallida sólo dicen «credenciales inválidas».",
         RGBColor(0x6D,0x28,0xD9)),
    ]
    x = Inches(0.6); y = Inches(1.6); w = Inches(12.1); h = Inches(0.83)
    for i,(t, d, c) in enumerate(items):
        yy = y + (h + Inches(0.06))*i
        add_rect(s, x, yy, w, h, fill=PRIMARY_BG, radius=True)
        add_rect(s, x, yy, Inches(0.18), h, fill=c)
        add_text(s, x+Inches(0.35), yy+Inches(0.13), Inches(11.5), Inches(0.35),
                 t, size=13, bold=True, color=DARK_BLUE)
        add_text(s, x+Inches(0.35), yy+Inches(0.45), Inches(11.5), Inches(0.35),
                 d, size=11, color=SLATE)
    add_footer(s, 14, TOTAL)

# ====================================================================
# SLIDE 15 — Despliegue
# ====================================================================
def slide_deploy():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_rect(s, 0, 0, Inches(0.18), prs.slide_height, fill=TEAL)
    add_text(s, Inches(0.6), Inches(0.5), Inches(11), Inches(0.7),
             "13 · Despliegue continuo (Render + GitHub)", size=24, bold=True, color=DARK_BLUE)
    add_rect(s, Inches(0.6), Inches(1.3), Inches(1.5), Inches(0.04), fill=GREEN)

    # Pipeline horizontal
    stages = [
        ("Dev",            "VS Code · git",   MEDICO_BLUE),
        ("git push",       "rama: cambios",   TEAL),
        ("GitHub",         "Webhook a Render", DARK_BLUE),
        ("Build",          "pip install / Docker", ACCENT_AMB),
        ("Deploy",         "Render Free Tier", GREEN),
        ("Live",           "*.onrender.com",  RGBColor(0x10,0xB9,0x81)),
    ]
    bx = Inches(0.6); by = Inches(1.6); bw = Inches(1.95); bh = Inches(1.1)
    for i,(t, sub, c) in enumerate(stages):
        x = bx + (bw + Inches(0.05))*i
        add_rect(s, x, by, bw, bh, fill=c, radius=True)
        add_text(s, x, by+Inches(0.2), bw, Inches(0.4),
                 t, size=15, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        add_text(s, x, by+Inches(0.62), bw, Inches(0.4),
                 sub, size=10, color=WHITE, align=PP_ALIGN.CENTER)
        if i < len(stages)-1:
            arrow = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW,
                                       x + bw - Inches(0.02), by + Inches(0.42),
                                       Inches(0.13), Inches(0.25))
            arrow.fill.solid(); arrow.fill.fore_color.rgb = MUTED
            arrow.line.fill.background()

    # Dos servicios en Render
    add_rect(s, Inches(0.6), Inches(3.0), Inches(5.95), Inches(3.7),
             fill=PRIMARY_BG, radius=True)
    add_text(s, Inches(0.85), Inches(3.15), Inches(5.5), Inches(0.4),
             "Servicio 1 · Backend FastAPI", size=15, bold=True, color=MEDICO_BLUE)
    add_bullets(s, Inches(0.85), Inches(3.6), Inches(5.5), Inches(3), [
        "Runtime: Python 3.11.9",
        "Build: pip install -r requirements.txt",
        "Start: uvicorn server:app --host 0.0.0.0 --port $PORT",
        "Envs: SUPABASE_*, RESEND_API_KEY, FRONTEND_DIR, UPLOADS_DIR, CORS_ORIGINS",
        "URL: turnix-project.onrender.com",
    ], size=11)

    add_rect(s, Inches(6.75), Inches(3.0), Inches(5.95), Inches(3.7),
             fill=PRIMARY_BG, radius=True)
    add_text(s, Inches(7), Inches(3.15), Inches(5.5), Inches(0.4),
             "Servicio 2 · Gateway Java (Docker)", size=15, bold=True, color=TEAL)
    add_bullets(s, Inches(7), Inches(3.6), Inches(5.5), Inches(3), [
        "Runtime: Eclipse Temurin 21 JRE Alpine",
        "Build: Dockerfile multistage (Maven 3.9 + JRE)",
        "rootDir: turnix-gateway",
        "Envs: BACKEND_URL, BACKEND_URL_WS",
        "URL: turnix-gateway.onrender.com",
    ], size=11)
    add_footer(s, 15, TOTAL)

# ====================================================================
# SLIDE 16 — Demo
# ====================================================================
def slide_demo():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, DARK_BLUE)
    add_text(s, Inches(0.6), Inches(0.5), Inches(12), Inches(0.7),
             "14 · DEMO EN VIVO", size=32, bold=True, color=WHITE)
    add_rect(s, Inches(0.6), Inches(1.35), Inches(1.5), Inches(0.05), fill=GREEN)
    add_text(s, Inches(0.6), Inches(1.55), Inches(12), Inches(0.5),
             "Guion para los próximos 4 minutos en pantalla",
             size=15, color=RGBColor(0x9C, 0xAF, 0xC0))

    steps = [
        ("00:00", "Acceso", "Entrar en turnix-project.onrender.com → redirige a acceso.html.", MEDICO_BLUE),
        ("00:30", "Paciente", "Login user1 / 1234. Mostrar foto de perfil + sección Recetas (lista poblada).", GREEN),
        ("01:15", "Médico", "Abrir otra pestaña medico.html. Login medico1 / 1234. Llamar siguiente turno.", TEAL),
        ("02:00", "Receta + firma", "Modal de receta, rellenar campos, dibujar firma con el ratón, generar.", ACCENT_AMB),
        ("02:45", "Vuelta al paciente", "Push WebSocket → la receta aparece sola. Descargar PDF y mostrarlo.", GREEN),
        ("03:20", "Admin", "Login admin / 1234. Cambiar de modo claro a oscuro. Mostrar tabla de usuarios.", DARK_BLUE),
        ("03:45", "Gateway", "Abrir turnix-gateway.onrender.com/worker/stats en una pestaña. JSON en vivo.", RGBColor(0x6D,0x28,0xD9)),
    ]
    x = Inches(0.6); y = Inches(2.15); w = Inches(12.1); h = Inches(0.65)
    for i,(t, tag, desc, c) in enumerate(steps):
        yy = y + (h + Inches(0.05))*i
        add_rect(s, x, yy, w, h, fill=RGBColor(0x1E,0x29,0x3B), radius=True)
        add_text(s, x+Inches(0.2), yy+Inches(0.16), Inches(1), Inches(0.35),
                 t, size=14, bold=True, color=RGBColor(0x67,0xE8,0xF9), font="Consolas")
        add_pill(s, x+Inches(1.3), yy+Inches(0.13), tag, c, w=Inches(1.5), h=Inches(0.4), size=11)
        add_text(s, x+Inches(3.05), yy+Inches(0.16), Inches(9), Inches(0.4),
                 desc, size=12, color=WHITE)
    add_text(s, Inches(0.6), Inches(7.05), Inches(12), Inches(0.35),
             "Turnix Salud · Defensa técnica · Rodrigo García",
             size=10, color=RGBColor(0x64,0x74,0x8B))
    add_text(s, Inches(11.5), Inches(7.05), Inches(1.5), Inches(0.35),
             f"16 / {TOTAL}", size=10, color=RGBColor(0x64,0x74,0x8B), align=PP_ALIGN.RIGHT)

# ====================================================================
# SLIDE 17 — Decisiones técnicas
# ====================================================================
def slide_decisiones():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_rect(s, 0, 0, Inches(0.18), prs.slide_height, fill=TEAL)
    add_text(s, Inches(0.6), Inches(0.5), Inches(12), Inches(0.7),
             "Decisiones técnicas más relevantes", size=26, bold=True, color=DARK_BLUE)
    add_rect(s, Inches(0.6), Inches(1.3), Inches(1.5), Inches(0.04), fill=GREEN)

    rows = [
        ("¿Por qué FastAPI y no Flask/Django?",
         "Necesitamos WebSockets nativos, async I/O y OpenAPI gratis. FastAPI lo da out of the box."),
        ("¿Por qué frontend en HTML puro y no React?",
         "El alcance lo permite, el time-to-render es mínimo y no necesitamos build pipeline. Más fácil de defender ante un tribunal."),
        ("¿Por qué un gateway en Java?",
         "Suma valor académico (segundo lenguaje, contenedor Docker, microservicio real) y permite añadir métricas y políticas sin tocar el backend."),
        ("¿Por qué firma como dataURL en TEXT?",
         "Evita gestionar un object storage extra; cabe sin problemas para una imagen vectorial de ~10 KB."),
        ("¿Por qué Supabase en vez de Postgres autogestionado?",
         "Free-tier real con backups, IPv4 pooler, y el código sigue siendo Postgres estándar (asyncpg)."),
        ("¿Por qué WebSocket y no SSE?",
         "El chat es bidireccional. SSE serviría solo para push del backend, no para el paciente enviando."),
    ]
    x = Inches(0.6); y = Inches(1.6); w = Inches(12.1); h = Inches(0.85)
    for i,(q, a) in enumerate(rows):
        yy = y + (h + Inches(0.05))*i
        add_rect(s, x, yy, w, h, fill=PRIMARY_BG, radius=True)
        add_text(s, x+Inches(0.25), yy+Inches(0.12), Inches(11.5), Inches(0.35),
                 "▸ " + q, size=12, bold=True, color=DARK_BLUE)
        add_text(s, x+Inches(0.45), yy+Inches(0.45), Inches(11.3), Inches(0.4),
                 a, size=11, color=SLATE)
    add_footer(s, 17, TOTAL)

# ====================================================================
# SLIDE 18 — Roadmap
# ====================================================================
def slide_roadmap():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_rect(s, 0, 0, Inches(0.18), prs.slide_height, fill=TEAL)
    add_text(s, Inches(0.6), Inches(0.5), Inches(10), Inches(0.7),
             "Roadmap y lo que aprendí", size=28, bold=True, color=DARK_BLUE)
    add_rect(s, Inches(0.6), Inches(1.3), Inches(1.5), Inches(0.04), fill=GREEN)

    # Done / Next / Future
    cols = [
        ("✅", "Hecho",
         ["Turnos en tiempo real y chat", "Recetas con firma manuscrita + PDF",
          "Panel admin con modo claro/oscuro", "Email verificado por código",
          "Gateway Java + worker + métricas", "CI/CD a Render"],
         GREEN),
        ("🎯", "Siguiente",
         ["QR de verificación en cada PDF", "Notificaciones push reales (web push)",
          "Multi-clínica (tenants)", "Calendario de turnos al estilo Google",
          "Histórico exportable a CSV", "Tests E2E con Playwright en CI"],
         MEDICO_BLUE),
        ("🚀", "Futuro",
         ["Videollamada nativa (WebRTC)", "Receta con QR firmada digitalmente",
          "App móvil React Native", "IA: pre-diagnóstico por síntomas",
          "Integración con receta electrónica oficial", "Estadísticas tipo PowerBI"],
         DARK_BLUE),
    ]
    cw = Inches(3.95); ch = Inches(5.2); x0 = Inches(0.6); y0 = Inches(1.6)
    for i,(ic, ttl, items, c) in enumerate(cols):
        x = x0 + (cw + Inches(0.2))*i
        add_rect(s, x, y0, cw, ch, fill=PRIMARY_BG, radius=True)
        add_rect(s, x, y0, cw, Inches(0.8), fill=c, radius=True)
        add_text(s, x+Inches(0.3), y0+Inches(0.18), Inches(0.6), Inches(0.4),
                 ic, size=18, color=WHITE)
        add_text(s, x+Inches(1), y0+Inches(0.22), cw-Inches(1.2), Inches(0.4),
                 ttl, size=15, bold=True, color=WHITE)
        for j,it in enumerate(items):
            add_text(s, x+Inches(0.3), y0+Inches(0.95)+Inches(0.6)*j,
                     cw-Inches(0.6), Inches(0.5),
                     "• " + it, size=11, color=SLATE, line_spacing=1.2)

    add_text(s, Inches(0.6), Inches(7.0), Inches(12), Inches(0.4),
             "Lo más valioso del proyecto: unificar 4 tecnologías diferentes (Python, Java, Postgres, JS) en un pipeline reproducible end-to-end.",
             size=11, color=MUTED, bold=True)
    add_footer(s, 18, TOTAL)

# ====================================================================
# SLIDE 19 — Gracias
# ====================================================================
def slide_gracias():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, DARK_BLUE)
    # decorativo
    add_rect(s, Inches(0), Inches(2.3), Inches(13.333), Inches(0.04), fill=TEAL)
    add_rect(s, Inches(0), Inches(5.2),  Inches(13.333), Inches(0.04), fill=GREEN)

    add_text(s, Inches(0.6), Inches(2.7), Inches(12), Inches(1.5),
             "Gracias", size=78, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    add_text(s, Inches(0.6), Inches(4.1), Inches(12), Inches(0.5),
             "Preguntas, código y demo en vivo a disposición del tribunal",
             size=18, color=RGBColor(0x9C, 0xAF, 0xC0), align=PP_ALIGN.CENTER)

    # Links bottom
    add_text(s, Inches(0.6), Inches(5.6), Inches(12), Inches(0.45),
             "github.com/RodrigoGarcia2004/Turnix-Project   ·   turnix-project.onrender.com   ·   turnix-gateway.onrender.com",
             size=12, color=RGBColor(0x67, 0xE8, 0xF9), align=PP_ALIGN.CENTER, font="Consolas")

    add_text(s, Inches(0.6), Inches(6.4), Inches(12), Inches(0.4),
             "Rodrigo García · 2026",
             size=12, color=RGBColor(0x9C, 0xAF, 0xC0), align=PP_ALIGN.CENTER)

# ===== Construir =====
slide_portada()
slide_indice()
slide_problema()
slide_vision()
slide_arquitectura()
slide_stack()
slide_modelo_datos()
slide_flujo_paciente()
slide_flujo_medico()
slide_flujo_admin()
slide_websockets()
slide_firma()
slide_gateway()
slide_seguridad()
slide_deploy()
slide_demo()
slide_decisiones()
slide_roadmap()
slide_gracias()

out = "/app/presentation_assets/Turnix_Presentacion.pptx"
prs.save(out)
print("Guardado:", out, "·", os.path.getsize(out), "bytes ·", len(prs.slides), "slides")
