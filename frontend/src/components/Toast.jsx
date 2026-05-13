import React, { useEffect, useState } from 'react';

/**
 * Tiny transient notification — used to confirm "Layout updated" when the
 * chat bar or another browser mutates state. Auto-dismisses after `ttl`ms.
 */
export default function Toast({ message, ttl = 2500, onDone }) {
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (!message) return;
    setShow(true);
    const t = setTimeout(() => {
      setShow(false);
      setTimeout(() => onDone?.(), 300);
    }, ttl);
    return () => clearTimeout(t);
  }, [message, ttl, onDone]);

  if (!message) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      className={`fixed z-50 top-4 left-1/2 -translate-x-1/2
                  bg-ink text-paper px-4 py-2 border rule-thick
                  transition-all duration-300 ease-out
                  ${show ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-2'}`}
    >
      <span className="meta-sans uppercase tracking-widest text-paper">{message}</span>
    </div>
  );
}
