"use client";

import { useEffect, useState } from "react";

const KEY = "upmarket-theme";

/** Light ⇄ dark, remembered per browser. The inline boot script in layout
 *  applies the stored choice before paint; this only handles the click. */
export default function ThemeToggle() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(KEY);
    const system = window.matchMedia("(prefers-color-scheme: dark)").matches;
    setDark(stored ? stored === "dark" : system);
  }, []);

  function toggle() {
    const next = !dark;
    setDark(next);
    document.documentElement.setAttribute("data-theme", next ? "dark" : "light");
    try {
      localStorage.setItem(KEY, next ? "dark" : "light");
    } catch {
      /* private mode — the choice just will not persist */
    }
  }

  return (
    <button
      onClick={toggle}
      className="btn btn-ghost"
      style={{ padding: "8px 12px" }}
      aria-label={dark ? "تم روشن" : "تم تیره"}
      title={dark ? "تم روشن" : "تم تیره"}
    >
      {dark ? "☀️" : "🌙"}
    </button>
  );
}
