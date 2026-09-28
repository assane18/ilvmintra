/*
 * Zone de dépôt pour les pièces jointes.
 * Remplace visuellement chaque <input type="file"> des formulaires de création
 * (form[data-recap-confirm]) par une zone cliquable / glisser-déposer qui liste
 * les fichiers choisis (nom, taille), permet d'en retirer un, et rappelle la
 * taille maximale acceptée par le serveur (MAX_CONTENT_LENGTH = 20 Mo).
 * L'input d'origine reste dans le formulaire (masqué) : la soumission est
 * inchangée côté serveur.
 */
(function () {
    var MAX_MB = 20;

    function human(bytes) {
        if (bytes < 1024) return bytes + ' o';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' Ko';
        return (bytes / (1024 * 1024)).toFixed(1) + ' Mo';
    }

    function acceptLabel(input) {
        var a = (input.getAttribute('accept') || '').trim();
        if (!a) return 'Tous formats';
        return a.replace(/image\/\*/g, 'images').replace(/,/g, ', ').replace(/\./g, '').toUpperCase();
    }

    function enhance(input) {
        if (input.dataset.dropzoneReady) return;
        input.dataset.dropzoneReady = '1';

        var zone = document.createElement('div');
        zone.className = 'dropzone border-2 border-dashed border-gray-300 dark:border-slate-600 bg-gray-50 dark:bg-slate-950 p-4 text-center cursor-pointer transition hover:border-accent-400';
        zone.innerHTML =
            '<div class="dz-empty">' +
              '<p class="text-sm font-bold text-slate-700 dark:text-slate-200">Glissez vos fichiers ici ou <span class="text-accent-600 dark:text-accent-400 underline">parcourir</span></p>' +
              '<p class="text-[10px] text-slate-400 mt-1">' + acceptLabel(input) + (input.multiple ? ' · plusieurs fichiers' : ' · un seul fichier') + ' · ' + MAX_MB + ' Mo max au total</p>' +
            '</div>' +
            '<ul class="dz-list text-left space-y-1 hidden"></ul>';
        input.classList.add('hidden');
        input.parentNode.insertBefore(zone, input.nextSibling);
        var list = zone.querySelector('.dz-list');
        var empty = zone.querySelector('.dz-empty');

        function render() {
            var files = Array.from(input.files || []);
            list.innerHTML = '';
            var total = 0;
            files.forEach(function (f, idx) {
                total += f.size;
                var li = document.createElement('li');
                li.className = 'flex items-center justify-between gap-3 bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 px-3 py-2 text-xs';
                li.innerHTML = '<span class="truncate font-bold text-slate-700 dark:text-slate-200">' + f.name.replace(/</g, '&lt;') + '</span>' +
                    '<span class="text-slate-400 whitespace-nowrap">' + human(f.size) + '</span>' +
                    '<button type="button" data-idx="' + idx + '" class="dz-remove text-red-500 hover:text-red-700 font-black" title="Retirer">✕</button>';
                list.appendChild(li);
            });
            var tooBig = total > MAX_MB * 1024 * 1024;
            if (tooBig) {
                var warn = document.createElement('li');
                warn.className = 'text-xs font-bold text-red-600 dark:text-red-400';
                warn.textContent = 'Total ' + human(total) + ' : dépasse la limite de ' + MAX_MB + ' Mo, retirez un fichier.';
                list.appendChild(warn);
            }
            zone.classList.toggle('border-red-400', tooBig);
            list.classList.toggle('hidden', files.length === 0);
            empty.classList.toggle('hidden', files.length > 0);
            if (files.length > 0) {
                var add = document.createElement('li');
                add.className = 'text-[10px] text-slate-400 text-center pt-1';
                add.textContent = input.multiple ? 'Cliquez ou déposez pour ajouter d’autres fichiers' : 'Cliquez ou déposez pour remplacer';
                list.appendChild(add);
            }
        }

        function setFiles(fileArray) {
            var dt = new DataTransfer();
            fileArray.forEach(function (f) { dt.items.add(f); });
            input.files = dt.files;
            input.dispatchEvent(new Event('change', { bubbles: true }));
        }

        zone.addEventListener('click', function (e) {
            if (e.target.closest('.dz-remove')) return;
            input.click();
        });
        list.addEventListener('click', function (e) {
            var btn = e.target.closest('.dz-remove');
            if (!btn) return;
            var files = Array.from(input.files);
            files.splice(parseInt(btn.dataset.idx, 10), 1);
            setFiles(files);
        });
        ['dragenter', 'dragover'].forEach(function (ev) {
            zone.addEventListener(ev, function (e) { e.preventDefault(); zone.classList.add('border-accent-500', 'bg-accent-50'); });
        });
        ['dragleave', 'drop'].forEach(function (ev) {
            zone.addEventListener(ev, function (e) { e.preventDefault(); zone.classList.remove('border-accent-500', 'bg-accent-50'); });
        });
        zone.addEventListener('drop', function (e) {
            var dropped = Array.from(e.dataTransfer.files || []);
            if (!dropped.length) return;
            if (input.multiple) setFiles(Array.from(input.files).concat(dropped));
            else setFiles([dropped[0]]);
        });
        input.addEventListener('change', render);
        render();
    }

    document.addEventListener('DOMContentLoaded', function () {
        if (!window.DataTransfer) return; // navigateur trop ancien : input natif conservé
        document.querySelectorAll('form[data-recap-confirm] input[type="file"]').forEach(enhance);
    });
})();
