/*
 * Affichage/masquage des champs conditionnels d'un formulaire du moteur no-code.
 * Chaque .form-field-wrapper conditionnel porte data-condition-on (nom du champ
 * déclencheur), data-condition-type (type du déclencheur) et data-condition-values
 * (liste JSON des valeurs attendues ; vide = case cochée). Un champ masqué perd
 * son attribut required, qu'il retrouve quand il redevient visible.
 * Partagé entre la page de dépôt (forms/new_submission.html) et l'aperçu du
 * builder admin (forms_admin/preview.html). Doit être chargé APRÈS le formulaire
 * (script non différé placé en fin de page).
 */
function evaluateFieldConditions() {
    document.querySelectorAll('.form-field-wrapper[data-condition-on]').forEach(wrapper => {
        const refName = wrapper.dataset.conditionOn;
        const refType = wrapper.dataset.conditionType;
        let condValues = [];
        try { condValues = JSON.parse(wrapper.dataset.conditionValues || '[]'); } catch (e) { condValues = []; }
        const refInputs = document.getElementsByName(refName);
        let visible = false;
        if (refInputs.length) {
            if (refType === 'CHECKBOX') {
                visible = refInputs[0].checked;
            } else if (refType === 'MULTI_SELECT') {
                visible = Array.from(refInputs).some(inp => inp.checked && condValues.includes(inp.value));
            } else {
                visible = Array.from(refInputs).some(inp => condValues.includes(inp.value) && (inp.type !== 'radio' || inp.checked));
            }
        }
        wrapper.classList.toggle('hidden', !visible);
        wrapper.querySelectorAll('input, textarea, select').forEach(inp => {
            if (inp.dataset.required === '1') {
                inp.required = visible;
            }
        });
    });
}

document.querySelectorAll('.form-field-wrapper input, .form-field-wrapper textarea, .form-field-wrapper select').forEach(inp => {
    if (inp.required) inp.dataset.required = '1';
    inp.addEventListener('input', evaluateFieldConditions);
    inp.addEventListener('change', evaluateFieldConditions);
});
evaluateFieldConditions();
