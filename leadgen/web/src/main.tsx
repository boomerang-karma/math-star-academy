import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { ApiClient } from "./api/client";
import { App } from "./app/App";
import { CognitoAuth, browserEnvironment, createAuth } from "./auth/auth";
import { loadConfig } from "./config";
import "./styles.css";

function Fatal({ error }: { error: unknown }) {
  return (
    <main className="main narrow">
      <div className="notice notice-error" role="alert">
        <strong>LeadIntel could not start</strong>
        <p>{error instanceof Error ? error.message : String(error)}</p>
      </div>
    </main>
  );
}

async function bootstrap(): Promise<void> {
  const container = document.getElementById("root");
  if (!container) {
    return;
  }
  const root = createRoot(container);
  try {
    const config = await loadConfig();
    const auth = createAuth(config, browserEnvironment());
    const resume = () => window.location.pathname + window.location.search;
    if (auth instanceof CognitoAuth && !auth.isAuthenticated() && window.location.pathname !== "/auth/callback") {
      await auth.login(resume());
      return;
    }
    const api = new ApiClient(auth, undefined, () => {
      if (auth instanceof CognitoAuth) {
        auth.invalidate();
        void auth.login(resume());
      }
    });
    root.render(
      <StrictMode>
        <BrowserRouter>
          <App config={config} auth={auth} api={api} />
        </BrowserRouter>
      </StrictMode>,
    );
  } catch (error) {
    root.render(<Fatal error={error} />);
  }
}

void bootstrap();
