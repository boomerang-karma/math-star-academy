import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { useApp, useCan } from "../app/context";
import { DEV_PERSONAS, DevAuth } from "../auth/auth";
import { humanize } from "../lib/format";

function SearchBox() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  function submit(event: FormEvent) {
    event.preventDefault();
    const term = q.trim();
    if (term.length >= 2) {
      navigate(`/search?q=${encodeURIComponent(term)}`);
    }
  }
  return (
    <form className="search" role="search" onSubmit={submit}>
      <label className="visually-hidden" htmlFor="global-search">
        Search companies and people
      </label>
      <input
        id="global-search"
        type="search"
        placeholder="Search companies and people"
        value={q}
        minLength={2}
        maxLength={100}
        onChange={(e) => setQ(e.target.value)}
      />
    </form>
  );
}

function DevPersonaPicker({ auth }: { auth: DevAuth }) {
  const { reloadMe } = useApp();
  const current = Object.entries(DEV_PERSONAS).find(([, p]) => p.user === auth.identity.user)?.[0] ?? "admin";
  return (
    <label className="persona">
      <span className="muted small">Acting as</span>
      <select
        value={current}
        onChange={(e) => {
          const persona = DEV_PERSONAS[e.target.value];
          if (persona) {
            auth.setIdentity(persona);
            reloadMe();
          }
        }}
      >
        {Object.keys(DEV_PERSONAS).map((key) => (
          <option key={key} value={key}>
            {humanize(key)}
          </option>
        ))}
      </select>
    </label>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const { auth, config, me } = useApp();
  const can = useCan();
  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <span className="brand-name">LeadIntel</span>
          {config.environment !== "prod" ? <span className="badge badge-env">{config.environment}</span> : null}
        </div>
        <nav className="nav" aria-label="Main">
          <NavLink to="/leads">Leads</NavLink>
          {can("entities:merge") ? <NavLink to="/review">Review queue</NavLink> : null}
          {can("connectors:configure") ? <NavLink to="/admin/companies">Tracked companies</NavLink> : null}
        </nav>
        <SearchBox />
        <div className="user">
          {auth instanceof DevAuth ? (
            <DevPersonaPicker auth={auth} />
          ) : (
            <>
              <span className="muted small" title={me?.subject}>
                {me ? me.roles.map(humanize).join(", ") : ""}
              </span>
              <button type="button" className="button button-quiet" onClick={() => void auth.logout()}>
                Sign out
              </button>
            </>
          )}
        </div>
      </header>
      <main id="main" className="main">
        {children}
      </main>
    </div>
  );
}
