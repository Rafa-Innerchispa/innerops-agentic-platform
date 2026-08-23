import { ThemedLayoutV2 } from "@refinedev/antd";
import { Button } from "antd";
import { GlobalOutlined } from "@ant-design/icons";
import { Outlet } from "react-router-dom";
import { PageShell } from "./PageShell";
import { useLang } from "../i18n/LangContext";

export function AppLayout() {
  const { labels, toggleLang } = useLang();
  return (
    <ThemedLayoutV2
      Title={() => <span>{labels.title}</span>}
      HeaderButtons={() => (
        <Button type="text" icon={<GlobalOutlined />} onClick={toggleLang}>
          {labels.langBtn}
        </Button>
      )}
    >
      <PageShell>
        <Outlet />
      </PageShell>
    </ThemedLayoutV2>
  );
}
