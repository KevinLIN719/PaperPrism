/* 删除目标在打开对话框时固定，避免下拉选择变化后删错论文。 */
(() => {
  const dialog = $('#delete-paper-dialog');
  let target = '', pending = false;
  $('#delete-paper').onclick = () => {
    target = $('#pick').value;
    if (!target) return;
    $('#delete-paper-name').textContent = target.split('/').pop();
    $('#delete-keep-records').checked = true;
    $('#delete-paper-error').textContent = '';
    dialog.showModal();
  };
  $('#delete-paper-cancel').onclick = () => { if (!pending) dialog.close(); };
  dialog.addEventListener('cancel', e => { if (pending) e.preventDefault(); });
  $('#delete-paper-form').onsubmit = async e => {
    e.preventDefault();
    if (pending || !target) return;
    pending = true;
    $('#delete-paper-confirm').disabled = $('#delete-paper-cancel').disabled = true;
    $('#delete-paper-error').textContent = '';
    try {
      const response = await fetch('/api/paper/delete', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({path:target,keep_records:$('#delete-keep-records').checked}),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || '删除失败');
      if (state.path === target) {
        if (typeof readingBookmarkPath !== 'undefined') readingBookmarkPath = '';
        state.annoToken += 1;
        location.reload();
      } else {
        await loadList();
        if ([...$('#pick').options].some(o => o.value === state.path)) $('#pick').value = state.path;
        dialog.close();
      }
    } catch (err) {
      $('#delete-paper-error').textContent = err.message || String(err);
    } finally {
      pending = false;
      $('#delete-paper-confirm').disabled = $('#delete-paper-cancel').disabled = false;
    }
  };
})();
