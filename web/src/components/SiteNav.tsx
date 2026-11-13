import { useEffect, useRef } from "react";
import WhatIsReal from "./WhatIsReal";

/** Where each part of Khutlisa is. The same links on every screen: who is owed, everything for holders, the
 *  owner's own journey, estates, and the one panel that says what is real here. */
const HOLDERS = [
  { href: "/#holders", label: "Top holders" },
  { href: "/#book", label: "The whole book" },
  { href: "/#list", label: "Your own list and notices" },
  { href: "/payer#limits", label: "Your limits" },
  { href: "/payer", label: "The queue" },
  { href: "/risk", label: "Risk" },
];

export default function SiteNav() {
  const group = useRef<HTMLDetailsElement>(null);
  // The holders' menu closes when a link in it is followed or a click lands elsewhere.
  useEffect(() => {
    const away = (e: MouseEvent) => {
      if (group.current && !group.current.contains(e.target as Node)) group.current.open = false;
    };
    window.addEventListener("click", away);
    return () => window.removeEventListener("click", away);
  }, []);
  return (
    <nav className="site-nav" aria-label="Khutlisa">
      <a className="site-link" href="/#owed">Who is owed</a>
      <details className="site-group" ref={group}>
        <summary className="site-link">For holders</summary>
        <ul className="site-menu">
          {HOLDERS.map((l) => (
            <li key={l.href}>
              <a href={l.href} onClick={() => group.current && (group.current.open = false)}>{l.label}</a>
            </li>
          ))}
        </ul>
      </details>
      <a className="site-link" href="/#history">Find your money</a>
      <a className="site-link" href="/#estates">Estates</a>
      <WhatIsReal small />
    </nav>
  );
}
