/*
 * Visite guidée interactive de L'Agora (2026-11-18).
 *
 * Étapes fournies par templates/_tour.html (JSON #agora-tour-data), selon le
 * rôle. Chaque étape vit sur une page (portal / validation / dashboard) : si
 * l'étape courante n'est pas sur la page affichée, on y navigue (simple GET)
 * et la visite reprend grâce à sessionStorage.
 *
 * Aucune manipulation réelle n'est possible pendant la visite : un voile plein
 * écran intercepte tous les clics, la molette et le clavier (sauf dans la
 * bulle). L'élément montré est seulement éclairé, jamais cliquable.
 *
 * Fin ou abandon : POST doneUrl (la visite ne se relance plus d'elle-même).
 * Relance : tout élément [data-tour-start], ou window.AgoraTour.start().
 */
(function () {
    'use strict';
    var dataEl = document.getElementById('agora-tour-data');
    if (!dataEl) return;
    var cfg;
    try { cfg = JSON.parse(dataEl.textContent); } catch (e) { return; }
    if (!cfg || !cfg.stepsUrl) return;

    var KEY = 'agoraTour';
    var steps = null, loading = null;

    // Étapes chargées à la demande (seulement si la visite doit s'afficher).
    function loadSteps() {
        if (steps) return Promise.resolve(steps);
        if (!loading) {
            loading = fetch(cfg.stepsUrl, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
                .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
                .then(function (data) { steps = Array.isArray(data) ? data : []; return steps; })
                .catch(function () { loading = null; steps = null; return []; });
        }
        return loading;
    }
    var root, hole, pop, current = -1, target = null, lastFocus = null;

    function readState() { try { return JSON.parse(sessionStorage.getItem(KEY)); } catch (e) { return null; } }
    function writeState(s) {
        try { if (s) sessionStorage.setItem(KEY, JSON.stringify(s)); else sessionStorage.removeItem(KEY); } catch (e) { /* stockage indisponible : la visite reste sur la page */ }
    }
    function norm(p) { return (p || '').replace(/\/+$/, ''); }
    function samePage(url) {
        try { return norm(new URL(url, location.href).pathname) === norm(location.pathname); } catch (e) { return false; }
    }
    // page 'any' : étape visible sur n'importe quelle page (menu, en-tête) -> pas de navigation.
    function pageUrl(step) { return step.page === 'any' ? location.href : (cfg.pages[step.page] || cfg.pages.portal); }

    /* ---------- Styles (classes propres, indépendantes des thèmes) ---------- */
    function injectStyles() {
        if (document.getElementById('agt-style')) return;
        var css =
            '.agt-root{position:fixed;inset:0;z-index:2147483000;font-family:inherit}' +
            '.agt-block{position:fixed;inset:0;background:transparent;cursor:default}' +
            '.agt-root.agt-center .agt-block{background:rgba(15,23,42,.62)}' +
            '.agt-hole{position:fixed;border-radius:6px;box-shadow:0 0 0 9999px rgba(15,23,42,.62);outline:3px solid rgb(var(--accent-400,45 212 191));outline-offset:2px;pointer-events:none;transition:all .25s ease}' +
            '.agt-root.agt-center .agt-hole{display:none}' +
            '.agt-pop{position:fixed;width:min(380px,calc(100vw - 32px));background:#fff;color:#1e293b;border:1px solid #e2e8f0;box-shadow:0 20px 50px rgba(0,0,0,.35);padding:20px;border-radius:10px;transition:top .25s ease,left .25s ease}' +
            '.dark .agt-pop{background:#0f172a;color:#e2e8f0;border-color:#334155}' +
            '.agt-pop.agt-wide{width:min(560px,calc(100vw - 32px))}' +
            '.agt-step{font-size:10px;font-weight:900;letter-spacing:.12em;text-transform:uppercase;color:rgb(var(--accent-600,13 148 136))}' +
            '.dark .agt-step{color:rgb(var(--accent-400,45 212 191))}' +
            '.agt-bar{height:3px;background:#e2e8f0;margin:8px 0 12px;border-radius:2px;overflow:hidden}.dark .agt-bar{background:#334155}' +
            '.agt-bar>span{display:block;height:100%;background:rgb(var(--accent-500,20 184 166));transition:width .25s ease}' +
            '.agt-title{font-size:17px;font-weight:900;margin:0 0 6px}' +
            '.agt-text{font-size:14px;line-height:1.55;margin:0}.agt-text strong{font-weight:800}' +
            '.agt-img{display:block;width:100%;margin-top:12px;border:1px solid #e2e8f0;border-radius:6px}.dark .agt-img{border-color:#334155}' +
            '.agt-actions{display:flex;align-items:center;gap:8px;margin-top:16px}' +
            '.agt-btn{font:inherit;font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.06em;padding:9px 14px;border-radius:6px;border:1px solid transparent;cursor:pointer}' +
            '.agt-skip{background:transparent;color:#64748b;padding-left:0;margin-right:auto;text-transform:none;letter-spacing:0;font-weight:700}.agt-skip:hover{color:#0f172a;text-decoration:underline}.dark .agt-skip:hover{color:#fff}' +
            '.agt-prev{background:transparent;border-color:#cbd5e1;color:#334155}.dark .agt-prev{border-color:#475569;color:#e2e8f0}' +
            '.agt-next{background:rgb(var(--accent-600,13 148 136));color:#fff}.agt-next:hover{filter:brightness(1.1)}' +
            '.agt-btn:focus-visible{outline:3px solid rgb(var(--accent-400,45 212 191));outline-offset:2px}' +
            '@media (max-width:639px){.agt-pop,.agt-pop.agt-wide{left:12px!important;right:12px;width:auto;top:auto!important;bottom:12px}}' +
            '@media (prefers-reduced-motion:reduce){.agt-hole,.agt-pop,.agt-bar>span{transition:none}}';
        var st = document.createElement('style');
        st.id = 'agt-style';
        st.textContent = css;
        document.head.appendChild(st);
    }

    /* ---------- Construction du voile ---------- */
    function build() {
        if (root) return;
        injectStyles();
        root = document.createElement('div');
        root.className = 'agt-root';
        root.innerHTML =
            '<div class="agt-block"></div>' +
            '<div class="agt-hole" aria-hidden="true"></div>' +
            '<div class="agt-pop" role="dialog" aria-modal="true" aria-labelledby="agt-title" aria-describedby="agt-text">' +
            '  <div class="agt-step"></div><div class="agt-bar"><span></span></div>' +
            '  <h2 class="agt-title" id="agt-title"></h2>' +
            '  <p class="agt-text" id="agt-text"></p>' +
            '  <img class="agt-img" alt="" hidden>' +
            '  <div class="agt-actions">' +
            '    <button type="button" class="agt-btn agt-skip">Passer la visite</button>' +
            '    <button type="button" class="agt-btn agt-prev">Précédent</button>' +
            '    <button type="button" class="agt-btn agt-next">Suivant</button>' +
            '  </div>' +
            '</div>';
        document.body.appendChild(root);
        hole = root.querySelector('.agt-hole');
        pop = root.querySelector('.agt-pop');
        root.querySelector('.agt-skip').addEventListener('click', function () { finish(); });
        root.querySelector('.agt-prev').addEventListener('click', function () { go(current - 1); });
        root.querySelector('.agt-next').addEventListener('click', function () { go(current + 1); });
        // Le voile absorbe tout : clics, double-clics, molette, tactile.
        ['click', 'mousedown', 'dblclick', 'contextmenu', 'wheel', 'touchstart', 'touchmove'].forEach(function (ev) {
            root.querySelector('.agt-block').addEventListener(ev, function (e) { e.preventDefault(); e.stopPropagation(); }, { passive: false });
        });
        document.addEventListener('keydown', onKey, true);
        window.addEventListener('resize', place);
        lastFocus = document.activeElement;
    }

    function teardown() {
        if (!root) return;
        document.removeEventListener('keydown', onKey, true);
        window.removeEventListener('resize', place);
        root.remove();
        root = hole = pop = null;
        target = null;
        current = -1;
        if (lastFocus && lastFocus.focus) { try { lastFocus.focus(); } catch (e) { /* élément disparu */ } }
    }

    /* ---------- Clavier : seule la bulle est utilisable ---------- */
    function onKey(e) {
        if (!root) return;
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); finish(); return; }
        var inPop = pop.contains(e.target);
        if (e.key === 'ArrowRight' && !e.altKey) { e.preventDefault(); e.stopPropagation(); go(current + 1); return; }
        if (e.key === 'ArrowLeft' && !e.altKey) { e.preventDefault(); e.stopPropagation(); if (current > 0) go(current - 1); return; }
        if (e.key === 'Tab') {
            var f = Array.prototype.filter.call(pop.querySelectorAll('button'), function (b) { return !b.hidden; });
            if (!f.length) return;
            var i = f.indexOf(document.activeElement);
            e.preventDefault();
            e.stopPropagation();
            var n = e.shiftKey ? (i <= 0 ? f.length - 1 : i - 1) : (i === -1 || i === f.length - 1 ? 0 : i + 1);
            f[n].focus();
            return;
        }
        if (!inPop) { e.preventDefault(); e.stopPropagation(); }
    }

    /* ---------- Cible d'une étape ---------- */
    function visible(el) {
        if (!el) return false;
        var r = el.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) return false;
        if (r.right <= 0 || r.left >= window.innerWidth) return false;   // menu mobile hors écran
        var cs = getComputedStyle(el);
        return cs.visibility !== 'hidden' && cs.display !== 'none';
    }
    function findTarget(step) {
        var sels = [];
        if (step.sel) sels = sels.concat(step.sel.split(',').map(function (s) { return s.trim(); }));
        if (step.mobile) sels.push(step.mobile);
        for (var i = 0; i < sels.length; i++) {
            var el = null;
            try { el = document.querySelector(sels[i]); } catch (e) { el = null; }
            if (el) {
                // Élément très haut (ex. barre latérale entière) : on le garde tel quel.
                if (!visible(el)) { try { el.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) { /* ancien navigateur */ } }
                if (visible(el)) return el;
            }
        }
        return null;
    }

    /* ---------- Affichage ---------- */
    function render(i) {
        var step = steps[i];
        build();
        current = i;
        writeState({ i: i });
        target = step.sel || step.mobile ? findTarget(step) : null;
        var missing = (step.sel && !target);
        root.classList.toggle('agt-center', !target);
        pop.classList.toggle('agt-wide', !!step.img && !target);

        root.querySelector('.agt-step').textContent = 'Étape ' + (i + 1) + ' sur ' + steps.length;
        root.querySelector('.agt-bar > span').style.width = Math.round(((i + 1) / steps.length) * 100) + '%';
        root.querySelector('.agt-title').textContent = step.title || '';
        root.querySelector('.agt-text').innerHTML = (missing && step.missing) ? step.missing : (step.text || '');
        var img = root.querySelector('.agt-img');
        if (step.img) { img.src = step.img; img.hidden = false; img.onload = place; } else { img.hidden = true; img.removeAttribute('src'); }
        root.querySelector('.agt-prev').hidden = i === 0;
        var next = root.querySelector('.agt-next');
        next.textContent = i === steps.length - 1 ? 'Terminer' : 'Suivant';

        if (target) {
            try { target.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) { /* ancien navigateur */ }
        }
        place();
        setTimeout(place, 60);   // après défilement / chargement des polices
        next.focus({ preventScroll: true });
    }

    function place() {
        if (!root || !pop) return;
        var vw = window.innerWidth, vh = window.innerHeight, m = 12;
        var pw = pop.offsetWidth, ph = pop.offsetHeight;
        if (!target || !visible(target)) {
            root.classList.add('agt-center');
            pop.style.left = Math.max(m, (vw - pw) / 2) + 'px';
            pop.style.top = Math.max(m, (vh - ph) / 2) + 'px';
            return;
        }
        root.classList.remove('agt-center');
        var r = target.getBoundingClientRect(), pad = 6;
        var top = Math.max(4, r.top - pad), left = Math.max(4, r.left - pad);
        var bottom = Math.min(vh - 4, r.bottom + pad), right = Math.min(vw - 4, r.right + pad);
        hole.style.top = top + 'px';
        hole.style.left = left + 'px';
        hole.style.width = Math.max(0, right - left) + 'px';
        hole.style.height = Math.max(0, bottom - top) + 'px';

        // Bulle : à droite d'un élément étroit et haut (menu), sinon dessous, sinon dessus.
        var x, y;
        if (r.height > vh * 0.5 && right + m + pw <= vw) { x = right + m; y = Math.min(Math.max(m, r.top), vh - ph - m); }
        else if (bottom + m + ph <= vh) { y = bottom + m; x = r.left; }
        else if (top - m - ph >= 0) { y = top - m - ph; x = r.left; }
        else if (right + m + pw <= vw) { x = right + m; y = Math.min(Math.max(m, r.top), vh - ph - m); }
        else { x = (vw - pw) / 2; y = vh - ph - m; }
        pop.style.left = Math.min(Math.max(m, x), vw - pw - m) + 'px';
        pop.style.top = Math.min(Math.max(m, y), vh - ph - m) + 'px';
    }

    /* ---------- Navigation entre étapes ---------- */
    function go(i) {
        if (i < 0) return;
        if (i >= steps.length) { finish(); return; }
        var step = steps[i];
        if (!samePage(pageUrl(step))) {
            writeState({ i: i });
            location.assign(pageUrl(step));
            return;
        }
        render(i);
    }

    function finish() {
        writeState(null);
        try {
            fetch(cfg.doneUrl, { method: 'POST', credentials: 'same-origin', keepalive: true,
                                 headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        } catch (e) { /* hors ligne : la visite se relancera, sans gravité */ }
        teardown();
    }

    function start() {
        if (root) teardown();
        loadSteps().then(function (s) { if (s.length) go(0); });
    }

    window.AgoraTour = { start: start };

    document.addEventListener('click', function (e) {
        var b = e.target.closest && e.target.closest('[data-tour-start]');
        if (b) { e.preventDefault(); start(); }
    });

    function boot() {
        var st = readState();
        if (st && typeof st.i === 'number') {
            loadSteps().then(function (s) {
                if (s[st.i] && samePage(pageUrl(s[st.i]))) render(st.i);
                else writeState(null);   // l'utilisateur est parti ailleurs : on n'insiste pas
            });
            return;
        }
        if (cfg.autostart && samePage(cfg.pages.portal)) start();
    }
    if (document.readyState === 'complete') setTimeout(boot, 300);
    else window.addEventListener('load', function () { setTimeout(boot, 300); });
})();
