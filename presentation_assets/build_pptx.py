"""
Version simplificada de la presentacion Turnix.
Foco: que hace la app y como se usa. SIN tecnologias, sin codigo, sin BD.
13 slides para 15 min de defensa - tono divulgativo.
"""
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from lxml import etree
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

ASSETS = "/app/presentation_assets"

prs = Presentation()
prs.slide_width  = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]
TOTAL = 13

# ===== Helpers =====
def add_solid_bg(slide, color):
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    bg.line.fill.background()
    bg.fill.solid(); bg.fill.fore_color.rgb = color
    slide.shapes._spTree.remove(bg._element); slide.shapes._spTree.insert(2, bg._element)

def add_gradient_band(slide, top, height, c1, c2):
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
    sp.append(etree.fromstring(grad_xml))

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
                font="Calibri", spacing=8):
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = Emu(0); tf.margin_right = Emu(0)
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        p.line_spacing = 1.3
        p.space_after = Pt(spacing)
        r = p.add_run(); r.text = "•  "
        r.font.name = font; r.font.size = Pt(size); r.font.color.rgb = TEAL; r.font.bold = True
        r2 = p.add_run(); r2.text = item
        r2.font.name = font; r2.font.size = Pt(size); r2.font.color.rgb = color
    return tb

def add_rect(slide, left, top, width, height, fill=WHITE, line=None, radius=False):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE, left, top, width, height)
    shp.fill.solid(); shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line; shp.line.width = Pt(0.75)
    return shp

def add_pill(slide, left, top, text, fill, color=WHITE, w=Inches(1.6), h=Inches(0.4), size=12):
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

def add_footer(slide, num):
    add_text(slide, Inches(0.4), Inches(7.05), Inches(6), Inches(0.35),
             "Turnix Salud  ·  Rodrigo García", size=10, color=MUTED)
    add_text(slide, Inches(11.5), Inches(7.05), Inches(1.5), Inches(0.35),
             f"{num} / {TOTAL}", size=10, color=MUTED, align=PP_ALIGN.RIGHT)

def add_title(slide, num, title):
    add_rect(slide, 0, 0, Inches(0.18), prs.slide_height, fill=TEAL)
    add_text(slide, Inches(0.6), Inches(0.5), Inches(12), Inches(0.7),
             f"{num} · {title}", size=28, bold=True, color=DARK_BLUE)
    add_rect(slide, Inches(0.6), Inches(1.3), Inches(1.5), Inches(0.04), fill=GREEN)

# ====================================================================
# SLIDE 1 — Portada
# ====================================================================
def slide_portada():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, PRIMARY_BG)
    add_gradient_band(s, 0, Inches(7.5), SECOND_BG, PRIMARY_BG)

    # Bloque grande blanco
    add_rect(s, Inches(1.2), Inches(1.3), Inches(11), Inches(5), fill=WHITE, radius=True)
    add_rect(s, Inches(1.2), Inches(1.3), Inches(0.2), Inches(5), fill=TEAL)

    add_text(s, Inches(1.7), Inches(1.9), Inches(11), Inches(1.0),
             "Turnix Salud", size=54, bold=True, color=DARK_BLUE)
    add_text(s, Inches(1.7), Inches(2.9), Inches(11), Inches(0.6),
             "La plataforma que conecta pacientes y médicos",
             size=22, color=MEDICO_BLUE)
    add_rect(s, Inches(1.7), Inches(3.7), Inches(2), Inches(0.05), fill=GREEN)
    add_text(s, Inches(1.7), Inches(3.95), Inches(11), Inches(1),
             ["Pide tu turno, habla con tu médico y recibe",
              "tus recetas firmadas, todo desde el navegador."],
             size=18, color=SLATE, line_spacing=1.4)

    add_text(s, Inches(1.7), Inches(5.7), Inches(11), Inches(0.4),
             "Proyecto Fin de Ciclo  ·  Rodrigo García  ·  2026",
             size=13, color=MUTED)

# ====================================================================
# SLIDE 2 — ¿Qué es Turnix?
# ====================================================================
def slide_que_es():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_title(s, "01", "¿Qué es Turnix?")

    add_text(s, Inches(0.6), Inches(1.55), Inches(12), Inches(0.6),
             "Una app web que digitaliza la consulta médica de principio a fin.",
             size=18, color=MEDICO_BLUE, bold=True)

    # 3 cards: lo que une
    cards = [
        ("📅", "Turnos",    "Pide cita y haz cola desde el sofá. Sabes siempre cuántas personas tienes delante."),
        ("💬", "Consulta",  "Hablas con el médico desde el navegador. Sin instalar nada, sin esperar en la sala."),
        ("📋", "Recetas",   "El médico firma con el ratón y tú descargas tu receta en PDF al instante."),
    ]
    bx = Inches(0.6); by = Inches(2.5); bw = Inches(3.95); bh = Inches(3.4)
    for i,(ic, ttl, body) in enumerate(cards):
        x = bx + (bw + Inches(0.2))*i
        add_rect(s, x, by, bw, bh, fill=PRIMARY_BG, radius=True)
        add_rect(s, x, by, bw, Inches(0.95), fill=TEAL, radius=True)
        add_text(s, x+Inches(0.3), by+Inches(0.22), Inches(0.8), Inches(0.5),
                 ic, size=28, color=WHITE)
        add_text(s, x+Inches(1.2), by+Inches(0.28), bw-Inches(1.4), Inches(0.5),
                 ttl, size=20, bold=True, color=WHITE)
        add_text(s, x+Inches(0.35), by+Inches(1.25), bw-Inches(0.7), bh-Inches(1.4),
                 body, size=15, color=SLATE, line_spacing=1.45)

    add_text(s, Inches(0.6), Inches(6.3), Inches(12), Inches(0.5),
             "Todo en un mismo sitio, accesible desde móvil, tablet u ordenador.",
             size=14, color=MUTED, italic_safe=False) if False else \
    add_text(s, Inches(0.6), Inches(6.3), Inches(12), Inches(0.5),
             "Todo en un mismo sitio, accesible desde móvil, tablet u ordenador.",
             size=14, color=MUTED)
    add_footer(s, 2)

# ====================================================================
# SLIDE 3 — ¿A quién va dirigido?
# ====================================================================
def slide_perfiles():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_title(s, "02", "Tres perfiles, una sola plataforma")

    perfiles = [
        ("👤", "Paciente", MEDICO_BLUE,
         ["Pide turno por especialidad",
          "Habla con su médico por chat",
          "Descarga sus recetas en PDF",
          "Consulta su historial médico"]),
        ("👨‍⚕️", "Médico", TEAL,
         ["Ve los pacientes en espera",
          "Atiende uno por uno por chat",
          "Genera la receta y la firma",
          "Recibe valoraciones del paciente"]),
        ("🛡", "Administrador", DARK_BLUE,
         ["Gestiona usuarios y permisos",
          "Aprueba cambios de especialidad",
          "Supervisa la actividad",
          "Activa modo claro u oscuro"]),
    ]
    bx = Inches(0.6); by = Inches(1.7); bw = Inches(3.95); bh = Inches(4.7)
    for i,(ic, ttl, c, items) in enumerate(perfiles):
        x = bx + (bw + Inches(0.2))*i
        add_rect(s, x, by, bw, bh, fill=PRIMARY_BG, radius=True)
        # circulo con icono
        circ = s.shapes.add_shape(MSO_SHAPE.OVAL, x+Inches(1.45), by+Inches(0.4), Inches(1.05), Inches(1.05))
        circ.fill.solid(); circ.fill.fore_color.rgb = c; circ.line.fill.background()
        add_text(s, x+Inches(1.45), by+Inches(0.55), Inches(1.05), Inches(0.8),
                 ic, size=30, color=WHITE, align=PP_ALIGN.CENTER)
        add_text(s, x, by+Inches(1.65), bw, Inches(0.5),
                 ttl, size=22, bold=True, color=c, align=PP_ALIGN.CENTER)
        # bullets
        for j,it in enumerate(items):
            add_text(s, x+Inches(0.45), by+Inches(2.4)+Inches(0.55)*j, bw-Inches(0.6), Inches(0.5),
                     "•  " + it, size=14, color=SLATE)

    add_footer(s, 3)

# ====================================================================
# SLIDE 4 — ¿Cómo funciona? (flujo general)
# ====================================================================
def slide_flujo():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_title(s, "03", "¿Cómo funciona, paso a paso?")

    add_text(s, Inches(0.6), Inches(1.55), Inches(12), Inches(0.5),
             "El recorrido del paciente, desde que entra hasta que recibe su receta.",
             size=15, color=MEDICO_BLUE)

    steps = [
        ("1", "Entrar",     "El paciente abre la web y elige Portal Paciente.",            MEDICO_BLUE),
        ("2", "Pedir turno","Selecciona la especialidad y se pone en cola.",               TEAL),
        ("3", "Esperar",    "Ve cuántas personas tiene delante en tiempo real.",          ACCENT_AMB),
        ("4", "Consultar",  "Cuando es su turno, chatea con el médico desde el navegador.", DARK_BLUE),
        ("5", "Recibir",    "Si necesita medicación, el médico genera y firma la receta.", GREEN),
        ("6", "Descargar",  "El paciente descarga su receta en PDF cuando quiera.",        RGBColor(0x6D,0x28,0xD9)),
    ]
    # 3 arriba, 3 abajo
    bw = Inches(3.95); bh = Inches(2.15)
    for i,(num, ttl, desc, c) in enumerate(steps):
        col = i % 3; row = i // 3
        x = Inches(0.6) + (bw + Inches(0.2))*col
        y = Inches(2.25) + (bh + Inches(0.2))*row
        add_rect(s, x, y, bw, bh, fill=PRIMARY_BG, radius=True)
        # numero grande en circulo
        circ = s.shapes.add_shape(MSO_SHAPE.OVAL, x+Inches(0.3), y+Inches(0.3), Inches(0.85), Inches(0.85))
        circ.fill.solid(); circ.fill.fore_color.rgb = c; circ.line.fill.background()
        add_text(s, x+Inches(0.3), y+Inches(0.42), Inches(0.85), Inches(0.6),
                 num, size=26, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        add_text(s, x+Inches(1.3), y+Inches(0.4), bw-Inches(1.5), Inches(0.45),
                 ttl, size=18, bold=True, color=DARK_BLUE)
        add_text(s, x+Inches(0.4), y+Inches(1.25), bw-Inches(0.7), Inches(0.85),
                 desc, size=12, color=SLATE, line_spacing=1.4)
        # flecha (solo entre cards de la misma fila)
        if col < 2:
            arrow = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW,
                                       x + bw - Inches(0.03), y + Inches(0.95),
                                       Inches(0.25), Inches(0.3))
            arrow.fill.solid(); arrow.fill.fore_color.rgb = MUTED
            arrow.line.fill.background()
    add_footer(s, 4)

# ====================================================================
# SLIDE 5 — Página de inicio
# ====================================================================
def slide_inicio():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_title(s, "04", "La página de inicio")

    s.shapes.add_picture(f"{ASSETS}/01_acceso_home.jpeg",
                         Inches(6.5), Inches(1.6), width=Inches(6.6))

    add_text(s, Inches(0.6), Inches(1.6), Inches(5.7), Inches(0.5),
             "Una sola pantalla para todos.",
             size=18, bold=True, color=MEDICO_BLUE)

    add_bullets(s, Inches(0.6), Inches(2.2), Inches(5.7), Inches(4.5), [
        "Dos puertas claras: Portal Médico y Portal Paciente.",
        "Servicios visibles desde el inicio: turnos, recetas, historial y administración.",
        "Botón de modo claro / modo oscuro siempre disponible arriba a la derecha.",
        "Diseño pensado para que cualquier persona, sin experiencia técnica, sepa dónde pulsar.",
    ], size=14)

    add_footer(s, 5)

# ====================================================================
# SLIDE 6 — El paciente
# ====================================================================
def slide_paciente():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_title(s, "05", "Lo que ve el paciente")

    s.shapes.add_picture(f"{ASSETS}/05_paciente_recetas.jpeg",
                         Inches(7.5), Inches(1.55), width=Inches(5.6))

    add_text(s, Inches(0.6), Inches(1.6), Inches(6.7), Inches(0.5),
             "Su salud, organizada en su cuenta personal.",
             size=18, bold=True, color=MEDICO_BLUE)

    add_bullets(s, Inches(0.6), Inches(2.2), Inches(6.7), Inches(4.5), [
        "Foto de perfil y datos personales editables.",
        "Lista de turnos pedidos, con su estado actual.",
        "Sección «Mis Recetas» con todas las prescripciones recibidas.",
        "Cada receta tiene un botón verde para descargarla en PDF.",
        "Notificación automática cuando un médico le emite una nueva receta.",
    ], size=14)

    add_footer(s, 6)

# ====================================================================
# SLIDE 7 — El médico
# ====================================================================
def slide_medico():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_title(s, "06", "Lo que ve el médico")

    s.shapes.add_picture(f"{ASSETS}/03_medico_panel.jpeg",
                         Inches(7), Inches(1.55), width=Inches(6.1))

    add_text(s, Inches(0.6), Inches(1.6), Inches(6.2), Inches(0.5),
             "Su consulta digital con todo a mano.",
             size=18, bold=True, color=MEDICO_BLUE)

    add_bullets(s, Inches(0.6), Inches(2.2), Inches(6.2), Inches(4.5), [
        "Su nota media de pacientes, en grande.",
        "Lista de pacientes en espera, ordenados por orden de llegada.",
        "Acceso al historial y documentos del paciente actual.",
        "Botón para llamar al siguiente paciente con un solo clic.",
        "Modo offline para indicar que está en descanso.",
    ], size=14)

    add_footer(s, 7)

# ====================================================================
# SLIDE 8 — La receta firmada (feature destacada)
# ====================================================================
def slide_receta():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_title(s, "07", "La receta firmada con el ratón")

    s.shapes.add_picture(f"{ASSETS}/04_medico_firma_modal.jpeg",
                         Inches(0.6), Inches(1.55), width=Inches(6.7))

    add_text(s, Inches(7.6), Inches(1.6), Inches(5.4), Inches(0.5),
             "Una firma de verdad, sin papel.",
             size=18, bold=True, color=MEDICO_BLUE)

    pasos = [
        ("1", "El médico rellena medicamento, dosis y duración."),
        ("2", "Firma con el ratón o el trackpad sobre el recuadro blanco."),
        ("3", "Confirma con su contraseña para validar la prescripción."),
        ("4", "El paciente recibe un aviso al instante."),
        ("5", "Cualquiera de los dos puede descargar el PDF cuando quiera."),
    ]
    for i,(n, txt) in enumerate(pasos):
        yy = Inches(2.25) + Inches(0.78)*i
        add_rect(s, Inches(7.6), yy, Inches(5.4), Inches(0.65), fill=PRIMARY_BG, radius=True)
        circ = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(7.7), yy+Inches(0.12), Inches(0.42), Inches(0.42))
        circ.fill.solid(); circ.fill.fore_color.rgb = TEAL; circ.line.fill.background()
        add_text(s, Inches(7.7), yy+Inches(0.18), Inches(0.42), Inches(0.3),
                 n, size=13, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        add_text(s, Inches(8.3), yy+Inches(0.18), Inches(4.95), Inches(0.4),
                 txt, size=12, color=SLATE)

    add_footer(s, 8)

# ====================================================================
# SLIDE 9 — El administrador + modo claro/oscuro
# ====================================================================
def slide_admin():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_title(s, "08", "Administración y modo claro / oscuro")

    s.shapes.add_picture(f"{ASSETS}/06_admin_light.jpeg",
                         Inches(0.6), Inches(1.65), width=Inches(6.1))
    s.shapes.add_picture(f"{ASSETS}/07_admin_dark.jpeg",
                         Inches(6.85), Inches(1.65), width=Inches(6.1))

    add_pill(s, Inches(0.6), Inches(5.05), "🌞  Modo claro", MEDICO_BLUE, w=Inches(1.8))
    add_pill(s, Inches(6.85), Inches(5.05), "🌙  Modo oscuro", DARK_BLUE, w=Inches(1.8))

    add_bullets(s, Inches(0.6), Inches(5.7), Inches(12.1), Inches(1.5), [
        "Vista clara de todos los usuarios, con su rol y estado.",
        "El administrador puede editar, dar de baja o aprobar especialidades.",
        "El mismo panel se adapta al estilo visual preferido (claro u oscuro).",
    ], size=13)

    add_footer(s, 9)

# ====================================================================
# SLIDE 10 — Lo que destaca
# ====================================================================
def slide_destaca():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_title(s, "09", "Lo que destaca de Turnix")

    items = [
        ("⚡", "En tiempo real",
         "Los turnos avanzan solos, el chat es instantáneo y las recetas aparecen sin recargar."),
        ("🖱", "Firma con el ratón",
         "Sin escáner, sin papel: el médico firma con el ratón y la firma queda dentro del PDF."),
        ("📱", "Funciona en todo",
         "Móvil, tablet u ordenador. Solo necesitas un navegador moderno y conexión."),
        ("🌗", "Claro u oscuro",
         "Cada usuario elige el tema visual que más le guste y se recuerda automáticamente."),
        ("🔐", "Acciones protegidas",
         "Las acciones importantes (firmar receta, dar de baja un usuario) piden confirmación con contraseña."),
        ("📧", "Avisos por email",
         "Verificación de cuenta y recuperación de contraseña se hacen por correo."),
    ]
    bx = Inches(0.6); by = Inches(1.6); bw = Inches(3.95); bh = Inches(2.55)
    for i,(ic, ttl, desc) in enumerate(items):
        col = i % 3; row = i // 3
        x = bx + (bw + Inches(0.2))*col
        y = by + (bh + Inches(0.2))*row
        add_rect(s, x, y, bw, bh, fill=PRIMARY_BG, radius=True)
        add_text(s, x+Inches(0.3), y+Inches(0.25), Inches(0.7), Inches(0.6),
                 ic, size=28, color=TEAL)
        add_text(s, x+Inches(1.1), y+Inches(0.32), bw-Inches(1.3), Inches(0.5),
                 ttl, size=16, bold=True, color=DARK_BLUE)
        add_text(s, x+Inches(0.35), y+Inches(1.1), bw-Inches(0.7), bh-Inches(1.2),
                 desc, size=12, color=SLATE, line_spacing=1.4)

    add_footer(s, 10)

# ====================================================================
# SLIDE 11 — Demo en vivo
# ====================================================================
def slide_demo():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, DARK_BLUE)
    add_text(s, Inches(0.6), Inches(0.5), Inches(12), Inches(0.8),
             "10 · Demo en vivo", size=32, bold=True, color=WHITE)
    add_rect(s, Inches(0.6), Inches(1.4), Inches(1.5), Inches(0.05), fill=GREEN)
    add_text(s, Inches(0.6), Inches(1.6), Inches(12), Inches(0.5),
             "El recorrido completo en cuatro minutos",
             size=16, color=RGBColor(0x9C, 0xAF, 0xC0))

    steps = [
        ("00:00", "Entro como paciente",   "Abro la web, inicio sesión y pido un turno.",                     MEDICO_BLUE),
        ("00:45", "Cambio al médico",      "En otra pestaña entro como médico y veo al paciente en espera.",  TEAL),
        ("01:30", "Chateamos",             "Atiendo al paciente: chat en directo entre las dos pestañas.",    ACCENT_AMB),
        ("02:00", "Genero la receta",      "Relleno el medicamento y firmo con el ratón. Confirmo.",          GREEN),
        ("02:45", "El paciente la recibe", "Salta el aviso, voy a Mis Recetas y descargo el PDF.",            RGBColor(0x6D,0x28,0xD9)),
        ("03:30", "Modo administrador",    "Como admin, muestro la gestión de usuarios y cambio de tema.",    RGBColor(0x10,0xB9,0x81)),
    ]
    x = Inches(0.6); y = Inches(2.3); w = Inches(12.1); h = Inches(0.7)
    for i,(t, tag, desc, c) in enumerate(steps):
        yy = y + (h + Inches(0.08))*i
        add_rect(s, x, yy, w, h, fill=RGBColor(0x1E,0x29,0x3B), radius=True)
        add_text(s, x+Inches(0.25), yy+Inches(0.22), Inches(1.1), Inches(0.4),
                 t, size=14, bold=True, color=RGBColor(0x67,0xE8,0xF9), font="Consolas")
        add_pill(s, x+Inches(1.5), yy+Inches(0.16), tag, c, w=Inches(2.2), h=Inches(0.4), size=12)
        add_text(s, x+Inches(3.95), yy+Inches(0.22), Inches(8), Inches(0.4),
                 desc, size=13, color=WHITE)

    add_text(s, Inches(0.6), Inches(7.05), Inches(12), Inches(0.4),
             "Turnix Salud  ·  Rodrigo García",
             size=10, color=RGBColor(0x64,0x74,0x8B))
    add_text(s, Inches(11.5), Inches(7.05), Inches(1.5), Inches(0.4),
             f"11 / {TOTAL}", size=10, color=RGBColor(0x64,0x74,0x8B), align=PP_ALIGN.RIGHT)

# ====================================================================
# SLIDE 12 — Próximos pasos
# ====================================================================
def slide_futuro():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, WHITE)
    add_title(s, "11", "Próximos pasos")

    add_text(s, Inches(0.6), Inches(1.55), Inches(12), Inches(0.5),
             "Hasta dónde puede llegar Turnix en el futuro",
             size=15, color=MEDICO_BLUE)

    ideas = [
        ("📹", "Videollamada",     "Pasar del chat de texto a la videoconsulta directa."),
        ("🔔", "Avisos al móvil",  "Notificaciones nativas cuando es tu turno o llega una receta."),
        ("🏥", "Multi-clínica",    "Que cada centro de salud tenga su propio espacio dentro de Turnix."),
        ("📅", "Calendario",       "Agendar turnos con día y hora, no solo lista de espera."),
        ("🤖", "Pre-triaje",       "Un asistente que pregunte síntomas antes de pasar con el médico."),
        ("📊", "Estadísticas",     "Panel con tiempos de espera medios, valoraciones y consultas atendidas."),
    ]
    bx = Inches(0.6); by = Inches(2.15); bw = Inches(3.95); bh = Inches(2.3)
    for i,(ic, ttl, desc) in enumerate(ideas):
        col = i % 3; row = i // 3
        x = bx + (bw + Inches(0.2))*col
        y = by + (bh + Inches(0.18))*row
        add_rect(s, x, y, bw, bh, fill=PRIMARY_BG, radius=True)
        add_text(s, x+Inches(0.3), y+Inches(0.3), Inches(0.7), Inches(0.5),
                 ic, size=24, color=GREEN)
        add_text(s, x+Inches(1.1), y+Inches(0.35), bw-Inches(1.3), Inches(0.4),
                 ttl, size=16, bold=True, color=DARK_BLUE)
        add_text(s, x+Inches(0.35), y+Inches(1.05), bw-Inches(0.7), bh-Inches(1.2),
                 desc, size=12, color=SLATE, line_spacing=1.4)

    add_footer(s, 12)

# ====================================================================
# SLIDE 13 — Gracias
# ====================================================================
def slide_gracias():
    s = prs.slides.add_slide(BLANK)
    add_solid_bg(s, DARK_BLUE)
    add_rect(s, 0, Inches(2.2), prs.slide_width, Inches(0.05), fill=TEAL)
    add_rect(s, 0, Inches(5.2), prs.slide_width, Inches(0.05), fill=GREEN)

    add_text(s, Inches(0.6), Inches(2.7), Inches(12), Inches(1.5),
             "Gracias", size=90, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    add_text(s, Inches(0.6), Inches(4.3), Inches(12), Inches(0.5),
             "¿Alguna pregunta?",
             size=22, color=RGBColor(0x9C, 0xAF, 0xC0), align=PP_ALIGN.CENTER)
    add_text(s, Inches(0.6), Inches(6.3), Inches(12), Inches(0.4),
             "Turnix Salud  ·  Rodrigo García  ·  2026",
             size=14, color=RGBColor(0x67, 0xE8, 0xF9), align=PP_ALIGN.CENTER)

# ===== Build =====
slide_portada()
slide_que_es()
slide_perfiles()
slide_flujo()
slide_inicio()
slide_paciente()
slide_medico()
slide_receta()
slide_admin()
slide_destaca()
slide_demo()
slide_futuro()
slide_gracias()

out = "/app/presentation_assets/Turnix_Presentacion.pptx"
prs.save(out)
print("Guardado:", out, "·", os.path.getsize(out), "bytes ·", len(prs.slides), "slides")
