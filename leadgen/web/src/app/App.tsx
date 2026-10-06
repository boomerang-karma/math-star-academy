import { useCallback, useEffect, useMemo, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import type { ApiClient } from "../api/client";
import type { Me } from "../api/types";
import type { AuthSession } from "../auth/auth";
import { Layout } from "../components/Layout";
import { ErrorNotice } from "../components/Status";
import type { RuntimeConfig } from "../config";
import { AuthCallback } from "../pages/AuthCallback";
import { EntityPage } from "../pages/EntityPage";
import { Lead360 } from "../pages/Lead360";
import { LeadList } from "../pages/LeadList";
import { NotFound } from "../pages/NotFound";
import { ReviewQueue } from "../pages/ReviewQueue";
import { SearchPage } from "../pages/SearchPage";
import { TrackedCompanies } from "../pages/TrackedCompanies";
import { AppContext } from "./context";
import type { AppContextValue } from "./context";

export function App({ config, auth, api }: { config: RuntimeConfig; auth: AuthSession; api: ApiClient }) {
  const location = useLocation();
  const onCallback = location.pathname === "/auth/callback";
  const [me, setMe] = useState<Me | null>(null);
  const [meError, setMeError] = useState<unknown>(null);
  const [nonce, setNonce] = useState(0);
  const reloadMe = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (onCallback || !auth.isAuthenticated()) {
      return;
    }
    let live = true;
    setMeError(null);
    api.me().then(
      (value) => live && setMe(value),
      (err: unknown) => live && setMeError(err),
    );
    return () => {
      live = false;
    };
  }, [api, auth, nonce, onCallback]);

  const value = useMemo<AppContextValue>(
    () => ({ api, auth, config, me, reloadMe }),
    [api, auth, config, me, reloadMe],
  );

  if (onCallback) {
    return (
      <AppContext.Provider value={value}>
        <main className="main narrow">
          <AuthCallback />
        </main>
      </AppContext.Provider>
    );
  }
  return (
    <AppContext.Provider value={value}>
      <Layout>
        {meError ? <ErrorNotice error={meError} onRetry={reloadMe} /> : null}
        <Routes>
          <Route path="/" element={<Navigate to="/leads" replace />} />
          <Route path="/leads" element={<LeadList />} />
          <Route path="/leads/:id" element={<Lead360 />} />
          <Route path="/entities/:id" element={<EntityPage />} />
          <Route path="/review" element={<ReviewQueue />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/admin/companies" element={<TrackedCompanies />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Layout>
    </AppContext.Provider>
  );
}
