import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/inter";
import "./styles.css";
import "./journey.css";
import "./story.css";
import "./cards.css";
import "./book.css";
import "./outreach/outreach.css";
import App from "./App";
import { DemoProvider } from "./demo";
import ModeBanner from "./outreach/ModeBanner";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <DemoProvider>
      <App />
      <ModeBanner />
    </DemoProvider>
  </StrictMode>,
);
