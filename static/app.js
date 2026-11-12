// Keep ordinary forms usable after a session expires. Never retain account passwords.
const prefix = 'vinkoll-draft:';
const readDraft = key => {
  try { return JSON.parse(sessionStorage.getItem(key)); } catch { return null; }
};
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
  const target = new URL(form.action || window.location.href);
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
