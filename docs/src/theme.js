const toggle = document.getElementById('theme-toggle');
const html = document.documentElement;

const stored = localStorage.getItem('theme');
if (stored) {
  html.setAttribute('data-theme', stored);
  toggle.textContent = stored === 'dark' ? '\u2600' : '\u263D';
} else if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
  html.setAttribute('data-theme', 'dark');
  toggle.textContent = '\u2600';
}

toggle.addEventListener('click', () => {
  const current = html.getAttribute('data-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-theme', next);
  localStorage.setItem('theme', next);
  toggle.textContent = next === 'dark' ? '\u2600' : '\u263D';
});
