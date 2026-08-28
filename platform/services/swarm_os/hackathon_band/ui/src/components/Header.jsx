import { useI18n } from "../i18n/I18nContext";

export default function Header({ status }) {
  const { t, toggle } = useI18n();
  const ready = status?.readiness?.ready;
  const providers = status?.providers || {};

  return (
    <header className="dash-header">
      <div className="brand">
        <h1>{t.title}</h1>
        <p>{t.tagline}</p>
      </div>
      <div className="header-right">
        <button type="button" className="lang-btn" onClick={toggle}>
          {t.langSwitch}
        </button>
        <div className="provider-pills">
          <Pill label="Band" ok={providers.band} extra="LIVE" />
          <Pill label="Featherless" ok={providers.featherless} />
          <Pill label="AIML" ok={providers.aiml} />
        </div>
        <span className={`ready-pill ${ready ? "ok" : "bad"}`}>
          {ready ? t.ready : t.missingKeys}
        </span>
      </div>
    </header>
  );
}

function Pill({ label, ok, extra }) {
  return (
    <span className={`pill ${ok ? "on" : "off"}`}>
      {label}{extra && ok ? ` · ${extra}` : ""}
    </span>
  );
}
