/*
 * Avertissement « demande en double » avant soumission (2026-11-16).
 * S'active sur tout <form data-dup-check="URL"> : au submit, envoie les champs
 * texte du formulaire (jamais les fichiers) à l'URL, et si des demandes
 * ouvertes similaires du même demandeur existent, affiche une fenêtre
 * « Vous avez déjà une demande en cours » avec le choix : voir la demande,
 * ou créer quand même (champ caché dup_ack=1). Passe la main ensuite au
 * récapitulatif (recap_confirm.js) : écouteur en phase de capture, donc il
 * s'exécute avant.
 */
(function () {
    function escapeHtml(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }

    function showModal(form, items) {
        var overlay = document.createElement('div');
        overlay.className = 'fixed inset-0 bg-slate-900/60 dark:bg-slate-950/80 z-50 flex items-center justify-center backdrop-blur-sm p-4';
        var rows = items.map(function (it) {
            return '<a href="' + escapeHtml(it.url) + '" class="block border border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-500/10 p-3 hover:bg-amber-100 dark:hover:bg-amber-500/20 transition">' +
                '<span class="font-mono text-[10px] text-slate-500">' + escapeHtml(it.uid) + '</span> · <span class="text-[10px] font-bold uppercase text-amber-700 dark:text-amber-300">' + escapeHtml(it.status) + '</span>' +
                '<span class="block text-sm font-bold text-slate-800 dark:text-white mt-0.5">' + escapeHtml(it.title) + '</span>' +
                '<span class="block text-[11px] text-slate-500 dark:text-slate-400">' + escapeHtml(it.when) + '</span></a>';
        }).join('');
        overlay.innerHTML =
            '<div class="bg-white dark:bg-slate-800 p-8 w-full max-w-lg shadow-2xl relative border border-amber-300 dark:border-amber-500/40 max-h-[85vh] flex flex-col">' +
            '  <div class="mb-4 flex items-start gap-3">' +
            '    <i data-lucide="copy" class="w-6 h-6 text-amber-500 shrink-0"></i>' +
            '    <div><h3 class="text-xl font-black text-slate-900 dark:text-white uppercase tracking-tight">Demande déjà en cours ?</h3>' +
            '    <p class="text-sm text-slate-500 dark:text-slate-400">Vous avez déjà une demande ouverte qui ressemble à celle-ci. Inutile de la refaire : vous pouvez la consulter et y ajouter un message.</p></div>' +
            '  </div>' +
            '  <div class="overflow-y-auto flex-1 space-y-2">' + rows + '</div>' +
            '  <div class="flex gap-3 mt-6 shrink-0">' +
            '    <a href="' + escapeHtml(items[0].url) + '" class="flex-1 bg-amber-500 hover:bg-amber-400 text-white font-black py-3 text-center text-xs uppercase tracking-widest transition">Voir ma demande en cours</a>' +
            '    <button type="button" data-dup-force class="flex-1 bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-200 font-black py-3 hover:bg-slate-200 dark:hover:bg-slate-600 transition text-xs uppercase tracking-widest">Créer quand même</button>' +
            '  </div>' +
            '</div>';
        document.body.appendChild(overlay);
        if (window.lucide) window.lucide.createIcons();
        overlay.addEventListener('click', function (ev) { if (ev.target === overlay) overlay.remove(); });
        overlay.querySelector('[data-dup-force]').addEventListener('click', function () {
            overlay.remove();
            var ack = form.querySelector('input[name="dup_ack"]');
            if (!ack) { ack = document.createElement('input'); ack.type = 'hidden'; ack.name = 'dup_ack'; form.appendChild(ack); }
            ack.value = '1';
            form.__dupChecked = true;
            if (typeof form.requestSubmit === 'function') form.requestSubmit(); else form.submit();
        });
    }

    function textFields(form) {
        var params = new URLSearchParams();
        new FormData(form).forEach(function (v, k) { if (!(v instanceof File)) params.append(k, v); });
        return params;
    }

    function initForm(form) {
        var url = form.getAttribute('data-dup-check');
        if (!url) return;
        form.addEventListener('submit', function (ev) {
            if (form.__dupChecked) { form.__dupChecked = false; return; }
            if (!form.checkValidity()) return;
            ev.preventDefault();
            ev.stopImmediatePropagation();
            fetch(url, { method: 'POST', body: textFields(form), credentials: 'same-origin',
                         headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                .then(function (r) { return r.ok ? r.json() : { similar: [] }; })
                .catch(function () { return { similar: [] }; })
                .then(function (res) {
                    if (res && res.similar && res.similar.length) { showModal(form, res.similar); return; }
                    form.__dupChecked = true;
                    if (typeof form.requestSubmit === 'function') form.requestSubmit(); else form.submit();
                });
        }, true);
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('form[data-dup-check]').forEach(initForm);
    });
})();
