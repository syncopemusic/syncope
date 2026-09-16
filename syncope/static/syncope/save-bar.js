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
