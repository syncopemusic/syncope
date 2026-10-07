// Staged add/remove list: search results stage tr.staged-add (hidden add_*), x stages tr.pending-remove (hidden remove_<pk>).
// Rows carry data-id (the pk posted as remove_<pk>); data-<excludeKey> is what the search excludes. Search is optional:
// ids `<prefix>-search-{input,spinner,results,clear,count}`. An optional `tr.empty-row` shows while the list is empty.
// rootId (default tbodyId): wider element whose rows can also be removed (e.g. a second tbody in the same table).
// Hooks (pages that need more): buildRow(btn, info) -> cells html, extraCount() -> number, afterChange(count), onDiscardExtra().
function escapeHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

function initStagedList({ formId, tbodyId, rootId = tbodyId, addField, prefix, searchUrl, queryParam = 'q', excludeKey = 'id', numClass = 'col-num',
                          rowClass = '', buildRow, extraCount = () => 0, afterChange, onDiscardExtra }) {
    const tbody = document.getElementById(tbodyId), root = document.getElementById(rootId), emptyRow = tbody.querySelector('.empty-row');
    const el = n => document.getElementById(`${prefix}-search-${n}`);
    const count = () => root.querySelectorAll('tr.staged-add, tr.pending-remove').length + extraCount();
    const ids = () => Array.from(tbody.rows).map(tr => tr.dataset[excludeKey]).filter(Boolean);
    const refresh = () => live?.run(el('input').value);
    const mark = (row, pending) => {  // flips the pending-remove state, input and button of an existing row
        const btn = row.querySelector('.btn-remove');
        btn.dataset.title ??= btn.title;
        row.classList.toggle('pending-remove', pending);
        row.querySelector('.pending-remove-input')?.remove();
        if (pending) row.insertAdjacentHTML('beforeend', `<input type="hidden" class="pending-remove-input" name="remove_${row.dataset.id}" value="1">`);
        [btn.textContent, btn.title] = pending ? ['↺', 'Undo removal'] : ['×', btn.dataset.title];
    };
    const bar = initSaveBar({
        formId,
        countUnsavedChanges: count,
        beforeSync: () => {
            if (emptyRow) emptyRow.hidden = tbody.querySelector('tr:not(.empty-row)') !== null;
            afterChange?.(count());
        },
        onDiscard: () => {
            tbody.querySelectorAll('tr.staged-add').forEach(r => r.remove());
            root.querySelectorAll('tr.pending-remove').forEach(r => mark(r, false));
            onDiscardExtra?.();
        },
        afterDiscard: refresh,
    });
    root.addEventListener('click', e => {
        const row = e.target.closest('.btn-remove')?.closest('tr');
        if (!row) return;
        if (row.classList.contains('staged-add')) row.remove(); else mark(row, !row.classList.contains('pending-remove'));
        bar.sync();
        refresh();
    });
    const live = initLiveSearch({
        input: el('input'), spinner: el('spinner'), results: el('results'), clearBtn: el('clear'), countTarget: el('count'),
        buildUrl: q => `${searchUrl}?${queryParam}=${encodeURIComponent(q)}&exclude=${encodeURIComponent(ids().join(','))}`,
    });
    buildRow ??= (btn, info) => `<td class="${numClass}"></td>
        <td class="col-main">${info}<input type="hidden" name="${addField}" value="${btn.dataset.id}"></td>
        <td class="col-action"><button type="button" class="btn btn-remove" title="Remove staged addition">&times;</button></td>`;
    el('results')?.addEventListener('click', e => {
        const btn = e.target.closest('.btn-secondary'), row = btn?.closest('.search-result-row');
        if (!row) return;
        const info = row.querySelector('.search-result-info')?.innerHTML ?? escapeHtml(row.querySelector('.result-label').textContent.trim());
        const tr = tbody.insertRow();
        tr.className = `${rowClass} staged-add`.trim();
        tr.dataset[excludeKey] = btn.dataset.id;
        tr.innerHTML = buildRow(btn, info);
        row.remove();
        bar.sync();
    });
    bar.sync();
    return bar;
}
