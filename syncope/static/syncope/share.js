// Share button: POSTs shareData ({type, id}) to /share/create/ and copies the link.
// Needs #share-btn, optional #share-result for status text, and a CSRF token in the page.
function initShareButton(shareData) {
    const btn = document.getElementById('share-btn');
    if (!btn) return;
    const resultSpan = document.getElementById('share-result');

    function say(text, fallbackAlert) {
        if (!resultSpan) return alert(fallbackAlert || text);
        resultSpan.textContent = text;
        if (text === 'Copied') setTimeout(() => { resultSpan.textContent = ''; }, 3000);
    }

    btn.addEventListener('click', () => {
        btn.disabled = true;
        if (resultSpan) resultSpan.textContent = 'Copying...';
        fetch('/share/create/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value,
            },
            body: JSON.stringify(shareData),
        })
            .then(r => {
                if (!r.ok) throw new Error('Request failed');
                return r.json();
            })
            .then(data => {
                const shareUrl = window.location.origin + '/' + data.share_id + '/';
                return navigator.clipboard.writeText(shareUrl).then(
                    () => say('Copied', 'Share link copied:\n' + shareUrl),
                    () => say('Copied', 'Share link:\n' + shareUrl),
                );
            })
            .catch(() => say('Failed', 'Failed to generate share link'))
            .finally(() => { btn.disabled = false; });
    });
}
