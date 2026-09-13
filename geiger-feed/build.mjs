import { readFile, writeFile } from "node:fs/promises";

const TZ = "America/New_York";
const EVENT_LIMIT = 12;

// Tried in order. A definitive hit from any source wins; a blocked source is skipped.
const SOURCES = [
  { name: "newscentermaine", url: "https://www.newscentermaine.com/closings" },
  { name: "wgme", url: "https://wgme.com/weather/closings" },
  { name: "wmtw", url: "https://www.wmtw.com/weather/closings" },
];

const BROWSER_HEADERS = {
  "User-Agent":
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
  Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
  "Accept-Language": "en-US,en;q=0.9",
  "Cache-Control": "no-cache",
};

const DISTRICT_STRICT = /lewiston (?:public schools|school department|schools)/;
const DISTRICT_LOOSE = /\blewiston\b(?![\s\-\u2013]*(?:auburn|career|regional))/;
const NOT_DISTRICT = /\b(college|university|adult ed|head start|housing|city of|hospital)\b/;
const CLOSED = /\b(closed|closing|cancell?ed|cancellation|no school)\b/;
const DELAY = /(\d+)\s*(?:[-\u2013]|\s)?\s*hour\s+delay|\bdelay(?:ed|s)?\b/;

main();

async function main() {
  const calendar = JSON.parse(await readFile(new URL("../calendar.json", import.meta.url), "utf8"));
  const detected = await detectStatus();
  const feed = buildFeed(calendar, detected);

  await writeFile(new URL("../feed.json", import.meta.url), JSON.stringify(feed, null, 2) + "\n");

  console.log(`status: ${feed.current_status}  (source: ${feed.status_source})`);
  for (const a of detected.attempts) {
    console.log(`  ${a.source.padEnd(16)} ${a.error ?? `${a.status} [${a.confidence}] ${a.window ?? ""}`}`);
  }
}

/* ---------- scraping ---------- */

async function detectStatus() {
  const attempts = [];

  for (const source of SOURCES) {
    let html;
    try {
      const res = await fetch(source.url, { headers: BROWSER_HEADERS, redirect: "follow" });
      if (!res.ok) {
        attempts.push({ source: source.name, error: `HTTP ${res.status}` });
        continue;
      }
      html = await res.text();
    } catch (err) {
      attempts.push({ source: source.name, error: String(err) });
      continue;
    }

    const parsed = parseStatus(html);
    attempts.push({ source: source.name, ...parsed });

    // Any positive closing/delay finding is trusted immediately.
    if (parsed.status !== "School in Session") {
      return { status: parsed.status, source: source.name, attempts };
    }
    // A clean "nothing listed" is also definitive — stop here.
    if (parsed.confidence === "definitive") {
      return { status: "School in Session", source: source.name, attempts };
    }
  }

  // Every source blocked or ambiguous. Don't invent a closure.
  return { status: null, source: null, attempts };
}

function parseStatus(html) {
  const text = html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;|&#160;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/\s+/g, " ")
    .toLowerCase();

  if (/no (delays or closings|closings or delays|closings reported)/.test(text)) {
    return { status: "School in Session", confidence: "definitive", window: "empty list" };
  }

  // Full district name first. Bare "Lewiston" is a fallback, guarded so that
  // Lewiston-Auburn CC or Lewiston Adult Ed don't get read as the district.
  let idx = text.search(DISTRICT_STRICT);
  if (idx === -1) {
    const loose = text.search(DISTRICT_LOOSE);
    if (loose !== -1 && !NOT_DISTRICT.test(text.slice(loose, loose + 120))) idx = loose;
  }

  if (idx === -1) {
    // Page loaded but the district isn't listed. Only trust that if a closings
    // list actually rendered — otherwise we're probably looking at a block page.
    const rendered = /closings|delays/.test(text);
    return {
      status: "School in Session",
      confidence: rendered ? "definitive" : "weak",
      window: "district not listed",
    };
  }

  // Whichever keyword sits closest to the district name wins, so a neighbouring
  // entry's status doesn't bleed in. Check feed.json's _debug after the first
  // real storm and widen or narrow this window against the actual markup.
  const win = text.slice(idx, idx + 90);
  const closedAt = win.search(CLOSED);
  const delayMatch = win.match(DELAY);
  const delayAt = delayMatch ? win.indexOf(delayMatch[0]) : -1;

  if (closedAt !== -1 && (delayAt === -1 || closedAt < delayAt)) {
    return { status: "No School", confidence: "definitive", window: win };
  }
  if (delayAt !== -1) {
    return {
      status: delayMatch[1] ? `${delayMatch[1]}-Hour Delay` : "Delayed Start",
      confidence: "definitive",
      window: win,
    };
  }

  return { status: "School in Session", confidence: "definitive", window: win };
}

/* ---------- feed ---------- */

function buildFeed(calendar, detected) {
  const today = localDate();
  const todayEvent = calendar.events.find((e) => e.date === today);
  const dow = new Date(`${today}T12:00:00Z`).getUTCDay();

  let status;
  if (dow === 0 || dow === 6) {
    status = "Weekend";
  } else if (todayEvent && (todayEvent.type === "No School" || todayEvent.type === "Holiday")) {
    // Calendar beats the scrape — no point reporting a delay on a scheduled day off.
    status = "No School";
  } else if (detected.status) {
    status = detected.status;
  } else {
    status = "School in Session";
  }

  return {
    school_name: calendar.school_name,
    academic_year: calendar.academic_year,
    last_updated: calendar.last_updated,
    current_status: status,
    status_source: detected.source ?? "calendar",
    status_checked_at: new Date().toISOString(),
    event_limit: 5,
    events: calendar.events.filter((e) => e.date >= today).slice(0, EVENT_LIMIT),
    _debug: detected.attempts,
  };
}

function localDate() {
  // en-CA gives YYYY-MM-DD, and the TZ database handles DST for us.
  return new Intl.DateTimeFormat("en-CA", { timeZone: TZ }).format(new Date());
}
