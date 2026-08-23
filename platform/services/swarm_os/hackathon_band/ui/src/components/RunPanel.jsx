import { useI18n } from "../i18n/I18nContext";

const PHONE_KEY = "hackathon_extra_phones";
const EMAIL_KEY = "hackathon_extra_emails";

export function loadExtraPhones() {
  try {
    return localStorage.getItem(PHONE_KEY) || "";
  } catch {
    return "";
  }
}

export function loadExtraEmails() {
  try {
    return localStorage.getItem(EMAIL_KEY) || "";
  } catch {
    return "";
  }
}

export function saveExtraPhones(value) {
  try {
    localStorage.setItem(PHONE_KEY, value);
  } catch {
    /* ignore */
  }
}

export function saveExtraEmails(value) {
  try {
    localStorage.setItem(EMAIL_KEY, value);
  } catch {
    /* ignore */
  }
}

export default function RunPanel({
  question,
  setQuestion,
  extraPhones,
  setExtraPhones,
  extraEmails,
  setExtraEmails,
  suggested = [],
  running,
  ready,
  onRun,
  error,
}) {
  const { t } = useI18n();

  const onPhonesChange = (e) => {
    const v = e.target.value;
    setExtraPhones(v);
    saveExtraPhones(v);
  };

  const onEmailsChange = (e) => {
    const v = e.target.value;
    setExtraEmails(v);
    saveExtraEmails(v);
  };

  return (
    <section className="panel run-panel">
      <div className="panel-head">
        <h2>{t.sectionRun}</h2>
        {!ready && <span className="warn-pill">{t.missingKeys}</span>}
      </div>
      <label>{t.questionLabel}</label>
      <textarea
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        rows={3}
        disabled={running}
        className="query-input"
      />
      <div className="suggested">
        <span className="muted">{t.suggested}:</span>
        {suggested.map((q) => (
          <button
            key={q}
            type="button"
            className="chip"
            disabled={running}
            onClick={() => setQuestion(q)}
          >
            {q.length > 52 ? `${q.slice(0, 52)}…` : q}
          </button>
        ))}
      </div>
      <label className="phone-label">{t.alertPhones}</label>
      <input
        type="text"
        className="phone-input"
        value={extraPhones}
        onChange={onPhonesChange}
        disabled={running}
        placeholder={t.alertPhonesPlaceholder}
        spellCheck={false}
      />
      <p className="muted phone-hint">{t.alertPhonesHint}</p>
      <label className="phone-label">{t.alertEmails}</label>
      <input
        type="text"
        className="phone-input"
        value={extraEmails}
        onChange={onEmailsChange}
        disabled={running}
        placeholder={t.alertEmailsPlaceholder}
        spellCheck={false}
      />
      <p className="muted phone-hint">{t.alertEmailsHint}</p>
      <p className="muted aiml-hint">{t.aimlWait}</p>
      <button type="button" className="primary" onClick={onRun} disabled={running || !ready}>
        {running ? t.running : t.run}
      </button>
      {error && <div className="error-box">{error}</div>}
    </section>
  );
}
