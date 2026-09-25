function relocateResultCount(results, countTarget) {
    if (!countTarget) return;
    const count = results.querySelector('.result-count');
    countTarget.textContent = count ? count.textContent : '';
    count?.remove();
}

function initLiveSearch({ input, spinner, results, clearBtn, buildUrl, countTarget }) {
    if (!input) return;
    let timeout;

    function run(query) {
        spinner.classList.add('is-active');
        fetch(buildUrl(query)).then(r => r.text()).then(html => {
            spinner.classList.remove('is-active');
            results.innerHTML = html;
            relocateResultCount(results, countTarget);
        });
    }

    input.addEventListener('input', function() {
        clearTimeout(timeout);
        spinner.classList.add('is-active');
        timeout = setTimeout(() => run(input.value), 1000);
    });
    input.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') e.preventDefault();
    });
    clearBtn?.addEventListener('click', function() {
        clearTimeout(timeout);
        input.value = '';
        run('');
    });

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

    const live = initLiveSearch({
        input: input,
        spinner: spinner,
        results: results,
        buildUrl: q => `${searchUrl}?q=${encodeURIComponent(q)}`,
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
