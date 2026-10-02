// Page-wide behaviour driven by data attributes, so templates need no inline on* handlers.
//   data-confirm="Text"      ask before a click (button, checkbox) or a submit (form) goes through
//   data-clear="selector"    on change, blank the matching fields in the same form
document.addEventListener('click', function (e) {
    const el = e.target.closest('[data-confirm]');
    if (el && el.tagName !== 'FORM' && !confirm(el.dataset.confirm)) e.preventDefault();
});

document.addEventListener('submit', function (e) {
    if (e.target.dataset.confirm && !confirm(e.target.dataset.confirm)) e.preventDefault();
});

document.addEventListener('change', function (e) {
    const el = e.target.closest('[data-clear]');
    if (el) el.form.querySelectorAll(el.dataset.clear).forEach(field => { field.value = ''; });
});
