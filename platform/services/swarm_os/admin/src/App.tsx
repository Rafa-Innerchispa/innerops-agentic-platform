import { useMemo } from "react";
import { Refine, ResourceProps } from "@refinedev/core";
import { RefineThemes, useNotificationProvider } from "@refinedev/antd";
import { ConfigProvider, App as AntApp, theme } from "antd";
import routerBindings, { UnsavedChangesNotifier } from "@refinedev/react-router-v6";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import {
  TeamOutlined,
  ShoppingOutlined,
  AppstoreOutlined,
  ShopOutlined,
  FileTextOutlined,
  CarOutlined,
  SettingOutlined,
  CommentOutlined,
  FileSearchOutlined,
  MailOutlined,
  DeploymentUnitOutlined,
  ApartmentOutlined,
} from "@ant-design/icons";
import { HackathonPage } from "./pages/hackathon";
import { AppLayout } from "./components/AppLayout";
import { LangProvider, useLang } from "./i18n/LangContext";
import { dataProvider } from "./providers/dataProvider";
import { ClientList } from "./pages/clients/list";
import { Dashboard } from "./pages/dashboard";
import { ResourceList } from "./pages/generic/ResourceList";
import { SettingsPage } from "./pages/settings";
import { DataCenterPage } from "./pages/datacenter";
import { VisitList } from "./pages/visits/list";
import { ReportList } from "./pages/reports/list";
import { EmailMonitorPage } from "./pages/email";

function AppRoutes() {
  const { labels } = useLang();
  const resources: ResourceProps[] = useMemo(
    () => [
      { name: "inneros", list: "/inneros", meta: { label: labels.inneros, icon: <DeploymentUnitOutlined /> } },
      { name: "datacenter", list: "/datacenter", meta: { label: labels.datacenter, icon: <CommentOutlined /> } },
      { name: "entities", list: "/entities", meta: { label: labels.entities, icon: <ApartmentOutlined /> } },
      { name: "clients", list: "/clients", meta: { label: labels.clients, icon: <TeamOutlined /> } },
      { name: "inventory-items", list: "/inventory", meta: { label: labels.inventory, icon: <ShoppingOutlined /> } },
      { name: "catalog-products", list: "/catalog", meta: { label: labels.catalog, icon: <AppstoreOutlined /> } },
      { name: "suppliers", list: "/suppliers", meta: { label: labels.suppliers, icon: <ShopOutlined /> } },
      { name: "quotes", list: "/quotes", meta: { label: labels.quotes, icon: <FileTextOutlined /> } },
      { name: "sop-visits", list: "/visits", meta: { label: labels.visits, icon: <CarOutlined /> } },
      { name: "technical-reports", list: "/reports", meta: { label: labels.reports, icon: <FileSearchOutlined /> } },
      { name: "email-monitor", list: "/email", meta: { label: labels.email, icon: <MailOutlined /> } },
      { name: "settings", list: "/settings", meta: { label: labels.settings, icon: <SettingOutlined /> } },
    ],
    [labels],
  );

  return (
    <ConfigProvider
      theme={{
        algorithm: theme.darkAlgorithm,
        ...RefineThemes.Blue,
        token: {
          colorPrimary: "#3b82f6",
          colorError: "#dc2626",
          colorBgContainer: "#1e293b",
          colorBgElevated: "#0f172a",
          colorText: "#e2e8f0",
          colorTextHeading: "#f8fafc",
          colorBorder: "#334155",
        },
      }}
    >
      <AntApp>
        <Refine
          key={labels.datacenter}
          dataProvider={dataProvider}
          routerProvider={routerBindings}
          notificationProvider={useNotificationProvider}
          resources={resources}
          options={{ syncWithLocation: true, warnWhenUnsavedChanges: true }}
        >
          <Routes>
            <Route element={<AppLayout />}>
              <Route index element={<Dashboard />} />
              <Route path="/inneros" element={<HackathonPage />} />
              <Route path="/datacenter" element={<DataCenterPage />} />
              <Route path="/entities" element={<ResourceList resource="entities" />} />
              <Route path="/clients" element={<ClientList />} />
              <Route path="/inventory" element={<ResourceList resource="inventory-items" />} />
              <Route path="/catalog" element={<ResourceList resource="catalog-products" />} />
              <Route path="/suppliers" element={<ResourceList resource="suppliers" />} />
              <Route path="/quotes" element={<ResourceList resource="quotes" />} />
              <Route path="/visits" element={<VisitList />} />
              <Route path="/reports" element={<ReportList />} />
              <Route path="/email" element={<EmailMonitorPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Route>
          </Routes>
          <UnsavedChangesNotifier />
        </Refine>
      </AntApp>
    </ConfigProvider>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <LangProvider>
        <AppRoutes />
      </LangProvider>
    </BrowserRouter>
  );
}
