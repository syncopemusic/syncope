// Shared by every filter panel (members, attendance, event/project/poll/invitation/song lists): checkbox + input toggles, nested multiselects, "Filter (N)" badge.
// An unchecked filter's input is hidden and disabled, so it is not submitted.
function syncFilterForm(form) {
    form.querySelectorAll('.filter-sub').forEach(sub => {
        const count = sub.querySelector('select').selectedOptions.length;
        sub.open = sub.querySelector('input[type=checkbox]').checked;
        sub.querySelector('.filter-count').textContent = count ? `(${count})` : '';
    });
    const total = form.querySelectorAll('input[type=checkbox]:checked').length;
    document.getElementById('filter-total').textContent = total ? `(${total})` : '';
}

function initFilterForm(form, onChange) {
    form.addEventListener('change', e => {
        const sub = e.target.closest('.filter-sub');
        if (sub) {
            // Nested list: checkbox mirrors "anything selected"; unticking clears the selection.
            const box = sub.querySelector('input[type=checkbox]');
            const select = sub.querySelector('select');
            if (e.target === box && !box.checked) select.selectedIndex = -1;
            else if (e.target !== box) box.checked = select.selectedOptions.length > 0;
        } else if (e.target.dataset.toggle) {
            const input = form.elements[e.target.dataset.toggle];
            input.hidden = input.disabled = !e.target.checked;
            form.querySelector(`[data-today=${e.target.dataset.toggle}]`)?.toggleAttribute('hidden', !e.target.checked);
            if (e.target.checked && input.type === 'date' && !input.value) input.value = new Date().toLocaleDateString('sv');
        }
        syncFilterForm(form);
        onChange(e);
    });
    form.addEventListener('submit', e => e.preventDefault());
    form.addEventListener('click', e => {
        const name = e.target.dataset.today;
        if (!name) return;
        form.elements[name].value = new Date().toLocaleDateString('sv');  // local YYYY-MM-DD
        const box = form.querySelector(`[data-toggle=${name}]`);
        box.checked = true;
        box.dispatchEvent(new Event('change', { bubbles: true }));
    });
}
