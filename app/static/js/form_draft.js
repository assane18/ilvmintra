/*
 * Brouillon automatique + protection contre la perte de saisie.
 * S'active sur tout <form data-recap-confirm> (les formulaires de création de
 * demande) sans autre balisage : les valeurs des champs texte / select / cases /
 * radios (jamais les fichiers) sont mémorisées en localStorage à chaque saisie,
 * sous une clé propre à la page. Au retour, une bannière propose de reprendre le
 * brouillon ; il est effacé quand le formulaire est réellement soumis.
 * Tant que des champs sont remplis et non soumis, quitter la page déclenche
 * l'avertissement natif du navigateur.
 */
(function () {
    var STORAGE_PREFIX = 'ilvm_draft:';

    function storage() { try { return window.localStorage; } catch (e) { return null; } }

    function fieldKey(el) {
        if (!el.name || el.type === 'file' || el.type === 'hidden' || el.type === 'submit' || el.type === 'button') return null;
        if (el.name === 'csrf_token') return null;
        if (el.type === 'checkbox' || el.type === 'radio') return el.name + '=' + el.value;
        return el.name;
    }

    function collect(form) {
        var data = {};
        form.querySelectorAll('input, select, textarea').forEach(function (el) {
            var key = fieldKey(el);
            if (!key) return;
            if (el.type === 'checkbox' || el.type === 'radio') data[key] = el.checked;
            else data[key] = el.value;
        });
        return data;
    }

    function hasContent(data) {
        return Object.keys(data).some(function (k) { var v = data[k]; return v === true || (typeof v === 'string' && v.trim() !== ''); });
    }

    function restore(form, data) {
        form.querySelectorAll('input, select, textarea').forEach(function (el) {
            var key = fieldKey(el);
            if (!key || !(key in data)) return;
            if (el.type === 'checkbox' || el.type === 'radio') el.checked = !!data[key];
            else el.value = data[key];
            // Réveille les champs conditionnels / scripts qui écoutent les changements.
            el.dispatchEvent(new Event('change', { bubbles: true }));
        });
    }

    function banner(form, onResume, onDiscard) {
        var box = document.createElement('div');
        box.className = 'mb-4 p-4 border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 text-amber-900 dark:text-amber-100 text-sm flex flex-wrap items-center gap-3';
        box.innerHTML = '<span class="font-bold flex-1">Un brouillon non envoyé a été retrouvé pour ce formulaire.</span>' +
            '<button type="button" class="draft-resume bg-amber-600 hover:bg-amber-700 text-white px-3 py-1.5 text-xs font-black uppercase tracking-wide">Reprendre le brouillon</button>' +
            '<button type="button" class="draft-discard text-xs font-bold underline">Repartir de zéro</button>';
        form.parentNode.insertBefore(box, form);
        box.querySelector('.draft-resume').addEventListener('click', function () { onResume(); box.remove(); });
        box.querySelector('.draft-discard').addEventListener('click', function () { onDiscard(); box.remove(); });
    }

    document.addEventListener('DOMContentLoaded', function () {
        var store = storage();
        if (!store) return;

        document.querySelectorAll('form[data-recap-confirm]').forEach(function (form) {
            var key = STORAGE_PREFIX + location.pathname;
            var dirty = false;
            var submitting = false;

            var saved = null;
            try { saved = JSON.parse(store.getItem(key) || 'null'); } catch (e) { saved = null; }
            if (saved && hasContent(saved) && !hasContent(collect(form))) {
                banner(form,
                    function () { restore(form, saved); dirty = true; },
                    function () { store.removeItem(key); });
            }

            var timer = null;
            form.addEventListener('input', function () {
                dirty = true;
                clearTimeout(timer);
                timer = setTimeout(function () {
                    var data = collect(form);
                    if (hasContent(data)) store.setItem(key, JSON.stringify(data));
                    else store.removeItem(key);
                }, 400);
            });

            // Le récapitulatif (recap_confirm.js) re-déclenche un submit après
            // confirmation : on considère le brouillon consommé à ce moment-là.
            form.addEventListener('submit', function () {
                submitting = true;
                setTimeout(function () { store.removeItem(key); }, 0);
            });

            window.addEventListener('beforeunload', function (e) {
                if (dirty && !submitting && hasContent(collect(form))) {
                    e.preventDefault();
                    e.returnValue = '';
                }
            });
        });
    });
})();
