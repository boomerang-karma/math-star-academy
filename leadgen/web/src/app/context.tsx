import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { DependencyList } from "react";

import type { ApiClient } from "../api/client";
import type { Me } from "../api/types";
import type { AuthSession } from "../auth/auth";
import type { RuntimeConfig } from "../config";

export interface AppContextValue {
  api: ApiClient;
  auth: AuthSession;
  config: RuntimeConfig;
  me: Me | null;
  reloadMe: () => void;
}

export const AppContext = createContext<AppContextValue | null>(null);

export function useApp(): AppContextValue {
  const value = useContext(AppContext);
  if (!value) {
    throw new Error("useApp must be used inside <AppContext.Provider>");
  }
  return value;
}

/** Permission check for hiding UI the API would refuse anyway (the API is the authority). */
export function useCan(): (permission: string) => boolean {
  const { me } = useApp();
  return useCallback((permission: string) => me?.permissions.includes(permission) ?? false, [me]);
}

export interface Resource<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => void;
}

/** Load data for a view; results from superseded loads are discarded. */
export function useResource<T>(load: () => Promise<T>, deps: DependencyList): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  const generation = useRef(0);

  useEffect(() => {
    const current = ++generation.current;
    setLoading(true);
    setError(null);
    load().then(
      (value) => {
        if (generation.current === current) {
          setData(value);
          setLoading(false);
        }
      },
      (err: unknown) => {
        if (generation.current === current) {
          setError(err);
          setLoading(false);
        }
      },
    );
    return () => {
      generation.current++;
    };
    // `deps` are the load's inputs (the callback itself is recreated every render).
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, loading, reload };
}
