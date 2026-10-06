import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useApp } from "../app/context";
import { CognitoAuth } from "../auth/auth";
import { ErrorNotice, Loading } from "../components/Status";

/** Landing page for the Cognito Hosted UI redirect: swap the code for tokens, then resume. */
export function AuthCallback() {
  const { auth, reloadMe } = useApp();
  const navigate = useNavigate();
  const [error, setError] = useState<unknown>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) {
      return; // the authorization code is single-use; StrictMode would run this twice
    }
    started.current = true;
    if (!(auth instanceof CognitoAuth)) {
      navigate("/", { replace: true });
      return;
    }
    auth.handleCallback(new URL(window.location.href)).then(
      (returnTo) => {
        reloadMe();
        navigate(returnTo, { replace: true });
      },
      (err: unknown) => setError(err),
    );
  }, [auth, navigate, reloadMe]);

  if (error) {
    return (
      <>
        <ErrorNotice error={error} />
        <button type="button" className="button" onClick={() => void auth.login("/")}>
          Sign in again
        </button>
      </>
    );
  }
  return <Loading label={"Signing you in…"} />;
}
