/* ran-web privacy page — privacy.js
 * Extracted from privacy/index.html to enable strict script-src 'self' CSP.
 */

document.getElementById('lang-toggle').addEventListener('click', () => {
  const es = document.body.classList.toggle('lang-es');
  document.body.classList.toggle('lang-en', !es);
  document.documentElement.lang = es ? 'es' : 'en';
});
