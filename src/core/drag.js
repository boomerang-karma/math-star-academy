/**
 * drag.js — unified pointer drag-and-drop for touch + mouse.
 *
 * Native HTML5 drag-and-drop is unreliable on touch devices and impossible to
 * style for a children's app, so every game uses this small Pointer Events
 * based helper instead. It supports:
 *   - large forgiving drop targets (the spec's fine-motor requirement)
 *   - a "ghost" that follows the finger and snaps back on an invalid drop
 *   - drop-zone highlight callbacks for immediate visual feedback
 *
 * Usage:
 *   makeDraggable(node, { data, onDrop, dropZones: () => [...], onPickup })
 */
export function makeDraggable(node, opts = {}) {
  node.classList.add('draggable');
  node.style.touchAction = 'none';

  let dragging = false;
  let moved = false;
  let startX = 0, startY = 0, originX = 0, originY = 0;
  let lastZone = null;
  let pointerId = null;

  const onDown = (e) => {
    if (opts.disabled?.()) return;
    if (e.button != null && e.button !== 0) return;
    dragging = true;
    moved = false;
    pointerId = e.pointerId;
    node.setPointerCapture?.(pointerId);
    const rect = node.getBoundingClientRect();
    startX = e.clientX;
    startY = e.clientY;
    originX = rect.left;
    originY = rect.top;
    node.classList.add('dragging');
    node.style.zIndex = 9999;
    opts.onPickup?.(node, opts.data);
    e.preventDefault();
  };

  const zonesUnder = (x, y) => {
    const zones = opts.dropZones?.() || [];
    return zones.find((z) => {
      const r = (z.el || z).getBoundingClientRect();
      const pad = z.pad ?? 0;
      return x >= r.left - pad && x <= r.right + pad && y >= r.top - pad && y <= r.bottom + pad;
    });
  };

  const onMove = (e) => {
    if (!dragging || e.pointerId !== pointerId) return;
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;
    if (!moved && Math.abs(dx) + Math.abs(dy) > 6) moved = true;
    node.style.position = 'fixed';
    node.style.left = originX + dx + 'px';
    node.style.top = originY + dy + 'px';

    const zone = zonesUnder(e.clientX, e.clientY);
    if (zone !== lastZone) {
      if (lastZone) (lastZone.el || lastZone).classList.remove('drop-hover');
      if (zone) (zone.el || zone).classList.add('drop-hover');
      lastZone = zone;
    }
  };

  const finish = (e) => {
    if (!dragging || e.pointerId !== pointerId) return;
    dragging = false;
    node.releasePointerCapture?.(pointerId);
    node.classList.remove('dragging');
    if (lastZone) (lastZone.el || lastZone).classList.remove('drop-hover');

    const zone = zonesUnder(e.clientX, e.clientY);
    const accepted = zone && opts.onDrop?.(node, zone, opts.data, { x: e.clientX, y: e.clientY });

    if (!accepted) snapBack();
    lastZone = null;

    // A real drag also produces a synthetic click on the same element. Games
    // often add a tap handler as a fallback; swallow that one click so a drag
    // isn't double-processed (which would re-trigger the tap path).
    if (moved) {
      const swallow = (ev) => {
        ev.stopPropagation();
        ev.preventDefault();
      };
      node.addEventListener('click', swallow, { capture: true, once: true });
      setTimeout(() => node.removeEventListener('click', swallow, true), 400);
    }
  };

  const snapBack = () => {
    node.style.transition = 'left .28s cubic-bezier(.34,1.56,.64,1), top .28s cubic-bezier(.34,1.56,.64,1)';
    // Return to flow position by clearing fixed positioning after the tween.
    const rect = node.getBoundingClientRect();
    node.style.left = rect.left + 'px';
    node.style.top = rect.top + 'px';
    requestAnimationFrame(() => {
      node.style.left = originX + 'px';
      node.style.top = originY + 'px';
    });
    setTimeout(() => {
      node.style.transition = '';
      node.style.position = '';
      node.style.left = '';
      node.style.top = '';
      node.style.zIndex = '';
    }, 300);
  };

  node.addEventListener('pointerdown', onDown);
  node.addEventListener('pointermove', onMove);
  node.addEventListener('pointerup', finish);
  node.addEventListener('pointercancel', finish);

  // Return a disposer so games can clean up listeners on unmount.
  return () => {
    node.removeEventListener('pointerdown', onDown);
    node.removeEventListener('pointermove', onMove);
    node.removeEventListener('pointerup', finish);
    node.removeEventListener('pointercancel', finish);
  };
}

/** Reset any inline positioning left over from a drag (used after moves). */
export function resetDragStyles(node) {
  node.style.position = '';
  node.style.left = '';
  node.style.top = '';
  node.style.zIndex = '';
  node.style.transition = '';
}
