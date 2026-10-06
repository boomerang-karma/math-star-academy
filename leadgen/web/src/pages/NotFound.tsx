import { Link } from "react-router-dom";

export function NotFound() {
  return (
    <>
      <h1>Page not found</h1>
      <p>
        <Link to="/leads">Back to leads</Link>
      </p>
    </>
  );
}
