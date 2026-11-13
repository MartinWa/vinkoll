// Keep ordinary forms usable after a session expires. Never retain account passwords.
const prefix = 'vinkoll-draft:';
const readDraft = key => {
  try { return JSON.parse(sessionStorage.getItem(key)); } catch { return null; }
};
const initialized = new WeakSet();
function initializePage() {
  for (const marker of document.querySelectorAll('[data-completed-draft]')) {
    try { sessionStorage.removeItem(prefix + marker.dataset.completedDraft); } catch { /* Optional. */ }
  }
  for (const marker of document.querySelectorAll('[data-completed-operation]')) {
    try {
      for (const key of Object.keys(sessionStorage)) {
        if (key.startsWith(prefix) && readDraft(key)?.token === marker.dataset.completedOperation) {
          sessionStorage.removeItem(key);
        }
      }
    } catch { /* Storage may be disabled. The form still works. */ }
  }
  for (const form of document.querySelectorAll('[data-preserve-form]')) {
    if (initialized.has(form)) continue;
    initialized.add(form);
    const target = new URL(form.getAttribute('action') || window.location.href, window.location.href);
    const key = prefix + target.pathname + target.search;
    for (const discard of form.querySelectorAll('[data-discard-draft]')) {
      discard.addEventListener('click', () => {
        try { sessionStorage.removeItem(key); } catch { /* The reload still works without storage. */ }
      });
    }
    const draft = readDraft(key);
    // Restore only on a new GET form; validation responses already contain the submitted values.
    if (draft && !form.querySelector('.errorlist')) {
      for (const [name, value] of draft.entries) {
        if (name === 'csrfmiddlewaretoken' || name.toLowerCase().includes('password')) continue;
        for (const field of form.elements) {
          if (field.name !== name) continue;
          if (field.type === 'file') continue;
          if (field.type === 'radio' || field.type === 'checkbox') field.checked = field.value === value;
          else field.value = value;
        }
      }
      const notice = form.querySelector('.draft-status');
      if (notice) notice.hidden = false;
    }
    form.addEventListener('submit', () => {
      const entries = [...new FormData(form)].filter(([name, value]) =>
        name !== 'csrfmiddlewaretoken' && !name.toLowerCase().includes('password') && typeof value === 'string');
      try {
        sessionStorage.setItem(key, JSON.stringify({entries, token: form.elements.token?.value || null}));
      } catch { /* The session-expired page also displays the submitted values. */ }
    });
  }
  for (const button of document.querySelectorAll('[data-copy]')) {
    if (initialized.has(button)) continue;
    initialized.add(button);
    button.addEventListener('click', async () => {
      const preview = document.getElementById(button.dataset.copy);
      const status = button.parentElement.querySelector('[data-copy-status]');
      try {
        await navigator.clipboard.writeText(preview.value);
        status.textContent = status.dataset.copied;
      } catch {
        preview.focus();
        preview.select();
        status.textContent = status.dataset.copyFailed;
      }
    });
  }
  for (const photo of document.querySelectorAll('[data-wine-photo]')) {
    if (initialized.has(photo)) continue;
    initialized.add(photo);
    const fallback = () => {
      photo.hidden = true;
      const placeholder = photo.parentElement.querySelector('.bottle-shape');
      if (placeholder) placeholder.hidden = false;
    };
    photo.addEventListener('error', fallback);
    if (photo.complete && !photo.naturalWidth) fallback();
  }
}
initializePage();
document.addEventListener('htmx:afterSwap', initializePage);
document.addEventListener('htmx:beforeSwap', event => {
  if (event.detail.xhr.status === 401) {
    event.detail.shouldSwap = true;
    event.detail.isError = false;
    event.detail.target = document.body;
    event.detail.selectOverride = '#main';
    event.detail.swapOverride = 'innerHTML';
  }
});
