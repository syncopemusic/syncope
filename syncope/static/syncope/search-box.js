function initLiveSearch({ input, spinner, results, clearBtn, buildUrl }) {
    if (!input) return;
    let timeout;

    function run(query) {
        spinner.classList.add('is-active');
        fetch(buildUrl(query)).then(r => r.text()).then(html => {
            spinner.classList.remove('is-active');
            results.innerHTML = html;
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

    return { run };
}
