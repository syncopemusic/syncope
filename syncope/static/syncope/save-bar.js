// Counts fields whose value actually differs from what the form was rendered with, for a
// plain "loop over form fields" edit page - `initSaveBar`'s countUnsavedChanges still needs a
// real number, not a single dirty flag, or the "N unsaved changes" note always reads "1".
function trackFormFieldChanges(form) {
    const original = new Map();
    const changed = new Set();

    function valueOf(el) {
        return (el.type === 'checkbox' || el.type === 'radio') ? el.checked : el.value;
    }

    function snapshot() {
        original.clear();
        changed.clear();
        Array.from(form.elements).forEach(el => { if (el.name) original.set(el, valueOf(el)); });
    }
    snapshot();

    form.addEventListener('input', function (e) {
        if (!original.has(e.target)) return;
        if (valueOf(e.target) !== original.get(e.target)) changed.add(e.target);
        else changed.delete(e.target);
    });
    form.addEventListener('change', function (e) {
        if (!original.has(e.target)) return;
        if (valueOf(e.target) !== original.get(e.target)) changed.add(e.target);
        else changed.delete(e.target);
    });

    return { count: () => changed.size, reset: snapshot };
}

// Pointer-based drag-to-reorder for a tbody's rows via a `.drag-handle` cell (mouse and touch
// alike). Shared by every drag-to-reorder table (event songs, resources, ...) so the pointer
// capture/release dance only has to be got right once.
function initDragReorder(tbody, { rowSelector = 'tr', onDrop } = {}) {
    let dragRow = null;
    let dragPointerId = null;

    tbody.addEventListener('pointerdown', function (e) {
        const handle = e.target.closest('.drag-handle');
        if (!handle) return;
        const row = handle.closest(rowSelector);
        if (!row) return;
        e.preventDefault();
        handle.setPointerCapture(e.pointerId);
        dragRow = row;
        dragPointerId = e.pointerId;
        row.classList.add('dragging');
        window.addEventListener('pointerup', endDrag);
        window.addEventListener('pointercancel', endDrag);
        window.addEventListener('blur', endDrag);
    });

    tbody.addEventListener('pointermove', function (e) {
        if (!dragRow || e.pointerId !== dragPointerId) return;
        const rows = Array.from(tbody.querySelectorAll(rowSelector));
        let target = null;
        for (const row of rows) {
            if (row === dragRow) continue;
            const rect = row.getBoundingClientRect();
            if (e.clientY < rect.top + rect.height / 2) { target = row; break; }
        }
        if (target) tbody.insertBefore(dragRow, target);
        else tbody.appendChild(dragRow);
    });

    function endDrag(e) {
        if (!dragRow) return;
        if (e && typeof e.pointerId === 'number' && e.pointerId !== dragPointerId) return;
        const handle = dragRow.querySelector('.drag-handle');
        try {
            if (handle && dragPointerId !== null && handle.hasPointerCapture(dragPointerId)) {
                handle.releasePointerCapture(dragPointerId);
            }
        } catch (err) { /* pointer already invalid/released - ignore */ }
        dragRow.classList.remove('dragging');
        dragRow = null;
        dragPointerId = null;
        window.removeEventListener('pointerup', endDrag);
        window.removeEventListener('pointercancel', endDrag);
        window.removeEventListener('blur', endDrag);
        if (onDrop) onDrop();
    }
    tbody.addEventListener('pointerup', endDrag);
    tbody.addEventListener('pointercancel', endDrag);
}

function initSaveBar({ formId, saveBarId = 'save-bar', countUnsavedChanges, beforeSync, onDiscard, afterDiscard }) {
    const saveBar = document.getElementById(saveBarId);
    const form = document.getElementById(formId);

    function sync() {
        if (beforeSync) beforeSync();
        if (!saveBar) return;
        const n = countUnsavedChanges();
        const dirty = n > 0;
        saveBar.classList.toggle('dirty', dirty);
        const cleanActions = document.getElementById('clean-actions');
        const dirtyActions = document.getElementById('dirty-actions');
        if (cleanActions) cleanActions.style.display = dirty ? 'none' : '';
        if (dirtyActions) dirtyActions.style.display = dirty ? '' : 'none';
        const note = saveBar.querySelector('.dirty-note');
        if (note) note.textContent = dirty ? `${n} unsaved change${n === 1 ? '' : 's'}` : '';
    }

    let formSubmitting = false;
    form?.addEventListener('submit', () => { formSubmitting = true; });
    window.addEventListener('beforeunload', function (e) {
        if (formSubmitting || !saveBar?.classList.contains('dirty')) return;
        e.preventDefault();
        e.returnValue = '';
    });

    function discardChanges() {
        if (countUnsavedChanges() === 0) return;
        if (!confirm('Do you want to discard changes?')) return;
        onDiscard();
        sync();
        if (afterDiscard) afterDiscard();
    }
    document.getElementById('discard-btn')?.addEventListener('click', discardChanges);

    return { sync };
}
