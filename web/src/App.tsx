import { useEffect, useState } from "react";
import { getRegister, getTotals } from "./api";
import type { History, Match, RegisterInfo, Totals } from "./types";
import Opening from "./screens/Opening";
import HistoryScreen from "./screens/HistoryScreen";
import OwedScreen from "./screens/OwedScreen";
import HoldersScreen from "./screens/HoldersScreen";
import ClaimScreen from "./screens/ClaimScreen";
import PayoutScreen from "./screens/PayoutScreen";
import PayerScreen from "./screens/PayerScreen";
import BookScreen from "./screens/BookScreen";
import BatchScreen from "./screens/BatchScreen";
import HolderListScreen from "./outreach/HolderListScreen";
import NoticeScreen from "./outreach/NoticeScreen";
import EstateScreen from "./estate/EstateScreen";
import EstatesIntro from "./estate/EstatesIntro";
import RiskScreen from "./risk/RiskScreen";

// Where the person is. The address bar holds it after the "#", so a reload or a shared link lands on the same
// screen: "", "#history", "#claim" (details for a chosen match), "#claim/<id>", "#payout/<id>".
// The payer view is a separate address, /payer, and so is the holder's risk view, /risk. An estate claim (an owner
// who has died, paid to several heirs) is "#estate/<id>".
type Place =
  | { screen: "opening" }
  | { screen: "owed" }
  | { screen: "holders" }
  | { screen: "list" }
  | { screen: "history" }
  | { screen: "book"; id: string | null }
  | { screen: "batch"; id: string }
  | { screen: "claim"; id: string | null }
  | { screen: "payout"; id: string }
  | { screen: "estate"; id: string }
  | { screen: "estates" };

function readHash(): Place {
  const [name, raw] = window.location.hash.replace(/^#/, "").split("/");
  const id = raw ? decodeURIComponent(raw) : raw;
  if (name === "history") return { screen: "history" };
  if (name === "owed") return { screen: "owed" };
  if (name === "holders") return { screen: "holders" };
  if (name === "book") return { screen: "book", id: id || null };
  if (name === "batch" && id) return { screen: "batch", id };
  if (name === "list") return { screen: "list" };
  if (name === "claim") return { screen: "claim", id: id || null };
  if (name === "payout" && id) return { screen: "payout", id };
  if (name === "estate" && id) return { screen: "estate", id };
  if (name === "estates") return { screen: "estates" };
  return { screen: "opening" };
}

const hashOf = (place: Place) =>
  place.screen === "opening" ? "" : place.screen === "history" || place.screen === "owed" || place.screen === "holders" || place.screen === "list" || place.screen === "estates" ? `#${place.screen}` : place.id ? `#${place.screen}/${encodeURIComponent(place.id)}` : `#${place.screen}`;

const isPayer = () => window.location.pathname.replace(/\/+$/, "") === "/payer";
// A notice a holder sent: /n opens the box for the code on the letter, /n/<code> opens that notice.
const noticeCode = () => {
  const found = window.location.pathname.match(/^\/n(?:\/([^/]*))?\/?$/);
  return found ? decodeURIComponent(found[1] ?? "") : null;
};
const isRisk = () => window.location.pathname.replace(/\/+$/, "") === "/risk";

export default function App() {
  const [place, setPlace] = useState<Place>(readHash);
  const [totals, setTotals] = useState<Totals | null>(null);
  const [problem, setProblem] = useState("");
  const [chosen, setChosen] = useState<{ match: Match; history: History } | null>(null);
  const [searched, setSearched] = useState(place.screen === "history");
  const [register, setRegister] = useState<RegisterInfo | null>(null);
  // The claim the person last had open, so the top bar can take them back to it from the search.
  const [lastClaim, setLastClaim] = useState<string | null>(place.screen === "claim" || place.screen === "payout" ? place.id : null);

  useEffect(() => {
    if (isPayer() || isRisk()) return;
    getTotals()
      .then((t) =>
        // Totals of invented records must never stand in for California's figures on the opening.
        t.sample
          ? setProblem("California's totals have not been made on this server, so the opening has no figures to show. Run scripts/make_totals.py (see the README).")
          : setTotals(t))
      .catch((e: Error) => setProblem(e.message));
    getRegister().then(setRegister).catch(() => setRegister(null));
  }, []);

  useEffect(() => {
    const follow = () => setPlace(readHash());
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, []);

  useEffect(() => {
    if (isPayer() || isRisk() || noticeCode() !== null) return;
    const wanted = hashOf(place);
    if (window.location.hash !== wanted) window.history.pushState(null, "", wanted || window.location.pathname);
    if (place.screen === "history") setSearched(true);
    if ((place.screen === "claim" || place.screen === "payout") && place.id) setLastClaim(place.id);
    document.title = { opening: "Khutlisa", owed: "Khutlisa: who is owed", holders: "Khutlisa: for holders", list: "Khutlisa: the holder's list", book: "Khutlisa: the whole book", batch: "Khutlisa: a batch", history: "Khutlisa: your history", claim: "Khutlisa: your claim", payout: "Khutlisa: payment", estate: "Khutlisa: an estate", estates: "Khutlisa: estates" }[place.screen];
    window.scrollTo(0, 0);
  }, [place]);

  const home = () => {
    if (isPayer() || isRisk()) window.location.assign("/");
    else setPlace({ screen: "opening" });
  };

  if (isPayer()) return <PayerScreen onHome={home} />;
  if (isRisk()) return <RiskScreen onHome={home} />;
  const code = noticeCode();
  if (code !== null) return <NoticeScreen code={code} onHome={() => window.location.assign("/")} />;

  return (
    <>
      {place.screen === "opening" && <Opening totals={totals} problem={problem} onBegin={() => setPlace({ screen: "history" })} onOwed={() => setPlace({ screen: "owed" })} onHolders={() => setPlace({ screen: "holders" })} />}
      {place.screen === "owed" && <OwedScreen totals={totals} onHome={home} onBegin={() => setPlace({ screen: "history" })} />}
      {place.screen === "holders" && <HoldersScreen onHome={home} onOwed={() => setPlace({ screen: "owed" })} onBook={(key) => setPlace({ screen: "book", id: key })} />}
      {place.screen === "book" && (
        <BookScreen holder={place.id} onHome={home} onHolders={() => setPlace({ screen: "holders" })}
          onChoose={(key) => setPlace({ screen: "book", id: key })} onBatch={(id) => setPlace({ screen: "batch", id })} />
      )}
      {place.screen === "batch" && <BatchScreen key={place.id} batchId={place.id} onHome={home} onBook={(key) => setPlace({ screen: "book", id: key })} />}
      {place.screen === "list" && <HolderListScreen onHome={home} />}
      {/* The search stays mounted once opened, so its matches are still there when the person comes back to it. */}
      {searched && (
        <div hidden={place.screen !== "history"}>
          <HistoryScreen
            register={register}
            shown={place.screen === "history"}
            onBack={home}
            onOpenClaim={lastClaim ? () => setPlace({ screen: "claim", id: lastClaim }) : chosen ? () => setPlace({ screen: "claim", id: null }) : undefined}
            onChooseMatch={(match, history) => {
              setChosen({ match, history });
              setPlace({ screen: "claim", id: null });
            }}
          />
        </div>
      )}
      {place.screen === "claim" && (
        <ClaimScreen
          key={place.id ?? "new"}
          claimId={place.id}
          chosen={chosen}
          onCreated={(id) => setPlace({ screen: "claim", id })}
          onPayout={(id) => setPlace({ screen: "payout", id })}
          onHome={home}
          onBackToSearch={() => setPlace({ screen: "history" })}
        />
      )}
      {place.screen === "estates" && <EstatesIntro onHome={home} onEstate={(id) => setPlace({ screen: "estate", id })} />}
      {place.screen === "estate" && (
        <EstateScreen key={place.id} claimId={place.id} onHome={home} onClaim={(id) => setPlace({ screen: "claim", id })} />
      )}
      {place.screen === "payout" && (
        <PayoutScreen key={place.id} claimId={place.id} onHome={home} onClaim={(id) => setPlace({ screen: "claim", id })}
          onBackToSearch={() => setPlace({ screen: "history" })} />
      )}
    </>
  );
}
