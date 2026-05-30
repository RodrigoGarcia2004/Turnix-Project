/* ============================================================
   Turnix - Logica compartida: splash + dark mode + modal video
   ============================================================ */
(function () {
    // ---------- SPLASH ----------
    function ensureSplash() {
        if (document.getElementById('turnix-splash')) return;
        const wrap = document.createElement('div');
        wrap.id = 'turnix-splash';
        wrap.innerHTML = `
            <div class="splash-inner">
                <div class="logo-orbit">
                    <img src="turnix-logo.png" alt="Turnix">
                </div>
                <div class="splash-text">Turnix · Salud</div>
            </div>`;
        document.documentElement.appendChild(wrap);
    }
    ensureSplash();

    function hideSplash() {
        const s = document.getElementById('turnix-splash');
        if (s) {
            s.classList.add('hide');
            setTimeout(() => s.remove(), 600);
        }
    }
    window.addEventListener('load', () => setTimeout(hideSplash, 650));

    // ---------- DARK MODE ----------
    const THEME_KEY = 'turnix-theme';

    function applyStoredTheme() {
        const saved = localStorage.getItem(THEME_KEY);
        if (saved === 'dark') document.body.classList.add('dark');
    }

    function ensureDarkUI() {
        if (document.getElementById('turnix-dark-toggle')) return;
        const btn = document.createElement('button');
        btn.id = 'turnix-dark-toggle';
        btn.className = 'turnix-dark-toggle';
        btn.title = 'Cambiar tema';
        btn.setAttribute('aria-label', 'Cambiar tema claro/oscuro');
        btn.textContent = document.body.classList.contains('dark') ? '☀️' : '🌙';

        const overlay = document.createElement('div');
        overlay.id = 'turnix-theme-overlay';
        overlay.innerHTML = '<div class="ov-stage"><img src="turnix-logo.png" alt=""></div>';

        document.body.appendChild(btn);
        document.body.appendChild(overlay);

        btn.addEventListener('click', () => toggleTheme(btn, overlay));
    }

    // ---------- "Volver al inicio" flotante (todas las paginas menos index) ----------
    function ensureHomeBtn() {
        if (document.getElementById('turnix-home-btn')) return;
        const path = (location.pathname || '').toLowerCase();
        // No mostrar en la home / index
        if (path === '/' || path.endsWith('/index.html') || path === '/index.html') return;
        // Evitar duplicado: si la pagina ya tiene un enlace propio "Volver al inicio",
        // lo respetamos.
        if (document.querySelector('.btn-volver, [data-back-home]')) return;
        const links = document.querySelectorAll('a');
        for (const a of links) {
            const t = (a.textContent || '').trim().toLowerCase();
            if (t.includes('volver al inicio') || t === '← inicio' ||
                t.includes('volver a turnix')) return;
        }
        const a = document.createElement('a');
        a.id = 'turnix-home-btn';
        a.className = 'turnix-home-btn';
        a.href = '/';
        a.setAttribute('data-testid', 'volver-al-inicio');
        a.innerHTML = '← Inicio';
        a.title = 'Volver al inicio';
        document.body.appendChild(a);
    }

    function toggleTheme(btn, overlay) {
        overlay.classList.add('show');
        setTimeout(() => {
            const goingDark = !document.body.classList.contains('dark');
            document.body.classList.toggle('dark', goingDark);
            localStorage.setItem(THEME_KEY, goingDark ? 'dark' : 'light');
            btn.textContent = goingDark ? '☀️' : '🌙';
            setTimeout(() => overlay.classList.remove('show'), 480);
        }, 550);
    }

    // Aplicar tema antes de cargar UI para evitar flash
    if (document.body) {
        applyStoredTheme();
        ensureDarkUI();
        ensureHomeBtn();
    } else {
        document.addEventListener('DOMContentLoaded', () => {
            applyStoredTheme();
            ensureDarkUI();
            ensureHomeBtn();
        });
    }

    // ---------- MODAL "Aceptar videollamada" ----------
    function ensureVideoModal() {
        if (document.getElementById('turnix-video-incoming')) return;
        const m = document.createElement('div');
        m.id = 'turnix-video-incoming';
        m.innerHTML = `
            <div class="vi-card">
                <div class="vi-icon">📹</div>
                <h3>Videollamada entrante</h3>
                <p id="turnix-vi-caller">El médico te está llamando para una videoconsulta</p>
                <div class="vi-buttons">
                    <button class="vi-reject" id="turnix-vi-reject">❌ Rechazar</button>
                    <button class="vi-accept" id="turnix-vi-accept">✅ Aceptar</button>
                </div>
            </div>`;
        document.body.appendChild(m);
    }

    /**
     * Muestra un modal "Videollamada entrante" en el paciente.
     * @param {string} caller - Nombre del médico
     * @param {Function} onAccept - callback cuando acepta
     * @param {Function} onReject - callback cuando rechaza
     */
    window.turnixShowIncomingCall = function (caller, onAccept, onReject) {
        ensureVideoModal();
        const m = document.getElementById('turnix-video-incoming');
        const caption = document.getElementById('turnix-vi-caller');
        if (caller) caption.textContent = `${caller} te está llamando a una videoconsulta`;
        m.classList.add('show');
        const accept = document.getElementById('turnix-vi-accept');
        const reject = document.getElementById('turnix-vi-reject');
        const close = () => { m.classList.remove('show'); accept.onclick = null; reject.onclick = null; };
        accept.onclick = () => { close(); if (onAccept) onAccept(); };
        reject.onclick = () => { close(); if (onReject) onReject(); };
    };

    window.turnixHideIncomingCall = function () {
        const m = document.getElementById('turnix-video-incoming');
        if (m) m.classList.remove('show');
    };

    // ---------- Helper: parser robusto de mensajes WS con 2 ":" ----------
    /**
     * Parse "KIND:target:payload..." donde payload puede contener ':'.
     * Devuelve { kind, target, payload }.
     */
    window.turnixSplit3 = function (data) {
        const i1 = data.indexOf(':');
        if (i1 < 0) return { kind: data, target: '', payload: '' };
        const i2 = data.indexOf(':', i1 + 1);
        if (i2 < 0) return { kind: data.slice(0, i1), target: data.slice(i1 + 1), payload: '' };
        return {
            kind: data.slice(0, i1),
            target: data.slice(i1 + 1, i2),
            payload: data.slice(i2 + 1),
        };
    };
})();
