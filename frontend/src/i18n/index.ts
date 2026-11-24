import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";

// Russian and Korean dictionaries are added later as ./locales/ru.json and ./locales/ko.json
// with the same keys; nothing else in the app needs to change.
export const SUPPORTED_LANGUAGES = ["en"] as const;

function initialLanguage(): string {
  try {
    const saved = localStorage.getItem("lang");
    if (saved && (SUPPORTED_LANGUAGES as readonly string[]).includes(saved)) return saved;
  } catch {
    /* storage unavailable */
  }
  return "en";
}

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en } },
  lng: initialLanguage(),
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

export default i18n;
