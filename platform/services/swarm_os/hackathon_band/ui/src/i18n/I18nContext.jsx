import React, { createContext, useContext, useMemo, useState } from "react";
import { translations } from "./translations";

const I18nContext = createContext(null);

export function I18nProvider({ children }) {
  const [lang, setLang] = useState("en");
  const t = useMemo(() => translations[lang], [lang]);
  const toggle = () => setLang((l) => (l === "en" ? "es" : "en"));
  return (
    <I18nContext.Provider value={{ lang, t, toggle, setLang }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n outside provider");
  return ctx;
}
