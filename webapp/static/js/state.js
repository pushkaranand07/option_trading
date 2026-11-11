// The page's one shared state object and the instrument names.
import { store } from "./util.js";

export const S = { sym: (new URLSearchParams(location.search).get("sym") || store("sym") || "NIFTY").toUpperCase(), tf: "5m", indices: [], quotes: {}, status: {}, plan: null, expiry: null, aiJob: null,
  tab: "today",
  jrHorizon: "all",                       // My Trades
  morning: null, live: {}, extraCtx: {},  // Plan tab
  nse: {}, nseExp: {}, nseView: store("nseView") || "oi", strat: {}, stratLive: {}, research: {}, ticket: {}, view: {}, takenRank: {},
  openDetail: new Set(), recView: store("recView") === "ai" ? "ai" : "you",
  recDay: {},                             // a calendar day picked in a view: its sections show that day's trades only
  recMonth: {},                           // the month shown in each view's calendar, "YYYY-MM"; default: this month
};

export const isIndex = (sym) => S.indices.some((i) => i.symbol === sym);
export const nameOf = (sym) => S.indices.find((i) => i.symbol === sym)?.name || sym;
export const NAMES = { NIFTY: "NIFTY 50", BANKNIFTY: "NIFTY BANK" };
