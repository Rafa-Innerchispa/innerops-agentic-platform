import { useI18n } from "../i18n/I18nContext";

const NODES = [
  { key: "router", x: 50, y: 12, color: "#22d3ee", glow: "#0891b2", provider: "Featherless" },
  { key: "memory", x: 18, y: 50, color: "#a3e635", glow: "#65a30d", provider: "Featherless" },
  { key: "analyst", x: 82, y: 50, color: "#f472b6", glow: "#db2777", provider: "AIML" },
  { key: "documentation", x: 50, y: 88, color: "#fbbf24", glow: "#d97706", provider: "AIML" },
];

const EDGES = [
  ["router", "memory"],
  ["memory", "analyst"],
  ["analyst", "documentation"],
];

function nodeByKey(agents, key) {
  return agents.find((a) => a.key === key) || {};
}

export default function AgentMap({ agents = [], activeStep, hoverKey, setHoverKey }) {
  const { lang, t } = useI18n();
  const pos = Object.fromEntries(NODES.map((n) => [n.key, n]));

  return (
    <section className="panel map-panel">
      <div className="panel-head">
        <h2>{t.sectionMap}</h2>
        <span className="muted">{t.hoverAgent}</span>
      </div>
      <svg viewBox="0 0 100 100" className="agent-map" role="img" aria-label={t.agentFlow}>
        <defs>
          {NODES.map((n) => (
            <radialGradient key={n.key} id={`grad-${n.key}`}>
              <stop offset="0%" stopColor={n.color} stopOpacity="1" />
              <stop offset="100%" stopColor={n.glow} stopOpacity="0.3" />
            </radialGradient>
          ))}
          <filter id="glow">
            <feGaussianBlur stdDeviation="1.2" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        {EDGES.map(([a, b]) => {
          const p1 = pos[a];
          const p2 = pos[b];
          const active =
            activeStep &&
            (activeStep.includes(a) || activeStep.includes(b)) &&
            !activeStep.includes("complete");
          return (
            <line
              key={`${a}-${b}`}
              x1={p1.x}
              y1={p1.y}
              x2={p2.x}
              y2={p2.y}
              className={`edge ${active ? "edge-active" : ""}`}
              style={{
                stroke: active ? `url(#grad-${b})` : undefined,
              }}
            />
          );
        })}
        {NODES.map((n) => {
          const agent = nodeByKey(agents, n.key);
          const isHover = hoverKey === n.key;
          const isActive = activeStep?.includes(n.key);
          return (
            <g
              key={n.key}
              transform={`translate(${n.x}, ${n.y})`}
              className={`agent-node ${isActive ? "active" : ""} ${isHover ? "hover" : ""}`}
              onMouseEnter={() => setHoverKey(n.key)}
              onMouseLeave={() => setHoverKey(null)}
            >
              <circle
                r="11"
                className="node-halo"
                fill={n.color}
                opacity={isHover || isActive ? 0.28 : 0.1}
              />
              <circle
                r="7"
                className="node-core"
                fill={`url(#grad-${n.key})`}
                filter={isHover || isActive ? "url(#glow)" : undefined}
                stroke={n.color}
                strokeWidth={isHover ? "0.55" : "0.4"}
              />
              <text y="15" className="node-label" fill={n.color}>
                @{agent.handle?.split("/")[1] || n.key}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="agent-detail-slot">
        {hoverKey ? (
          <div
            className="agent-detail"
            style={{
              borderColor: pos[hoverKey]?.color || "#444",
              boxShadow: `0 0 20px ${pos[hoverKey]?.glow || "#333"}44`,
            }}
          >
            {(() => {
              const a = nodeByKey(agents, hoverKey);
              const n = pos[hoverKey];
              return (
                <>
                  <h3 style={{ color: n?.color }}>@{a.handle}</h3>
                  <p>{lang === "es" ? a.description_es : a.description_en}</p>
                  <div className="tag-row">
                    {(a.tags || []).map((tag) => (
                      <span key={tag} className="tag" style={{ borderColor: n?.color }}>
                        {tag}
                      </span>
                    ))}
                    <span className="tag tag-prov">{a.provider} · {n?.provider}</span>
                  </div>
                </>
              );
            })()}
          </div>
        ) : (
          <div className="agent-detail agent-detail-empty muted">{t.hoverAgent}</div>
        )}
      </div>
    </section>
  );
}
