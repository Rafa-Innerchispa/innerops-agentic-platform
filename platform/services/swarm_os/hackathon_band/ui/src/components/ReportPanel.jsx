import ReactMarkdown from "react-markdown";
import { useI18n } from "../i18n/I18nContext";

export default function ReportPanel({ report }) {
  const { t } = useI18n();
  return (
    <section className="panel report-panel">
      <div className="panel-head">
        <h2>{t.sectionReport}</h2>
      </div>
      {report ? (
        <div className="markdown-body">
          <ReactMarkdown>{report}</ReactMarkdown>
        </div>
      ) : (
        <p className="muted">{t.reportEmpty}</p>
      )}
    </section>
  );
}
