'use strict';
// Preserve native selects as the form's source of truth while rendering aligned menus.
(() => {
  let active = null;
  const close = (focus = false) => {
    if (!active) return;
    const {button, menu} = active; active = null;
    button.setAttribute('aria-expanded', 'false'); menu.remove();
    if (focus && button.isConnected) button.focus();
  };
  const update = (select, button) => {
    button.disabled = select.disabled;
    button.querySelector('.select-display').textContent = select.selectedOptions[0]?.textContent || '';
  };
  function enhance(select) {
    if (select.dataset.enhancedSelect || select.multiple) return;
    select.dataset.enhancedSelect = 'true';
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'select-trigger';
    button.setAttribute('aria-haspopup', 'listbox'); button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-label', select.getAttribute('aria-label') || select.labels?.[0]?.textContent.trim() || '选择选项');
    button.innerHTML = '<span class="select-display"></span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';
    select.insertAdjacentElement('afterend', button); select.classList.add('select-original');
    select.tabIndex = -1; select.setAttribute('aria-hidden', 'true');
    const sync = () => update(select, button); sync();
    select.addEventListener('change', sync);
    new MutationObserver(sync).observe(select, {attributes:true, childList:true, subtree:true});
    button.addEventListener('click', () => {
      if (active?.button === button) { close(true); return; }
      close(); if (select.disabled) return;
      const menu = document.createElement('div'); menu.className = 'select-menu'; menu.setAttribute('role','listbox');
      menu.setAttribute('aria-label', button.getAttribute('aria-label'));
      for (const option of select.options) {
        const choice = document.createElement('button'); choice.type = 'button'; choice.setAttribute('role','option');
        choice.setAttribute('aria-selected', String(option.selected)); choice.disabled = option.disabled || !!option.parentElement?.disabled;
        choice.textContent = option.textContent;
        choice.addEventListener('click', () => { select.value = option.value; select.dispatchEvent(new Event('change', {bubbles:true})); update(select, button); close(true); });
        menu.append(choice);
      }
      const dialog = button.closest('dialog'); (dialog || document.body).append(menu);
      const rect = button.getBoundingClientRect(), bounds = dialog?.getBoundingClientRect();
      const leftBound = bounds ? Math.max(12, bounds.left + 8) : 12;
      const rightBound = bounds ? Math.min(document.documentElement.clientWidth - 12, bounds.right - 8) : document.documentElement.clientWidth - 12;
      const topBound = bounds ? Math.max(12, bounds.top + 8) : 12;
      const bottomBound = bounds ? Math.min(window.innerHeight - 12, bounds.bottom - 8) : window.innerHeight - 12;
      const width = Math.min(rect.width, rightBound - leftBound); menu.style.width = `${width}px`;
      const left = Math.max(leftBound, Math.min(rect.left, rightBound - width));
      const below = bottomBound - rect.bottom - 6, above = rect.top - topBound - 6, up = below < 200 && above > below;
      menu.style.maxHeight = `${Math.max(40, Math.min(320, up ? above : below))}px`;
      const top = up ? rect.top - menu.offsetHeight - 6 : rect.bottom + 6;
      if (dialog) { menu.style.position = 'absolute'; menu.style.left = `${left - bounds.left - dialog.clientLeft}px`; menu.style.top = `${top - bounds.top - dialog.clientTop}px`; }
      else { menu.style.left = `${left}px`; menu.style.top = `${top}px`; }
      active = {button, menu}; button.setAttribute('aria-expanded','true');
      (menu.querySelector('[aria-selected="true"]:not(:disabled)') || menu.querySelector('button:not(:disabled)'))?.focus();
    });
  }
  function scan(root) { if (root.nodeType !== 1) return; if (root.matches('select')) enhance(root); root.querySelectorAll('select').forEach(enhance); }
  document.addEventListener('click', e => { if (active && !active.menu.contains(e.target) && !active.button.contains(e.target)) close(); });
  document.addEventListener('keydown', e => {
    if (!active) return;
    if (e.key === 'Escape') { e.preventDefault(); close(true); return; }
    if (e.key === 'Tab') { close(); return; }
    if (!active.menu.contains(e.target) || !['ArrowDown','ArrowUp','Home','End'].includes(e.key)) return;
    e.preventDefault(); const choices = [...active.menu.querySelectorAll('button:not(:disabled)')], index = choices.indexOf(document.activeElement);
    const next = e.key === 'Home' ? 0 : e.key === 'End' ? choices.length-1 : (index + (e.key === 'ArrowDown' ? 1 : -1) + choices.length) % choices.length;
    choices[next]?.focus();
  });
  window.addEventListener('resize', () => close());
  document.addEventListener('scroll', e => { if (active && !active.menu.contains(e.target)) close(); }, true);
  scan(document.body);
  new MutationObserver(records => records.forEach(record => record.addedNodes.forEach(scan))).observe(document.body, {childList:true,subtree:true});
})();
