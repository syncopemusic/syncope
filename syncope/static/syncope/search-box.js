function relocateResultCount(results, countTarget) {
    if (!countTarget) return;
    const count = results.querySelector('.result-count');
    countTarget.textContent = count ? count.textContent : '';
    count?.remove();
}

// searchUrl: list-page endpoint, queried with the page's own query string (keeps sorting) plus q.
// filterForm: its fields replace the page's filter params, and the shareable page URL is kept in sync.
// onSearch(query), if given, replaces the default fetch-into-results (pages that reload their own view).
function initLiveSearch({ input, spinner, results, clearBtn, buildUrl, searchUrl, filterForm, countTarget, onSearch }) {
    if (!input) return;
    let timeout;
    buildUrl ??= q => {
        const params = new URLSearchParams(location.search);
        if (filterForm) {
            Array.from(filterForm.elements, el => el.name).forEach(name => params.delete(name));
            new FormData(filterForm).forEach((value, name) => params.append(name, value));
        }
        params.set('q', q);
        if (filterForm) history.replaceState(null, '', `?${params}`);
        return `${searchUrl}?${params}`;
    };

    function run(query) {
        spinner.classList.add('is-active');
        const done = onSearch ? Promise.resolve(onSearch(query)) : fetch(buildUrl(query)).then(r => r.text()).then(html => {
            results.innerHTML = html;
            relocateResultCount(results, countTarget);
        });
        return done.finally(() => spinner.classList.remove('is-active'));
    }

    input.addEventListener('input', function() {
        clearTimeout(timeout);
        spinner.classList.add('is-active');
        timeout = setTimeout(() => run(input.value), 1000);
    });
    input.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') e.preventDefault();
    });
    if (clearBtn) {
        // Existing "Clear" buttons become an inline × inside the field, shown only while it has text.
        Object.assign(clearBtn, { className: 'search-clear', textContent: '×', ariaLabel: 'Clear search' });
        input.after(clearBtn);
        const sync = () => { clearBtn.hidden = !input.value; };
        input.addEventListener('input', sync);
        clearBtn.addEventListener('click', function() {
            clearTimeout(timeout);
            input.value = '';
            sync();
            input.focus();
            run('');
        });
        sync();
    }

    relocateResultCount(results, countTarget);
    return { run };
}

// Wires a .person-picker's hidden FK field, search input, and results dropdown together.
// Shared by every page that renders _person_picker.html (song meta, song lyrics, ...).
function wirePersonPicker(container) {
    if (!container) return;
    const fieldInput = container.querySelector('input[type=hidden]');
    const input = container.querySelector('.person-picker-input');
    const spinner = container.querySelector('.person-picker-spinner');
    const results = container.querySelector('.person-picker-results');
    const searchUrl = container.dataset.searchUrl;
    const nextUrl = container.dataset.next || '';

    const live = initLiveSearch({
        input: input,
        spinner: spinner,
        results: results,
        buildUrl: q => `${searchUrl}?q=${encodeURIComponent(q)}&next=${encodeURIComponent(nextUrl)}`,
    });

    input.addEventListener('focus', function() {
        input.select();
        if (input.value.trim()) {
            results.hidden = false;
            live.run(input.value);
        }
    });

    input.addEventListener('blur', function() {
        setTimeout(() => { results.hidden = true; }, 150);
    });

    // Without this, clicking a button inside results (Select, + New X) blurs
    // the input first, racing the 150ms hide above - on a normal desktop
    // click that outlasts 150ms, results gets hidden mid-click and the
    // browser cancels the click entirely.
    results.addEventListener('mousedown', function(e) {
        e.preventDefault();
    });

    input.addEventListener('input', function() {
        fieldInput.value = '';
        fieldInput.dispatchEvent(new Event('input', {bubbles: true}));
        results.hidden = !input.value.trim();
    });

    results.addEventListener('click', function(e) {
        const btn = e.target.closest('[data-id]');
        if (!btn) return;
        fieldInput.value = btn.dataset.id;
        input.value = btn.closest('.search-result-row').querySelector('.result-label').textContent.trim();
        results.hidden = true;
        fieldInput.dispatchEvent(new Event('input', {bubbles: true}));
    });
}
