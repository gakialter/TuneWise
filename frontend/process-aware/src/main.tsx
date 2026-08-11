import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import ProcessAwareDemo from "./ProcessAwareDemo";
import "./styles.css";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("Root element #root was not found.");
}

createRoot(rootElement).render(
  <StrictMode>
    <ProcessAwareDemo />
  </StrictMode>,
);
