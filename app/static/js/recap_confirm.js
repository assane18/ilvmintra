/*
 * Récapitulatif de confirmation avant soumission finale d'un formulaire de création.
 * S'active sur tout <form data-recap-confirm="Titre affiché"> présent sur la page :
 * intercepte le submit, affiche la liste des champs remplis (label -> valeur), et ne
 * soumet réellement le formulaire qu'après clic sur "Confirmer".
 *
 * Générique par construction (aucune connaissance des champs d'un formulaire précis) :
 * parcourt le DOM dans l'ordre, associe chaque contrôle visible au <label> qui le
 * précède, et regroupe les contrôles qui partagent un même `name` (cases à cocher
 * multiples, boutons radio).
 */
(function () {
    function isVisible(el) {
        return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
    }

    function collectFields(form) {
        var nodes = form.querySelectorAll('label, input, select, textarea');
        var currentCaption = '';
        var entries = []; // { name, caption, el, optionLabel }

        nodes.forEach(function (node) {
            var tag = node.tagName;
            if (tag === 'LABEL') {
                var wrappedControl = node.querySelector('input, select, textarea');
                if (!wrappedControl) {
                    currentCaption = node.textContent.replace(/\*/g, '').trim();
                } else {
                    // Label qui enveloppe directement son contrôle (case à cocher, option) :
                    // le texte du label (hors valeur du contrôle) sert de libellé d'option.
                    var clone = node.cloneNode(true);
                    var innerControl = clone.querySelector('input, select, textarea');
                    if (innerControl) innerControl.remove();
                    wrappedControl.__optionLabel = clone.textContent.trim();
                }
                return;
            }
            var type = (node.getAttribute('type') || '').toLowerCase();
            if (type === 'hidden' || type === 'submit' || type === 'button' || node.disabled) return;
            if (!isVisible(node)) return;
            entries.push({
                name: node.getAttribute('name') || ('_no_name_' + entries.length),
                caption: currentCaption,
                el: node,
                optionLabel: node.__optionLabel || null
            });
        });

        var groups = {};
        var order = [];
        entries.forEach(function (e) {
            if (!groups[e.name]) {
                groups[e.name] = [];
                order.push(e.name);
            }
            groups[e.name].push(e);
        });

        var fields = [];
        order.forEach(function (name) {
            var group = groups[name];
            var label, value;

            if (group.length === 1 && group[0].optionLabel) {
                // Contrôle seul, directement enveloppé dans son propre label (ex: case
                // "J'accepte..."), non partagé avec d'autres contrôles du même name.
                var e = group[0];
                label = e.optionLabel;
                value = fieldValue(e.el);
            } else {
                label = group[0].caption || group[0].optionLabel || name;
                if (group[0].el.type === 'checkbox' || group[0].el.type === 'radio') {
                    var checked = group.filter(function (e) { return e.el.checked; });
                    if (!checked.length) {
                        value = null;
                    } else {
                        value = checked.map(function (e) {
                            return e.optionLabel || e.el.value;
                        }).join(', ');
                    }
                } else {
                    value = fieldValue(group[0].el);
                }
            }

            if (value === null || value === '') return; // "simplifié" : on n'affiche que le renseigné
            fields.push({ label: label, value: value });
        });

        return fields;
    }

    function fieldValue(el) {
        if (el.tagName === 'SELECT') {
            if (el.multiple) {
                var opts = Array.from(el.selectedOptions).map(function (o) { return o.text; });
                return opts.length ? opts.join(', ') : null;
            }
            var opt = el.options[el.selectedIndex];
            return opt && opt.value ? opt.text : null;
        }
        if (el.type === 'checkbox') {
            return el.checked ? 'Oui' : 'Non';
        }
        if (el.type === 'radio') {
            return el.checked ? (el.__optionLabel || el.value) : null;
        }
        if (el.type === 'file') {
            if (!el.files || !el.files.length) return null;
            return Array.from(el.files).map(function (f) { return f.name; }).join(', ');
        }
        return el.value != null ? el.value.trim() : null;
    }

    function escapeHtml(str) {
        var div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function showRecapModal(form, title, fields) {
        var overlay = document.createElement('div');
        overlay.className = 'fixed inset-0 bg-slate-900/60 dark:bg-slate-950/80 z-50 flex items-center justify-center backdrop-blur-sm transition-opacity p-4';

        var rows = fields.map(function (f) {
            return '<div class="flex justify-between gap-4 py-2 border-b border-slate-100 dark:border-slate-700 last:border-0">' +
                '<span class="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase shrink-0">' + escapeHtml(f.label) + '</span>' +
                '<span class="text-sm text-slate-800 dark:text-white text-right break-words">' + escapeHtml(f.value) + '</span>' +
                '</div>';
        }).join('');

        overlay.innerHTML =
            '<div class="bg-white dark:bg-slate-800 p-8 rounded-3xl w-full max-w-lg shadow-2xl relative border border-slate-100 dark:border-slate-700 max-h-[85vh] flex flex-col">' +
            '  <button type="button" data-recap-cancel class="absolute top-6 right-6 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition">' +
            '    <i data-lucide="x" class="w-6 h-6"></i>' +
            '  </button>' +
            '  <div class="mb-4">' +
            '    <h3 class="text-xl font-black text-slate-900 dark:text-white uppercase tracking-tight">Récapitulatif</h3>' +
            '    <p class="text-sm text-slate-500 dark:text-slate-400">' + escapeHtml(title) + ' — vérifiez avant de confirmer.</p>' +
            '  </div>' +
            '  <div class="overflow-y-auto flex-1 -mx-2 px-2">' +
            (rows || '<p class="text-sm text-slate-400 italic">Aucune information à afficher.</p>') +
            '  </div>' +
            '  <div class="flex gap-3 mt-6 shrink-0">' +
            '    <button type="button" data-recap-cancel class="flex-1 bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-200 font-black py-3 rounded-xl hover:bg-slate-200 dark:hover:bg-slate-600 transition text-xs uppercase tracking-widest">Modifier</button>' +
            '    <button type="button" data-recap-confirm-btn class="flex-1 bg-teal-600 hover:bg-teal-500 text-white font-black py-3 rounded-xl shadow-lg transition text-xs uppercase tracking-widest">Confirmer la création</button>' +
            '  </div>' +
            '</div>';

        document.body.appendChild(overlay);
        if (window.lucide) window.lucide.createIcons();

        function close() {
            overlay.remove();
        }

        overlay.addEventListener('click', function (ev) {
            if (ev.target === overlay) close();
        });
        overlay.querySelectorAll('[data-recap-cancel]').forEach(function (btn) {
            btn.addEventListener('click', close);
        });
        overlay.querySelector('[data-recap-confirm-btn]').addEventListener('click', function () {
            close();
            form.__recapConfirmed = true;
            if (typeof form.requestSubmit === 'function') {
                form.requestSubmit();
            } else {
                form.submit();
            }
        });
    }

    function initForm(form) {
        var title = form.getAttribute('data-recap-confirm') || 'Votre demande';
        form.addEventListener('submit', function (ev) {
            if (form.__recapConfirmed) {
                form.__recapConfirmed = false;
                return; // soumission réelle après confirmation dans le modal
            }
            if (!form.checkValidity()) {
                return; // laisser la validation native du navigateur s'afficher normalement
            }
            ev.preventDefault();
            var fields = collectFields(form);
            showRecapModal(form, title, fields);
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('form[data-recap-confirm]').forEach(initForm);
    });
})();
