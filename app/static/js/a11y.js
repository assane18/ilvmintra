/* =============================================================================
   Accessibilité clavier — Intranet ILVM (complément de css/a11y.css)
   -----------------------------------------------------------------------------
   Chargé en `defer` par base.html. Ne dépend d'aucun autre script : il observe
   le DOM (MutationObserver) au lieu de modifier le JS existant de base.html,
   afin de rester robuste face aux chantiers parallèles sur l'en-tête.

     1. Lien d'évitement : donne le focus à <main id="contenu">.
     2. Onglets ([role="tablist"]) : flèches ←/→, Début/Fin, roving tabindex.
     3. Menus / panneaux : aria-expanded synchronisé, fermeture par Échap et
        retour du focus sur le bouton déclencheur (notifications, panneau profil,
        menu latéral mobile), éléments de notification atteignables au clavier.
     4. Recherche globale : aria-controls/aria-expanded sur le champ, aria-live
        sur la liste, navigation ↓/↑ dans les résultats, Échap referme.
     5. prefers-reduced-motion : marqueur sur <html>, arrêt du canvas de fond.
   ============================================================================= */
(function () {
    'use strict';

    function $(sel, root) { return (root || document).querySelector(sel); }
    function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
    function observeClass(el, cb) {
        if (!el || !window.MutationObserver) return;
        new MutationObserver(cb).observe(el, { attributes: true, attributeFilter: ['class', 'style'] });
        cb();
    }
    function focusSafely(el) { if (el && typeof el.focus === 'function') { try { el.focus(); } catch (e) {} } }

    // Liste des fermetures « Échap » actives ; la plus récente (dernier menu
    // ouvert) est traitée en premier.
    var escapeHandlers = [];
    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape' && e.key !== 'Esc') return;
        for (var i = escapeHandlers.length - 1; i >= 0; i--) {
            if (escapeHandlers[i]()) { e.preventDefault(); return; }
        }
    });

    /* --- 1. Lien d'évitement ------------------------------------------------ */
    function initSkipLink() {
        var link = $('.a11y-skip-link');
        var main = $('#contenu');
        if (!link || !main) return;
        if (!main.hasAttribute('tabindex')) main.setAttribute('tabindex', '-1');
        link.addEventListener('click', function (e) {
            e.preventDefault();
            focusSafely(main);
            main.scrollIntoView({ block: 'start' });
        });
    }

    /* --- 2. Onglets --------------------------------------------------------- */
    function initTablists() {
        $$('[role="tablist"]').forEach(function (list) {
            var tabs = $$('[role="tab"]', list);
            if (!tabs.length) return;
            if (!list.hasAttribute('aria-orientation')) list.setAttribute('aria-orientation', 'horizontal');
            // Roving tabindex : seul l'onglet actif est dans l'ordre de tabulation.
            function sync() {
                var anySelected = tabs.some(function (t) { return t.getAttribute('aria-selected') === 'true'; });
                tabs.forEach(function (t, i) {
                    var selected = t.getAttribute('aria-selected') === 'true' || (!anySelected && i === 0);
                    t.setAttribute('tabindex', selected ? '0' : '-1');
                });
            }
            tabs.forEach(function (t) {
                if (window.MutationObserver) {
                    new MutationObserver(sync).observe(t, { attributes: true, attributeFilter: ['aria-selected'] });
                }
            });
            sync();
            list.addEventListener('keydown', function (e) {
                var idx = tabs.indexOf(document.activeElement);
                if (idx === -1) return;
                var next = null;
                switch (e.key) {
                    case 'ArrowRight': case 'ArrowDown': next = tabs[(idx + 1) % tabs.length]; break;
                    case 'ArrowLeft': case 'ArrowUp': next = tabs[(idx - 1 + tabs.length) % tabs.length]; break;
                    case 'Home': next = tabs[0]; break;
                    case 'End': next = tabs[tabs.length - 1]; break;
                    default: return;
                }
                e.preventDefault();
                next.click();          // active l'onglet (Alpine met à jour aria-selected)
                focusSafely(next);
            });
        });
    }

    /* --- 3. Menus et panneaux ----------------------------------------------- */
    // Notifications : bouton onclick="toggleNotifs()" + #notif-dropdown (classe hidden).
    function initNotifications() {
        var dropdown = $('#notif-dropdown');
        var container = $('#notif-container');
        if (!dropdown || !container) return;
        var trigger = $('button[onclick*="toggleNotifs"]', container) || $('button', container);
        var list = $('#notif-list');
        if (trigger) {
            trigger.setAttribute('aria-controls', 'notif-dropdown');
            trigger.setAttribute('aria-haspopup', 'true');
            if (!trigger.hasAttribute('aria-label')) trigger.setAttribute('aria-label', 'Notifications');
        }
        if (list) {
            if (!list.hasAttribute('aria-live')) list.setAttribute('aria-live', 'polite');
            list.setAttribute('aria-relevant', 'additions text');
        }
        function isOpen() { return !dropdown.classList.contains('hidden'); }
        observeClass(dropdown, function () {
            if (trigger) trigger.setAttribute('aria-expanded', isOpen() ? 'true' : 'false');
        });
        escapeHandlers.push(function () {
            if (!isOpen()) return false;
            dropdown.classList.add('hidden');
            focusSafely(trigger);
            return true;
        });
        // Les notifications injectées sont des <div onclick> : on les rend
        // atteignables et activables au clavier (Entrée / Espace).
        if (list && window.MutationObserver) {
            var makeFocusable = function () {
                $$(':scope > div', list).forEach(function (item) {
                    if (!item.onclick || item.hasAttribute('tabindex')) return;
                    item.setAttribute('tabindex', '0');
                    item.setAttribute('role', 'button');
                    item.addEventListener('keydown', function (e) {
                        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); item.click(); }
                    });
                });
            };
            new MutationObserver(makeFocusable).observe(list, { childList: true });
            makeFocusable();
        }
    }

    // Panneau profil (layout sidebar) : #profile-trigger ouvre #profile-panel
    // (classe translate-x-full quand fermé) + #profile-overlay.
    function initProfilePanel() {
        var trigger = $('#profile-trigger');
        var panel = $('#profile-panel');
        var overlay = $('#profile-overlay');
        var closeBtn = $('#profile-close');
        if (!trigger || !panel) return;
        trigger.setAttribute('aria-controls', 'profile-panel');
        trigger.setAttribute('aria-haspopup', 'dialog');
        if (!panel.hasAttribute('role')) panel.setAttribute('role', 'dialog');
        if (!panel.hasAttribute('aria-modal')) panel.setAttribute('aria-modal', 'true');
        if (!panel.hasAttribute('aria-label') && !panel.hasAttribute('aria-labelledby')) panel.setAttribute('aria-label', 'Mon profil');
        function isOpen() { return !panel.classList.contains('translate-x-full'); }
        var wasOpen = isOpen();
        observeClass(panel, function () {
            var open = isOpen();
            trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
            panel.setAttribute('aria-hidden', open ? 'false' : 'true');
            if (open && !wasOpen) {
                // Le panneau glisse (200 ms) : on attend la fin pour focaliser.
                setTimeout(function () { focusSafely(closeBtn || panel); }, 220);
            } else if (!open && wasOpen) {
                focusSafely(trigger);
            }
            wasOpen = open;
        });
        escapeHandlers.push(function () {
            if (!isOpen()) return false;
            panel.classList.add('translate-x-full');
            if (overlay) overlay.classList.add('hidden');
            return true;
        });
    }

    // Menu latéral mobile (layout sidebar).
    function initSidebar() {
        var sidebar = $('#app-sidebar');
        var overlay = $('#sidebar-overlay');
        var toggle = $('#sidebar-mobile-toggle');
        if (!sidebar || !overlay) return;
        if (toggle) toggle.setAttribute('aria-controls', 'app-sidebar');
        function isOpenMobile() { return !sidebar.classList.contains('-translate-x-full') && window.innerWidth < 768; }
        observeClass(sidebar, function () {
            if (toggle) toggle.setAttribute('aria-expanded', isOpenMobile() ? 'true' : 'false');
        });
        escapeHandlers.push(function () {
            if (!isOpenMobile()) return false;
            sidebar.classList.add('-translate-x-full');
            overlay.classList.add('hidden');
            focusSafely(toggle);
            return true;
        });
    }

    // Menu mobile du layout navbar (#mobile-menu-toggle gère déjà aria-expanded).
    function initMobileMenu() {
        var toggle = $('#mobile-menu-toggle');
        var menu = $('#mobile-menu');
        if (!toggle || !menu) return;
        toggle.setAttribute('aria-controls', 'mobile-menu');
        escapeHandlers.push(function () {
            if (menu.classList.contains('hidden')) return false;
            toggle.click();
            focusSafely(toggle);
            return true;
        });
    }

    /* --- 4. Recherche globale ----------------------------------------------- */
    function initGlobalSearch() {
        var input = $('#global-search-input');
        var box = $('#global-search-results');
        if (!input || !box) return;
        input.setAttribute('aria-controls', 'global-search-results');
        input.setAttribute('aria-autocomplete', 'list');
        input.setAttribute('aria-haspopup', 'true');
        if (!input.hasAttribute('aria-label')) input.setAttribute('aria-label', input.getAttribute('placeholder') || 'Rechercher');
        if (!box.hasAttribute('aria-live')) box.setAttribute('aria-live', 'polite');
        if (!box.hasAttribute('role')) box.setAttribute('role', 'region');
        if (!box.hasAttribute('aria-label')) box.setAttribute('aria-label', 'Résultats de recherche');
        function isOpen() { return !box.classList.contains('hidden'); }
        observeClass(box, function () { input.setAttribute('aria-expanded', isOpen() ? 'true' : 'false'); });
        function links() { return $$('a[href]', box); }
        input.addEventListener('keydown', function (e) {
            if (e.key === 'ArrowDown' && isOpen()) {
                var first = links()[0];
                if (first) { e.preventDefault(); focusSafely(first); }
            }
        });
        box.addEventListener('keydown', function (e) {
            var items = links();
            var idx = items.indexOf(document.activeElement);
            if (idx === -1) return;
            if (e.key === 'ArrowDown') { e.preventDefault(); focusSafely(items[Math.min(idx + 1, items.length - 1)]); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); if (idx === 0) focusSafely(input); else focusSafely(items[idx - 1]); }
            else if (e.key === 'Escape') { e.preventDefault(); box.classList.add('hidden'); focusSafely(input); }
        });
    }

    /* --- 5. Mouvement réduit ------------------------------------------------ */
    function initReducedMotion() {
        if (!window.matchMedia) return;
        var mq = window.matchMedia('(prefers-reduced-motion: reduce)');
        function apply() {
            var reduce = mq.matches;
            document.documentElement.setAttribute('data-reduced-motion', reduce ? 'true' : 'false');
            window.ILVM_REDUCED_MOTION = reduce;
            var canvas = $('#networkCanvas');
            if (canvas && reduce) {
                canvas.style.display = 'none';
                // Arrêt de la boucle d'animation si le script du fond expose son handle.
                ['networkAnimationFrame', 'networkAnimationId', 'animationFrameId'].forEach(function (k) {
                    if (window[k] && window.cancelAnimationFrame) { window.cancelAnimationFrame(window[k]); window[k] = null; }
                });
            } else if (canvas && !reduce) {
                canvas.style.display = '';
            }
        }
        apply();
        if (mq.addEventListener) mq.addEventListener('change', apply);
        else if (mq.addListener) mq.addListener(apply);
    }

    function init() {
        initSkipLink();
        initTablists();
        initNotifications();
        initProfilePanel();
        initSidebar();
        initMobileMenu();
        initGlobalSearch();
        initReducedMotion();
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
