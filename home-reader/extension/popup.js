async function refresh() {
  const {state, enabled} = await chrome.storage.local.get(['state','enabled']);
  document.getElementById('state').textContent = state || 'Остановлено.';
  document.getElementById('start').disabled = !!enabled;
  document.getElementById('stop').disabled = !enabled;
}
for (const action of ['start','stop']) {
  document.getElementById(action).addEventListener('click', async () => {
    await chrome.runtime.sendMessage({action});
    await refresh();
  });
}
chrome.storage.onChanged.addListener(refresh);
void refresh();
