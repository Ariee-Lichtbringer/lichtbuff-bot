import "dotenv/config";
import cors from "cors";
import express from "express";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { pool, query, requireGuild } from "./db.js";

const app = express();
const port = Number(process.env.PORT || 3000);
const defaultGuildSlug = process.env.DEFAULT_GUILD_SLUG || "lichtloot";
const masterCode = process.env.MASTER_CODE || "Lichtbringer-Master";
const lichtbotQueueToken = process.env.LICHTBOT_QUEUE_TOKEN || "";
const logAnalysisCallbackToken = process.env.LOG_ANALYSIS_CALLBACK_TOKEN || "";
const p0PlusTransferExportChannelId = "1529393614247952434";
const worldbuffBackupChannelId = "1529393614247952434";
const worldbuffAnnouncementChannelId = process.env.WORLDBUFF_ANNOUNCEMENT_CHANNEL_ID || "1281152286772695071";
const masterCodeOverrides = new Map();
const worldbuffAccessCodeOverrides = new Map();
const lootMasterAccessCodeOverrides = new Map();
const worldbuffPublicCsvUrl =
  process.env.WORLDBUFF_PUBLIC_CSV_URL ||
  "https://docs.google.com/spreadsheets/d/1eItzaMGhpJ28vv4sDA8wwmu0YhUxcbiz-2VLiCVyjv4/export?format=csv&gid=1498762908";
const worldbuffTickerCsvUrl =
  process.env.WORLDBUFF_TICKER_CSV_URL ||
  "https://docs.google.com/spreadsheets/d/1o7fzOAn9wC0iWcauC3bDo2RYR8kZ1xQMjkvSi1lJG8Q/gviz/tq?tqx=out:csv&gid=0";
const p0ReleaseCsvUrl =
  process.env.P0_RELEASE_CSV_URL ||
  "https://docs.google.com/spreadsheets/d/1ejape-5N42TDUIsglYZV1uPupQxYMiUK6JE1QiPJKbE/export?format=csv&gid=0";
const warcraftLogsTokenCache = new Map();
const staticLootCache = new Map();
const missingRaidHelperCache = new Map();
const STATIC_LOOT_CACHE_TTL_MS = 5 * 60 * 1000;
const MISSING_RAID_HELPER_CACHE_TTL_MS = 5 * 60 * 1000;
let p0ReleaseCache = null;
let p0ReleaseCacheUntil = 0;
let rpbConfigAllCache = null;
let warcraftLogsNextRequestAt = 0;

const defaultAllowedOrigins = [
  "https://lichtloot.de",
  "https://www.lichtloot.de",
  "https://lichtloot-production.up.railway.app",
  "null"
];
const configuredAllowedOrigins = clean(process.env.CORS_ORIGIN)
  .split(",")
  .map(origin => origin.trim())
  .filter(Boolean);
function normalizeCorsOrigin(origin) {
  const value = clean(origin).replace(/\/+$/, "");
  if (!value || value === "null" || value === "*") return value;
  try {
    const url = new URL(value);
    return `${url.protocol}//${url.host}`.toLowerCase();
  } catch {
    return value.toLowerCase();
  }
}
const allowedOrigins = new Set([...defaultAllowedOrigins, ...configuredAllowedOrigins].map(normalizeCorsOrigin));
function isAllowedCorsOrigin(origin) {
  const normalized = normalizeCorsOrigin(origin);
  if (!normalized || allowedOrigins.has("*") || allowedOrigins.has(normalized)) return true;
  try {
    const { protocol, hostname } = new URL(normalized);
    return protocol === "https:" || protocol === "http:"
      ? Boolean(hostname)
      : false;
  } catch {
    return false;
  }
}
const corsOptions = {
  origin(origin, callback) {
    if (isAllowedCorsOrigin(origin)) {
      callback(null, true);
      return;
    }
    callback(null, false);
  },
  methods: ["GET", "POST", "OPTIONS"],
  allowedHeaders: ["Content-Type", "Authorization"],
  optionsSuccessStatus: 204
};
app.use(cors(corsOptions));
app.options("*", cors(corsOptions));
app.use("/api/combat-log/import", express.text({ type: "*/*", limit: "120mb" }));
app.use(express.json({ limit: "80mb" }));
app.use(express.urlencoded({ extended: true, limit: "80mb" }));

// Alte Lootseiten laden einzelne P0+-Bausteine noch per JSONP. Railway
// liefert normalerweise JSON; mit einem gueltigen Callback-Namen wird die
// Antwort deshalb gezielt als ausfuehrbares JSONP zurueckgegeben. Der enge
// Namensfilter verhindert, dass beliebiger JavaScript-Code eingeschleust
// werden kann.
app.use("/api/apps-script", (req, res, next) => {
  const callback = clean(req.query?.callback);
  if (req.method !== "GET" || !callback) {
    next();
    return;
  }
  if (!/^[A-Za-z_$][0-9A-Za-z_$]*$/.test(callback)) {
    res.status(400).json({ success: false, error: "Ungueltiger JSONP-Callback." });
    return;
  }

  res.json = body => {
    res.type("application/javascript");
    return res.send(`${callback}(${JSON.stringify(body)});`);
  };
  next();
});

app.use("/downloads", express.static("public/downloads"));
app.use(express.static("public", {
  setHeaders(res, filePath) {
    if (/\.(html|json)$/i.test(filePath)) {
      res.setHeader("Cache-Control", "no-store, no-cache, must-revalidate, proxy-revalidate");
      res.setHeader("Pragma", "no-cache");
      res.setHeader("Expires", "0");
    }
  }
}));

await ensureGuildApplicationSchema().catch(error => {
  console.warn("Gilden-Anfragen-Schema konnte nicht vorbereitet werden:", error.message || error);
});

await ensureGuildPinSchema().catch(error => {
  console.warn("GildenPIN-Schema konnte nicht vorbereitet werden:", error.message || error);
});

await loadMasterCodeOverrides().catch(error => {
  console.warn("Master-Code Overrides konnten nicht geladen werden:", error.message || error);
});

await ensureRaidSchema().catch(error => {
  console.warn("Raid-Schema konnte nicht vorbereitet werden:", error.message || error);
});

await ensurePrioSchema().catch(error => {
  console.warn("Prio-Schema konnte nicht vorbereitet werden:", error.message || error);
});

await ensureP0PlusAuditSchema().catch(error => {
  console.warn("P0+-Audit-Schema konnte nicht vorbereitet werden:", error.message || error);
});

await ensureDiscordChannelSchema().catch(error => {
  console.warn("Discord-Channel-Schema konnte nicht vorbereitet werden:", error.message || error);
});

await ensureRaidHelperTemplateSchema().catch(error => {
  console.warn("RaidHelper-Template-Schema konnte nicht vorbereitet werden:", error.message || error);
});

await ensureRaidHelperScheduleSchema().catch(error => {
  console.warn("RaidHelper-Schedule-Schema konnte nicht vorbereitet werden:", error.message || error);
});

await ensurePlayerRoleSchema().catch(error => {
  console.warn("Spielerrollen-Schema konnte nicht vorbereitet werden:", error.message || error);
});

await ensureBuffTables().catch(error => {
  console.warn("Buff-Tabellen konnten nicht vorbereitet werden:", error.message || error);
});

await ensureItemIdentitySchema().catch(error => {
  console.warn("Item-Eindeutigkeit konnte nicht vorbereitet werden:", error.message || error);
});

await seedDefaultLootItemsOnce().catch(error => {
  console.warn("Standard-Lootdaten konnten nicht importiert werden:", error.message || error);
});

await ensureLootItemMetadataColumns().catch(error => {
  console.warn("Item-Metadaten-Spalten konnten nicht vorbereitet werden:", error.message || error);
});

await applyLootItemCorrectionsOnce().catch(error => {
  console.warn("Lootdaten-Korrekturen konnten nicht angewendet werden:", error.message || error);
});

await applyKaeseItemIdCorrection().catch(error => {
  console.warn("Kaese-ItemID konnte nicht korrigiert werden:", error.message || error);
});

await importLootItemMetadata().catch(error => {
  console.warn("Item-Metadaten konnten nicht nach Railway übertragen werden:", error.message || error);
});

await restoreLootItemsFromStaticDataOnce().catch(error => {
  console.warn("Lootdaten-Wiederherstellung konnte nicht angewendet werden:", error.message || error);
});

await applyZgHakkariOffhandCorrectionOnce().catch(error => {
  console.warn("ZG-Hakkari-Schildhand konnte nicht korrigiert werden:", error.message || error);
});

await applyLootRaidAssignmentCorrectionsOnce().catch(error => {
  console.warn("Loot-Raid-Zuordnungen konnten nicht korrigiert werden:", error.message || error);
});

await applyEterniumLockboxRaidItemsOnce().catch(error => {
  console.warn("Eterniumschließkassette konnte nicht für alle Raids ergänzt werden:", error.message || error);
});

app.get("/health", (req, res) => {
  res.json({ success: true, service: "lichtloot-api", build: "item-create-v2" });
});

app.get("/db-health", async (req, res, next) => {
  try {
    const result = await query("select now() as now");
    res.json({ success: true, now: result.rows[0].now });
  } catch (error) {
    next(error);
  }
});

app.get("/api/foerderverein/contracts/:sha256/download", async (req, res, next) => {
  try {
    const sha256 = String(req.params.sha256 || "").trim().toLowerCase();
    if (!/^[a-f0-9]{64}$/.test(sha256)) {
      return res.status(400).json({ success: false, error: "Ungültiger Vertragslink." });
    }

    const result = await query(
      `select file_name, mime_type, file_data, file_size_bytes
       from foerderverein_contract_files
       where source_context = 'foerderverein'
         and lower(sha256) = $1
       limit 1`,
      [sha256]
    );

    const contract = result.rows[0];
    if (!contract) {
      return res.status(404).json({ success: false, error: "Vertrag nicht gefunden." });
    }

    const filename = String(contract.file_name || "vertrag.pdf").replace(/["\r\n]/g, "_");
    res.setHeader("Content-Type", contract.mime_type || "application/octet-stream");
    res.setHeader("Content-Disposition", `inline; filename="${filename}"`);
    res.setHeader("Cache-Control", "private, no-store");
    if (contract.file_size_bytes) {
      res.setHeader("Content-Length", String(contract.file_size_bytes));
    }
    res.send(contract.file_data);
  } catch (error) {
    next(error);
  }
});

app.get(["/sicherung", "/sicherung.html"], async (req, res, next) => {
  try {
    let html = "";
    try {
      html = await readFile(new URL("./sicherung.html", import.meta.url), "utf8");
    } catch {
      html = await readFile(new URL("../public/sicherung.html", import.meta.url), "utf8");
    }
    res.type("html").send(html);
  } catch (error) {
    next(error);
  }
});

app.get("/api/dashboard", async (req, res, next) => {
  try {
    const guild = await requireGuild(resolveGuildSlug(req.query.guild));
    await loadWorldbuffAccessCode(guild.id);
    await loadLootMasterAccessCode(guild.id);
    const result = await query(
      `select r.*,
              (
                select count(*)
                from p0plus_points pp
                where pp.guild_id = r.guild_id
                  and pp.source = 'Raidlead Transfer'
                  and pp.note in (
                    concat('RaidID: ', coalesce(r.external_raid_id, r.id::text)),
                    concat('RaidID: ', r.id::text),
                    concat('RaidID: ', r.raid_pin)
                  )
              ) as p0plus_transfer_count
       from raids r
       where r.guild_id = $1
         and raid_date >= current_date - interval '1 day'
         and coalesce(status, '') not in ('archiviert', 'archive')
       order by
         case when raid_date >= current_date then 0 else 1 end,
         case when raid_date >= current_date then raid_date end asc,
         case when raid_date < current_date then raid_date end desc,
         coalesce(raid_time, '') asc,
         created_at desc
       limit 50`,
      [guild.id]
    );
    const raids = result.rows.map(row => {
      const raid = normalizeRaidRow(row);
      return { ...raid, leadPin: "", LeadPin: "" };
    });
    res.json({ success: true, guild: guild.slug, raids, allRaids: raids, activeRaids: raids });
  } catch (error) {
    next(error);
  }
});

function clean(value) {
  return String(value || "").trim();
}

function prioClassOrderSql(column = "c.class_name") {
  return `case lower(coalesce(${column}, ''))
    when 'warrior' then 1
    when 'krieger' then 1
    when 'druid' then 2
    when 'druide' then 2
    when 'druiden' then 2
    when 'paladin' then 3
    when 'rogue' then 4
    when 'schurke' then 4
    when 'schurken' then 4
    when 'hunter' then 5
    when 'jaeger' then 5
    when 'jäger' then 5
    when 'priest' then 6
    when 'priester' then 6
    when 'mage' then 7
    when 'magier' then 7
    when 'warlock' then 8
    when 'hexenmeister' then 8
    when 'shaman' then 9
    when 'schamane' then 9
    when 'schamanen' then 9
    else 99
  end`;
}

function poItemAliasKey(value) {
  return clean(value)
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "");
}

const PO_ITEM_ALIASES = {
  brust4werte: "Formel: Brust - Große Werte",
  gressil: "Gressil, Vorbote des Untergangs",
  thc: "Die zehrende Kälte",
  zehrendekalte: "Die zehrende Kälte",
  diezehrendekalte: "Die zehrende Kälte"
};

function normalizePoItemName(value) {
  const raw = clean(value);
  return PO_ITEM_ALIASES[poItemAliasKey(raw)] || raw;
}

const ITEM_LOOKUP_STOP_WORDS = new Set([
  "der",
  "die",
  "das",
  "dem",
  "den",
  "des",
  "ein",
  "eine",
  "einer",
  "eines",
  "einem",
  "einen",
  "von",
  "vom",
  "und",
  "of",
  "the"
]);

await applyNaxxPoItemAliasCleanupOnce().catch(error => {
  console.warn("Naxx-PO-Item-Dubletten konnten nicht zusammengeführt werden:", error.message || error);
});

function normalizeItemLookupText(value) {
  return clean(value)
    .replace(/ä/g, "ae")
    .replace(/ö/g, "oe")
    .replace(/ü/g, "ue")
    .replace(/Ä/g, "Ae")
    .replace(/Ö/g, "Oe")
    .replace(/Ü/g, "Ue")
    .replace(/ß/g, "ss")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[’'`´]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function normalizeItemLookupToken(token) {
  let value = clean(token);
  if (value.length > 4 && value.endsWith("s")) value = value.slice(0, -1);
  return value;
}

function itemLookupTokens(value) {
  return normalizeItemLookupText(value)
    .split(/\s+/)
    .map(normalizeItemLookupToken)
    .filter(token => token && !ITEM_LOOKUP_STOP_WORDS.has(token));
}

function itemLookupKey(value) {
  return itemLookupTokens(value).join("");
}

function itemLookupTokenMatch(searchTokens, candidateTokens) {
  if (!searchTokens.length || !candidateTokens.length) return false;
  const candidateSet = new Set(candidateTokens);
  return searchTokens.every(token => candidateSet.has(token));
}

async function findExistingItemByLookupName(client, raidType, itemName) {
  const searchTokens = itemLookupTokens(itemName);
  const searchKey = itemLookupKey(itemName);
  if (!searchKey) return null;

  const result = await client.query(
    `select id, name, item_id
     from items
     where lower(raid_type) = any($1)
     order by
       case when item_id is null then 1 else 0 end,
       created_at asc`,
    [raidTypeSearchValues(raidType)]
  );

  let tokenFallback = null;
  for (const row of result.rows || []) {
    const candidateTokens = itemLookupTokens(row.name);
    if (itemLookupKey(row.name) === searchKey) return row;
    if (
      !tokenFallback &&
      searchTokens.length >= 2 &&
      itemLookupTokenMatch(searchTokens, candidateTokens)
    ) {
      tokenFallback = row;
    }
  }
  return tokenFallback;
}

function poItemAliasVariants(value) {
  const normalized = normalizePoItemName(value);
  const variants = new Set([clean(value), normalized]);
  for (const [alias, target] of Object.entries(PO_ITEM_ALIASES)) {
    if (target === normalized) variants.add(alias);
  }
  return [...variants].filter(Boolean);
}

function resolveGuildSlug(value) {
  const slug = slugify(value || defaultGuildSlug);
  if (!slug) return defaultGuildSlug;
  if (
    [
      "lichtloot",
      "lichtbringer",
      "lichtzbringer",
      "lichbringer",
      "lichtbringer-loot",
      "lichtloot-gilde"
    ].includes(slug)
  ) {
    return "lichtloot";
  }
  return slug;
}

function requireExplicitGuildSlug(value) {
  const raw = clean(value);
  if (!raw) {
    const error = new Error("Gilde fehlt. Bitte Seite mit korrektem Gildenlink öffnen.");
    error.statusCode = 400;
    throw error;
  }
  return resolveGuildSlug(raw);
}

function slugify(value) {
  return clean(value)
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/ä/g, "ae")
    .replace(/ö/g, "oe")
    .replace(/ü/g, "ue")
    .replace(/ß/g, "ss")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function itemKey(value) {
  return clean(value)
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/ä/g, "ae")
    .replace(/ö/g, "oe")
    .replace(/ü/g, "ue")
    .replace(/ß/g, "ss")
    .replace(/['’`´]/g, "")
    .replace(/[-–—]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeIconName(icon) {
  return clean(icon)
    .replace(/\.jpg$/i, "")
    .replace(/\.blp$/i, "")
    .replace(/^https:\/\/wow\.zamimg\.com\/images\/wow\/icons\/large\//i, "")
    .replace(/^Interface\\Icons\\/i, "")
    .replace(/^interface\\icons\\/i, "")
    .toLowerCase();
}

function toWarcraftLogsSlug(value) {
  return clean(value)
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/ä/g, "a")
    .replace(/ö/g, "o")
    .replace(/ü/g, "u")
    .replace(/ß/g, "ss")
    .replace(/['’`´]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function warcraftLogsBaseUrl() {
  return clean(process.env.WCL_BASE_URL || "https://vanilla.warcraftlogs.com").replace(/\/+$/g, "");
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function waitForWarcraftLogsSlot() {
  const minDelayMs = Number(process.env.WCL_REQUEST_DELAY_MS || 350);
  const now = Date.now();
  const waitMs = Math.max(0, warcraftLogsNextRequestAt - now);
  warcraftLogsNextRequestAt = Math.max(now, warcraftLogsNextRequestAt) + minDelayMs;
  if (waitMs > 0) await sleep(waitMs);
}

function readableWarcraftLogsHttpError(status, text) {
  if (status === 429) {
    return "Warcraft Logs blockt gerade wegen zu vieler Anfragen. Bitte 1-2 Minuten warten und den Import erneut starten.";
  }
  if (status === 502) {
    return "Warcraft Logs Vanilla antwortet gerade mit 502. Bitte in 1-2 Minuten erneut versuchen.";
  }
  const cleaned = clean(String(text || "").replace(/<[^>]*>/g, " ").replace(/\s+/g, " ")).slice(0, 220);
  return `Warcraft Logs antwortet mit HTTP ${status}${cleaned ? `: ${cleaned}` : ""}`;
}

async function getWarcraftLogsAccessToken() {
  const clientId = clean(process.env.WCL_CLIENT_ID);
  const clientSecret = clean(process.env.WCL_CLIENT_SECRET);
  const baseUrl = warcraftLogsBaseUrl();

  if (!clientId || !clientSecret) {
    const error = new Error("Warcraft-Logs-Zugang fehlt. Bitte WCL_CLIENT_ID und WCL_CLIENT_SECRET in Railway eintragen.");
    error.needsSetup = true;
    throw error;
  }

  const cached = warcraftLogsTokenCache.get(baseUrl);
  if (cached && cached.expiresAt > Date.now() + 30_000) return cached.token;

  const response = await fetch(`${baseUrl}/oauth/token`, {
    method: "POST",
    headers: {
      Authorization: `Basic ${Buffer.from(`${clientId}:${clientSecret}`).toString("base64")}`,
      "Content-Type": "application/x-www-form-urlencoded"
    },
    body: new URLSearchParams({ grant_type: "client_credentials" })
  });
  const text = await response.text();

  if (!response.ok) {
    throw new Error(`Token konnte nicht geholt werden (${response.status}): ${text}`);
  }

  const data = JSON.parse(text);
  if (!data.access_token) throw new Error("Warcraft Logs lieferte keinen Access Token.");

  warcraftLogsTokenCache.set(baseUrl, {
    token: data.access_token,
    expiresAt: Date.now() + Math.max(60, Number(data.expires_in || 3600) - 120) * 1000
  });
  return data.access_token;
}

async function warcraftLogsGraphql(token, gqlQuery, variables = {}) {
  const baseUrl = warcraftLogsBaseUrl();
  let status = 0;
  let text = "";

  for (let attempt = 1; attempt <= 5; attempt += 1) {
    await waitForWarcraftLogsSlot();
    const response = await fetch(`${baseUrl}/api/v2/client`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ query: gqlQuery, variables })
    });
    status = response.status;
    text = await response.text();

    if (response.ok) break;
    if (![429, 500, 502, 503, 504].includes(status) || attempt === 5) break;
    const retryAfterSeconds = Number(response.headers.get("retry-after") || 0);
    const retryDelay = retryAfterSeconds > 0 ? retryAfterSeconds * 1000 : (status === 429 ? 2500 * attempt : 700 * attempt);
    await sleep(retryDelay);
  }

  if (status < 200 || status >= 300) {
    throw new Error(readableWarcraftLogsHttpError(status, text));
  }

  const data = JSON.parse(text);
  if (data.errors?.length) {
    throw new Error(data.errors.map(error => error.message).join("; "));
  }

  return data.data || {};
}

async function fetchWarcraftLogsCharacter(token, character, serverSlug, region) {
  const gqlQuery =
    "query($name:String!,$serverSlug:String!,$serverRegion:String!){"+
    "characterData{"+
    "character(name:$name,serverSlug:$serverSlug,serverRegion:$serverRegion){"+
    "id name recentReports(limit:8){data{code title startTime}}"+
    "}"+
    "}"+
    "}";

  const data = await warcraftLogsGraphql(token, gqlQuery, {
    name: character,
    serverSlug,
    serverRegion: region
  });
  const found = data.characterData?.character;
  if (!found) throw new Error("Charakter wurde bei Warcraft Logs nicht gefunden.");
  return found;
}

async function fetchWarcraftLogsReportGear(token, reportCode, character, server) {
  const actorQuery =
    "query($code:String!){"+
    "reportData{report(code:$code){fights{ id name startTime endTime } masterData{actors{ id name server type subType }}}}"+
    "}";
  const actorData = await warcraftLogsGraphql(token, actorQuery, { code: reportCode });
  const report = actorData.reportData?.report || {};
  const actors = report.masterData?.actors || [];
  const actor =
    actors.find(actorRow =>
      itemKey(actorRow.name) === itemKey(character) &&
      (!server || itemKey(actorRow.server) === itemKey(server) || !actorRow.server)
    ) ||
    actors.find(actorRow => itemKey(actorRow.name) === itemKey(character));

  if (!actor?.id) return null;

  const fights = (report.fights || [])
    .filter(fight => Number(fight.id) && Number(fight.endTime) > Number(fight.startTime))
    .sort((a, b) => Number(b.startTime || 0) - Number(a.startTime || 0));
  if (!fights.length) return null;

  const eventQuery =
    "query($code:String!,$sourceID:Int!,$fightIDs:[Int]){"+
    "reportData{report(code:$code){events(dataType:CombatantInfo,sourceID:$sourceID,fightIDs:$fightIDs,limit:1){data}}}"+
    "}";

  for (const fight of fights) {
    const eventData = await warcraftLogsGraphql(token, eventQuery, {
      code: reportCode,
      sourceID: Number(actor.id),
      fightIDs: [Number(fight.id)]
    });
    const eventsRaw = eventData.reportData?.report?.events?.data || [];
    const events = typeof eventsRaw === "string" ? JSON.parse(eventsRaw) : eventsRaw;
    const combatantInfo = Array.isArray(events) ? events[0] : events;
    const items = normalizeWarcraftLogsGear(combatantInfo?.gear || []);
    const talents = normalizeWarcraftLogsTalents(combatantInfo);

    if (items.length) {
      return {
        items,
        className: actor.subType || actor.type || "",
        talents,
        rawTalents: combatantInfo?.talents || combatantInfo?.talentTree || combatantInfo?.specs || combatantInfo?.spec || null,
        rawStats: combatantInfo?.stats || combatantInfo?.expansion || null,
        fight: {
          id: fight.id,
          name: fight.name || "",
          startTime: fight.startTime || "",
          endTime: fight.endTime || ""
        }
      };
    }
  }

  return null;
}

function inferRaidTypeFromLogText(value) {
  const text = clean(value).toLowerCase();
  if (!text) return "";

  const checks = [
    ["AQ40", ["aq40", "ahn'qiraj", "ahn qiraj", "temple of ahn", "tempel von ahn"]],
    ["AQ20", ["aq20", "ruins of ahn", "ruinen von ahn"]],
    ["BWL", ["bwl", "blackwing lair", "pechschwingenhort"]],
    ["MC", ["mc", "molten core", "geschmolzener kern"]],
    ["NAXX", ["naxx", "naxxramas"]],
    ["ZG", ["zg", "zul'gurub", "zulgurub"]],
    ["ONY", ["ony", "onyxia", "onixia"]]
  ];

  for (const [raid, terms] of checks) {
    if (terms.some(term => text.includes(term))) return raid;
  }
  return "";
}

function formatDateInBerlin(date) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Europe/Berlin",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  }).format(date);
}

async function fetchWarcraftLogsReportMeta(reportCode) {
  const token = await getWarcraftLogsAccessToken();
  const gqlQuery =
    "query($code:String!){"+
    "reportData{report(code:$code){title startTime fights{ name startTime endTime }}}"+
    "}";
  const data = await warcraftLogsGraphql(token, gqlQuery, { code: reportCode });
  const report = data.reportData?.report || {};
  const fights = Array.isArray(report.fights) ? report.fights : [];
  const fightNames = fights.map(fight => fight.name || "").join(" ");
  const startTime = Number(report.startTime || fights.find(fight => Number(fight.startTime))?.startTime || 0);
  const raidDate = startTime ? formatDateInBerlin(new Date(startTime)) : "";
  const raid = inferRaidTypeFromLogText([report.title || "", fightNames].join(" "));

  return {
    title: clean(report.title),
    raid,
    raidDate
  };
}

async function fetchWarcraftLogsReportMetaSafe(reportCode) {
  try {
    return await fetchWarcraftLogsReportMeta(reportCode);
  } catch (error) {
    console.warn("Warcraft-Logs-Metadaten konnten nicht geladen werden:", error.message || error);
    return {};
  }
}

function normalizeWarcraftLogsGear(gear) {
  const slotNames = {
    0: "Kopf", 1: "Hals", 2: "Schultern", 3: "Hemd", 4: "Brust", 5: "Taille",
    6: "Beine", 7: "Füße", 8: "Handgelenke", 9: "Hände", 10: "Ring 1", 11: "Ring 2",
    12: "Schmuck 1", 13: "Schmuck 2", 14: "Rücken", 15: "Waffenhand", 16: "Schildhand", 17: "Distanz"
  };

  return (Array.isArray(gear) ? gear : []).map((item, index) => {
    const id = item.id || item.itemID || item.itemId || "";
    const slot = item.slot !== undefined && item.slot !== null && item.slot !== "" ? item.slot : index;
    return {
      slot,
      slotName: slotNames[slot] || String(slot || "Slot"),
      id,
      itemId: id,
      name: item.name || item.itemName || (id ? `Item ${id}` : "Unbekannt"),
      quality: item.quality || "",
      icon: normalizeIconName(item.icon || item.iconName || ""),
      itemLevel: item.itemLevel || item.ilvl || "",
      permanentEnchant: item.permanentEnchant || item.permanentEnchantName || item.enchant || "",
      permanentEnchantName: item.permanentEnchantName || item.enchantName || "",
      enchantments: normalizeWarcraftLogsEnchantments(item),
      gems: normalizeWarcraftLogsGems(item.gems || item.gem || item.socketedGems || [])
    };
  }).filter(item => item.id);
}

function normalizeWarcraftLogsEnchantments(item) {
  const enchants = [];
  if (item.permanentEnchant || item.permanentEnchantName || item.enchant || item.enchantName) {
    enchants.push({
      id: item.permanentEnchant || item.enchant || "",
      name: item.permanentEnchantName || item.enchantName || "",
      type: "PERMANENT"
    });
  }

  (Array.isArray(item.enchantments || item.enchants) ? (item.enchantments || item.enchants) : []).forEach(enchant => {
    if (!enchant) return;
    enchants.push({
      id: enchant.id || enchant.enchantment_id || enchant.enchantmentId || enchant.spellID || enchant.spellId || "",
      name: enchant.name || enchant.enchantmentName || enchant.spellName || "",
      type: enchant.type || enchant.enchantment_slot?.type || ""
    });
  });

  return enchants;
}

function normalizeWarcraftLogsGems(gems) {
  return (Array.isArray(gems) ? gems : [gems]).filter(Boolean).map(gem => {
    if (typeof gem === "string" || typeof gem === "number") return { id: gem, name: "" };
    return {
      id: gem.id || gem.itemID || gem.itemId || "",
      name: gem.name || gem.itemName || "",
      icon: normalizeIconName(gem.icon || gem.iconName || "")
    };
  });
}

function normalizeWarcraftLogsTalents(combatantInfo) {
  if (!combatantInfo) return [];
  const rawTalents = combatantInfo.talents || combatantInfo.talentTree || combatantInfo.specs || combatantInfo.spec || [];

  if (
    Array.isArray(rawTalents) &&
    rawTalents.length &&
    rawTalents.every(talent => typeof talent === "number" || /^\d+$/.test(String(talent || "")))
  ) {
    return [{ name: "Spec", rank: rawTalents.join("/") + (rawTalents.length === 2 ? "/0" : ""), type: "spec", trees: rawTalents }];
  }

  const talents = [];
  const addTalent = (talent, treeName = "") => {
    if (!talent) return;
    if (typeof talent === "string") {
      talents.push({ name: talent, rank: "", tree: treeName });
      return;
    }
    const name = talent.name || talent.talentName || talent.abilityName || talent.spellName || talent.id || talent.guid || "";
    const rank = talent.rank || talent.points || talent.amount || talent.value || "";
    if (name || rank) {
      talents.push({
        name: String(name || "Talent"),
        rank,
        tree: treeName || talent.tree || talent.treeName || talent.category || "",
        id: talent.id || talent.guid || talent.spellID || talent.spellId || ""
      });
    }
  };

  if (Array.isArray(rawTalents)) {
    rawTalents.forEach(talent => {
      if (talent && Array.isArray(talent.talents)) {
        talent.talents.forEach(child => addTalent(child, talent.name || talent.tree || talent.treeName || ""));
      } else {
        addTalent(talent);
      }
    });
  } else if (typeof rawTalents === "object") {
    Object.keys(rawTalents).forEach(key => {
      const value = rawTalents[key];
      if (Array.isArray(value)) value.forEach(talent => addTalent(talent, key));
      else if (typeof value === "object") addTalent(value, key);
      else if (value) addTalent({ name: key, rank: value });
    });
  }

  return talents;
}

async function getCharacterGearFromWCL({ query: params }) {
  const character = clean(params.character || params.player);
  const server = clean(params.server);
  const region = clean(params.region || process.env.WCL_REGION || "EU").toUpperCase();

  if (!character || !server) {
    return { success: false, error: "Bitte zuerst Charakter und Server auswählen." };
  }

  try {
    const token = await getWarcraftLogsAccessToken();
    const serverSlug = toWarcraftLogsSlug(server);
    const characterInfo = await fetchWarcraftLogsCharacter(token, character, serverSlug, region);
    const reports = (characterInfo.recentReports?.data || [])
      .sort((a, b) => Number(b.startTime || 0) - Number(a.startTime || 0));

    for (const report of reports.slice(0, 8)) {
      const gearResult = await fetchWarcraftLogsReportGear(token, report.code, character, server);
      if (gearResult?.items?.length) {
        return {
          success: true,
          source: "Warcraft Logs",
          character: characterInfo.name || character,
          server,
          region,
          report: {
            code: report.code,
            title: report.title || "",
            startTime: report.startTime || ""
          },
          fight: gearResult.fight || null,
          items: gearResult.items,
          className: gearResult.className || "",
          talents: gearResult.talents || [],
          rawTalents: gearResult.rawTalents || null,
          rawStats: gearResult.rawStats || null
        };
      }
    }

    return { success: false, character, server, error: "Keine Ausrüstung in den letzten Warcraft-Logs-Reports gefunden." };
  } catch (error) {
    return {
      success: false,
      needsSetup: Boolean(error.needsSetup),
      error: `Warcraft-Logs-Import fehlgeschlagen: ${error.message}`
    };
  }
}

function buildLootSlug(guildName, lootName) {
  const explicit = slugify(lootName);
  if (explicit) return explicit;
  const base = slugify(guildName);
  return base ? `${base}-loot` : "";
}

const defaultNewGuildRaidImages = {
  mc: "images/raid-templates/mc.jpg",
  bwl: "images/raid-templates/bwl.jpg",
  ony: "images/raid-templates/ony.jpg",
  aq40: "images/raid-templates/aq40.jpg",
  aq20: "images/raid-templates/aq20.jpg",
  naxx: "images/raid-templates/naxx.jpg",
  zg: "images/raid-templates/zg.jpg",
  "zg-mittwoch": "images/raid-templates/zg.jpg",
  "zg-prime": "images/raid-templates/zg.jpg",
  "zg-late": "images/raid-templates/zg.jpg"
};
const defaultNewGuildLogoUrl = "images/guild-defaults/default-logo.png";

function defaultGuildLayoutForSlug(slug) {
  if (String(slug || "").trim().toLowerCase() === "lichtloot") return {};
  return { raidImages: {} };
}

function guildLogoUrlForSlug(slug, logoUrl) {
  const cleanLogo = clean(logoUrl);
  const cleanSlug = String(slug || "").trim().toLowerCase();
  if (cleanSlug === "lichtloot") return cleanLogo || "images/content.png";
  if (!cleanLogo || cleanLogo === "images/content.png" || cleanLogo === "./images/content.png") {
    return defaultNewGuildLogoUrl;
  }
  return cleanLogo;
}

function mergeGuildLayoutDefaults(slug, layout) {
  const existing = layout && typeof layout === "object" && !Array.isArray(layout) ? layout : {};
  const defaults = defaultGuildLayoutForSlug(slug);
  return {
    ...defaults,
    ...existing,
    raidImages: {
      ...(defaults.raidImages || {}),
      ...(existing.raidImages || {})
    }
  };
}

async function listGuilds() {
  await ensureGuildLayoutSchema();
  await ensureGuildDiscordConfigSchema();
  let result = await query(
    `select g.slug, g.name, g.server,
            case when g.slug = 'lichtloot' then 'Lichtbringer' else coalesce(nullif(g.name, ''), g.slug) end as guild_pin,
            g.logo_url, g.background_url, g.discord_guild_id, g.created_at,
            coalesce(gs.points_label, 'P0/P0+') as points_label,
            coalesce(gs.primary_color, '#facc15') as primary_color,
            coalesce(gs.accent_color, '#1d4ed8') as accent_color,
            coalesce(gs.layout_json, '{}'::jsonb) as layout_json
     from guilds g
     left join guild_settings gs on gs.guild_id = g.id
     order by g.created_at asc, g.name asc`
  );
  return {
    success: true,
    guilds: result.rows.map(row => ({
      slug: row.slug,
      name: row.name,
      server: row.server || "",
      guildPin: row.guild_pin || "",
      logoUrl: guildLogoUrlForSlug(row.slug, row.logo_url),
      backgroundUrl: row.background_url || "",
      discordGuildId: row.discord_guild_id || "",
      pointsLabel: row.points_label || "P0/P0+",
      primaryColor: row.primary_color || "#facc15",
      accentColor: row.accent_color || "#1d4ed8",
      layout: mergeGuildLayoutDefaults(row.slug, row.layout_json || {}),
      createdAt: row.created_at
    }))
  };
}

async function ensureGuildDiscordConfigSchema() {
  await query(`alter table guilds add column if not exists discord_guild_id text not null default ''`);
}

async function listGuildsForBot({ query: params }) {
  requireMasterOrQueueToken(params);
  await ensureGuildDiscordConfigSchema();
  await ensureGuildLayoutSchema();
  const result = await query(
    `select g.slug,
            g.name,
            g.server,
            g.discord_guild_id,
            coalesce(gs.layout_json, '{}'::jsonb) as layout_json,
            coalesce(nullif(g.discord_guild_id, ''), (
              select nullif(ga.discord_guild_id, '')
              from guild_applications ga
              where ga.guild_slug = g.slug
                 or lower(ga.guild_name) = lower(g.name)
                 or lower(ga.loot_name) = lower(g.name)
              order by ga.setup_completed_at desc nulls last, ga.updated_at desc
              limit 1
            ), '') as resolved_discord_guild_id
     from guilds g
     left join guild_settings gs on gs.guild_id = g.id
     order by g.created_at asc, g.name asc`
  );
  return {
    success: true,
    guilds: result.rows.map(row => ({
      slug: row.slug,
      name: row.name,
      server: row.server || "",
      discordGuildId: row.resolved_discord_guild_id || row.discord_guild_id || "",
      layout: row.layout_json && typeof row.layout_json === "object" ? row.layout_json : {}
    }))
  };
}

async function ensureGuildLayoutSchema() {
  await query(
    `alter table guild_settings
       add column if not exists layout_json jsonb not null default '{}'::jsonb`
  );
}

async function ensureNewGuildAdminPlayerLogin(client, guildId, guildSlug, guildPin, server) {
  const slug = clean(guildSlug).toLowerCase();
  const pin = normalizePin(guildPin);
  if (!pin || !slug || slug === "lichtloot") return null;
  await ensurePlayerRoleSchema();

  const playerResult = await client.query(
    `insert into players (guild_id, player_pin, role, approval_status, approved_at, approved_by)
     values ($1, $2, 'admin', 'approved', now(), 'Gildenanlage')
     on conflict (guild_id, player_pin) do update
       set role = case when players.role in ('', 'member', 'spieler') then 'admin' else players.role end,
           approval_status = 'approved',
           approved_at = coalesce(players.approved_at, now()),
           approved_by = coalesce(nullif(players.approved_by, ''), 'Gildenanlage'),
           updated_at = now()
     returning id, player_pin`,
    [guildId, pin]
  );
  const player = playerResult.rows[0];
  await client.query(
    `insert into characters (player_id, name, server, class_name, is_main)
     select $1, 'Admin', coalesce(nullif($2, ''), 'Everlook'), 'Gildenleitung', true
     where not exists (
       select 1 from characters
       where player_id = $1
         and lower(name) = 'admin'
     )`,
    [player.id, clean(server)]
  );
  return player;
}

async function createGuild({ query: params }) {
  const guildName = clean(params.guildName || params.name);
  const lootName = clean(params.lootName || params.slugName);
  const server = clean(params.server);
  const guildPin = normalizePin(params.guildPin || params.guild_pin);
  const slug = buildLootSlug(guildName, lootName);

  if (!guildName || !slug) {
    const error = new Error("Bitte Gildenname und Lootsystem-Name angeben.");
    error.statusCode = 400;
    throw error;
  }

  const client = await pool.connect();
  try {
    await client.query("begin");
    if (guildPin) {
      const duplicate = await client.query(
        "select slug from guilds where lower(guild_pin) = lower($1) and slug <> $2 limit 1",
        [guildPin, slug]
      );
      if (duplicate.rows.length) {
        const error = new Error("Dieser GildenPIN ist bereits vergeben.");
        error.statusCode = 409;
        throw error;
      }
    }

    const defaultLogoUrl = slug === "lichtloot" ? "" : defaultNewGuildLogoUrl;
    const guildResult = await client.query(
      `insert into guilds (name, slug, server, guild_pin, logo_url)
       values ($1, $2, $3, nullif($4, ''), $5)
       on conflict (slug) do update
         set name = excluded.name,
             server = coalesce(nullif(excluded.server, ''), guilds.server),
             guild_pin = coalesce(excluded.guild_pin, guilds.guild_pin),
             logo_url = coalesce(nullif(guilds.logo_url, ''), excluded.logo_url),
             updated_at = now()
       returning id, name, slug, server, created_at`,
      [guildName, slug, server || null, guildPin, defaultLogoUrl]
    );

    await client.query(
      `insert into guild_settings (guild_id, layout_json)
       values ($1, $2::jsonb)
       on conflict (guild_id) do nothing`,
      [guildResult.rows[0].id, JSON.stringify(defaultGuildLayoutForSlug(guildResult.rows[0].slug))]
    );

    if (guildPin) {
      await saveGuildMasterCodeValue(client, guildResult.rows[0].id, guildPin);
      await ensureNewGuildAdminPlayerLogin(
        client,
        guildResult.rows[0].id,
        guildResult.rows[0].slug,
        guildPin,
        guildResult.rows[0].server || server
      );
    }

    await client.query("commit");
    const guild = guildResult.rows[0];
    return {
      success: true,
      guild: {
        slug: guild.slug,
        name: guild.name,
        server: guild.server || "",
        guildPin,
        createdAt: guild.created_at
      },
      guildSlug: guild.slug,
      guildPin,
      startUrl: makeGuildPageUrl("start.html", guild.slug, params),
      leadershipUrl: makeGuildPageUrl("gildenleitung.html", guild.slug, params)
    };
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function updateGuildConfig({ query: params, body = {} }) {
  await ensureGuildLayoutSchema();
  const values = { ...params, ...body };
  const slug = clean(values.guild || values.slug);
  if (!slug) {
    const error = new Error("Gilde fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const guild = await requireGuild(resolveGuildSlug(slug));
  const name = clean(values.guildName || values.name);
  const server = clean(values.server);
  const logoUrl = clean(values.logoUrl || values.logo_url);
  const backgroundUrl = clean(values.backgroundUrl || values.background_url);
  const pointsLabel = clean(values.pointsLabel || values.points_label);
  const primaryColor = clean(values.primaryColor || values.primary_color);
  const accentColor = clean(values.accentColor || values.accent_color);
  let layoutJson = values.layout || values.layoutJson || values.layout_json || null;
  if (typeof layoutJson === "string") {
    try {
      layoutJson = JSON.parse(layoutJson);
    } catch (error) {
      layoutJson = null;
    }
  }
  if (!layoutJson || typeof layoutJson !== "object" || Array.isArray(layoutJson)) {
    layoutJson = {};
  }

  const client = await pool.connect();
  try {
    await client.query("begin");
    const guildResult = await client.query(
      `update guilds
       set name = coalesce(nullif($2, ''), name),
           server = coalesce(nullif($3, ''), server),
           logo_url = coalesce(nullif($4, ''), logo_url),
           background_url = coalesce(nullif($5, ''), background_url),
           updated_at = now()
       where id = $1
       returning slug, name, server, logo_url, background_url, created_at`,
      [guild.id, name, server, logoUrl, backgroundUrl]
    );

    await client.query(
      `insert into guild_settings (guild_id, points_label, primary_color, accent_color, layout_json)
       values ($1, coalesce(nullif($2, ''), 'P0/P0+'), coalesce(nullif($3, ''), '#facc15'), coalesce(nullif($4, ''), '#1d4ed8'), $5::jsonb)
       on conflict (guild_id) do update
         set points_label = coalesce(nullif(excluded.points_label, ''), guild_settings.points_label),
             primary_color = coalesce(nullif(excluded.primary_color, ''), guild_settings.primary_color),
             accent_color = coalesce(nullif(excluded.accent_color, ''), guild_settings.accent_color),
             layout_json = case when excluded.layout_json = '{}'::jsonb then guild_settings.layout_json else excluded.layout_json end,
             updated_at = now()`,
      [guild.id, pointsLabel, primaryColor, accentColor, JSON.stringify(layoutJson)]
    );

    const settingsResult = await client.query(
      `select points_label, primary_color, accent_color, layout_json from guild_settings where guild_id = $1`,
      [guild.id]
    );

    await client.query("commit");
    const row = guildResult.rows[0];
    return {
      success: true,
      guild: {
        slug: row.slug,
        name: row.name,
        server: row.server || "",
        logoUrl: guildLogoUrlForSlug(row.slug, row.logo_url),
        backgroundUrl: row.background_url || "",
        pointsLabel: settingsResult.rows[0]?.points_label || "P0/P0+",
        primaryColor: settingsResult.rows[0]?.primary_color || "#facc15",
        accentColor: settingsResult.rows[0]?.accent_color || "#1d4ed8",
        layout: mergeGuildLayoutDefaults(row.slug, settingsResult.rows[0]?.layout_json || {}),
        createdAt: row.created_at
      }
    };
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function ensureGuildPinSchema() {
  await query(
    `alter table guilds
       add column if not exists guild_pin text`
  );
  await query(
    `create unique index if not exists idx_guilds_guild_pin_lower
       on guilds (lower(guild_pin))
       where guild_pin is not null and guild_pin <> ''`
  );
}

async function resolveGuildByPin({ query: params, body = {} }) {
  await ensureGuildPinSchema();
  const values = { ...params, ...body };
  const pin = normalizePin(values.guildPin || values.gildenPin || values.pin);
  if (!pin) {
    const error = new Error("Bitte GildenPIN eingeben.");
    error.statusCode = 400;
    throw error;
  }
  if (pin === "LICHTBRINGER") {
    const fallback = await query(
      `select slug, name, server, logo_url, background_url
       from guilds
       where slug = 'lichtloot'
       limit 1`
    );
    const row = fallback.rows[0];
    if (!row) {
      const error = new Error("GildenPIN wurde nicht gefunden.");
      error.statusCode = 404;
      throw error;
    }
    return {
      success: true,
      guild: {
        slug: row.slug,
        name: "Lichtbringer",
        server: row.server || "",
        logoUrl: guildLogoUrlForSlug(row.slug, row.logo_url),
        backgroundUrl: row.background_url || ""
      },
      guildSlug: row.slug,
      startUrl: makeGuildPageUrl("start.html", row.slug, values),
      leadershipUrl: makeGuildPageUrl("gildenleitung.html", row.slug, values)
    };
  }
  const result = await query(
    `select slug, name, server, logo_url, background_url
     from guilds
     where lower(guild_pin) = lower($1)
        or lower(name) = lower($1)
        or lower(slug) = lower($1)
     limit 1`,
    [pin]
  );
  let row = result.rows[0];
  if (!row && pin === "LICHTBRINGER") {
    const fallback = await query(
      `select slug, name, server, logo_url, background_url
       from guilds
       where slug = 'lichtloot'
       limit 1`
    );
    row = fallback.rows[0];
  }
  if (!row) {
    const error = new Error("GildenPIN wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }
  return {
    success: true,
    guild: {
      slug: row.slug,
      name: row.name || "",
      server: row.server || "",
      logoUrl: guildLogoUrlForSlug(row.slug, row.logo_url),
      backgroundUrl: row.background_url || ""
    },
    guildSlug: row.slug,
    startUrl: makeGuildPageUrl("start.html", row.slug, values),
    leadershipUrl: makeGuildPageUrl("gildenleitung.html", row.slug, values)
  };
}

async function ensureGuildApplicationSchema() {
  await query(
    `create table if not exists guild_applications (
       id uuid primary key default gen_random_uuid(),
       guild_name text not null,
       loot_name text not null default '',
       server text not null default '',
       contact_name text not null default '',
       contact_discord text not null default '',
       contact_email text not null default '',
       discord_guild_id text not null default '',
       desired_guild_pin text not null default '',
       notes text not null default '',
       status text not null default 'pending',
       setup_token text unique,
       setup_token_expires_at timestamptz,
       approved_by text,
       approved_at timestamptz,
       rejected_at timestamptz,
       setup_completed_at timestamptz,
       guild_slug text,
       guild_pin text,
       logo_url text not null default '',
       background_url text not null default '',
       primary_color text not null default '#facc15',
       accent_color text not null default '#1d4ed8',
       database_status text not null default 'pending',
       created_at timestamptz not null default now(),
       updated_at timestamptz not null default now()
     )`
  );
  await query(
    `alter table guild_applications
       add column if not exists setup_completed_at timestamptz,
       add column if not exists guild_slug text,
       add column if not exists guild_pin text,
       add column if not exists logo_url text not null default '',
       add column if not exists background_url text not null default '',
       add column if not exists primary_color text not null default '#facc15',
       add column if not exists accent_color text not null default '#1d4ed8',
       add column if not exists database_status text not null default 'pending'`
  );
}

function getPublicBaseUrl(params = {}) {
  return clean(params.baseUrl || params.origin || process.env.PUBLIC_BASE_URL || "https://lichtloot.de").replace(/\/+$/, "");
}

function makeGuildPageUrl(page, slug, params = {}) {
  const baseUrl = getPublicBaseUrl(params);
  const safePage = clean(page).replace(/^\/+/, "") || "start.html";
  const url = new URL(`${baseUrl}/${safePage}`);
  url.searchParams.set("guild", resolveGuildSlug(slug));
  return url.toString();
}

function makeGuildSetupUrl(token, params = {}) {
  return `${getPublicBaseUrl(params)}/gilde-einrichten.html?token=${encodeURIComponent(token)}`;
}

function normalizeGuildApplicationRow(row, params = {}) {
  const token = clean(row.setup_token);
  return {
    id: row.id,
    guildName: row.guild_name || "",
    lootName: row.loot_name || "",
    server: row.server || "",
    contactName: row.contact_name || "",
    contactDiscord: row.contact_discord || "",
    contactEmail: row.contact_email || "",
    discordGuildId: row.discord_guild_id || "",
    desiredGuildPin: row.desired_guild_pin || "",
    notes: row.notes || "",
    status: row.status || "pending",
    setupToken: token,
    setupUrl: token ? makeGuildSetupUrl(token, params) : "",
    setupTokenExpiresAt: row.setup_token_expires_at || null,
    approvedBy: row.approved_by || "",
    approvedAt: row.approved_at || null,
    rejectedAt: row.rejected_at || null,
    setupCompletedAt: row.setup_completed_at || null,
    guildSlug: row.guild_slug || "",
    guildPin: row.guild_pin || "",
    logoUrl: guildLogoUrlForSlug(row.guild_slug, row.logo_url),
    backgroundUrl: row.background_url || "",
    primaryColor: row.primary_color || "#facc15",
    accentColor: row.accent_color || "#1d4ed8",
    databaseStatus: row.database_status || "pending",
    createdAt: row.created_at || null,
    updatedAt: row.updated_at || null
  };
}

async function submitGuildApplication({ query: params, body = {} }) {
  await ensureGuildApplicationSchema();
  const values = { ...params, ...body };
  const guildName = clean(values.guildName || values.guild_name);
  const lootName = clean(values.lootName || values.loot_name);
  const server = clean(values.server);
  const contactName = clean(values.contactName || values.contact_name);
  const contactDiscord = clean(values.contactDiscord || values.contact_discord);
  const contactEmail = clean(values.contactEmail || values.contact_email);
  const discordGuildId = clean(values.discordGuildId || values.discord_guild_id);
  const desiredGuildPin = normalizePin(values.guildPin || values.desiredGuildPin || values.desired_guild_pin);
  const notes = clean(values.notes);

  if (!guildName || !contactName || (!contactDiscord && !contactEmail)) {
    const error = new Error("Bitte Gildenname, Ansprechpartner und Discord oder E-Mail ausfüllen.");
    error.statusCode = 400;
    throw error;
  }

  const result = await query(
    `insert into guild_applications
       (guild_name, loot_name, server, contact_name, contact_discord, contact_email, discord_guild_id, desired_guild_pin, notes)
     values ($1,$2,$3,$4,$5,$6,$7,$8,$9)
     returning *`,
    [guildName, lootName, server, contactName, contactDiscord, contactEmail, discordGuildId, desiredGuildPin, notes]
  );

  return {
    success: true,
    application: normalizeGuildApplicationRow(result.rows[0], values),
    message: "Gilden-Anfrage gespeichert. Die Freischaltung erfolgt im Admin-Bereich."
  };
}

async function getGuildApplications({ query: params }) {
  requireMasterCode(params.masterCode);
  await ensureGuildApplicationSchema();
  const result = await query(
    `select *
     from guild_applications
     order by
       case status when 'pending' then 0 when 'approved' then 1 when 'completed' then 2 else 3 end,
       created_at desc`
  );
  return {
    success: true,
    applications: result.rows.map(row => normalizeGuildApplicationRow(row, params))
  };
}

async function approveGuildApplication({ query: params, body = {} }) {
  requireMasterCode(params.masterCode || body.masterCode);
  await ensureGuildApplicationSchema();
  const values = { ...params, ...body };
  const id = clean(values.id);
  if (!id) {
    const error = new Error("Anfrage fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const token = clean(values.setupToken) || `${randomUUID().replace(/-/g, "")}${randomUUID().slice(0, 8)}`;
  const result = await query(
    `update guild_applications
     set status = 'approved',
         setup_token = $2,
         setup_token_expires_at = now() + interval '14 days',
         approved_by = $3,
         approved_at = now(),
         rejected_at = null,
         updated_at = now()
     where id = $1
     returning *`,
    [id, token, clean(values.approvedBy) || "Gildenleitung"]
  );
  if (!result.rows[0]) {
    const error = new Error("Anfrage nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }
  return {
    success: true,
    application: normalizeGuildApplicationRow(result.rows[0], values)
  };
}

async function rejectGuildApplication({ query: params, body = {} }) {
  requireMasterCode(params.masterCode || body.masterCode);
  await ensureGuildApplicationSchema();
  const id = clean(params.id || body.id);
  if (!id) {
    const error = new Error("Anfrage fehlt.");
    error.statusCode = 400;
    throw error;
  }
  const result = await query(
    `update guild_applications
     set status = 'rejected',
         rejected_at = now(),
         updated_at = now()
     where id = $1
     returning *`,
    [id]
  );
  if (!result.rows[0]) {
    const error = new Error("Anfrage nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }
  return { success: true, application: normalizeGuildApplicationRow(result.rows[0], params) };
}

async function getGuildSetup({ query: params }) {
  await ensureGuildApplicationSchema();
  const token = clean(params.token);
  if (!token) {
    const error = new Error("Freischaltlink fehlt.");
    error.statusCode = 400;
    throw error;
  }
  const result = await query(
    `select *
     from guild_applications
     where setup_token = $1
       and status in ('approved', 'completed')
       and (setup_token_expires_at is null or setup_token_expires_at > now())
     limit 1`,
    [token]
  );
  if (!result.rows[0]) {
    const error = new Error("Freischaltlink ist ungültig oder abgelaufen.");
    error.statusCode = 404;
    throw error;
  }
  return { success: true, application: normalizeGuildApplicationRow(result.rows[0], params) };
}

async function completeGuildSetup({ query: params, body = {} }) {
  await ensureGuildApplicationSchema();
  await ensureGuildDiscordConfigSchema();
  const values = { ...params, ...body };
  const token = clean(values.token);
  if (!token) {
    const error = new Error("Freischaltlink fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const applicationResult = await query(
    `select *
     from guild_applications
     where setup_token = $1
       and status = 'approved'
       and (setup_token_expires_at is null or setup_token_expires_at > now())
     limit 1`,
    [token]
  );
  const application = applicationResult.rows[0];
  if (!application) {
    const error = new Error("Freischaltlink ist ungültig, abgelaufen oder bereits abgeschlossen.");
    error.statusCode = 404;
    throw error;
  }

  const guildName = clean(values.guildName) || application.guild_name;
  const lootName = clean(values.lootName) || application.loot_name || guildName;
  const server = clean(values.server) || application.server;
  const guildPin = normalizePin(values.guildPin) || application.desired_guild_pin;
  const discordGuildId = clean(values.discordGuildId || values.discord_guild_id || application.discord_guild_id);
  const logoUrl = clean(values.logoUrl);
  const backgroundUrl = clean(values.backgroundUrl);
  const primaryColor = clean(values.primaryColor) || "#facc15";
  const accentColor = clean(values.accentColor) || "#1d4ed8";

  const created = await createGuild({ query: { guildName, lootName, server, guildPin } });
  const saved = await updateGuildConfig({
    query: { guild: created.guild.slug },
    body: { guildName, server, logoUrl, backgroundUrl, primaryColor, accentColor }
  });

  if (discordGuildId) {
    await query(
      `update guilds
       set discord_guild_id = $2,
           updated_at = now()
       where slug = $1`,
      [created.guild.slug, discordGuildId]
    );
  }

  const rowResult = await query(
    `update guild_applications
     set status = 'completed',
         setup_completed_at = now(),
         guild_slug = $2,
         guild_pin = $3,
         logo_url = $4,
         background_url = $5,
         primary_color = $6,
         accent_color = $7,
         updated_at = now()
     where id = $1
     returning *`,
    [application.id, created.guild.slug, guildPin, logoUrl, backgroundUrl, primaryColor, accentColor]
  );

  return {
    success: true,
    application: normalizeGuildApplicationRow(rowResult.rows[0], values),
    guild: { ...saved.guild, guildPin },
    guildSlug: created.guild.slug,
    guildPin,
    startUrl: makeGuildPageUrl("start.html", created.guild.slug, values),
    leadershipUrl: makeGuildPageUrl("gildenleitung.html", created.guild.slug, values)
  };
}

function normalizePin(value) {
  return clean(value).toUpperCase();
}

const playerRoleLabels = {
  member: "Mitglied",
  gildenleitung: "Gildenleitung",
  gildenoffiziere: "Gildenoffiziere",
  raidoffiziere: "Raidoffiziere"
};
const raidCreateRoles = new Set(["gildenleitung", "gildenoffiziere", "raidoffiziere"]);
const poReviewOfficerNames = new Set([
  "aeranor",
  "andytheke",
  "ariee",
  "bambow",
  "belly",
  "bimm",
  "bimmii",
  "bimmi",
  "blondie",
  "bruno55",
  "burny",
  "cutiepie",
  "dennis",
  "eiereule",
  "emori",
  "erzcastiel",
  "evalina",
  "gimillion",
  "gimlion",
  "giminiufnsak",
  "grashupfer",
  "immobimm",
  "juksi",
  "kaese",
  "kase",
  "kraz",
  "lagertha",
  "linara",
  "linari",
  "lissy",
  "liya",
  "loujsa",
  "marshmallow",
  "milina",
  "milkshake",
  "pinari",
  "ronary",
  "rubina",
  "schepperle",
  "sillanou",
  "sillasou",
  "veltharos"
]);

function normalizeReviewName(value) {
  return clean(value)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
}

function normalizePlayerRole(value) {
  const raw = clean(value).toLowerCase();
  if (raw === "gildenleitung" || raw === "leitung") return "gildenleitung";
  if (raw === "gildenoffiziere" || raw === "gildenoffizier") return "gildenoffiziere";
  if (raw === "raidoffiziere" || raw === "raidoffizier" || raw === "raidlead") return "raidoffiziere";
  return "member";
}

function normalizePlayerApprovalStatus(value) {
  const raw = clean(value).toLowerCase();
  if (["approved", "freigegeben", "approve"].includes(raw)) return "approved";
  if (["rejected", "abgelehnt", "reject"].includes(raw)) return "rejected";
  return "pending";
}

function playerApprovalLabel(value) {
  const status = normalizePlayerApprovalStatus(value);
  if (status === "pending") return "wartet auf Freigabe";
  if (status === "rejected") return "abgelehnt";
  return "freigegeben";
}

function playerRoleLabel(value) {
  return playerRoleLabels[normalizePlayerRole(value)] || playerRoleLabels.member;
}

function canPlayerRoleCreateRaid(value) {
  return raidCreateRoles.has(normalizePlayerRole(value));
}

function normalizeCharacter(row) {
  const playerRole = normalizePlayerRole(row.player_role || row.role);
  const permissions = Array.isArray(row.permissions) ? row.permissions : [];
  const isBlocked = Boolean(row.is_blocked);
  const approvalStatus = normalizePlayerApprovalStatus(row.approval_status);
  return {
    id: row.id,
    char: row.name,
    name: row.name,
    player: row.name,
    server: row.server,
    className: row.class_name,
    Klasse: row.class_name,
    mainChar: row.main_char || "",
    isMain: Boolean(row.is_main),
    role: playerRole,
    playerRole,
    playerRoleLabel: playerRoleLabel(playerRole),
    permissions,
    canCreateRaid: permissions.includes("create_raids") || permissions.includes("guild_admin") || canPlayerRoleCreateRaid(playerRole),
    approvalStatus,
    playerApprovalStatus: approvalStatus,
    approvalLabel: playerApprovalLabel(approvalStatus),
    isApproved: approvalStatus === "approved",
    isBlocked,
    blocked: isBlocked,
    blockedAt: row.blocked_at || null,
    blockedReason: row.blocked_reason || "",
    created_at: row.created_at
  };
}

async function findPlayerByPin(guildId, pin) {
  const result = await query(
    `select id, player_pin, role, is_blocked, blocked_at, blocked_reason, approval_status
     from players
     where guild_id = $1
       and player_pin = $2
       and coalesce(is_blocked, false) = false
       and approval_status = 'approved'`,
    [guildId, normalizePin(pin)]
  );
  return result.rows[0] || null;
}

async function getPlayerDisplayNameByPin(guildId, pin) {
  const result = await query(
    `select coalesce((
       select c.name
       from characters c
       where c.player_id = p.id
       order by c.is_main desc, c.created_at asc
       limit 1
     ), p.player_pin) as display_name
     from players p
     where p.guild_id = $1 and p.player_pin = $2`,
    [guildId, normalizePin(pin)]
  );
  return clean(result.rows[0]?.display_name);
}

async function getVerifiedSenderCharacterName(guildId, pin, charName, server) {
  const name = clean(charName);
  if (!name) return "";

  const params = [guildId, normalizePin(pin), name];
  let serverClause = "";
  if (clean(server)) {
    params.push(clean(server));
    serverClause = `and lower(c.server) = lower($${params.length})`;
  }

  const result = await query(
    `select c.name
     from players p
     join characters c on c.player_id = p.id
     where p.guild_id = $1
       and p.player_pin = $2
       and p.approval_status = 'approved'
       and lower(c.name) = lower($3)
       ${serverClause}
     order by c.created_at asc
     limit 1`,
    params
  );
  return clean(result.rows[0]?.name);
}

async function findPlayerByRecipient(guildId, recipient, server) {
  const raw = clean(recipient);
  if (!raw) return null;

  const byPin = await findPlayerByPin(guildId, raw);
  if (byPin) return byPin;

  const params = [guildId, raw];
  let serverClause = "";
  if (clean(server)) {
    params.push(clean(server));
    serverClause = `and lower(c.server) = lower($${params.length})`;
  }

  const result = await query(
    `select p.id, p.player_pin, c.name as character_name, c.server
     from characters c
     join players p on p.id = c.player_id
     where p.guild_id = $1
       and coalesce(p.is_blocked, false) = false
       and p.approval_status = 'approved'
       and lower(c.name) = lower($2)
       ${serverClause}
     order by c.created_at asc
     limit 1`,
    params
  );
  return result.rows[0] || null;
}

async function findCharacter(guildId, charName, server) {
  const result = await query(
    `select c.id, c.name, c.server, c.class_name, c.created_at, p.id as player_id, p.player_pin
     from characters c
     join players p on p.id = c.player_id
     where p.guild_id = $1 and lower(c.name) = lower($2) and lower(c.server) = lower($3)
     limit 1`,
    [guildId, clean(charName), clean(server)]
  );
  return result.rows[0] || null;
}

async function getCharactersByPin(guildId, pin) {
  const normalizedPin = normalizePin(pin);
  await ensureCrossGuildPlayerLogin(guildId, normalizedPin);
  const playerResult = await query(
    "select id, is_blocked, blocked_reason, approval_status from players where guild_id = $1 and player_pin = $2 limit 1",
    [guildId, normalizedPin]
  );
  if (playerResult.rows[0]?.is_blocked) {
    const error = new Error(playerResult.rows[0]?.blocked_reason || "Dieser SpielerLogin ist gesperrt.");
    error.statusCode = 403;
    throw error;
  }
  if (playerResult.rows[0] && normalizePlayerApprovalStatus(playerResult.rows[0]?.approval_status) !== "approved") {
    const error = new Error("Dieser SpielerLogin wartet noch auf Freigabe durch die Gildenleitung.");
    error.statusCode = 403;
    throw error;
  }

  const result = await query(
    `select
       c.id,
       c.name,
       c.server,
       c.class_name,
       c.is_main,
       c.created_at,
       p.role as player_role,
       p.permissions,
       p.notification_discord_names,
       p.approval_status,
       p.is_blocked,
       p.blocked_at,
       p.blocked_reason,
       first_value(c.name) over (
         partition by p.id
         order by c.is_main desc, c.created_at asc
       ) as main_char
     from players p
     join characters c on c.player_id = p.id
     where p.guild_id = $1 and p.player_pin = $2 and coalesce(p.is_blocked, false) = false and p.approval_status = 'approved'
     order by c.is_main desc, c.created_at asc, c.name asc`,
    [guildId, normalizedPin]
  );
  return result.rows.map(normalizeCharacter);
}

async function ensureCrossGuildPlayerLogin(guildId, pin) {
  const normalizedPin = normalizePin(pin);
  if (!normalizedPin) return null;

  const local = await query(
    "select id, approval_status from players where guild_id = $1 and player_pin = $2 limit 1",
    [guildId, normalizedPin]
  );

  const source = await query(
    `select p.id, p.player_pin, p.security_question, p.security_answer
     from players p
     where p.guild_id <> $1
       and p.player_pin = $2
       and coalesce(p.is_blocked, false) = false
       and p.approval_status = 'approved'
     order by p.created_at asc
     limit 1`,
    [guildId, normalizedPin]
  );
  const sourcePlayer = source.rows[0];
  if (!sourcePlayer) return local.rows[0] || null;

  const client = await pool.connect();
  try {
    await client.query("begin");
    const playerResult = await client.query(
      `insert into players (guild_id, player_pin, security_question, security_answer, approval_status)
       values ($1, $2, $3, $4, 'pending')
       on conflict (guild_id, player_pin) do update
         set security_question = coalesce(players.security_question, excluded.security_question),
             security_answer = coalesce(players.security_answer, excluded.security_answer),
             updated_at = now()
       returning id, player_pin`,
      [guildId, normalizedPin, sourcePlayer.security_question || null, sourcePlayer.security_answer || null]
    );
    const player = playerResult.rows[0];

    // Identitaet und Charaktere werden geteilt, alle Gildendaten bleiben
    // dennoch getrennt: Die neuen Charakterzeilen besitzen eigene IDs in
    // der Zielgilde. Prios, Punkte, Rollen und PO-Freigaben werden nicht
    // kopiert.
    await client.query(
      `insert into characters (player_id, name, server, class_name, is_main)
       select $1, source_char.name, source_char.server, source_char.class_name, source_char.is_main
       from characters source_char
       where source_char.player_id = $2
         and not exists (
           select 1
           from characters target_char
           where target_char.player_id = $1
             and lower(target_char.name) = lower(source_char.name)
             and lower(target_char.server) = lower(source_char.server)
         )`,
      [player.id, sourcePlayer.id]
    );

    await client.query("commit");
    return player;
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function repairEmptyCrossGuildPlayerLogins(guildId) {
  const result = await query(
    `select target.player_pin
     from players target
     where target.guild_id = $1
       and not exists (
         select 1 from characters target_char where target_char.player_id = target.id
       )
       and exists (
         select 1
         from players source
         join characters source_char on source_char.player_id = source.id
         where source.guild_id <> target.guild_id
           and source.player_pin = target.player_pin
           and coalesce(source.is_blocked, false) = false
           and source.approval_status = 'approved'
       )`,
    [guildId]
  );

  for (const row of result.rows) {
    await ensureCrossGuildPlayerLogin(guildId, row.player_pin);
  }

  return result.rowCount;
}

async function getPlayerCharacters(guildId, pin) {
  return getCharactersByPin(guildId, pin);
}

function parseDateValue(value) {
  const raw = clean(value);
  if (!raw) return new Date().toISOString().slice(0, 10);

  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;

  const german = raw.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/);
  if (german) {
    return `${german[3]}-${german[2].padStart(2, "0")}-${german[1].padStart(2, "0")}`;
  }

  const parsed = new Date(raw);
  if (!Number.isNaN(parsed.getTime())) return parsed.toISOString().slice(0, 10);

  return new Date().toISOString().slice(0, 10);
}

function formatGermanDate(value) {
  if (!value) return "";
  const iso = value instanceof Date ? value.toISOString().slice(0, 10) : parseDateValue(value);
  const parts = iso.split("-");
  return parts.length === 3 ? `${parts[2]}.${parts[1]}.${parts[0]}` : clean(value);
}

function weekdayShort(value) {
  const iso = parseDateValue(value);
  const date = new Date(`${iso}T12:00:00Z`);
  const names = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];
  return names[date.getUTCDay()] || "";
}

function normalizeRaidType(value) {
  const raw = clean(value) || "raid";
  const key = raw.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "raid";
  const aliases = {
    "molten-core": "mc",
    "blackwing-lair": "bwl",
    "ahn-qiraj-40": "aq40",
    "aq-40": "aq40",
    "ahn-qiraj": "aq40",
    "zul-gurub": "zg",
    "zg-20": "zg",
    "zul-gurub-20": "zg",
    "zg-mittwoch": "zg-mittwoch",
    "zul-gurub-mittwoch": "zg-mittwoch",
    "zg-prime": "zg-prime",
    "zul-gurub-prime": "zg-prime",
    "zg-late": "zg-late",
    "zul-gurub-late": "zg-late",
    "aq-20": "aq20",
    "ahn-qiraj-20": "aq20",
    "ruins-of-ahn-qiraj": "aq20",
    "onyxia": "ony",
    "onyxia-s-lair": "ony"
  };
  return aliases[key] || key;
}

function normalizeLogRaidType(value) {
  const raw = clean(value);
  if (!raw) return "";
  const normalized = normalizeRaidType(raw);
  if (normalized === "raid") return "";
  return normalized.toUpperCase();
}

function raidTypeSearchValues(value) {
  const normalized = normalizeRaidType(value);
  const variants = {
    mc: ["mc", "molten-core"],
    bwl: ["bwl", "blackwing-lair"],
    aq40: ["aq40", "aq-40", "ahn-qiraj-40", "ahn-qiraj"],
    naxx: ["naxx", "naxxramas"],
    zg: ["zg", "zg20", "zg 20", "zg-20", "zul-gurub", "zul gurub", "zul'gurub", "zul-gurub-20", "zul gurub 20"],
    "zg-mittwoch": ["zg-mittwoch", "zg mittwoch", "zul-gurub-mittwoch", "zul gurub mittwoch"],
    "zg-prime": ["zg-prime", "zg prime", "zul-gurub-prime", "zul gurub prime"],
    "zg-late": ["zg-late", "zg late", "zul-gurub-late", "zul gurub late"],
    aq20: ["aq20", "aq 20", "aq-20", "ahn-qiraj-20", "ahn qiraj 20", "ahn'qiraj 20", "ruins-of-ahn-qiraj", "ruins of ahn qiraj"],
    ony: ["ony", "onyxia", "onyxia-s-lair"]
  };
  return Array.from(new Set([normalized, ...(variants[normalized] || [])].map(value => value.toLowerCase())));
}

function displayRaidName(value) {
  const key = normalizeRaidType(value);
  const names = {
    mc: "Molten Core",
    bwl: "Blackwing Lair",
    aq40: "Ahn'Qiraj 40",
    naxx: "Naxxramas",
    zg: "Zul'Gurub",
    "zg-mittwoch": "ZG Mittwoch",
    "zg-prime": "ZG PRIME",
    "zg-late": "ZG LATE",
    aq20: "AQ 20",
    ony: "Onyxia"
  };
  return names[key] || clean(value) || "Raid";
}

function lootSourceRaidType(value) {
  const raid = normalizeRaidType(value);
  return ["zg-mittwoch", "zg-prime", "zg-late"].includes(raid) ? "zg" : raid;
}

function isNachtlootSpecialRaid(value) {
  return ["zg-mittwoch", "zg-prime", "zg-late"].includes(normalizeRaidType(value));
}

async function requireNachtlootSpecialRaidGuild(guildId, raidType) {
  if (!isNachtlootSpecialRaid(raidType)) return;
  const result = await query(`select slug from guilds where id = $1 limit 1`, [guildId]);
  if (clean(result.rows[0]?.slug).toLowerCase() !== "nachtloot") {
    const error = new Error("Dieser Raidtyp ist ausschließlich für NachtLoot verfügbar.");
    error.statusCode = 403;
    throw error;
  }
}

function readSlotFromNote(note) {
  const text = clean(note);
  const match = text.match(/Slot:\s*(.*)$/i);
  return match ? clean(match[1]) : "";
}

async function loadMasterCodeOverrides() {
  await query(
    `create table if not exists guild_master_codes (
       guild_id uuid primary key references guilds(id) on delete cascade,
       master_code text not null,
       updated_at timestamptz not null default now()
     )`
  );
  const result = await query(
    `select g.id as guild_id,
            coalesce(nullif(gmc.master_code, ''), nullif(g.guild_pin, '')) as master_code
     from guilds g
     left join guild_master_codes gmc on gmc.guild_id = g.id
     where coalesce(nullif(gmc.master_code, ''), nullif(g.guild_pin, '')) is not null`
  );
  masterCodeOverrides.clear();
  result.rows.forEach(row => masterCodeOverrides.set(String(row.guild_id), row.master_code));
}

async function saveGuildMasterCodeValue(client, guildId, code) {
  const value = clean(code);
  if (!value) return;
  await client.query(
    `insert into guild_master_codes (guild_id, master_code, updated_at)
     values ($1, $2, now())
     on conflict (guild_id) do update
       set master_code = excluded.master_code,
           updated_at = now()`,
    [guildId, value]
  );
  masterCodeOverrides.set(String(guildId), value);
}

function requireMasterCode(value) {
  const code = clean(value);
  if (code !== masterCode && !Array.from(masterCodeOverrides.values()).includes(code) && !Array.from(worldbuffAccessCodeOverrides.values()).includes(code)) {
    const error = new Error("Falscher Master-Code.");
    error.statusCode = 403;
    throw error;
  }
}

function requireMasterCodeForGuild(guild, value, action="", params={}) {
  const code = clean(value);
  const guildId = String(guild?.id || "");
  const guildSlug = clean(guild?.slug).toLowerCase();
  const guildCode = clean(masterCodeOverrides.get(guildId));
  const isDefaultGuild =
    guildSlug === clean(defaultGuildSlug).toLowerCase()
    || guildSlug === "lichtloot";
  const allowedCodes = new Set(
    [guildCode, isDefaultGuild ? clean(masterCode) : ""].filter(Boolean)
  );

  const worldbuffCode=clean(worldbuffAccessCodeOverrides.get(guildId));
  if(code && worldbuffCode && code===worldbuffCode){
    const worldbuffActions=new Set([
      "guildVerifyWorldbuffAccess","guildGetWorldbuffs","guildSetWorldbuffCaster",
      "guildRequestWorldbuffReplacement","guildDeleteWorldbuffTerm",
      "guildQueueWorldbuffBackup","guildRestoreDeletedWorldbuffTerms","guildSyncPublicBuffTerms"
    ]);
    const allowed=worldbuffActions.has(action)
      || (action==="guildCreateBuffTerm" && clean(params.target).toLowerCase()==="worldbuff")
      || (action==="guildQueueWorldbuffBotUpdate" && clean(params.type).toLowerCase()==="worldbuff_update");
    if(allowed)return;
    const error=new Error("Dieses Passwort erlaubt ausschließlich die Worldbuff-Verwaltung.");error.statusCode=403;throw error;
  }

  if (!code || !allowedCodes.has(code)) {
    const error = new Error("Dieser Master-Code gehört nicht zu dieser Gilde.");
    error.statusCode = 403;
    throw error;
  }
}

function requireRaidleadP0MasterCodeForGuild(guild, value) {
  const code = clean(value);
  const guildSlug = clean(guild?.slug).toLowerCase();
  const isLichtbringer = guildSlug === "lichtloot" || guildSlug === "lichtbringer";
  if (isLichtbringer && code === "1301") return;
  const lootMasterCode = clean(lootMasterAccessCodeOverrides.get(String(guild?.id || "")));
  if (code && lootMasterCode && code === lootMasterCode) return;
  requireMasterCodeForGuild(guild, code);
}

function requireMasterOrQueueToken(params = {}) {
  const code = clean(params.masterCode);
  if (code === masterCode || Array.from(masterCodeOverrides.values()).includes(code)) return;
  if (lichtbotQueueToken && clean(params.queueToken) === lichtbotQueueToken) return;
  const error = new Error("Nicht erlaubt.");
  error.statusCode = 403;
  throw error;
}

async function ensureRaidSchema() {
  await query(
    `alter table raids
       add column if not exists external_raid_id text,
       add column if not exists raid_time text,
       add column if not exists guild_name text,
       add column if not exists player_link text,
       add column if not exists p0plus_freigabe text not null default 'geschlossen',
       add column if not exists created_by text,
       add column if not exists raidhelper_enabled boolean not null default true,
       add column if not exists signup_deadline text,
       add column if not exists max_players integer,
       add column if not exists tank_slots integer,
       add column if not exists heal_slots integer,
       add column if not exists dd_slots integer,
       add column if not exists discord_channel_id text,
       add column if not exists discord_message_id text,
       add column if not exists description text,
       add column if not exists raid_image_url text,
       add column if not exists loot_master text,
       add column if not exists loot_master_targets jsonb not null default '[]'::jsonb,
       add column if not exists status_notify_targets jsonb not null default '[]'::jsonb,
       add column if not exists announcement_notify_targets jsonb not null default '[]'::jsonb`
  );
  await query(
    `alter table raid_signups
       add column if not exists role text not null default 'flex',
       add column if not exists source text not null default 'lichtloot',
       add column if not exists discord_user_id text,
       add column if not exists discord_name text`
  );
  await query(
    `create table if not exists raid_external_signups (
       id uuid primary key default gen_random_uuid(),
       raid_id uuid references raids(id) on delete cascade,
       guild_id uuid not null references guilds(id) on delete cascade,
       raid_type text not null,
       raid_date date,
       raid_time text,
       player_name text not null,
       player_pin text,
       class_name text,
       role text not null default 'flex',
       status text not null default 'signed',
       source text not null default 'discord',
       discord_user_id text,
       discord_name text,
       discord_channel_id text,
       discord_message_id text,
       note text,
       created_at timestamptz not null default now(),
       updated_at timestamptz not null default now()
     )`
  );
  await query(`alter table raids drop constraint if exists raids_guild_id_raid_type_raid_date_key`);
  await query(
    `create unique index if not exists idx_raids_guild_external_raid_id
       on raids(guild_id, external_raid_id)
       where external_raid_id is not null and external_raid_id <> ''`
  );
  await query(`create index if not exists idx_raid_signups_raid_status on raid_signups(raid_id, status)`);
  await query(
    `create unique index if not exists idx_raid_external_signups_unique_source
       on raid_external_signups(guild_id, coalesce(raid_id::text, ''), lower(player_name), source)`
  );
  await query(
    `create index if not exists idx_raid_external_signups_guild_raid
       on raid_external_signups(guild_id, raid_id, raid_date)`
  );
  await query(`alter table raid_external_signups add column if not exists player_pin text`);
  await query(
    `create table if not exists p0_discord_signups (
       id uuid primary key default gen_random_uuid(),
       guild_id uuid not null references guilds(id) on delete cascade,
       raid_id uuid not null references raids(id) on delete cascade,
       character_id uuid references characters(id) on delete set null,
       item_id uuid references items(id) on delete set null,
       player_name text not null,
       server text,
       item_name text not null,
       discord_user_id text not null,
       discord_name text,
       discord_channel_id text,
       discord_message_id text,
       approval_status text not null default 'pending',
       approved_by_discord_id text,
       approved_by_discord_name text,
       approved_at timestamptz,
       source text not null default 'discord-p0',
       created_at timestamptz not null default now(),
       updated_at timestamptz not null default now()
     )`
  );
  await query(`alter table p0_discord_signups add column if not exists approval_status text not null default 'pending'`);
  await query(`alter table p0_discord_signups add column if not exists approved_by_discord_id text`);
  await query(`alter table p0_discord_signups add column if not exists approved_by_discord_name text`);
  await query(`alter table p0_discord_signups add column if not exists approved_at timestamptz`);
  await query(
    `create unique index if not exists idx_p0_discord_signups_one_per_user
     on p0_discord_signups(guild_id, raid_id, discord_user_id)`
  );
  await query(`create index if not exists idx_p0_discord_signups_raid on p0_discord_signups(guild_id, raid_id)`);
  await query(
    `create table if not exists character_po_releases (
       id uuid primary key default gen_random_uuid(),
       guild_id uuid not null references guilds(id) on delete cascade,
       character_id uuid not null references characters(id) on delete cascade,
       raid_type text not null,
       source text not null default 'manual',
       approved_by text,
       approved_at timestamptz not null default now(),
       created_at timestamptz not null default now(),
       updated_at timestamptz not null default now(),
       unique(guild_id, character_id, raid_type)
     )`
  );
  await query(`create index if not exists idx_character_po_releases_guild_raid on character_po_releases(guild_id, raid_type)`);
  await query(
    `create table if not exists discord_player_links (
       id uuid primary key default gen_random_uuid(),
       guild_id uuid not null references guilds(id) on delete cascade,
       discord_user_id text not null,
       character_id uuid not null references characters(id) on delete cascade,
       discord_name text,
       source text not null default 'discord-p0',
       created_at timestamptz not null default now(),
       updated_at timestamptz not null default now()
     )`
  );
  await query(
    `create unique index if not exists idx_discord_player_links_user_char
       on discord_player_links(guild_id, discord_user_id, character_id)`
  );
}

async function ensurePrioSchema() {
  await query(
    `alter table prios
       add column if not exists created_at timestamptz not null default now(),
       add column if not exists updated_at timestamptz not null default now()`
  );
  await query(
    `delete from prios
     where id in (
       select id
       from (
         select id,
                row_number() over (
                  partition by raid_id, character_id
                  order by coalesce(updated_at, created_at) desc, created_at desc, id desc
                ) as rn
         from prios
       ) duplicates
       where rn > 1
     )`
  );
  await query(
    `create unique index if not exists idx_prios_raid_character_unique
       on prios(raid_id, character_id)`
  );
}

async function ensureP0PlusAuditSchema() {
  await query(
    `create table if not exists p0plus_point_audit (
       id uuid primary key default gen_random_uuid(),
       guild_id uuid not null references guilds(id) on delete cascade,
       character_id uuid references characters(id) on delete set null,
       item_id uuid references items(id) on delete set null,
       raid_id uuid references raids(id) on delete set null,
       raid_type text,
       player_name text,
       server text,
       item_name text,
       old_points numeric not null default 0,
       new_points numeric not null default 0,
       delta_points numeric not null default 0,
       action text not null,
       source text not null,
       note text,
       created_at timestamptz not null default now()
     )`
  );
  await query(`create index if not exists idx_p0plus_point_audit_guild_created on p0plus_point_audit(guild_id, created_at desc)`);
  await query(`create index if not exists idx_p0plus_point_audit_raid on p0plus_point_audit(guild_id, raid_type, raid_id)`);
}

async function ensureDiscordChannelSchema() {
  await query(
    `create table if not exists discord_bot_channels (
       id uuid primary key default gen_random_uuid(),
       guild_id uuid not null references guilds(id) on delete cascade,
       discord_guild_id text,
       discord_guild_name text,
       channel_id text not null,
       channel_name text not null,
       channel_type text,
       category_name text,
       position integer,
       can_send boolean not null default true,
       updated_at timestamptz not null default now(),
       unique (guild_id, channel_id)
     )`
  );
  await query(
    `create index if not exists idx_discord_bot_channels_guild
       on discord_bot_channels(guild_id, category_name, position, channel_name)`
  );
  await query(
    `create table if not exists discord_bot_roles (
       id uuid primary key default gen_random_uuid(),
       guild_id uuid not null references guilds(id) on delete cascade,
       discord_guild_id text,
       role_id text not null,
       role_name text not null,
       color integer,
       position integer,
       updated_at timestamptz not null default now(),
       unique (guild_id, role_id)
     )`
  );
  await query(
    `create table if not exists discord_bot_members (
       id uuid primary key default gen_random_uuid(),
       guild_id uuid not null references guilds(id) on delete cascade,
       discord_guild_id text,
       user_id text not null,
       username text not null,
       display_name text,
       global_name text,
       avatar_url text,
       bot boolean not null default false,
       updated_at timestamptz not null default now(),
       unique (guild_id, user_id)
     )`
  );
  await query(`create index if not exists idx_discord_bot_members_guild_name on discord_bot_members(guild_id, lower(username), lower(display_name))`);
}

async function ensureRaidHelperTemplateSchema() {
  await query(
    `create table if not exists raid_helper_templates (
       id uuid primary key default gen_random_uuid(),
       guild_id uuid not null references guilds(id) on delete cascade,
       template_key text,
       raid_type text not null,
       title text not null,
       description text,
       max_players integer,
       tank_slots integer,
       heal_slots integer,
       dd_slots integer,
       signup_deadline text,
       discord_channel_id text,
       raid_image_url text,
       created_at timestamptz not null default now(),
       updated_at timestamptz not null default now()
     )`
  );
  await query(
    `create unique index if not exists idx_raid_helper_templates_guild_key
       on raid_helper_templates(guild_id, lower(template_key))
       where template_key is not null and template_key <> ''`
  );
  await query(
    `create index if not exists idx_raid_helper_templates_guild
       on raid_helper_templates(guild_id, raid_type, title)`
  );
}

async function ensureRaidHelperScheduleSchema() {
  await query(
    `create table if not exists raid_helper_schedules (
       id uuid primary key default gen_random_uuid(),
       guild_id uuid not null references guilds(id) on delete cascade,
       schedule_key text,
       enabled boolean not null default true,
       raid_type text not null,
       title text not null,
       description text,
       max_players integer,
       tank_slots integer,
       heal_slots integer,
       dd_slots integer,
       signup_deadline text,
       discord_channel_id text,
       raid_image_url text,
       created_by text,
       recurrence text not null default 'weekly',
       interval_weeks integer not null default 1,
       weekday integer not null default 3,
       raid_time text not null default '20:00',
       post_time text not null default '09:00',
       next_raid_date date,
       next_post_date date,
       last_raid_date date,
       last_raid_id uuid references raids(id) on delete set null,
       created_at timestamptz not null default now(),
       updated_at timestamptz not null default now(),
       unique (guild_id, schedule_key)
     )`
  );
  await query(`alter table raid_helper_schedules add column if not exists post_time text not null default '09:00'`);
  await query(`alter table raid_helper_schedules add column if not exists next_post_date date`);
  await query(
    `create index if not exists idx_raid_helper_schedules_guild
       on raid_helper_schedules(guild_id, enabled, next_raid_date, raid_time)`
  );
}

async function ensurePlayerRoleSchema() {
  await query(
    `alter table players
       add column if not exists role text not null default 'member',
       add column if not exists approval_status text not null default 'pending',
       add column if not exists approved_at timestamptz,
       add column if not exists approved_by text not null default '',
       add column if not exists is_blocked boolean not null default false,
       add column if not exists blocked_at timestamptz,
       add column if not exists blocked_reason text not null default '',
       add column if not exists discord_role_ids jsonb not null default '[]'::jsonb,
       add column if not exists permissions jsonb not null default '[]'::jsonb,
       add column if not exists notification_discord_names jsonb not null default '[]'::jsonb`
  );
  await query(`alter table players alter column approval_status set default 'pending'`);
  await query(`update players set permissions=case
    when lower(role)='gildenleitung' then '["guild_admin"]'::jsonb
    when lower(role) in ('gildenoffiziere','gildenoffizier') then '["create_raids","manage_worldbuffs"]'::jsonb
    when lower(role) in ('raidoffiziere','raidoffizier','raidlead') then '["create_raids"]'::jsonb
    else permissions end
    where jsonb_array_length(coalesce(permissions,'[]'::jsonb))=0 and lower(role)<>'member'`);
}

async function ensureGuildNotificationSettingsSchema(){
  await query(`create table if not exists guild_notification_settings (
    guild_id uuid not null references guilds(id) on delete cascade,
    notification_key text not null,
    targets jsonb not null default '[]'::jsonb,
    updated_at timestamptz not null default now(),
    primary key (guild_id,notification_key)
  )`);
  await query(`alter table guild_notification_settings add column if not exists message_template text not null default ''`);
}

async function getGuildNotificationSettings({guildId,query:params}){
  requireMasterOrQueueToken(params);
  await ensureGuildNotificationSettingsSchema();
  const result=await query(`select notification_key,targets,message_template from guild_notification_settings where guild_id=$1`,[guildId]);
  return {success:true,settings:Object.fromEntries(result.rows.map(row=>[row.notification_key,Array.isArray(row.targets)?row.targets:[]])),templates:Object.fromEntries(result.rows.map(row=>[row.notification_key,clean(row.message_template)]))};
}

async function setGuildNotificationSetting({guildId,query:params}){
  requireMasterCode(params.masterCode);
  await ensureGuildNotificationSettingsSchema();
  const allowed=new Set(["notify_player_logins","loot_master","manage_worldbuffs","notify_po_releases","notify_po_release_granted","raid_status_changes","po_reviewers"]);
  const notificationKey=clean(params.notificationKey||params.key);
  const allowedLootMasterKey=/^loot_master:(mc|bwl|aq40|naxx|zg-mittwoch|zg-prime|zg-late|aq20)$/i.test(notificationKey);
  const allowedPoReleaseKey=/^notify_po_releases:(mc|bwl|aq40|naxx|zg-mittwoch|zg-prime|zg-late|aq20)$/i.test(notificationKey);
  const allowedPoReleaseGrantedKey=/^notify_po_release_granted:(mc|bwl|aq40|naxx|zg-mittwoch|zg-prime|zg-late|aq20)$/i.test(notificationKey);
  if(!allowed.has(notificationKey)&&!allowedLootMasterKey&&!allowedPoReleaseKey&&!allowedPoReleaseGrantedKey){const error=new Error("Unbekannte Discord-Benachrichtigung.");error.statusCode=400;throw error;}
  let targets=[];try{const parsed=typeof params.targets==="string"?JSON.parse(params.targets):params.targets;targets=Array.isArray(parsed)?parsed:[];}catch{}
  targets=targets.map(target=>({type:clean(target?.type).toLowerCase()==="role"?"role":"name",value:clean(target?.value||target?.name),label:clean(target?.label||target?.value||target?.name)})).filter(target=>target.value);
  const messageTemplate=String(params.messageTemplate||params.template||"").trim();
  await query(`insert into guild_notification_settings(guild_id,notification_key,targets,message_template,updated_at) values($1,$2,$3::jsonb,$4,now()) on conflict(guild_id,notification_key) do update set targets=$3::jsonb,message_template=$4,updated_at=now()`,[guildId,notificationKey,JSON.stringify(targets),messageTemplate]);
  return {success:true,notificationKey,targets,messageTemplate};
}

async function notificationMessageTemplate(guildId,notificationKey){
  await ensureGuildNotificationSettingsSchema();
  const result=await query(`select message_template from guild_notification_settings where guild_id=$1 and notification_key=$2`,[guildId,clean(notificationKey)]);
  return clean(result.rows[0]?.message_template);
}

const ALL_PO_RELEASE_DISPLAY_RAIDS = ["recruit", "p1p3", "mc", "bwl", "aq40", "naxx", "zg-mittwoch", "zg-prime", "zg-late"];

async function getPoReleaseDisplaySettings(guildId) {
  await ensureGuildLayoutSchema();
  const result = await query(`select layout_json from guild_settings where guild_id=$1`, [guildId]);
  const saved = result.rows[0]?.layout_json?.poReleaseVisibleRaids;
  const configured = Array.isArray(saved);
  const settingVersion = Number(result.rows[0]?.layout_json?.poReleaseDisplayVersion || 0);
  const visibleRaids = Array.isArray(saved)
    ? saved.map(value => clean(value).toLowerCase()).filter(value => ALL_PO_RELEASE_DISPLAY_RAIDS.includes(value))
    : [...ALL_PO_RELEASE_DISPLAY_RAIDS];
  if (configured && settingVersion < 2 && !visibleRaids.includes("recruit")) visibleRaids.unshift("recruit");
  return { success:true, visibleRaids, configured };
}

async function setPoReleaseDisplaySettings({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  await ensureGuildLayoutSchema();
  let requested = [];
  try { requested = typeof params.visibleRaids === "string" ? JSON.parse(params.visibleRaids) : params.visibleRaids; } catch {}
  const visibleRaids = Array.isArray(requested)
    ? [...new Set(requested.map(value => clean(value).toLowerCase()).filter(value => ALL_PO_RELEASE_DISPLAY_RAIDS.includes(value)))]
    : [...ALL_PO_RELEASE_DISPLAY_RAIDS];
  await query(
    `insert into guild_settings (guild_id, layout_json)
     values ($1, jsonb_build_object('poReleaseVisibleRaids', $2::jsonb, 'poReleaseDisplayVersion', 2))
     on conflict (guild_id) do update
       set layout_json=jsonb_set(jsonb_set(coalesce(guild_settings.layout_json,'{}'::jsonb),'{poReleaseVisibleRaids}',$2::jsonb,true),'{poReleaseDisplayVersion}','2'::jsonb,true), updated_at=now()`,
    [guildId, JSON.stringify(visibleRaids)]
  );
  return { success:true, visibleRaids };
}

async function ensureWorldbuffAccessSchema(){
  await query(`create table if not exists guild_worldbuff_access (guild_id uuid primary key references guilds(id) on delete cascade,password text not null,updated_at timestamptz not null default now())`);
}
async function loadWorldbuffAccessCode(guildId){
  await ensureWorldbuffAccessSchema();
  const id=String(guildId||"");
  if(worldbuffAccessCodeOverrides.has(id))return worldbuffAccessCodeOverrides.get(id);
  const result=await query(`select password from guild_worldbuff_access where guild_id=$1 limit 1`,[guildId]);
  const value=clean(result.rows[0]?.password);if(value)worldbuffAccessCodeOverrides.set(id,value);return value;
}
async function setWorldbuffAccessPassword({guildId,query:params={}}){
  const code=clean(params.masterCode);
  const allowedAdminCodes=new Set([clean(masterCode),clean(masterCodeOverrides.get(String(guildId||"")))].filter(Boolean));
  if(!code || !allowedAdminCodes.has(code)){
    const error=new Error("Nur die Gildenleitung darf das Worldbuff-Passwort ändern.");error.statusCode=403;throw error;
  }
  await ensureWorldbuffAccessSchema();
  const password=clean(params.password||params.worldbuffPassword);
  if(password.length<6){const error=new Error("Das Worldbuff-Passwort muss mindestens 6 Zeichen haben.");error.statusCode=400;throw error;}
  await query(`insert into guild_worldbuff_access(guild_id,password,updated_at) values($1,$2,now()) on conflict(guild_id) do update set password=$2,updated_at=now()`,[guildId,password]);
  worldbuffAccessCodeOverrides.set(String(guildId),password);return {success:true};
}

async function ensureLootMasterAccessSchema(){
  await query(`create table if not exists guild_loot_master_access (guild_id uuid primary key references guilds(id) on delete cascade,password text not null,updated_at timestamptz not null default now())`);
}
async function loadLootMasterAccessCode(guildId){
  await ensureLootMasterAccessSchema();
  const id=String(guildId||"");
  if(lootMasterAccessCodeOverrides.has(id)) return lootMasterAccessCodeOverrides.get(id);
  const result=await query(`select password from guild_loot_master_access where guild_id=$1 limit 1`,[guildId]);
  const value=clean(result.rows[0]?.password);
  if(value) lootMasterAccessCodeOverrides.set(id,value);
  return value;
}
async function effectiveLootMasterPin(guildId){
  const configured=clean(await loadLootMasterAccessCode(guildId));
  if(configured)return configured;
  const result=await query(`select slug from guilds where id=$1 limit 1`,[guildId]);
  const slug=clean(result.rows[0]?.slug).toLowerCase();
  return ["lichtloot","lichtbringer"].includes(slug)?"1301":"";
}
async function setLootMasterAccessPassword({guildId,query:params={}}){
  const code=clean(params.masterCode);
  const allowedAdminCodes=new Set([clean(masterCode),clean(masterCodeOverrides.get(String(guildId||"")))].filter(Boolean));
  if(!code || !allowedAdminCodes.has(code)){
    const error=new Error("Nur die Gildenleitung darf das Plündermeister-Passwort ändern.");error.statusCode=403;throw error;
  }
  const password=clean(params.password||params.lootMasterPassword);
  if(password.length<6){const error=new Error("Das Plündermeister-Passwort muss mindestens 6 Zeichen haben.");error.statusCode=400;throw error;}
  await ensureLootMasterAccessSchema();
  await query(`insert into guild_loot_master_access(guild_id,password,updated_at) values($1,$2,now()) on conflict(guild_id) do update set password=$2,updated_at=now()`,[guildId,password]);
  lootMasterAccessCodeOverrides.set(String(guildId),password);
  return {success:true,scope:"loot_master_p0"};
}

async function ensureBuffTables() {
  await query(
    `create table if not exists hordenbuff_events (
       id uuid primary key default gen_random_uuid(),
       guild_id uuid not null references guilds(id) on delete cascade,
       buff text not null default 'Rend',
       event_date date not null,
       event_time text not null,
       faction text not null default 'Horde',
       status text not null default 'offen',
       note text,
       created_at timestamptz not null default now(),
       updated_at timestamptz not null default now(),
       unique (guild_id, buff, event_date, event_time)
     )`
  );
  await query(
    `create table if not exists hordenbuff_entries (
       id uuid primary key default gen_random_uuid(),
       event_id uuid not null references hordenbuff_events(id) on delete cascade,
       ally_char text,
       horde_char text,
       status text not null default 'offen',
       note text,
       source text not null default 'railway',
       created_at timestamptz not null default now(),
       updated_at timestamptz not null default now()
     )`
  );
  await query(
    `create table if not exists worldbuff_events (
       id uuid primary key default gen_random_uuid(),
       guild_id uuid not null references guilds(id) on delete cascade,
       buff text not null,
       event_date date not null,
       event_time text not null,
       guild_name text,
       status text not null default 'offen',
       note text,
       source text not null default 'railway',
       created_at timestamptz not null default now(),
       updated_at timestamptz not null default now(),
       unique (guild_id, buff, event_date, event_time, guild_name)
     )`
  );
  await query(
    `create table if not exists worldbuff_entries (
       id uuid primary key default gen_random_uuid(),
       event_id uuid not null references worldbuff_events(id) on delete cascade,
       caster text,
       discord_name text,
       status text not null default 'offen',
       note text,
       source text not null default 'railway',
       created_at timestamptz not null default now(),
       updated_at timestamptz not null default now()
    )`
  );
  await query(
    `create table if not exists worldbuff_poster_events (
       id uuid primary key default gen_random_uuid(),
       guild_id uuid not null references guilds(id) on delete cascade,
       buff text not null,
       event_date date not null,
       event_time text not null,
       guild_name text not null,
       source text not null default 'wb_poster',
       created_at timestamptz not null default now(),
       updated_at timestamptz not null default now(),
       unique (guild_id, buff, event_date, event_time, guild_name)
     )`
  );
  await query(`create index if not exists hordenbuff_events_guild_date_idx on hordenbuff_events (guild_id, event_date, event_time)`);
  await query(`create index if not exists worldbuff_events_guild_date_idx on worldbuff_events (guild_id, event_date, event_time)`);
  await query(`create index if not exists worldbuff_poster_events_guild_date_idx on worldbuff_poster_events (guild_id, event_date, event_time)`);
}

function isUuid(value) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(clean(value));
}

function extractWarcraftLogsReportCode(value) {
  const text = clean(value);
  if (!text) return "";

  const reportMatch = text.match(/\/reports\/([A-Za-z0-9]+)/i);
  if (reportMatch) return reportMatch[1];

  const queryMatch = text.match(/[?&]report=([A-Za-z0-9]+)/i);
  if (queryMatch) return queryMatch[1];

  if (/^[A-Za-z0-9]{8,32}$/.test(text)) return text;
  return "";
}

function normalizeWarcraftLogsReportUrl(url, reportCode) {
  const raw = clean(url);
  if (raw && /^https?:\/\//i.test(raw)) return raw;
  return reportCode ? `${warcraftLogsBaseUrl()}/reports/${reportCode}` : raw;
}

function normalizeStatus(value) {
  const raw = clean(value).toLowerCase();
  if (raw === "offen") return "geöffnet";
  if (raw === "open") return "geöffnet";
  if (raw === "closed") return "geschlossen";
  return clean(value) || "geschlossen";
}

function normalizeSignupStatus(value) {
  const raw = clean(value).toLowerCase();
  if (["bench", "ersatzbank", "reserve"].includes(raw)) return "bench";
  if (["late", "spät", "spaet", "verspätet", "verspaetet"].includes(raw)) return "late";
  if (["tentative", "maybe", "vielleicht", "unsicher"].includes(raw)) return "tentative";
  if (["absent", "abgemeldet", "abwesend", "nein"].includes(raw)) return "absent";
  return "signed";
}

function normalizeSignupRole(value) {
  const raw = clean(value).toLowerCase();
  if (["tank", "tanks"].includes(raw)) return "tank";
  if (["heal", "heiler", "heals", "healer"].includes(raw)) return "heal";
  if (["dd", "dps", "damage"].includes(raw)) return "dd";
  return "flex";
}

function parseOptionalInteger(value) {
  const raw = clean(value);
  if (!raw) return null;
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

function raidPublicId(row) {
  return row.external_raid_id || row.id;
}

function displayStoredGuildName(value) {
  const raw = clean(value);
  return raw.toLowerCase() === "lichtloot" ? "Lichtbringer" : raw;
}

function normalizeRaidRow(row) {
  const raidDate = row.raid_date ? row.raid_date.toISOString().slice(0, 10) : "";
  const p0PlusTransferCount = Number(row.p0plus_transfer_count || 0);
  const guildName = displayStoredGuildName(row.guild_name || "");
  return {
    id: row.id,
    raidId: raidPublicId(row),
    RaidID: raidPublicId(row),
    raid: row.raid_type,
    raidName: row.name || displayRaidName(row.raid_type),
    raidDate,
    date: raidDate,
    datum: raidDate,
    raidTime: row.raid_time || "",
    time: row.raid_time || "",
    uhrzeit: row.raid_time || "",
    guild: guildName,
    gilde: guildName,
    playerPin: row.raid_pin || "",
    prioPin: row.raid_pin || "",
    leadPin: row.lead_pin || "",
    status: row.status || "geschlossen",
    p0PlusFreigabe: row.p0plus_freigabe || "geschlossen",
    raidHelperEnabled: row.raidhelper_enabled !== false,
    signupDeadline: row.signup_deadline || "",
    maxPlayers: row.max_players === null || row.max_players === undefined ? "" : Number(row.max_players),
    tankSlots: row.tank_slots === null || row.tank_slots === undefined ? "" : Number(row.tank_slots),
    healSlots: row.heal_slots === null || row.heal_slots === undefined ? "" : Number(row.heal_slots),
    ddSlots: row.dd_slots === null || row.dd_slots === undefined ? "" : Number(row.dd_slots),
    discordChannelId: row.discord_channel_id || "",
    discordMessageId: row.discord_message_id || "",
    description: row.description || "",
    raidImageUrl: row.raid_image_url || "",
    imageUrl: row.raid_image_url || "",
    signupCounts: row.signup_counts || null,
    p0PlusTransferred: p0PlusTransferCount > 0,
    p0PlusTransferCount,
    playerLink: row.player_link || "",
    createdBy: row.created_by || "",
    erstelltVon: row.created_by || "",
    lootMaster: row.loot_master || "",
    pluendermeister: row.loot_master || "",
    lootMasterTargets: Array.isArray(row.loot_master_targets) ? row.loot_master_targets : [],
    statusNotifyTargets: Array.isArray(row.status_notify_targets) ? row.status_notify_targets : [],
    announcementNotifyTargets: Array.isArray(row.announcement_notify_targets) ? row.announcement_notify_targets : [],
    createdAt: row.created_at,
    updatedAt: row.updated_at
  };
}

function normalizeHordenbuffStatus(value) {
  const raw = clean(value).toLowerCase();
  if (!raw) return "offen";
  if (raw.includes("erledigt") || raw === "done" || raw === "fertig") return "erledigt";
  if (raw.includes("zugeteilt")) return "zugeteilt";
  if (raw.includes("offen")) return "offen";
  return clean(value);
}

function normalizeWorldbuffStatus(value) {
  const raw = clean(value).replace(/[🟡🟢✅🔴🟠⚪]/g, "").trim().toLowerCase();
  if (!raw) return "offen";
  if (raw.includes("bestätigt") || raw.includes("bestaetigt") || raw.includes("reserviert")) return "bestätigt";
  if (raw.includes("erledigt") || raw === "done" || raw === "fertig") return "erledigt";
  if (raw.includes("offen") || raw.includes("frei")) return "offen";
  return clean(value);
}

function normalizeHordenbuffRow(row) {
  return {
    rowNumber: row.entry_id || "",
    eventId: row.event_id,
    buff: row.buff || "Rend",
    tag: row.tag || weekdayShort(row.event_date),
    datum: formatGermanDate(row.event_date),
    date: row.event_date ? row.event_date.toISOString().slice(0, 10) : "",
    uhrzeit: row.event_time || "",
    gilde: row.faction || "Horde",
    charakter: row.ally_char || "",
    uebernehmer: row.horde_char || "",
    status: row.entry_status || row.event_status || "offen",
    note: row.entry_note || row.event_note || "",
    notiz: row.entry_note || row.event_note || "",
    source: row.source || "railway",
    key: `${formatGermanDate(row.event_date)}|${row.event_time || ""}|Rend|${row.faction || "Horde"}`
  };
}

function parseCsvRows(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let quote = false;
  const input = String(text || "");

  for (let index = 0; index < input.length; index += 1) {
    const char = input[index];
    if (char === "\"") {
      if (quote && input[index + 1] === "\"") {
        cell += "\"";
        index += 1;
      } else {
        quote = !quote;
      }
    } else if ((char === "," || char === ";") && !quote) {
      row.push(cell);
      cell = "";
    } else if ((char === "\n" || char === "\r") && !quote) {
      if (char === "\r" && input[index + 1] === "\n") index += 1;
      row.push(cell);
      cell = "";
      if (row.some(value => clean(value))) rows.push(row);
      row = [];
    } else {
      cell += char;
    }
  }

  row.push(cell);
  if (row.some(value => clean(value))) rows.push(row);
  return rows;
}

function normalizeCsvHeader(value) {
  return slugify(value).replace(/-/g, " ");
}

function normalizeWorldbuffName(value) {
  const text = clean(value)
    .replace(/^[-–•]+\s*/, "")
    .replace(/[🟢🔴🟠⚪🟡]/g, "")
    .replace(/\*/g, "")
    .trim();
  const lower = text.toLowerCase();
  if (lower === "zg" || lower.includes("hakkar")) return "Hakkar";
  if (lower.includes("ony")) return "Ony";
  if (lower.includes("nef")) return "Nef";
  if (lower.includes("rend")) return "Rend";
  return text;
}

function normalizeWorldbuffGuildName(value) {
  let text = clean(value);
  if (!text || text === "-") return "";
  text = text.replace(/^(Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag|Mo|Di|Mi|Do|Fr|Sa|So)\s*[·•\-:|/]\s*/i, "").trim();
  if (/lichtbringer/i.test(text)) return "Lichtbringer";
  if (/lichtloot/i.test(text)) return "lichtloot";
  return text;
}

function worldbuffDailySlotType(buff) {
  const normalized = normalizeWorldbuffName(buff);
  if (normalized === "Hakkar") return "hakkar";
  if (normalized === "Ony" || normalized === "Nef") return "ony-nef";
  return normalized ? normalized.toLowerCase() : "";
}

function worldbuffDailySlotKey(entry) {
  const date = parseDateValue(entry.date || entry.datum || entry.event_date || entry.eventDate);
  const time = clean(entry.uhrzeit || entry.time || entry.event_time || entry.eventTime).replace(/:00$/, "");
  const buff = normalizeWorldbuffName(entry.buff);
  const guild = normalizeWorldbuffGuildName(entry.gilde || entry.guild || entry.guild_name).toLowerCase();
  if (!date || !time || !buff) return "";
  return [date, time, buff, guild].join("|");
}

function normalizeWorldbuffRow(row) {
  const datum = clean(row.datum || row.Datum || row.date || row.Date);
  const uhrzeit = clean(row.uhrzeit || row.Uhrzeit || row.time || row.Time);
  const buff = normalizeWorldbuffName(row.buff || row.Buff || row.name || row.Name || row.type || row.Type);
  const gilde = normalizeWorldbuffGuildName(row.gilde || row.Gilde || row.guild || row.Guild || row.fraktion || row.Fraktion || row["Gilde / Fraktion"]);

  if (!datum || !uhrzeit || !buff) return null;
  return {
    buff,
    datum,
    date: parseDateValue(datum),
    uhrzeit,
    time: uhrzeit,
    gilde,
    charakter: clean(row.charakter || row.Charakter || row.caster || row.Caster || row.werfer || row.Werfer || row.character),
    uebernehmer: clean(row.uebernehmer || row.Übernehmer || row.Uebernehmer || row.helfer || row.Helfer),
    status: clean(row.status || row.Status || "offen") || "offen",
    notiz: clean(row.notiz || row.Notiz || row.note || row.Note || row.hinweis || row.Hinweis),
    tag: clean(row.tag || row.Tag) || weekdayShort(datum),
    source: clean(row.source || row.Source || "railway-worldbuff")
  };
}

function normalizeWorldbuffDbRow(row) {
  const guildName = normalizeWorldbuffGuildName(row.guild_name || "");
  return {
    rowNumber: row.entry_id || row.event_id || "",
    eventId: row.event_id,
    buff: normalizeWorldbuffName(row.buff || "Worldbuff"),
    tag: row.tag || weekdayShort(row.event_date),
    datum: formatGermanDate(row.event_date),
    date: row.event_date ? row.event_date.toISOString().slice(0, 10) : "",
    uhrzeit: row.event_time || "",
    time: row.event_time || "",
    gilde: guildName,
    charakter: row.caster || "",
    caster: row.caster || "",
    discord: row.discord_name || "",
    uebernehmer: "",
    status: row.entry_status || row.event_status || "offen",
    notiz: row.entry_note || row.event_note || "",
    note: row.entry_note || row.event_note || "",
    source: row.entry_source || row.event_source || "railway",
    key: `${formatGermanDate(row.event_date)}|${row.event_time || ""}|${normalizeWorldbuffName(row.buff || "")}|${guildName}`
  };
}

function worldbuffCsvRowsToBuffs(text) {
  const rows = parseCsvRows(text);
  const headerIndex = rows.findIndex(row => {
    const headers = row.map(normalizeCsvHeader);
    return headers.includes("tag") && headers.includes("datum") && headers.includes("uhrzeit") && headers.includes("buff");
  });
  if (headerIndex < 0) return [];

  const headers = rows[headerIndex].map(normalizeCsvHeader);
  const find = (...names) => headers.findIndex(header => names.map(normalizeCsvHeader).includes(header));
  const idx = {
    tag: find("tag"),
    datum: find("datum"),
    uhrzeit: find("uhrzeit", "zeit"),
    buff: find("buff"),
    gilde: find("gilde fraktion", "gilde", "fraktion"),
    charakter: find("charakter", "char", "spieler", "werfer"),
    uebernehmer: find("uebernehmer", "helfer", "helper"),
    status: find("status"),
    notiz: find("notiz", "note", "hinweis")
  };
  let lastTag = "";
  let lastDatum = "";

  return rows.slice(headerIndex + 1).map(row => {
    const value = name => (idx[name] >= 0 ? clean(row[idx[name]]) : "");
    const tag = value("tag") || lastTag;
    const datum = value("datum") || lastDatum;
    if (value("tag")) lastTag = value("tag");
    if (value("datum")) lastDatum = value("datum");
    return normalizeWorldbuffRow({
      Tag: tag,
      Datum: datum,
      Uhrzeit: value("uhrzeit"),
      Buff: value("buff"),
      "Gilde / Fraktion": value("gilde"),
      Charakter: value("charakter"),
      Übernehmer: value("uebernehmer"),
      Status: value("status"),
      Notiz: value("notiz"),
      source: "Worldbuff-Sheet"
    });
  }).filter(Boolean);
}

function worldbuffTickerRowsToBuffs(text) {
  return parseCsvRows(text).map(row => {
    let cells = row.map(clean).filter(Boolean);
    if (cells.length < 3) {
      cells = splitWorldbuffTickerTextLine(cells.join(" "));
    }
    if (cells.length < 3) return null;
    const dateCell = cells.find(cell => /^\d{1,2}\.\d{1,2}\.\d{4}$/.test(cell) || /^\d{4}-\d{2}-\d{2}$/.test(cell));
    const timeCell = cells.find(cell => /^\d{1,2}:\d{2}(?::\d{2})?$/.test(cell));
    const buffCell = cells.find(cell => ["Hakkar", "Ony", "Nef", "Rend"].includes(normalizeWorldbuffName(cell)));
    if (!dateCell || !timeCell || !buffCell) return null;
    return normalizeWorldbuffRow({
      Datum: dateCell,
      Uhrzeit: timeCell,
      Buff: normalizeWorldbuffName(buffCell),
      "Gilde / Fraktion": cells.filter(cell => cell !== dateCell && cell !== timeCell && cell !== buffCell).join(" · "),
      source: "Worldbuffticker"
    });
  }).filter(Boolean);
}

function splitWorldbuffTickerTextLine(line) {
  const text = clean(line).replace(/\s+/g, " ");
  if (!text || /^\/{3,}$/.test(text)) return [];
  const buffWords = "(Hakkar|ZG|Ony|Onyxia|Nef|Nefarian|Rend)";
  const dateWords = "(\\d{1,2}\\.\\d{1,2}\\.\\d{4}|\\d{4}-\\d{2}-\\d{2})";
  const dayWords = "(?:Mo|Di|Mi|Do|Fr|Sa|So|Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)";
  const timeWords = "(\\d{1,2}:\\d{2}(?::\\d{2})?)";
  const patterns = [
    new RegExp(`^${buffWords}\\s+${dateWords}\\s+${dayWords}\\s+${timeWords}\\s+(.+)$`, "i"),
    new RegExp(`^${dateWords}\\s+${dayWords}\\s+${timeWords}\\s+${buffWords}\\s+(.+)$`, "i"),
    new RegExp(`^${buffWords}\\s+${dateWords}\\s+${timeWords}\\s+(.+)$`, "i"),
    new RegExp(`^${dateWords}\\s+${timeWords}\\s+${buffWords}\\s+(.+)$`, "i")
  ];

  for (const [index, pattern] of patterns.entries()) {
    const match = text.match(pattern);
    if (!match) continue;
    if (index === 0 || index === 2) {
      return [match[1], match[2], match[3], match[4]];
    }
    return [match[3], match[1], match[2], match[4]];
  }
  return [];
}

function worldbuffTimestamp(entry) {
  const iso = parseDateValue(entry.date || entry.datum);
  const match = clean(entry.uhrzeit || entry.time).match(/^(\d{1,2}):(\d{2})/);
  const hours = match ? Math.max(0, Math.min(23, Number(match[1]) || 0)) : 0;
  const minutes = match ? Math.max(0, Math.min(59, Number(match[2]) || 0)) : 0;
  return new Date(`${iso}T${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:00`).getTime();
}

async function fetchText(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.text();
}

async function getWorldbuffsFromSheets(params = {}) {
  const days = clean(params.days || "14");
  const dayCount = days === "all" ? 3650 : Math.max(Number(days) || 14, 1);
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const end = start.getTime() + dayCount * 24 * 60 * 60 * 1000;
  const entries = [];

  const sources = [
    { url: worldbuffPublicCsvUrl, parse: worldbuffCsvRowsToBuffs },
    { url: worldbuffTickerCsvUrl, parse: worldbuffTickerRowsToBuffs }
  ];

  for (const source of sources) {
    try {
      entries.push(...source.parse(await fetchText(source.url)));
    } catch (error) {
      console.warn("Worldbuff-Quelle nicht ladbar:", source.url, error.message || error);
    }
  }

  const filtered = entries
    .filter(entry => {
      const timestamp = worldbuffTimestamp(entry);
      return timestamp >= start.getTime() && timestamp < end;
    })
    .sort((a, b) => worldbuffTimestamp(a) - worldbuffTimestamp(b));

  return { success: true, buffs: filtered, entries: filtered };
}

function raidKeyFromP0ReleaseHeader(value) {
  const raw = clean(value).toLowerCase();
  if (!raw) return "";
  if (raw.includes("aq40") || raw.includes("tempel")) return "aq40";
  if (raw.includes("naxx")) return "naxx";
  if (raw.includes("bwl") || raw.includes("blackwing")) return "bwl";
  if (raw.includes("mc") || raw.includes("molten")) return "mc";
  return "";
}

async function getP0ReleaseList(guildId = "") {
  const now = Date.now();
  const cacheKey = clean(guildId) || "global";
  if (p0ReleaseCache && p0ReleaseCache.key === cacheKey && now < p0ReleaseCacheUntil) {
    return { success: true, releases: p0ReleaseCache };
  }

  const releases = {
    mc: [], bwl: [], aq40: [], naxx: [],
    "zg-mittwoch": [], "zg-prime": [], "zg-late": []
  };
  let includeLegacyCsv = !guildId;
  if (guildId) {
    const guildResult = await query(`select slug from guilds where id = $1 limit 1`, [guildId]);
    includeLegacyCsv = clean(guildResult.rows[0]?.slug).toLowerCase() === "lichtloot";
  }
  if (includeLegacyCsv) {
    const rows = parseCsvRows(await fetchText(p0ReleaseCsvUrl));
    const raidColumns = new Map();
    (rows[0] || []).forEach((cell, index) => {
      const raidKey = raidKeyFromP0ReleaseHeader(cell);
      if (raidKey) raidColumns.set(index, raidKey);
    });
    rows.slice(1).forEach(row => {
      raidColumns.forEach((raidKey, index) => {
        const player = clean(row[index]);
        if (player && !releases[raidKey].some(existing => existing.toLowerCase() === player.toLowerCase())) {
          releases[raidKey].push(player);
        }
      });
    });
  }

  if (guildId) {
    try {
      await ensureCharacterPoReleaseSchema();
      const dbResult = await query(
        `select c.name, cpr.raid_type
         from character_po_releases cpr
         join characters c on c.id = cpr.character_id
         join players p on p.id = c.player_id
         where cpr.guild_id = $1 and p.guild_id = $1`,
        [guildId]
      );
      for (const row of dbResult.rows) {
        const raidKey = normalizePoReleaseRaid(row.raid_type);
        const player = clean(row.name);
        if (raidKey && player && !releases[raidKey].some(existing => existing.toLowerCase() === player.toLowerCase())) {
          releases[raidKey].push(player);
        }
      }
    } catch (error) {
      console.warn("P0+ Freigaben aus Datenbank konnten nicht geladen werden:", error.message || error);
    }
  }

  Object.keys(releases).forEach(key => releases[key].sort((a, b) => a.localeCompare(b, "de")));
  Object.defineProperty(releases, "key", { value: cacheKey, enumerable: false });
  p0ReleaseCache = releases;
  p0ReleaseCacheUntil = now + 5 * 60 * 1000;
  return { success: true, releases };
}

function normalizePoReleaseRaid(value) {
  const raid = normalizeRaidType(value);
  if (["p1p3", "p1-p3", "p1_p3"].includes(clean(value).toLowerCase())) return "p1p3";
  return ["mc", "bwl", "aq40", "naxx", "zg-mittwoch", "zg-prime", "zg-late"].includes(raid) ? raid : "";
}

function normalizePoReleaseCharacterName(value) {
  return clean(value)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/ß/g, "ss")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
}

function isNachtlootRecruitRaid(value) {
  return ["bwl", "aq40", "naxx"].includes(normalizePoReleaseRaid(value));
}

async function ensureCharacterPoReleaseSchema() {
  await ensureRaidSchema();
  await query(`alter table characters add column if not exists recruit_status_lifted boolean not null default false`);
  await query(`alter table characters add column if not exists recruit_status_lifted_at timestamptz`);
  await query(`alter table characters add column if not exists recruit_status_lifted_by text`);
  await query(
    `create table if not exists po_release_requests (
       id uuid primary key default gen_random_uuid(),
       guild_id uuid not null references guilds(id) on delete cascade,
       character_id uuid not null references characters(id) on delete cascade,
       request_type text not null,
       raid_type text,
       specialization text,
       armory_url text,
       screenshot_data text,
       requirements jsonb not null default '{}'::jsonb,
       status text not null default 'pending',
       review_note text,
       reviewed_by text,
       reviewed_at timestamptz,
       created_at timestamptz not null default now(),
       updated_at timestamptz not null default now()
     )`
  );
  await query(`create index if not exists idx_po_release_requests_guild_status on po_release_requests(guild_id, status, created_at desc)`);
  await query(
    `create table if not exists character_recruit_releases (
       id uuid primary key default gen_random_uuid(),
       guild_id uuid not null references guilds(id) on delete cascade,
       character_id uuid not null references characters(id) on delete cascade,
       raid_type text not null,
       approved_by text not null default '',
       approved_at timestamptz not null default now(),
       updated_at timestamptz not null default now(),
       unique(guild_id, character_id, raid_type)
     )`
  );
  await query(
    `insert into character_recruit_releases(guild_id,character_id,raid_type,approved_by,approved_at)
     select p.guild_id,c.id,raid.raid_type,coalesce(c.recruit_status_lifted_by,'Migration'),coalesce(c.recruit_status_lifted_at,now())
     from characters c join players p on p.id=c.player_id
     cross join (values ('mc'),('bwl'),('aq40'),('naxx'),('zg-mittwoch'),('zg-prime'),('zg-late')) raid(raid_type)
     where c.recruit_status_lifted=true
     on conflict(guild_id,character_id,raid_type) do nothing`
  );
  await query(`update characters set recruit_status_lifted=false where recruit_status_lifted=true`);
}

async function requireNachtlootGuild(guildId) {
  const result = await query(`select slug from guilds where id = $1 limit 1`, [guildId]);
  if (clean(result.rows[0]?.slug).toLowerCase() !== "nachtloot") {
    const error = new Error("PO-Freigabeanträge stehen nur Nachtwächter zur Verfügung.");
    error.statusCode = 403;
    throw error;
  }
}

function poRequestRequirements(type, raid, className, specialization) {
  const source = "https://docs.google.com/spreadsheets/d/136_vXW_p3Z3CMGuXkRkv4hftcxW02p2QO_YMb7OaVfA/edit?gid=1777084015#gid=1777084015";
  if (type === "recruit") return { title:"Aufhebung Rekrutenstatus", rule:"Verzauberungen Rekrut (P2/P3)", source, checks:["Armory oder Screenshot prüfen", "Vorgeschriebene Rekruten-Verzauberungen für Klasse und Raid erfüllt"] };
  if (type === "p1p3") return { title:"P1–P3 Freigabe", rule:"Verzauberungen Fullraider (P1–P3)", source, checks:["Armory oder Screenshot prüfen", "Fullraider-Verzauberungen für Klasse und Raid erfüllt"] };
  return { title:`P0 Freigabe ${String(raid || "").toUpperCase()}`, rule:"P0 Gear-Voraussetzungen und bestmögliche Verzauberungen", source, className:clean(className), specialization:clean(specialization), checks:["Armory oder Screenshot prüfen", "Gear-Voraussetzungen für Klasse/Skillung erfüllt", "Bestmögliche Verzauberungen auf allen relevanten Slots"] };
}

async function submitPoReleaseRequest({ guildId, query: params = {} }) {
  await ensureCharacterPoReleaseSchema();
  await requireNachtlootGuild(guildId);
  const pin = normalizePin(params.playerPin || params.pin);
  const character = await findCharacterForPin(guildId, pin, params.character || params.char || params.player, params.server);
  if (!character) { const error = new Error("Charakter oder SpielerLogin ist nicht gültig."); error.statusCode = 403; throw error; }
  const requestType = clean(params.requestType || params.type).toLowerCase();
  if (!["recruit", "p1p3", "p0"].includes(requestType)) { const error = new Error("Bitte eine gültige Freigabe auswählen."); error.statusCode = 400; throw error; }
  const selectedRaid = normalizePoReleaseRaid(params.raid || params.raidType);
  const raid = selectedRaid;
  if (!raid || raid === "p1p3") { const error = new Error("Bitte den Raid für die Freigabe auswählen."); error.statusCode = 400; throw error; }
  if (["recruit", "p1p3"].includes(requestType) && !isNachtlootRecruitRaid(raid)) {
    const error = new Error("Der Rekrutenstatus gilt nur für BWL, AQ40 und Naxx.");
    error.statusCode = 400;
    throw error;
  }
  const armoryUrl = clean(params.armoryUrl);
  const screenshotData = clean(params.screenshotData);
  if (!armoryUrl && !screenshotData) { const error = new Error("Bitte Armory-Link oder Screenshot angeben."); error.statusCode = 400; throw error; }
  if (screenshotData && !/^data:image\/(png|jpe?g|webp);base64,/i.test(screenshotData)) { const error = new Error("Screenshot-Format ist ungültig."); error.statusCode = 400; throw error; }
  const requirements = poRequestRequirements(requestType, selectedRaid, clean(params.className) || character.class_name, params.specialization);
  const result = await query(
    `insert into po_release_requests (guild_id, character_id, request_type, raid_type, specialization, armory_url, screenshot_data, requirements)
     values ($1,$2,$3,$4,$5,$6,$7,$8::jsonb) returning *`,
    [guildId, character.id, requestType, selectedRaid || null, clean(params.specialization), armoryUrl, screenshotData, JSON.stringify(requirements)]
  );
  const request=result.rows[0];
  const poNotificationKey=`notify_po_releases:${clean(selectedRaid).toLowerCase()}`;
  const notificationTargets=await notificationTargetsForPermissions(guildId,poNotificationKey).catch(()=>[]);
  if(notificationTargets.length){
    const messageTemplate=(await notificationMessageTemplate(guildId,poNotificationKey).catch(()=>""))||(await notificationMessageTemplate(guildId,"notify_po_releases").catch(()=>""));
    await enqueueBotUpdate({guildId,type:"po_release_request_notice",payload:{targets:notificationTargets,messageTemplate,character:character.name||"",server:character.server||"",className:character.class_name||"",requestType,raid:selectedRaid||"",requestId:request.id}}).catch(error=>console.warn("PO-Freigabehinweis konnte nicht queued werden:",error.message||error));
  }
  return { success:true, request };
}

async function getPoReleaseRequests({ guildId, query: params = {}, management = false }) {
  await ensureCharacterPoReleaseSchema(); await requireNachtlootGuild(guildId);
  let characterId = "";
  if (management) requireMasterCode(params.masterCode);
  else {
    const character = await findCharacterForPin(guildId, params.playerPin || params.pin, params.character || params.char || params.player, params.server);
    if (!character) { const error = new Error("Charakter oder SpielerLogin ist nicht gültig."); error.statusCode = 403; throw error; }
    characterId = character.id;
  }
  const values = [guildId];
  const clause = characterId ? `and r.character_id = $2` : "";
  if (characterId) values.push(characterId);
  const result = await query(
    `select r.*, c.name, c.server, c.class_name from po_release_requests r join characters c on c.id=r.character_id
     where r.guild_id=$1 ${clause} order by case when r.status='pending' then 0 else 1 end, r.created_at desc`, values
  );
  return { success:true, entries:result.rows.map(row=>({ id:row.id, characterId:row.character_id, name:row.name, server:row.server, className:row.class_name, requestType:row.request_type, raid:row.raid_type||"", specialization:row.specialization||"", armoryUrl:row.armory_url||"", screenshotData:row.screenshot_data||"", requirements:row.requirements||{}, status:row.status, reviewNote:row.review_note||"", reviewedBy:row.reviewed_by||"", reviewedAt:row.reviewed_at||"", createdAt:row.created_at })) };
}

async function reviewPoReleaseRequest({ guildId, query: params = {} }) {
  requireMasterCode(params.masterCode); await ensureCharacterPoReleaseSchema(); await requireNachtlootGuild(guildId);
  const id = clean(params.id || params.requestId);
  const decision = clean(params.decision || params.status).toLowerCase();
  if (!isUuid(id) || !["approved","rejected"].includes(decision)) { const error = new Error("Antrag oder Entscheidung ist ungültig."); error.statusCode=400; throw error; }
  const found = await query(`select * from po_release_requests where guild_id=$1 and id=$2 limit 1`, [guildId,id]);
  const request = found.rows[0]; if (!request) { const error=new Error("Antrag wurde nicht gefunden."); error.statusCode=404; throw error; }
  const reviewer=clean(params.reviewedBy || params.reviewer || "Gildenleitung");
  if (decision === "approved") {
    if (request.request_type === "recruit" || request.request_type === "p1p3") {
      const raid=normalizePoReleaseRaid(request.raid_type);
      if(!isNachtlootRecruitRaid(raid)){const error=new Error("Der Rekrutenstatus gilt nur für BWL, AQ40 und Naxx.");error.statusCode=400;throw error;}
      await query(`insert into character_recruit_releases(guild_id,character_id,raid_type,approved_by,approved_at,updated_at) values($1,$2,$3,$4,now(),now()) on conflict(guild_id,character_id,raid_type) do update set approved_by=$4,approved_at=now(),updated_at=now()`,[guildId,request.character_id,raid,reviewer]);
    }
    else {
      const raid=normalizePoReleaseRaid(request.raid_type);
      await query(`insert into character_po_releases(guild_id,character_id,raid_type,source,approved_by,approved_at) values($1,$2,$3,'application',$4,now()) on conflict(guild_id,character_id,raid_type) do update set source='application',approved_by=$4,approved_at=now(),updated_at=now()`,[guildId,request.character_id,raid,reviewer]);
    }
  }
  const updated=await query(`update po_release_requests set status=$3,review_note=$4,reviewed_by=$5,reviewed_at=now(),updated_at=now() where guild_id=$1 and id=$2 returning *`,[guildId,id,decision,clean(params.reviewNote),reviewer]);
  p0ReleaseCache=null;
  return { success:true, request:updated.rows[0] };
}

async function deletePoReleaseRequest({ guildId, query: params = {} }) {
  requireMasterCode(params.masterCode);
  await ensureCharacterPoReleaseSchema();
  await requireNachtlootGuild(guildId);
  const id = clean(params.id || params.requestId);
  if (!isUuid(id)) {
    const error = new Error("Antrag ist ungültig.");
    error.statusCode = 400;
    throw error;
  }
  const deleted = await query(
    `delete from po_release_requests where guild_id=$1 and id=$2 returning id, character_id, request_type, raid_type`,
    [guildId, id]
  );
  if (!deleted.rows[0]) {
    const error = new Error("Antrag wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }
  return { success:true, deleted:deleted.rows[0] };
}

function poReleaseFlagsFromRows(rows) {
  const flags = { p1p3: false, mc: false, bwl: false, aq40: false, naxx: false, "zg-mittwoch": false, "zg-prime": false, "zg-late": false };
  for (const row of rows || []) {
    const raid = normalizePoReleaseRaid(row.raid_type || row.raid);
    if (raid) flags[raid] = true;
  }
  return flags;
}

async function getCharacterPoReleaseRows(guildId) {
  await ensureCharacterPoReleaseSchema();
  const result = await query(
    `select
       c.id as character_id,
       c.name,
       c.server,
       c.class_name,
       c.is_main,
       c.recruit_status_lifted,
       c.recruit_status_lifted_at,
       c.recruit_status_lifted_by,
       p.player_pin,
       p.id as player_id,
       cpr.raid_type,
       cpr.source,
       cpr.approved_by,
       cpr.approved_at
     from players p
     join characters c on c.player_id = p.id
     left join character_po_releases cpr
       on cpr.guild_id = p.guild_id
      and cpr.character_id = c.id
     where p.guild_id = $1
     order by lower(c.name) asc, lower(coalesce(c.server, '')) asc`,
    [guildId]
  );
  const byCharacter = new Map();
  for (const row of result.rows) {
    const id = row.character_id;
    if (!byCharacter.has(id)) {
      byCharacter.set(id, {
        id,
        characterId: id,
        name: row.name || "",
        char: row.name || "",
        player: row.name || "",
        server: row.server || "",
        className: row.class_name || "",
        isMain: Boolean(row.is_main),
        recruitStatusLifted: Boolean(row.recruit_status_lifted),
        recruitStatusLiftedAt: row.recruit_status_lifted_at || "",
        recruitStatusLiftedBy: row.recruit_status_lifted_by || "",
        recruitReleases: { mc:false,bwl:false,aq40:false,naxx:false,"zg-mittwoch":false,"zg-prime":false,"zg-late":false },
        playerId: row.player_id,
        playerPin: row.player_pin || "",
        releases: {
          p1p3: false,
          mc: false, bwl: false, aq40: false, naxx: false,
          "zg-mittwoch": false, "zg-prime": false, "zg-late": false
        },
        approvedBy: {},
        approvedAt: {}
      });
    }
    const entry = byCharacter.get(id);
    const raid = normalizePoReleaseRaid(row.raid_type);
    if (raid) {
      entry.releases[raid] = true;
      entry.approvedBy[raid] = row.approved_by || "";
      entry.approvedAt[raid] = row.approved_at || "";
    }
  }
  const recruitResult=await query(`select character_id,raid_type,approved_by,approved_at from character_recruit_releases where guild_id=$1`,[guildId]);
  for(const row of recruitResult.rows){const entry=byCharacter.get(row.character_id),raid=normalizePoReleaseRaid(row.raid_type);if(entry&&raid&&raid!=="p1p3"){entry.recruitReleases[raid]=true;}}
  return [...byCharacter.values()];
}

async function getCharacterPoReleases({ guildId, query: params = {} }) {
  requireMasterCode(params.masterCode);
  const search = clean(params.search || params.q).toLowerCase();
  let characters = await getCharacterPoReleaseRows(guildId);
  if (search) {
    characters = characters.filter(entry =>
      [entry.name, entry.server, entry.className, entry.playerPin].some(value => clean(value).toLowerCase().includes(search))
    );
  }
  return { success: true, characters, entries: characters, count: characters.length };
}

async function setCharacterPoRelease({ guildId, query: params = {} }) {
  requireMasterCode(params.masterCode);
  await ensureCharacterPoReleaseSchema();
  const raid = normalizePoReleaseRaid(params.raid || params.raidType);
  const characterId = clean(params.characterId || params.charId);
  const enabled = !["false", "0", "no", "nein", "delete", "remove"].includes(clean(params.enabled || params.value || "true").toLowerCase());
  if (!raid) {
    const error = new Error("Raid für P0+ Freigabe fehlt.");
    error.statusCode = 400;
    throw error;
  }
  if (!isUuid(characterId)) {
    const error = new Error("Charakter fehlt.");
    error.statusCode = 400;
    throw error;
  }
  const character = await query(
    `select c.id, c.name, c.server, c.class_name
     from characters c
     join players p on p.id = c.player_id
     where p.guild_id = $1 and c.id = $2
     limit 1`,
    [guildId, characterId]
  );
  if (!character.rows[0]) {
    const error = new Error("Charakter wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }
  if (enabled) {
    await query(
      `insert into character_po_releases (guild_id, character_id, raid_type, source, approved_by, approved_at)
       values ($1, $2, $3, $4, $5, now())
       on conflict (guild_id, character_id, raid_type) do update
         set source = excluded.source,
             approved_by = excluded.approved_by,
             approved_at = now(),
             updated_at = now()`,
      [guildId, characterId, raid, clean(params.source || "manual"), clean(params.approvedBy || params.reviewer || "Gildenleitung")]
    );
  } else {
    await query(
      `delete from character_po_releases where guild_id = $1 and character_id = $2 and raid_type = $3`,
      [guildId, characterId, raid]
    );
  }
  p0ReleaseCache = null;
  return { success: true, enabled, raid, character: normalizeCharacter(character.rows[0]) };
}

const PO_RELEASE_DM_RAID_LABELS={mc:"Molten Core",bwl:"Blackwing Lair",aq40:"AQ40",naxx:"Naxxramas","zg-mittwoch":"ZG Mittwoch","zg-prime":"ZG Prime","zg-late":"ZG Late",aq20:"AQ20"};
async function sendPoReleaseGrantedDm({guildId,query:params={}}){
  requireMasterCode(params.masterCode);
  const characterId=clean(params.characterId||params.charId);
  const raid=normalizePoReleaseRaid(params.raid||params.raidType);
  if(!isUuid(characterId)){const error=new Error("Charakter fehlt.");error.statusCode=400;throw error;}
  if(!raid||!PO_RELEASE_DM_RAID_LABELS[raid]){const error=new Error("Bitte einen gültigen Raid auswählen.");error.statusCode=400;throw error;}
  const found=await query(`select c.id,c.name,c.server,c.class_name,g.slug,g.name as guild_name,link.discord_user_id,link.discord_name from characters c join players p on p.id=c.player_id join guilds g on g.id=p.guild_id left join lateral (select dpl.discord_user_id,dpl.discord_name from discord_player_links dpl where dpl.guild_id=p.guild_id and dpl.character_id=c.id order by dpl.updated_at desc,dpl.created_at desc limit 1) link on true where p.guild_id=$1 and c.id=$2 limit 1`,[guildId,characterId]);
  const character=found.rows[0];
  if(!character){const error=new Error("Charakter wurde nicht gefunden.");error.statusCode=404;throw error;}
  if(!clean(character.discord_user_id)){const error=new Error("Für diesen Charakter ist noch kein Discord-Account verknüpft. Der Spieler muss seine PO einmal über den PO-Bot eintragen oder seinen SpielerLogin verbinden.");error.statusCode=400;throw error;}
  const notificationKey=`notify_po_release_granted:${raid}`;
  const targets=await notificationTargetsForPermissions(guildId,[notificationKey,"notify_po_release_granted"]);
  const messageTemplate=(await notificationMessageTemplate(guildId,notificationKey).catch(()=>""))||(await notificationMessageTemplate(guildId,"notify_po_release_granted").catch(()=>""))||"✅ **Deine PO-Freigabe wurde erteilt**\n\nDeine PO für **{raid}** wurde freigegeben.\n\n**Gilde:** {gilde}\n**Charakter:** {charakter}-{server}\n**Klasse:** {klasse}";
  await enqueueBotUpdate({guildId,type:"po_release_granted_notice",payload:{guildSlug:character.slug,guildName:character.guild_name||character.slug,character:character.name||"",server:character.server||"",className:character.class_name||"",raid,raidLabel:PO_RELEASE_DM_RAID_LABELS[raid],discordUserId:character.discord_user_id,discordName:character.discord_name||"",targets,messageTemplate,createdAt:new Date().toISOString()}});
  return {success:true,queued:true,raid,raidLabel:PO_RELEASE_DM_RAID_LABELS[raid],character:character.name||""};
}

async function setCharacterRecruitStatusLift({ guildId, query: params = {} }) {
  requireMasterCode(params.masterCode);
  await ensureCharacterPoReleaseSchema();
  const characterId = clean(params.characterId || params.charId);
  const raid = normalizePoReleaseRaid(params.raid || params.raidType);
  const lifted = !["false", "0", "no", "nein", "reset"].includes(clean(params.lifted || params.enabled || params.value || "true").toLowerCase());
  if (!isUuid(characterId)) {
    const error = new Error("Charakter fehlt.");
    error.statusCode = 400;
    throw error;
  }
  if(!isNachtlootRecruitRaid(raid)) { const error=new Error("Der Rekrutenstatus gilt nur für BWL, AQ40 und Naxx.");error.statusCode=400;throw error; }
  const guildResult = await query(`select slug from guilds where id = $1 limit 1`, [guildId]);
  if (clean(guildResult.rows[0]?.slug).toLowerCase() !== "nachtloot") {
    const error = new Error("Der Rekrutenstatus wird nur für Nachtwächter verwaltet.");
    error.statusCode = 403;
    throw error;
  }
  const found=await query(`select c.id,c.name from characters c join players p on p.id=c.player_id where p.guild_id=$1 and c.id=$2 limit 1`,[guildId,characterId]);
  if (!found.rows[0]) {
    const error = new Error("Charakter wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }
  const reviewer=clean(params.approvedBy || params.reviewer || "Gildenleitung");
  if(lifted) await query(`insert into character_recruit_releases(guild_id,character_id,raid_type,approved_by,approved_at,updated_at) values($1,$2,$3,$4,now(),now()) on conflict(guild_id,character_id,raid_type) do update set approved_by=$4,approved_at=now(),updated_at=now()`,[guildId,characterId,raid,reviewer]);
  else await query(`delete from character_recruit_releases where guild_id=$1 and character_id=$2 and raid_type=$3`,[guildId,characterId,raid]);
  return {
    success: true,
    characterId,
    raid,
    lifted,
    liftedAt: lifted ? new Date().toISOString() : "",
    liftedBy: lifted ? reviewer : ""
  };
}

async function importCharacterPoReleases({ guildId, query: params = {} }) {
  requireMasterCode(params.masterCode);
  await ensureCharacterPoReleaseSchema();
  let entries = params.entries || params.rows || [];
  if (typeof entries === "string") {
    try { entries = JSON.parse(entries || "[]"); } catch { entries = []; }
  }
  if (!Array.isArray(entries)) entries = [];
  const characterResult = await query(
    `select c.id, c.name, c.server, c.created_at
     from characters c
     join players p on p.id = c.player_id
     where p.guild_id = $1
     order by lower(c.name) asc, lower(coalesce(c.server, '')) asc, c.created_at asc`,
    [guildId]
  );
  const charactersByNormalizedName = new Map();
  for (const character of characterResult.rows) {
    const key = normalizePoReleaseCharacterName(character.name);
    if (!key) continue;
    if (!charactersByNormalizedName.has(key)) charactersByNormalizedName.set(key, []);
    charactersByNormalizedName.get(key).push(character);
  }
  let updated = 0;
  let skipped = 0;
  const client = await pool.connect();
  try {
    await client.query("begin");
    for (const rawEntry of entries) {
      const name = clean(rawEntry.character || rawEntry.char || rawEntry.name || rawEntry.Charakter);
      const server = clean(rawEntry.server || rawEntry.Server);
      if (!name) {
        skipped += 1;
        continue;
      }
      let matchingCharacters = charactersByNormalizedName.get(normalizePoReleaseCharacterName(name)) || [];
      if (server) {
        matchingCharacters = matchingCharacters.filter(character => clean(character.server).toLowerCase() === server.toLowerCase());
      }
      if (!matchingCharacters.length) {
        skipped += 1;
        continue;
      }
      for (const character of matchingCharacters) {
        const characterId = character.id;
        await client.query(
          `delete from character_po_releases
           where guild_id = $1 and character_id = $2 and raid_type = any($3)`,
          [guildId, characterId, ["mc", "bwl", "aq40", "naxx", "zg-mittwoch", "zg-prime", "zg-late"]]
        );
        for (const raid of ["mc", "bwl", "aq40", "naxx", "zg-mittwoch", "zg-prime", "zg-late"]) {
          const value = rawEntry[raid] ?? rawEntry[raid.toUpperCase()] ?? rawEntry[`po_${raid}`] ?? rawEntry[`p0_${raid}`];
          const enabled = ["true", "1", "ja", "x", "✓", "✔", "freigabe", "freigegeben"].includes(clean(value).toLowerCase());
          if (enabled) {
            await client.query(
              `insert into character_po_releases (guild_id, character_id, raid_type, source, approved_by, approved_at)
               values ($1, $2, $3, 'sheet', $4, now())
               on conflict (guild_id, character_id, raid_type) do update
                 set source = 'sheet',
                     approved_by = excluded.approved_by,
                     approved_at = now(),
                     updated_at = now()`,
              [guildId, characterId, raid, clean(params.approvedBy || "Google Sheet")]
            );
            updated += 1;
          }
        }
      }
    }
    await client.query("commit");
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
  p0ReleaseCache = null;
  return { success: true, updated, skipped };
}

async function checkCharacterPoRelease({ guildId, query: params = {} }) {
  requireMasterOrQueueToken(params);
  const raid = normalizePoReleaseRaid(params.raid || params.raidType || params.raidName);
  if (!raid) return { success: true, allowed: true, raid: "" };
  const pin = params.playerPin || params.pin || params.spielerLogin;
  const charName = params.player || params.char || params.character || params.spieler;
  const character = await findCharacterForPin(guildId, pin, charName, params.server);
  if (!character) {
    const error = new Error("Dieser Charakter gehört nicht zu diesem SpielerPin.");
    error.statusCode = 403;
    throw error;
  }
  await ensureCharacterPoReleaseSchema();
  let result = await query(
    `select 1 from character_po_releases where guild_id = $1 and character_id = $2 and raid_type = $3 limit 1`,
    [guildId, character.id, raid]
  );
  let allowed = Boolean(result.rows[0]);
  if (!allowed) {
    const releasedCharacters = await query(
      `select c.name
       from character_po_releases cpr
       join characters c on c.id = cpr.character_id
       where cpr.guild_id = $1
         and cpr.raid_type = $2`,
      [guildId, raid]
    );
    const wantedName = normalizePoReleaseCharacterName(character.name);
    allowed = releasedCharacters.rows.some(row =>
      normalizePoReleaseCharacterName(row.name) === wantedName
    );
  }
  return {
    success: true,
    allowed,
    raid,
    character: normalizeCharacter(character),
    message: allowed ? "" : "du hast keine P0+ Freigabe wende dich an den Raidlead"
  };
}

function worldbuffMergeLookupKey(entry) {
  const date = parseDateValue(entry.date || entry.datum);
  const time = clean(entry.uhrzeit || entry.time).replace(/:00$/, "");
  const buff = normalizeWorldbuffName(entry.buff);
  const guild = normalizeWorldbuffGuildName(entry.gilde || entry.guild || entry.guild_name).toLowerCase();
  if (!date || !time || !buff) return "";
  return [date, time, buff, guild].join("|");
}

function shouldReplaceWorldbuffRow(existing, incoming) {
  const existingHasCaster = Boolean(clean(existing.charakter || existing.caster));
  const incomingHasCaster = Boolean(clean(incoming.charakter || incoming.caster));
  if (incomingHasCaster && !existingHasCaster) return true;
  if (!incomingHasCaster && existingHasCaster) return false;

  const existingStatus = normalizeWorldbuffStatus(existing.status);
  const incomingStatus = normalizeWorldbuffStatus(incoming.status);
  if (incomingStatus === "bestätigt" && existingStatus !== "bestätigt") return true;
  if (incomingStatus !== "bestätigt" && existingStatus === "bestätigt") return false;

  const incomingSource = clean(incoming.source);
  const existingSource = clean(existing.source);
  if (incomingSource.includes("railway") && !existingSource.includes("railway")) return true;
  if (!incomingSource.includes("railway") && existingSource.includes("railway")) return false;

  const existingGuild = normalizeWorldbuffGuildName(existing.gilde || existing.guild || existing.guild_name);
  const incomingGuild = normalizeWorldbuffGuildName(incoming.gilde || incoming.guild || incoming.guild_name);
  if (incomingGuild && !existingGuild) return true;
  if (!incomingGuild && existingGuild) return false;

  return worldbuffTimestamp(incoming) < worldbuffTimestamp(existing);
}

function sameWorldbuffCasterName(left, right) {
  return clean(left).toLowerCase() === clean(right).toLowerCase();
}

function throwWorldbuffSlotOccupied(existingCaster) {
  const error = new Error(`Dieser Worldbuff-Slot ist bereits von ${clean(existingCaster) || "einem anderen Spieler"} belegt.`);
  error.statusCode = 409;
  throw error;
}

function dedupeWorldbuffRows(rows) {
  const byDailySlot = new Map();

  (rows || []).forEach(row => {
    const normalized = { ...row };
    normalized.gilde = normalizeWorldbuffGuildName(row.gilde || row.guild || row.guild_name);
    const key = worldbuffDailySlotKey(normalized);
    if (!key) return;
    const existing = byDailySlot.get(key);
    if (!existing) {
      byDailySlot.set(key, normalized);
      return;
    }
    if (shouldReplaceWorldbuffRow(existing, normalized)) {
      byDailySlot.set(key, normalized);
    }
  });

  return Array.from(byDailySlot.values()).sort((a, b) => worldbuffTimestamp(a) - worldbuffTimestamp(b));
}

function mergeWorldbuffRowsWithSheetRows(railwayRows, sheetRows) {
  const sheetByKey = new Map();
  const railwayKeys = new Set();
  (sheetRows || []).forEach(row => {
    const key = worldbuffMergeLookupKey(row);
    if (!key) return;
    const existing = sheetByKey.get(key);
    if (!existing || clean(row.charakter || row.caster || row.werfer)) {
      sheetByKey.set(key, row);
    }
  });

  const merged = (railwayRows || []).map(row => {
    const rowKey = worldbuffMergeLookupKey(row);
    if (rowKey) railwayKeys.add(rowKey);
    const sheet = sheetByKey.get(worldbuffMergeLookupKey(row));
    if (!sheet) return row;
    const charakter = clean(row.charakter || row.caster) || clean(sheet.charakter || sheet.caster || sheet.werfer);
    const uebernehmer = clean(row.uebernehmer) || clean(sheet.uebernehmer || sheet.helfer);
    const rowStatus = normalizeWorldbuffStatus(row.status);
    const sheetStatus = normalizeWorldbuffStatus(sheet.status);
    const status = charakter && rowStatus === "offen" && sheetStatus && sheetStatus !== "offen"
      ? sheetStatus
      : (rowStatus || sheetStatus || "offen");
    return {
      ...row,
      charakter,
      caster: charakter,
      uebernehmer,
      status,
      notiz: clean(row.notiz || row.note) || clean(sheet.notiz || sheet.note),
      note: clean(row.notiz || row.note) || clean(sheet.notiz || sheet.note),
      source: clean(row.source) || clean(sheet.source) || "railway"
    };
  });

  (sheetRows || []).forEach(row => {
    const key = worldbuffMergeLookupKey(row);
    if (key && !railwayKeys.has(key)) {
      merged.push(row);
      railwayKeys.add(key);
    }
  });

  return merged.sort((a, b) => worldbuffTimestamp(a) - worldbuffTimestamp(b));
}

async function getWorldbuffs({ guildId, query: params }) {
  await ensureBuffTables();
  const days = clean(params.days || "14");
  const source = clean(params.source).toLowerCase();
  const allowSheetFallback = clean(params.allowSheetFallback || params.sheetFallback).toLowerCase() === "true";
  const dayCount = days === "all" ? 3650 : Math.max(Number(days) || 14, 1);
  const values = [guildId];
  let windowClause = "";
  if (days !== "all") {
    values.push(dayCount);
    windowClause = `and e.event_date <= current_date + ($2::int * interval '1 day')`;
  }

  const result = await query(
    `select e.id as event_id, e.buff, e.event_date, e.event_time, e.guild_name,
            e.status as event_status, e.note as event_note, e.source as event_source,
            we.id as entry_id, we.caster, we.discord_name,
            we.status as entry_status, we.note as entry_note, we.source as entry_source
     from worldbuff_events e
     left join lateral (
       select *
       from worldbuff_entries entry
       where entry.event_id = e.id
       order by
         case when nullif(entry.caster, '') is not null then 0 else 1 end,
         entry.updated_at desc,
         entry.created_at desc
       limit 1
     ) we on true
     where e.guild_id = $1
       and e.event_date >= current_date
       ${windowClause}
     order by e.event_date asc, e.event_time asc, e.buff asc, e.guild_name asc`,
    values
  );

  const posterResult = await query(
    `select p.id as event_id, p.buff, p.event_date, p.event_time, p.guild_name,
            'offen' as event_status, '' as event_note, p.source as event_source,
            null::uuid as entry_id, null::text as caster, null::text as discord_name,
            null::text as entry_status, null::text as entry_note, null::text as entry_source
     from worldbuff_poster_events p
     where p.guild_id = $1
     order by p.event_date asc, p.event_time asc, p.buff asc, p.guild_name asc`,
    [guildId]
  );

  const railwayRows = dedupeWorldbuffRows(
    [...result.rows, ...posterResult.rows].map(normalizeWorldbuffDbRow)
  );
  if (source === "railway") {
    return { success: true, source: "railway", posterStored: posterResult.rows.length, buffs: railwayRows, entries: railwayRows };
  }

  if (railwayRows.length) {
    return { success: true, source: "railway", posterStored: posterResult.rows.length, buffs: railwayRows, entries: railwayRows };
  }

  if (!allowSheetFallback) {
    return { success: true, source: "railway-empty", buffs: [], entries: [] };
  }

  const sheetRows = await getWorldbuffsFromSheets(params);
  const fallbackRows = dedupeWorldbuffRows(sheetRows.buffs || sheetRows.entries || []);
  return { ...sheetRows, source: "sheet-fallback", buffs: fallbackRows, entries: fallbackRows };
}

async function upsertWorldbuffEvent(client, guildId, params) {
  const eventDate = parseDateValue(params.datum || params.date || params.eventDate);
  const eventTime = clean(params.uhrzeit || params.time || params.eventTime || "19:35");
  const buff = normalizeWorldbuffName(params.buff || "Hakkar") || "Hakkar";
  const guildName = normalizeWorldbuffGuildName(params.gilde || params.guild || params.fraktion || params.faction);
  const status = normalizeWorldbuffStatus(params.eventStatus || params.status || "offen");
  const note = clean(params.eventNote || params.note || params.notiz);
  const source = clean(params.source || "railway");
  const result = await client.query(
    `insert into worldbuff_events (guild_id, buff, event_date, event_time, guild_name, status, note, source)
     values ($1, $2, $3, $4, $5, $6, $7, $8)
     on conflict (guild_id, buff, event_date, event_time, guild_name) do update
       set status = coalesce(nullif(excluded.status, ''), worldbuff_events.status),
           note = coalesce(nullif(excluded.note, ''), worldbuff_events.note),
           source = coalesce(nullif(excluded.source, ''), worldbuff_events.source),
           updated_at = now()
     returning *`,
    [guildId, buff, eventDate, eventTime, guildName, status, note, source]
  );
  return result.rows[0];
}

async function findWorldbuffEventOrEntry(client, guildId, rowNumber) {
  if (!isUuid(rowNumber)) return { event: null, entry: null };
  const entryResult = await client.query(
    `select we.*, e.id as event_id, e.buff, e.event_date, e.event_time, e.guild_name
     from worldbuff_entries we
     join worldbuff_events e on e.id = we.event_id
     where we.id = $1 and e.guild_id = $2`,
    [rowNumber, guildId]
  );
  if (entryResult.rows[0]) {
    const row = entryResult.rows[0];
    return {
      event: {
        id: row.event_id,
        buff: row.buff,
        event_date: row.event_date,
        event_time: row.event_time,
        guild_name: row.guild_name
      },
      entry: row
    };
  }

  const eventResult = await client.query(
    `select *
     from worldbuff_events
     where id = $1 and guild_id = $2`,
    [rowNumber, guildId]
  );
  return { event: eventResult.rows[0] || null, entry: null };
}

async function setWorldbuffCaster({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensureBuffTables();
  const client = await pool.connect();
  try {
    await client.query("begin");
    const actionName = clean(params.action).toLowerCase();
    const isGuildAdminEdit = actionName === "guildsetworldbuffcaster";
    const rowNumber = clean(params.rowNumber);
    const found = await findWorldbuffEventOrEntry(client, guildId, rowNumber);
    const caster = clean(params.charakter || params.caster || params.werfer);
    const discordName = clean(params.discord || params.discordName);
    let status = normalizeWorldbuffStatus(params.status || (caster ? "bestätigt" : "offen"));
    if (isGuildAdminEdit && !caster && status === "bestätigt") {
      status = "offen";
    }
    const note = clean(params.note || params.notiz);
    let event = found.event;
    if (!event && !clean(params.datum || params.date) && !clean(params.uhrzeit || params.time)) {
      const wantedBuff = normalizeWorldbuffName(params.buff);
      const nextOpen = await client.query(
        `select e.*
         from worldbuff_events e
         left join worldbuff_entries we on we.event_id = e.id and nullif(we.caster, '') is not null
         where e.guild_id = $1
           and e.event_date >= current_date
           and lower(coalesce(e.guild_name, '')) = 'lichtbringer'
           and ($2 = '' or e.buff = $2 or ($2 in ('Ony', 'Nef') and e.buff in ('Ony', 'Nef')))
           and we.id is null
           and lower(coalesce(e.status, 'offen')) not in ('erledigt', 'done', 'fertig')
         order by e.event_date asc, e.event_time asc
         limit 1`,
        [guildId, wantedBuff]
      );
      event = nextOpen.rows[0] || null;
    }
    event = event || await upsertWorldbuffEvent(client, guildId, params);
    const requestedBuff = normalizeWorldbuffName(params.buff);
    const requestedGuild = clean(params.gilde || params.guild || params.fraktion || params.faction);
    if (event && (requestedBuff || requestedGuild || note)) {
      const targetBuff = requestedBuff || event.buff;
      const targetGuild = requestedGuild || event.guild_name || "";
      const targetDate = parseDateValue(params.datum || params.date || event.event_date);
      const targetTime = clean(params.uhrzeit || params.time || event.event_time);
      const conflictingEvent = await client.query(
        `select *
         from worldbuff_events
         where guild_id = $1
           and id <> $2
           and buff = $3
           and event_date = $4
           and event_time = $5
           and coalesce(guild_name, '') = $6
         limit 1`,
        [guildId, event.id, targetBuff, targetDate, targetTime, targetGuild]
      );

      if (conflictingEvent.rows[0]) {
        const targetEvent = conflictingEvent.rows[0];
        await client.query(
          `update worldbuff_entries
           set event_id = $2,
               updated_at = now()
           where event_id = $1`,
          [event.id, targetEvent.id]
        );
        await client.query(
          `delete from worldbuff_events
           where id = $1 and guild_id = $2`,
          [event.id, guildId]
        );
        event = targetEvent;
      } else {
        const updatedEvent = await client.query(
          `update worldbuff_events
           set buff = $2,
               event_date = $3,
               event_time = $4,
               guild_name = $5,
               note = coalesce(nullif($6, ''), note),
               updated_at = now()
           where id = $1 and guild_id = $7
           returning *`,
          [event.id, targetBuff, targetDate, targetTime, targetGuild, note, guildId]
        );
        event = updatedEvent.rows[0] || event;
      }
    }
    let savedId = found.entry?.id || "";

    const clearsCaster = !caster && (status === "offen" || isGuildAdminEdit);
    await client.query(
      `select id from worldbuff_events where id = $1 and guild_id = $2 for update`,
      [event.id, guildId]
    );

    if (found.entry && clearsCaster) {
      await client.query(
        `delete from worldbuff_entries
         where id = $1`,
        [found.entry.id]
      );
      await client.query(
        `update worldbuff_events
         set status = 'offen',
             updated_at = now()
         where id = $1 and guild_id = $2`,
        [event.id, guildId]
      );
      savedId = event.id;
    } else if (found.entry) {
      const occupiedCaster = clean(found.entry.caster);
      if (!isGuildAdminEdit && occupiedCaster && caster && !sameWorldbuffCasterName(occupiedCaster, caster)) {
        throwWorldbuffSlotOccupied(occupiedCaster);
      }
      const saved = await client.query(
        `update worldbuff_entries
         set caster = $2,
             discord_name = coalesce(nullif($3, ''), discord_name),
             status = $4,
             note = $5,
             updated_at = now()
         where id = $1
         returning *`,
        [found.entry.id, caster, discordName, status, note]
      );
      savedId = saved.rows[0].id;
    } else if (caster || note || status !== "offen") {
      const existingEntry = await client.query(
        `select *
         from worldbuff_entries
         where event_id = $1
         order by updated_at desc, created_at desc
         limit 1`,
        [event.id]
      );
      if (existingEntry.rows[0]) {
        const occupiedCaster = clean(existingEntry.rows[0].caster);
        if (!isGuildAdminEdit && occupiedCaster && caster && !sameWorldbuffCasterName(occupiedCaster, caster)) {
          throwWorldbuffSlotOccupied(occupiedCaster);
        }
        const saved = await client.query(
          `update worldbuff_entries
           set caster = $2,
               discord_name = coalesce(nullif($3, ''), discord_name),
               status = $4,
               note = $5,
               updated_at = now()
           where id = $1
           returning *`,
          [existingEntry.rows[0].id, caster, discordName, status, note]
        );
        savedId = saved.rows[0].id;
      } else {
        const saved = await client.query(
          `insert into worldbuff_entries (event_id, caster, discord_name, status, note, source)
           values ($1, $2, $3, $4, $5, $6)
           returning *`,
          [event.id, caster, discordName, status, note, clean(params.source || "railway")]
        );
        savedId = saved.rows[0].id;
      }
    } else {
      await client.query(
        `update worldbuff_events
         set status = $2, updated_at = now()
         where id = $1`,
        [event.id, status]
      );
    }

    await client.query("commit");
    await enqueueBotUpdate({ guildId, type: "worldbuff_update", payload: { source: "worldbuff_saved" } }).catch(() => {});
    return {
      success: true,
      rowNumber: savedId || event.id,
      eventId: event.id,
      buff: normalizeWorldbuffName(params.buff || event.buff),
      datum: formatGermanDate(params.datum || event.event_date),
      uhrzeit: clean(params.uhrzeit || event.event_time),
      charakter: caster,
      status
    };
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function createWorldbuffTerm({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensureBuffTables();
  const client = await pool.connect();
  try {
    await client.query("begin");
    const event = await upsertWorldbuffEvent(client, guildId, params);
    const caster = clean(params.charakter || params.caster || params.werfer);
    if (caster || clean(params.note || params.notiz)) {
      const existingEntry = await client.query(
        `select id, caster
         from worldbuff_entries
         where event_id = $1
         order by updated_at desc, created_at desc
         limit 1`,
        [event.id]
      );
      const entryValues = [
        event.id,
        caster,
        clean(params.discord || params.discordName),
        normalizeWorldbuffStatus(params.status || (caster ? "bestätigt" : "offen")),
        clean(params.note || params.notiz)
      ];
      if (existingEntry.rows[0]) {
        const occupiedCaster = clean(existingEntry.rows[0].caster);
        if (occupiedCaster && caster && !sameWorldbuffCasterName(occupiedCaster, caster)) {
          throwWorldbuffSlotOccupied(occupiedCaster);
        }
        await client.query(
          `update worldbuff_entries
           set caster = coalesce(nullif($2, ''), caster),
               discord_name = coalesce(nullif($3, ''), discord_name),
               status = $4,
               note = coalesce(nullif($5, ''), note),
               source = 'railway',
               updated_at = now()
           where id = $1`,
          [existingEntry.rows[0].id, ...entryValues.slice(1)]
        );
      } else {
        await client.query(
          `insert into worldbuff_entries (event_id, caster, discord_name, status, note, source)
           values ($1, $2, $3, $4, $5, 'railway')`,
          entryValues
        );
      }
    }
    await client.query("commit");
    await enqueueBotUpdate({ guildId, type: "worldbuff_update", payload: { source: "worldbuff_created" } }).catch(() => {});
    return { success: true, eventId: event.id };
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function deleteWorldbuffTerm({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensureBuffTables();
  const rowNumber = clean(params.rowNumber);
  if (rowNumber && isUuid(rowNumber)) {
    const deleted = await query(
      `delete from worldbuff_events e
       where e.guild_id = $1
         and (
           e.id = $2
           or exists (
             select 1
             from worldbuff_entries we
             where we.event_id = e.id and we.id = $2
           )
         )`,
      [guildId, rowNumber]
    );
    await enqueueBotUpdate({ guildId, type: "worldbuff_update", payload: { source: "worldbuff_deleted" } }).catch(() => {});
    return { success: true, deleted: deleted.rowCount > 0 };
  }

  const eventDate = parseDateValue(params.datum || params.date);
  const eventTime = clean(params.uhrzeit || params.time);
  const buff = normalizeWorldbuffName(params.buff);
  const guildName = normalizeWorldbuffGuildName(params.gilde || params.guild || params.fraktion || params.faction);
  await query(
    `delete from worldbuff_events
     where guild_id = $1
       and event_date = $2
       and event_time = $3
       and buff = $4
       and coalesce(guild_name, '') = $5`,
    [guildId, eventDate, eventTime, buff, guildName]
  );
  await enqueueBotUpdate({ guildId, type: "worldbuff_update", payload: { source: "worldbuff_deleted" } }).catch(() => {});
  return { success: true };
}

async function importWorldbuffsFromSheets({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensureBuffTables();
  let sourceRows = [];
  if (params.buffs) {
    try {
      const parsed = typeof params.buffs === "string" ? JSON.parse(params.buffs) : params.buffs;
      if (Array.isArray(parsed)) sourceRows = parsed.map(normalizeWorldbuffRow).filter(Boolean);
    } catch (error) {
      const parseError = new Error("Worldbuff-Liste konnte nicht gelesen werden.");
      parseError.statusCode = 400;
      throw parseError;
    }
  }
  if (!sourceRows.length) {
    sourceRows = (await getWorldbuffsFromSheets({ ...params, days: params.days || "all" })).buffs || [];
  }
  sourceRows = dedupeWorldbuffRows(sourceRows);
  const client = await pool.connect();
  let synced = 0;
  let skippedOccupied = 0;
  let stored = 0;
  try {
    await client.query("begin");
    // Pro Gilde darf immer nur ein Poster-Snapshot geschrieben werden.
    // Der Lock gilt bis commit/rollback und wirkt auch über mehrere
    // Bot-Instanzen oder Railway-Replikate hinweg.
    await client.query(
      `select pg_advisory_xact_lock(hashtext($1))`,
      [`worldbuff-import:${guildId}`]
    );
    // Der letzte WBPoster-Post ist ein vollständiger Snapshot. Seine Zeilen
    // liegen bewusst separat von Spieler-Anmeldungen und werden atomar ersetzt.
    await client.query(
      `delete from worldbuff_poster_events where guild_id = $1`,
      [guildId]
    );
    for (const entry of sourceRows) {
      const eventDate = parseDateValue(entry.datum || entry.date);
      const eventTime = clean(entry.uhrzeit || entry.time);
      const buff = normalizeWorldbuffName(entry.buff);
      const guildName = normalizeWorldbuffGuildName(entry.gilde || entry.guild);
      if (!eventDate || !eventTime || !buff || !guildName) continue;

      await client.query(
        `insert into worldbuff_poster_events
           (guild_id, buff, event_date, event_time, guild_name, source)
         values ($1, $2, $3, $4, $5, 'wb_poster')
         on conflict (guild_id, buff, event_date, event_time, guild_name) do update
           set source = 'wb_poster', updated_at = now()`,
        [guildId, buff, eventDate, eventTime, guildName]
      );

      // Der WBPoster ist eine Liste einzelner, exakter Termine. Beim Import
      // darf deshalb weder nach Tag noch nach Buff-Gruppe zusammengefasst
      // werden. Datum, Uhrzeit, Buff und Gilde bilden gemeinsam den Termin.
      const savedEvent = await client.query(
        `insert into worldbuff_events
           (guild_id, buff, event_date, event_time, guild_name, status, note, source)
         values ($1, $2, $3, $4, $5, $6, $7, $8)
         on conflict (guild_id, buff, event_date, event_time, guild_name) do update
           set status = case
                 when worldbuff_events.status = 'bestätigt' then worldbuff_events.status
                 else excluded.status
               end,
               note = coalesce(nullif(excluded.note, ''), worldbuff_events.note),
               source = excluded.source,
               updated_at = now()
         returning *`,
        [
          guildId,
          buff,
          eventDate,
          eventTime,
          guildName,
          normalizeWorldbuffStatus(entry.status || "offen"),
          clean(entry.notiz || entry.note),
          clean(entry.source || "wb_poster")
        ]
      );
      const event = savedEvent.rows[0];
      const caster = clean(entry.charakter || entry.caster || entry.werfer);
      if (caster) {
        const existingEntry = await client.query(
          `select id, caster
           from worldbuff_entries
           where event_id = $1
           order by updated_at desc, created_at desc
           limit 1`,
          [event.id]
        );
        if (existingEntry.rows[0]) {
          const occupiedCaster = clean(existingEntry.rows[0].caster);
          if (occupiedCaster && !sameWorldbuffCasterName(occupiedCaster, caster)) {
            skippedOccupied += 1;
            continue;
          }
          await client.query(
            `update worldbuff_entries
             set caster = $2,
                 status = $3,
                 note = coalesce(nullif($4, ''), note),
                 source = coalesce(nullif($5, ''), source),
                 updated_at = now()
             where id = $1`,
            [
              existingEntry.rows[0].id,
              caster,
              normalizeWorldbuffStatus(entry.status || "bestätigt"),
              clean(entry.notiz || entry.note),
              clean(entry.source || "sheet-import")
            ]
          );
        } else {
          await client.query(
            `insert into worldbuff_entries (event_id, caster, discord_name, status, note, source)
             values ($1, $2, $3, $4, $5, $6)`,
            [
              event.id,
              caster,
              clean(entry.discord || entry.discordName),
              normalizeWorldbuffStatus(entry.status || "bestätigt"),
              clean(entry.notiz || entry.note),
              clean(entry.source || "sheet-import")
            ]
          );
        }
      }
      synced += 1;
    }
    const storedResult = await client.query(
      `select count(*)::int as count
       from worldbuff_poster_events
       where guild_id = $1`,
      [guildId]
    );
    stored = Number(storedResult.rows[0]?.count || 0);
    await client.query("commit");
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
  await enqueueBotUpdate({ guildId, type: "worldbuff_update", payload: { source: "worldbuff_import" } }).catch(() => {});
  return {
    success: true,
    synced,
    skippedOccupied,
    stored,
    syncVersion: "wb-poster-snapshot-v4"
  };
}

async function resolveGuildBackupChannelId({ guildId, envFallbackChannelId = "", kind = "backup" }) {
  await ensureGuildDiscordConfigSchema();
  await ensureDiscordChannelSchema();
  await ensureGuildLayoutSchema();

  const guildResult = await query(
    `select g.slug, g.name as guild_name, g.name as loot_name,
            coalesce(gs.layout_json, '{}'::jsonb) as layout_json
     from guilds g
     left join guild_settings gs on gs.guild_id = g.id
     where g.id = $1`,
    [guildId]
  );
  const guild = guildResult.rows[0] || {};
  const slug = clean(guild.slug).toLowerCase();
  const defaultSlug = clean(defaultGuildSlug).toLowerCase() || "lichtloot";
  const isDefaultGuild = !slug || slug === defaultSlug || slug === "lichtloot";
  const layout = guild.layout_json && typeof guild.layout_json === "object" ? guild.layout_json : {};
  const configuredChannelId = clean(
    kind === "worldbuff"
      ? (layout.worldbuffBackupChannelId || layout.worldbuffChannelId || layout.p0PlusBackupChannelId)
      : layout.p0PlusBackupChannelId
  );
  if (configuredChannelId) {
    const configuredResult = await query(
      `select channel_id
       from discord_bot_channels
       where guild_id = $1
         and channel_id = $2
         and can_send = true
       limit 1`,
      [guildId, configuredChannelId]
    );
    if (configuredResult.rows[0]?.channel_id) return configuredChannelId;
  }
  const terms = kind === "worldbuff"
    ? ["worldbuff", "worldbuffs", "wb", "wb-backup", "wb-sicherung", "buff-backup", "buff-sicherung", "backup", "sicherung"]
    : ["po-backup", "p0-backup", "po-sicherung", "p0-sicherung", "po+", "p0+", "backup", "sicherung"];

  const channelResult = await query(
    `select channel_id, channel_name, category_name
     from (
       select channel_id, channel_name, category_name, position,
         case
           when lower(coalesce(channel_name, '')) = any($2::text[]) then 0
           when lower(coalesce(category_name, '')) = any($2::text[]) then 1
           when $3 = 'worldbuff'
             and (
               lower(coalesce(channel_name, '')) like '%worldbuff%'
               or lower(coalesce(channel_name, '')) like '%wb%'
               or lower(coalesce(category_name, '')) like '%worldbuff%'
               or lower(coalesce(category_name, '')) like '%wb%'
             )
             and (
               lower(coalesce(channel_name, '')) like '%backup%'
               or lower(coalesce(channel_name, '')) like '%sicherung%'
               or lower(coalesce(category_name, '')) like '%backup%'
               or lower(coalesce(category_name, '')) like '%sicherung%'
             ) then 2
           when $3 <> 'worldbuff'
             and lower(coalesce(channel_name, '')) like '%po%'
             and lower(coalesce(channel_name, '')) like '%backup%' then 2
           when $3 <> 'worldbuff'
             and lower(coalesce(channel_name, '')) like '%p0%'
             and lower(coalesce(channel_name, '')) like '%backup%' then 2
           when lower(coalesce(channel_name, '')) like '%sicherung%' then 3
           when lower(coalesce(channel_name, '')) like '%backup%' then 4
           when lower(coalesce(category_name, '')) like '%sicherung%' then 5
           when lower(coalesce(category_name, '')) like '%backup%' then 6
           else 99
         end as backup_rank
       from discord_bot_channels
       where guild_id = $1
         and can_send = true
     ) ranked_channels
     where backup_rank < 99
     order by
       backup_rank,
       coalesce(position, 999999),
       lower(channel_name)
     limit 1`,
    [guildId, terms, kind]
  );
  const channelId = clean(channelResult.rows[0]?.channel_id);
  if (channelId) return channelId;
  return isDefaultGuild ? clean(envFallbackChannelId) : "";
}

async function getGuildLayoutValue(guildId, key) {
  await ensureGuildLayoutSchema();
  const result = await query(
    `select coalesce(layout_json, '{}'::jsonb) as layout_json
     from guild_settings
     where guild_id = $1`,
    [guildId]
  );
  const layout = result.rows[0]?.layout_json || {};
  if (!layout || typeof layout !== "object" || Array.isArray(layout)) return "";
  return clean(layout[key]);
}

async function resolveDefaultGuildId() {
  const slug = clean(defaultGuildSlug).toLowerCase() || "lichtloot";
  const result = await query(
    `select id
     from guilds
     where lower(slug) = $1
        or lower(slug) = 'lichtloot'
     order by case when lower(slug) = $1 then 0 else 1 end
     limit 1`,
    [slug]
  );
  return result.rows[0]?.id || null;
}

async function queueWorldbuffBackup({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  const guildResult = await query(`select lower(slug) as slug from guilds where id = $1 limit 1`, [guildId]);
  const guildSlug = clean(guildResult.rows[0]?.slug).toLowerCase();
  const fixedNachtlootChannel = guildSlug === "nachtloot" ? "1531288515994718318" : "";
  const backupChannelId = clean(params.channelId || params.targetChannelId || params.backupChannelId)
    || fixedNachtlootChannel
    || await resolveGuildBackupChannelId({
      guildId,
      envFallbackChannelId: "1529393614247952434",
      kind: "worldbuff"
    });
  if (!backupChannelId) {
    const error = new Error("Kein Backup-Channel fuer diese Gilde gefunden. Bitte Bot in den Backup-/Sicherungs-Channel einladen oder einen Channel mit 'backup' oder 'sicherung' im Namen anlegen.");
    error.statusCode = 400;
    throw error;
  }

  const days = clean(params.days || "all");
  const result = await getWorldbuffs({ guildId, query: { source: "railway", days } });
  const rows = [
    ["Tag", "Datum", "Uhrzeit", "Buff", "Gilde", "Werfer", "Status", "Notiz", "Quelle", "Row-ID"]
  ];

  for (const entry of result.buffs || []) {
    rows.push([
      entry.tag || "",
      entry.datum || "",
      entry.uhrzeit || "",
      entry.buff || "",
      entry.gilde || "",
      entry.charakter || "",
      entry.status || "",
      entry.note || entry.notiz || "",
      entry.source || "",
      entry.rowNumber || ""
    ]);
  }

  if (rows.length === 1) {
    rows.push(["", "", "", "", "", "", "", "Keine Worldbuff-Termine gefunden.", "", ""]);
  }

  const today = new Date().toISOString().slice(0, 10);
  const queued = await enqueueBotUpdate({
    guildId,
    type: "worldbuff_backup_export",
    payload: {
      channelId: backupChannelId,
      backupTargetGuild: guildSlug,
      backupKind: "worldbuff",
      days,
      createdDate: today,
      filename: `worldbuff-sicherung-${today}.xlsx`,
      count: Math.max(rows.length - 1, 0),
      sheets: [{ name: "Worldbuffs", rows }]
    }
  });

  return { ...queued, count: Math.max(rows.length - 1, 0) };
}

async function getPlayerWorldbuffs({ guildId, query: params }) {
  const pin = normalizePin(params.pin);
  if (!pin) return { success: false, error: "SpielerLogin fehlt." };
  const chars = await getPlayerCharacters(guildId, pin);
  const names = chars.map(char => clean(char.name).toLowerCase()).filter(Boolean);
  if (!names.length) return { success: true, buffs: [], openSlots: [] };
  const all = (await getWorldbuffs({ guildId, query: { days: params.days || 90 } })).buffs || [];
  const blockedStatuses = new Set(["abgesagt", "cancelled", "gelöscht", "geloescht", "erledigt", "done", "fertig"]);
  const openSlots = all.filter(entry =>
    ["Hakkar", "Ony", "Nef"].includes(normalizeWorldbuffName(entry.buff)) &&
    !clean(entry.charakter) &&
    !blockedStatuses.has(normalizeWorldbuffStatus(entry.status)) &&
    clean(entry.gilde).toLowerCase() === "lichtbringer"
  );
  const buffs = all
    .filter(entry => names.includes(clean(entry.charakter).toLowerCase()))
    .map(entry => ({
      ...entry,
      alternatives: openSlots
        .filter(slot => normalizeWorldbuffName(slot.buff) === normalizeWorldbuffName(entry.buff) && slot.rowNumber !== entry.rowNumber)
        .slice(0, 20)
    }));
  return { success: true, buffs, openSlots };
}

async function claimPlayerWorldbuff({ guildId, query: params }) {
  const pin = normalizePin(params.pin);
  const charakter = clean(params.charakter || params.caster);
  if (!pin || !charakter) return { success: false, error: "SpielerLogin oder Charakter fehlt." };
  const chars = await getPlayerCharacters(guildId, pin);
  if (!chars.some(char => clean(char.name).toLowerCase() === charakter.toLowerCase())) {
    return { success: false, error: "Dieser Charakter gehört nicht zu deinem SpielerLogin." };
  }
  const saved=await setWorldbuffCaster({
    guildId,
    query: {
      ...params,
      queueToken: lichtbotQueueToken,
      charakter,
      status: "bestätigt"
    }
  });
  if(saved?.success){
    await notifyWorldbuffPlayerChange({guildId,pin,character:charakter,action:"registered",reason:"",fromEvent:{buff:saved.buff,event_date:params.datum||params.date||"",event_time:saved.uhrzeit||params.uhrzeit||params.time||"",guild_name:params.gilde||params.guild||"Lichtbringer"}});
  }
  return saved;
}

async function notifyWorldbuffPlayerChange({ guildId, pin, character, action, reason, fromEvent, toEvent }) {
  const actionLabel = action === "cancelled" ? "abgesagt" : action === "registered" ? "angemeldet" : "verschoben";
  const formatEvent = event => event
    ? [event.buff, event.event_date ? new Date(event.event_date).toISOString().slice(0, 10) : "", clean(event.event_time), clean(event.guild_name)].filter(Boolean).join(" · ")
    : "-";
  const title = `Worldbuff-Termin ${actionLabel}: ${character}`;
  const body = [
    `${character} hat einen Worldbuff-Termin ${actionLabel}.`,
    "",
    `${action === "registered" ? "Termin" : "Bisheriger Termin"}: ${formatEvent(fromEvent)}`,
    action === "moved" ? `Neuer Termin: ${formatEvent(toEvent)}` : "",
    `Grund: ${reason}`
  ].filter(Boolean).join("\n");

  const recipient = await findPlayerByRecipient(guildId, "Ariee").catch(() => null);
  if (recipient?.player_pin) {
    await query(
      `insert into player_messages (guild_id, player_pin, title, body, sender)
       values ($1,$2,$3,$4,$5)`,
      [guildId, recipient.player_pin, title, body, character || `Spieler ${pin}`]
    ).catch(() => {});
  }

  const configuredTargets=await notificationTargetsForPermissions(guildId,["manage_worldbuffs","notify_worldbuff_changes"]).catch(()=>[]);
  const messageTemplate=await notificationMessageTemplate(guildId,"manage_worldbuffs").catch(()=>"");
  await enqueueBotUpdate({
    guildId,
    type: "worldbuff_player_change_notice",
    payload: {
      recipient: configuredTargets.length ? "" : "Ariee",
      targets: configuredTargets,
      messageTemplate,
      character,
      action,
      actionLabel,
      reason,
      from: formatEvent(fromEvent),
      to: action === "moved" ? formatEvent(toEvent) : ""
    }
  }).catch(() => {});
}

async function movePlayerWorldbuff({ guildId, query: params }) {
  const pin = normalizePin(params.pin);
  const fromRowNumber = clean(params.fromRowNumber);
  const toRowNumber = clean(params.toRowNumber);
  const reason = clean(params.reason || params.grund);
  if (!pin || !fromRowNumber || !toRowNumber) return { success: false, error: "Termin-Auswahl ist unvollständig." };
  if (!reason) return { success: false, error: "Bitte einen Grund für die Verschiebung angeben." };
  const chars = await getPlayerCharacters(guildId, pin);
  const names = chars.map(char => clean(char.name).toLowerCase()).filter(Boolean);
  const client = await pool.connect();
  let notice = null;
  try {
    await client.query("begin");
    const from = await client.query(
      `select we.*, e.buff, e.event_date, e.event_time, e.guild_name
       from worldbuff_entries we
       join worldbuff_events e on e.id = we.event_id
       where we.id = $1 and e.guild_id = $2`,
      [fromRowNumber, guildId]
    );
    const entry = from.rows[0];
    if (!entry || !names.includes(clean(entry.caster).toLowerCase())) {
      await client.query("rollback");
      return { success: false, error: "Der alte Termin wurde nicht gefunden." };
    }
    const target = await findWorldbuffEventOrEntry(client, guildId, toRowNumber);
    if (!target.event) {
      await client.query("rollback");
      return { success: false, error: "Der neue Termin wurde nicht gefunden." };
    }
    await client.query("delete from worldbuff_entries where id = $1", [entry.id]);
    const saved = await client.query(
      `insert into worldbuff_entries (event_id, caster, discord_name, status, note, source)
       values ($1, $2, $3, $4, $5, 'railway')
       returning id`,
      [target.event.id, entry.caster, entry.discord_name, entry.status, entry.note]
    );
    await client.query("commit");
    notice = {
      guildId,
      pin,
      character: clean(entry.caster),
      action: "moved",
      reason,
      fromEvent: entry,
      toEvent: target.event
    };
    await enqueueBotUpdate({ guildId, type: "worldbuff_update", payload: { source: "worldbuff_moved" } }).catch(() => {});
    await notifyWorldbuffPlayerChange(notice);
    return { success: true, rowNumber: saved.rows[0].id };
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function cancelPlayerWorldbuff({ guildId, query: params }) {
  const pin = normalizePin(params.pin);
  const rowNumber = clean(params.rowNumber || params.fromRowNumber);
  const reason = clean(params.reason || params.grund);
  if (!pin || !rowNumber) return { success: false, error: "Worldbuff-Termin fehlt." };
  if (!reason) return { success: false, error: "Bitte einen Grund für die Absage angeben." };
  const chars = await getPlayerCharacters(guildId, pin);
  const names = chars.map(char => clean(char.name).toLowerCase()).filter(Boolean);
  const client = await pool.connect();
  try {
    await client.query("begin");
    const found = await client.query(
      `select we.*, e.buff, e.event_date, e.event_time, e.guild_name
       from worldbuff_entries we
       join worldbuff_events e on e.id = we.event_id
       where we.id = $1 and e.guild_id = $2`,
      [rowNumber, guildId]
    );
    const entry = found.rows[0];
    if (!entry || !names.includes(clean(entry.caster).toLowerCase())) {
      await client.query("rollback");
      return { success: false, error: "Dieser Termin gehört nicht zu deinem SpielerLogin." };
    }
    await client.query("delete from worldbuff_entries where id = $1", [entry.id]);
    await client.query("commit");
    await enqueueBotUpdate({ guildId, type: "worldbuff_update", payload: { source: "worldbuff_cancelled" } }).catch(() => {});
    await notifyWorldbuffPlayerChange({
      guildId,
      pin,
      character: clean(entry.caster),
      action: "cancelled",
      reason,
      fromEvent: entry,
      toEvent: null
    });
    return { success: true };
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function upsertHordenbuffEvent(client, guildId, params) {
  const eventDate = parseDateValue(params.datum || params.date || params.eventDate);
  const eventTime = clean(params.uhrzeit || params.time || params.eventTime || "19:35");
  const buff = clean(params.buff || "Rend") || "Rend";
  const faction = clean(params.gilde || params.faction || "Horde") || "Horde";
  const status = normalizeHordenbuffStatus(params.eventStatus || params.status || "offen");
  const note = clean(params.eventNote || "");

  const result = await client.query(
    `insert into hordenbuff_events (guild_id, buff, event_date, event_time, faction, status, note)
     values ($1, $2, $3, $4, $5, $6, $7)
     on conflict (guild_id, buff, event_date, event_time) do update
       set faction = coalesce(nullif(excluded.faction, ''), hordenbuff_events.faction),
           status = coalesce(nullif(excluded.status, ''), hordenbuff_events.status),
           note = coalesce(nullif(excluded.note, ''), hordenbuff_events.note),
           updated_at = now()
     returning *`,
    [guildId, buff, eventDate, eventTime, faction, status, note]
  );
  return result.rows[0];
}

async function getHordenbuffs({ guildId, query: params }) {
  const days = clean(params.days || "all");
  const values = [guildId];
  let windowClause = "";
  if (days !== "all") {
    const dayCount = Math.max(Number(days) || 30, 1);
    values.push(dayCount);
    windowClause = `and e.event_date <= current_date + ($2::int * interval '1 day')`;
  }

  const result = await query(
    `select e.id as event_id, e.buff, e.event_date, e.event_time, e.faction,
            e.status as event_status, e.note as event_note,
            he.id as entry_id, he.ally_char, he.horde_char,
            he.status as entry_status, he.note as entry_note, he.source
     from hordenbuff_events e
     left join hordenbuff_entries he on he.event_id = e.id
     where e.guild_id = $1
       and e.event_date >= current_date
       ${windowClause}
     order by e.event_date asc, e.event_time asc, he.created_at asc`,
    values
  );

  return { success: true, buffs: result.rows.map(normalizeHordenbuffRow) };
}

async function setHordenbuffEntry({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  const client = await pool.connect();
  try {
    await client.query("begin");

    let event;
    const rowNumber = clean(params.rowNumber);
    let existingEntry = null;
    if (rowNumber && isUuid(rowNumber)) {
      const existing = await client.query(
        `select he.*, e.*
         from hordenbuff_entries he
         join hordenbuff_events e on e.id = he.event_id
         where he.id = $1 and e.guild_id = $2`,
        [rowNumber, guildId]
      );
      existingEntry = existing.rows[0] || null;
    }

    if (existingEntry) {
      event = {
        id: existingEntry.event_id,
        buff: existingEntry.buff,
        event_date: existingEntry.event_date,
        event_time: existingEntry.event_time,
        faction: existingEntry.faction,
        event_status: existingEntry.event_status,
        event_note: existingEntry.event_note
      };
    } else {
      event = await upsertHordenbuffEvent(client, guildId, params);
    }

    const requestedDate = parseDateValue(params.datum || params.date || params.eventDate || event.event_date);
    const requestedTime = clean(params.uhrzeit || params.time || params.eventTime || event.event_time);
    const requestedFaction = clean(params.gilde || params.guild || params.fraktion || params.faction || event.faction || "Horde");
    const eventChanged = existingEntry && (
      requestedDate !== parseDateValue(event.event_date) ||
      requestedTime !== clean(event.event_time) ||
      requestedFaction !== clean(event.faction || "Horde")
    );

    if (eventChanged) {
      const targetEvent = await upsertHordenbuffEvent(client, guildId, {
        ...params,
        datum: requestedDate,
        uhrzeit: requestedTime,
        faction: requestedFaction,
        fraktion: requestedFaction,
        buff: event.buff || "Rend",
        eventStatus: event.event_status || "offen",
        eventNote: event.event_note || ""
      });
      await client.query(
        `update hordenbuff_entries
         set event_id = $2,
             updated_at = now()
         where event_id = $1`,
        [event.id, targetEvent.id]
      );
      await client.query(
        `delete from hordenbuff_events
         where id = $1
           and guild_id = $2
           and not exists (select 1 from hordenbuff_entries where event_id = $1)`,
        [event.id, guildId]
      );
      event = targetEvent;
    }

    const allyChar = clean(params.charakter || params.allyChar || params.ally_char);
    const hordeChar = clean(params.uebernehmer || params.hordeChar || params.horde_char);
    const status = normalizeHordenbuffStatus(params.status);
    const note = clean(params.note || params.notiz);
    const shouldAutoAssign = hordeChar && !allyChar && status !== "erledigt";

    if (shouldAutoAssign) {
      const target = await client.query(
        `select he.id, he.note
         from hordenbuff_entries he
         where he.event_id = $1
           and nullif(he.ally_char, '') is not null
           and nullif(he.horde_char, '') is null
           and lower(coalesce(he.status, '')) not in ('erledigt', 'done', 'fertig')
           and ($2::uuid is null or he.id <> $2::uuid)
         order by he.created_at asc
         limit 1`,
        [event.id, rowNumber && isUuid(rowNumber) ? rowNumber : null]
      );

      if (target.rows[0]) {
        const assignedNote = note || target.rows[0].note || "Benötigt Buff für aktiven Termin; Helfer zugeteilt";
        const assigned = await client.query(
          `update hordenbuff_entries
           set horde_char = $2,
               status = 'zugeteilt',
               note = $3,
               updated_at = now()
           where id = $1
           returning *`,
          [target.rows[0].id, hordeChar, assignedNote]
        );

        if (existingEntry) {
          await client.query("delete from hordenbuff_entries where id = $1", [rowNumber]);
        }

        await client.query("commit");
        return { success: true, rowNumber: assigned.rows[0].id, autoAssigned: true };
      }
    }

    let saved;
    if (existingEntry) {
      saved = await client.query(
        `update hordenbuff_entries
         set ally_char = $2,
             horde_char = $3,
             status = $4,
             note = $5,
             updated_at = now()
         where id = $1
         returning *`,
        [rowNumber, allyChar, hordeChar, status, note]
      );
    } else {
      saved = await client.query(
        `insert into hordenbuff_entries (event_id, ally_char, horde_char, status, note, source)
         values ($1, $2, $3, $4, $5, $6)
         returning *`,
        [event.id, allyChar, hordeChar, status, note, clean(params.source || "railway")]
      );
    }

    await client.query("commit");
    await enqueueBotUpdate({ guildId, type: "hordenbuff_update", payload: { source: "hordenbuff_saved" } }).catch(() => {});
    return { success: true, rowNumber: saved.rows[0].id };
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function createHordenbuffTerm({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  const client = await pool.connect();
  try {
    await client.query("begin");
    const event = await upsertHordenbuffEvent(client, guildId, params);
    const allyChar = clean(params.charakter || params.allyChar || params.ally_char);
    const hordeChar = clean(params.uebernehmer || params.hordeChar || params.horde_char);
    if (allyChar || hordeChar) {
      await client.query(
        `insert into hordenbuff_entries (event_id, ally_char, horde_char, status, note, source)
         values ($1, $2, $3, $4, $5, 'railway')`,
        [
          event.id,
          allyChar,
          hordeChar,
          normalizeHordenbuffStatus(params.status),
          clean(params.note || params.notiz)
        ]
      );
    }
    await client.query("commit");
    return { success: true, eventId: event.id };
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function deleteHordenbuffEntry({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  const rowNumber = clean(params.rowNumber);
  const name = clean(params.name || params.charakter || params.allyChar || params.hordeChar);
  if (rowNumber && isUuid(rowNumber)) {
    await query(
      `delete from hordenbuff_entries he
       using hordenbuff_events e
       where he.event_id = e.id and e.guild_id = $1 and he.id = $2`,
      [guildId, rowNumber]
    );
    return { success: true };
  }

  const eventId = clean(params.eventId || params.event_id);
  if (eventId && isUuid(eventId)) {
    await query(
      `delete from hordenbuff_events
       where guild_id = $1 and id = $2`,
      [guildId, eventId]
    );
    return { success: true };
  }

  const eventDate = parseDateValue(params.datum || params.date);
  const eventTime = clean(params.uhrzeit || params.time);
  await query(
    `delete from hordenbuff_entries he
     using hordenbuff_events e
     where he.event_id = e.id
       and e.guild_id = $1
       and e.event_date = $2
       and e.event_time = $3
       and (lower(he.ally_char) = lower($4) or lower(he.horde_char) = lower($4))`,
    [guildId, eventDate, eventTime, name]
  );
  return { success: true };
}

async function queueBotUpdate({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  const type = clean(params.type || "hordenbuff_update") || "hordenbuff_update";
  const payload = params.payload && typeof params.payload === "object"
    ? params.payload
    : {
        raidId: clean(params.raidId || params.id || ""),
        source: clean(params.source || "")
      };
  return enqueueBotUpdate({ guildId, type, payload });
}

async function enqueueBotUpdate({ guildId, type, payload }) {
  await query(`alter table bot_update_queue add column if not exists payload jsonb not null default '{}'::jsonb`);
  await query(`alter table bot_update_queue add column if not exists claimed_at timestamptz`);
  if (type === "po_release_request_notice" && clean(payload?.requestId)) {
    const existing = await query(
      `select id
       from bot_update_queue
       where guild_id = $1
         and type = $2
         and status in ('open', 'processing')
         and payload->>'requestId' = $3
       order by created_at desc
       limit 1`,
      [guildId, type, clean(payload.requestId)]
    );
    if (existing.rows[0]) {
      await query(
        `update bot_update_queue
         set payload = $2::jsonb,
             status = 'open',
             created_at = now(),
             claimed_at = null
         where id = $1`,
        [existing.rows[0].id, JSON.stringify(payload || {})]
      );
      return { success: true, skipped: true, reason: "po_release_notice_already_open", rowNumber: existing.rows[0].id, type, payload };
    }
  }
  if (type === "raid_announcement_role_notice") {
    const raidId = clean(payload?.raidId || "");
    if (raidId) {
      const existing = await query(
        `select id
         from bot_update_queue
         where guild_id = $1
           and type = $2
           and status = 'open'
           and payload->>'raidId' = $3
         order by created_at desc
         limit 1`,
        [guildId, type, raidId]
      );
      if (existing.rows[0]) {
        await query(
          `update bot_update_queue
           set payload = $2::jsonb,
               created_at = now()
           where id = $1`,
          [existing.rows[0].id, JSON.stringify(payload || {})]
        );
        return {
          success: true,
          skipped: true,
          reason: "raid_announcement_notice_already_open",
          rowNumber: existing.rows[0].id,
          type,
          payload: payload || {}
        };
      }
    }
  }
  if (type === "po_post") {
    const payloadJson = JSON.stringify(payload || {});
    const existing = await query(
      `select id, type, payload, status, created_at
       from bot_update_queue
       where guild_id = $1
         and type = $2
         and payload = $3::jsonb
         and (
           status = 'open'
           or (status = 'done' and coalesce(resolved_at, created_at) > now() - interval '2 minutes')
         )
       order by created_at desc
       limit 1`,
      [guildId, type, payloadJson]
    );
    if (existing.rows[0]) {
      return {
        success: true,
        skipped: true,
        reason: "po_post_recently_queued",
        rowNumber: existing.rows[0].id,
        type: existing.rows[0].type,
        payload: existing.rows[0].payload || {}
      };
    }
  }
  const result = await query(
    `insert into bot_update_queue (guild_id, type, payload)
     values ($1, $2, $3::jsonb)
     returning id, type, payload`,
    [guildId, type, JSON.stringify(payload || {})]
  );
  if (type === "player_login_approval_notice" && clean(payload?.playerPin)) {
    await query(`alter table players add column if not exists login_notice_queued_at timestamptz`);
    await query(
      `update players
       set login_notice_queued_at = coalesce(login_notice_queued_at, now())
       where guild_id = $1 and player_pin = $2`,
      [guildId, clean(payload.playerPin)]
    );
  }
  return { success: true, rowNumber: result.rows[0].id, type: result.rows[0].type, payload: result.rows[0].payload || {} };
}

function logAnalysisPostChannelId(raid) {
  switch (normalizeLogRaidType(raid)) {
    case "MC":
      return "1509236588410834965";
    case "BWL":
      return "1509236359141785600";
    case "NAXX":
      return "1509235847109804082";
    case "AQ40":
      return "1509236271816511651";
    default:
      return "";
  }
}

async function resolveLogAnalysisPostChannelId(guildId, raid) {
  const guildResult = await query(`select lower(slug) as slug from guilds where id = $1 limit 1`, [guildId]);
  const guildSlug = clean(guildResult.rows[0]?.slug).toLowerCase();
  const configuredChannelId = await getGuildLayoutValue(guildId, "logAnalysisChannelId");

  // Nachtloot verwendet eigene Log-Analyse-Kanäle je Raid.
  if (guildSlug === "nachtloot") {
    const nachtlootChannels = {
      MC: "1533915098857341068",
      BWL: "1533915161524441168",
      AQ40: "1533915232085475469",
      NAXX: "1533915287081193654"
    };
    return nachtlootChannels[normalizeLogRaidType(raid)] || configuredChannelId || "1533914926190428393";
  }

  return configuredChannelId || logAnalysisPostChannelId(raid);
}

async function ensurePendingPlayerLoginNoticesQueued(guildId = null) {
  await query(`alter table players add column if not exists login_notice_queued_at timestamptz`);
  await query(`alter table bot_update_queue add column if not exists claimed_at timestamptz`);
  await query(
    `with stale as (
       update bot_update_queue
       set status = 'done', resolved_at = now()
       where type = 'player_login_approval_notice'
         and status = 'processing'
         and claimed_at < now() - interval '5 minutes'
       returning guild_id, payload->>'playerPin' as player_pin
     )
     update players p
     set login_notice_queued_at = null
     from stale
     where p.guild_id = stale.guild_id
       and p.player_pin = stale.player_pin
       and p.approval_status = 'pending'`
  );
  const pending = await query(
    `select p.id as player_id, p.guild_id, p.player_pin, p.created_at,
            g.slug as guild_slug, g.name as guild_name,
            c.name as character_name, c.server, c.class_name
     from players p
     join guilds g on g.id = p.guild_id
     left join lateral (
       select name, server, class_name
       from characters
       where player_id = p.id
       order by is_main desc nulls last, created_at asc
       limit 1
     ) c on true
     where p.approval_status = 'pending'
       and p.login_notice_queued_at is null
       and ($1::uuid is null or p.guild_id = $1)
     order by p.created_at asc
     limit 50`,
    [guildId]
  );
  for (const row of pending.rows) {
    const claimed = await query(
      `update players
       set login_notice_queued_at = now()
       where id = $1 and login_notice_queued_at is null
       returning id`,
      [row.player_id]
    );
    if (!claimed.rowCount) continue;
    try {
      const notificationTargets = await notificationTargetsForPermissions(row.guild_id, "notify_player_logins");
      const messageTemplate = await notificationMessageTemplate(row.guild_id, "notify_player_logins").catch(() => "");
      await enqueueBotUpdate({
        guildId: row.guild_id,
        type: "player_login_approval_notice",
        payload: {
          guildSlug: row.guild_slug,
          guildName: row.guild_name || row.guild_slug,
          playerPin: row.player_pin,
          character: row.character_name || "Unbekannt",
          server: row.server || "",
          className: row.class_name || "",
          notificationRoleIds: notificationTargets.filter(target => target.type === "role").map(target => target.value),
          notificationNames: notificationTargets.filter(target => target.type === "name").map(target => target.value),
          messageTemplate,
          createdAt: row.created_at || new Date().toISOString()
        }
      });
    } catch (error) {
      await query(`update players set login_notice_queued_at = null where id = $1`, [row.player_id]);
      console.warn("Offener SpielerLogin konnte nicht zur Benachrichtigung vorgemerkt werden:", error.message || error);
    }
  }
}

async function getBotQueue({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensurePendingPlayerLoginNoticesQueued(guildId);
  await query(`alter table bot_update_queue add column if not exists payload jsonb not null default '{}'::jsonb`);
  await query(
    `update bot_update_queue q
     set status = 'done', resolved_at = now()
     where q.guild_id = $1
       and q.status = 'open'
       and q.type in ('worldbuff_update', 'hordenbuff_update')
       and exists (
         select 1
         from bot_update_queue newer
         where newer.guild_id = q.guild_id
           and newer.type = q.type
           and newer.status = 'open'
           and (newer.created_at > q.created_at or (newer.created_at = q.created_at and newer.id::text > q.id::text))
       )`,
    [guildId]
  );
  const result = await query(
    `select id, type, payload, created_at
     from bot_update_queue
     where guild_id = $1 and status = 'open'
     order by case
       when type = 'player_login_approval_notice' then 0
       when type in ('po_release_request_notice', 'raid_status_staff_notice', 'loot_master_leadpin_notice') then 1
       else 2
     end, created_at asc
     limit 10`,
    [guildId]
  );
  return {
    success: true,
    items: result.rows.map(row => ({
      rowNumber: row.id,
      type: row.type,
      payload: row.payload || {},
      createdAt: row.created_at
    }))
  };
}

async function getBotQueueAllGuilds({ query: params }) {
  requireMasterOrQueueToken(params);
  await ensurePendingPlayerLoginNoticesQueued();
  await query(`alter table bot_update_queue add column if not exists payload jsonb not null default '{}'::jsonb`);
  await query(
    `update bot_update_queue q
     set status = 'done', resolved_at = now()
     where q.status = 'open'
       and q.type in ('worldbuff_update', 'hordenbuff_update')
       and exists (
         select 1
         from bot_update_queue newer
         where newer.guild_id = q.guild_id
           and newer.type = q.type
           and newer.status = 'open'
           and (newer.created_at > q.created_at or (newer.created_at = q.created_at and newer.id::text > q.id::text))
       )`
  );
  const requestedTypes = clean(params.types || params.typeFilter)
    .split(",")
    .map(clean)
    .filter(Boolean);
  const limit = Math.max(1, Math.min(500, Number(params.limit || 50) || 50));
  const result = await query(
    `select q.id, q.type, q.payload, q.created_at, g.slug as guild_slug, g.name as guild_name
     from bot_update_queue q
     join guilds g on g.id = q.guild_id
     where q.status = 'open'
       and ($1::text[] is null or q.type = any($1::text[]))
     order by case
       when q.type = 'player_login_approval_notice' then 0
       when q.type in (
         'po_release_request_notice',
         'raid_status_staff_notice',
         'loot_master_leadpin_notice',
         'p0plus_transfer_export',
         'p0plus_backup_export',
         'log_analysis_post'
       ) then 1
       when q.type in ('worldbuff_update', 'hordenbuff_update') then 3
       else 2
     end, q.created_at asc
     limit $2`,
    [requestedTypes.length ? requestedTypes : null, limit]
  );
  return {
    success: true,
    items: result.rows.map(row => ({
      rowNumber: row.id,
      type: row.type,
      guild: row.guild_slug,
      guildSlug: row.guild_slug,
      guildName: row.guild_name || row.guild_slug,
      payload: row.payload || {},
      createdAt: row.created_at
    }))
  };
}

function normalizeDiscordChannelRow(row) {
  return {
    id: row.channel_id || "",
    channelId: row.channel_id || "",
    name: row.channel_name || "",
    channelName: row.channel_name || "",
    type: row.channel_type || "",
    category: row.category_name || "",
    categoryName: row.category_name || "",
    discordGuildId: row.discord_guild_id || "",
    discordGuildName: row.discord_guild_name || "",
    canSend: row.can_send !== false,
    updatedAt: row.updated_at || ""
  };
}

async function saveDiscordBotChannels({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensureDiscordChannelSchema();
  const channels = Array.isArray(params.channels) ? params.channels : [];
  const seen = new Set();
  const replaceChannels = clean(params.replace || params.fullSync).toLowerCase() === "true";
  let saved = 0;

  for (const raw of channels) {
    const channelId = clean(raw.id || raw.channelId);
    const channelName = clean(raw.name || raw.channelName);
    if (!channelId || !channelName || seen.has(channelId)) continue;
    seen.add(channelId);
    await query(
      `insert into discord_bot_channels (
         guild_id, discord_guild_id, discord_guild_name, channel_id, channel_name,
         channel_type, category_name, position, can_send, updated_at
       )
       values ($1,$2,$3,$4,$5,$6,$7,$8,$9,now())
       on conflict (guild_id, channel_id)
       do update set
         discord_guild_id = excluded.discord_guild_id,
         discord_guild_name = excluded.discord_guild_name,
         channel_name = excluded.channel_name,
         channel_type = excluded.channel_type,
         category_name = excluded.category_name,
         position = excluded.position,
         can_send = excluded.can_send,
         updated_at = now()`,
      [
        guildId,
        clean(raw.discordGuildId || raw.guildId),
        clean(raw.discordGuildName || raw.guildName),
        channelId,
        channelName,
        clean(raw.type || raw.channelType),
        clean(raw.category || raw.categoryName),
        Number.isFinite(Number(raw.position)) ? Number(raw.position) : null,
        raw.canSend !== false
      ]
    );
    saved += 1;
  }

  if (replaceChannels && seen.size) {
    await query(
      `delete from discord_bot_channels
       where guild_id = $1
         and not (channel_id = any($2::text[]))`,
      [guildId, Array.from(seen)]
    );
  }

  return { success: true, saved };
}

async function getDiscordBotChannels({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensureDiscordChannelSchema();
  const result = await query(
    `select *
     from discord_bot_channels
     where guild_id = $1
       and can_send = true
     order by
       coalesce(category_name, ''),
       coalesce(position, 999999),
       lower(channel_name)`,
    [guildId]
  );
  return {
    success: true,
    channels: result.rows.map(normalizeDiscordChannelRow)
  };
}

async function saveDiscordBotRoles({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensureDiscordChannelSchema();
  const roles = Array.isArray(params.roles) ? params.roles : [];
  const seen = [];
  for (const role of roles) {
    const roleId = clean(role.id || role.roleId);
    const roleName = clean(role.name || role.roleName);
    if (!roleId || !roleName || roleName === "@everyone") continue;
    seen.push(roleId);
    await query(
      `insert into discord_bot_roles (guild_id, discord_guild_id, role_id, role_name, color, position, updated_at)
       values ($1,$2,$3,$4,$5,$6,now())
       on conflict (guild_id, role_id) do update
       set role_name=excluded.role_name,color=excluded.color,position=excluded.position,updated_at=now()`,
      [guildId, clean(role.discordGuildId || role.guildId), roleId, roleName, Number(role.color || 0), Number(role.position || 0)]
    );
  }
  if (seen.length) await query(`delete from discord_bot_roles where guild_id=$1 and not (role_id=any($2::text[]))`, [guildId, seen]);
  return { success:true, saved:seen.length };
}

async function getDiscordBotRoles({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensureDiscordChannelSchema();
  const result = await query(`select role_id,role_name,color,position from discord_bot_roles where guild_id=$1 order by position desc,lower(role_name)`, [guildId]);
  return { success:true, roles:result.rows.map(row => ({id:row.role_id,roleId:row.role_id,name:row.role_name,roleName:row.role_name,color:row.color,position:row.position})) };
}

async function saveDiscordBotMembers({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensureDiscordChannelSchema();
  const members = Array.isArray(params.members) ? params.members : [];
  const seen = [];
  for (const member of members) {
    const userId = clean(member.id || member.userId);
    const username = clean(member.username || member.name);
    if (!userId || !username || member.bot === true) continue;
    seen.push(userId);
    await query(
      `insert into discord_bot_members (guild_id,discord_guild_id,user_id,username,display_name,global_name,avatar_url,bot,updated_at)
       values ($1,$2,$3,$4,$5,$6,$7,$8,now())
       on conflict (guild_id,user_id) do update
       set discord_guild_id=excluded.discord_guild_id,username=excluded.username,display_name=excluded.display_name,
           global_name=excluded.global_name,avatar_url=excluded.avatar_url,bot=excluded.bot,updated_at=now()`,
      [guildId,clean(member.discordGuildId || member.guildId),userId,username,clean(member.displayName),clean(member.globalName),clean(member.avatarUrl),Boolean(member.bot)]
    );
  }
  if (seen.length) await query(`delete from discord_bot_members where guild_id=$1 and not (user_id=any($2::text[]))`, [guildId,seen]);
  return {success:true,saved:seen.length};
}

async function getDiscordBotMembers({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensureDiscordChannelSchema();
  const result = await query(
    `select user_id,username,display_name,global_name,avatar_url
     from discord_bot_members where guild_id=$1 and bot=false
     order by lower(coalesce(nullif(display_name,''),nullif(global_name,''),username)),lower(username)`,
    [guildId]
  );
  return {success:true,members:result.rows.map(row=>({id:row.user_id,userId:row.user_id,username:row.username,displayName:row.display_name||row.global_name||row.username,globalName:row.global_name||"",avatarUrl:row.avatar_url||""}))};
}

function normalizeRaidHelperTemplateRow(row) {
  return {
    id: row.id || "",
    templateId: row.id || "",
    key: row.template_key || "",
    templateKey: row.template_key || "",
    raid: row.raid_type || "",
    raidType: row.raid_type || "",
    title: row.title || "",
    description: row.description || "",
    maxPlayers: row.max_players ?? "",
    tankSlots: row.tank_slots ?? "",
    healSlots: row.heal_slots ?? "",
    ddSlots: row.dd_slots ?? "",
    signupDeadline: row.signup_deadline || "",
    discordChannelId: row.discord_channel_id || "",
    raidImageUrl: row.raid_image_url || "",
    createdAt: row.created_at || "",
    updatedAt: row.updated_at || ""
  };
}

function scheduleDateIso(value) {
  if (!value) return "";
  if (value instanceof Date) return value.toISOString().slice(0, 10);
  const text = String(value);
  if (/^\d{4}-\d{2}-\d{2}/.test(text)) return text.slice(0, 10);
  const parsed = new Date(text);
  return Number.isNaN(parsed.getTime()) ? "" : parsed.toISOString().slice(0, 10);
}

function normalizeRaidHelperScheduleRow(row) {
  const id = row.id || "";
  return {
    id,
    scheduleId: id,
    key: row.schedule_key || "",
    scheduleKey: row.schedule_key || "",
    enabled: row.enabled !== false,
    raid: row.raid_type || "",
    raidType: row.raid_type || "",
    title: row.title || "",
    description: row.description || "",
    maxPlayers: row.max_players ?? "",
    tankSlots: row.tank_slots ?? "",
    healSlots: row.heal_slots ?? "",
    ddSlots: row.dd_slots ?? "",
    signupDeadline: row.signup_deadline || "",
    discordChannelId: row.discord_channel_id || "",
    raidImageUrl: row.raid_image_url || "",
    createdBy: row.created_by || "",
    recurrence: row.recurrence || "weekly",
    intervalWeeks: row.interval_weeks ?? 1,
    weekday: row.weekday ?? 3,
    raidTime: row.raid_time || "20:00",
    postTime: row.post_time || "09:00",
    nextRaidDate: scheduleDateIso(row.next_raid_date),
    nextPostDate: scheduleDateIso(row.next_post_date),
    lastRaidDate: scheduleDateIso(row.last_raid_date),
    lastRaidId: row.last_raid_id || "",
    currentRaidId: id ? `schedule-${id}` : "",
    createdAt: row.created_at || "",
    updatedAt: row.updated_at || ""
  };
}

function randomRaidCode(length = 3) {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  let code = "";
  for (let index = 0; index < length; index += 1) {
    code += chars[Math.floor(Math.random() * chars.length)];
  }
  return code;
}

function localDateOnly(value = new Date()) {
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [year, month, day] = value.split("-").map(Number);
    return new Date(year, month - 1, day);
  }
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return new Date();
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function formatDateIso(date) {
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0")
  ].join("-");
}

function addDays(date, days) {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

function resolveNextScheduleDate({ weekday, nextRaidDate, intervalWeeks }) {
  const today = localDateOnly();
  let next = nextRaidDate ? localDateOnly(nextRaidDate) : null;
  const intervalDays = Math.max(1, Number(intervalWeeks) || 1) * 7;

  if (!next) {
    const target = Math.min(7, Math.max(1, Number(weekday) || 3));
    const todayWeekday = today.getDay() === 0 ? 7 : today.getDay();
    const diff = (target - todayWeekday + 7) % 7;
    next = addDays(today, diff);
  }

  while (next < today) {
    next = addDays(next, intervalDays);
  }

  return next;
}

function schedulePostIsDue({ postDate, postTime, force = false }) {
  if (force) return true;
  const dateIso = scheduleDateIso(postDate);
  if (!dateIso) return true;
  const timeText = clean(postTime || "00:00") || "00:00";
  const normalizedTime = /^\d{2}:\d{2}$/.test(timeText) ? timeText : "00:00";
  const scheduled = new Date(`${dateIso}T${normalizedTime}:00`);
  if (Number.isNaN(scheduled.getTime())) return true;
  return scheduled <= new Date();
}

async function processRaidHelperSchedules({ guildId, force = false, scheduleId = "" }) {
  await ensureRaidHelperScheduleSchema();
  const scopedScheduleId = clean(scheduleId);
  const scheduleValues = [guildId];
  let scheduleClause = "";
  if (scopedScheduleId && isUuid(scopedScheduleId)) {
    scheduleValues.push(scopedScheduleId);
    scheduleClause = "and id = $2";
  }
  const schedules = await query(
    `select *
     from raid_helper_schedules
     where guild_id = $1 and enabled = true
       ${scheduleClause}
     order by next_raid_date nulls first, raid_time, lower(title)`,
    scheduleValues
  );

  const processed = [];
  for (const schedule of schedules.rows) {
    const nextDate = resolveNextScheduleDate({
      weekday: schedule.weekday,
      nextRaidDate: scheduleDateIso(schedule.next_raid_date),
      intervalWeeks: schedule.interval_weeks
    });
    const nextDateIso = formatDateIso(nextDate);
    const externalRaidId = `schedule-${schedule.id}`;
    const existing = await query(
      `select id, raid_date, raid_pin, lead_pin, discord_message_id, discord_channel_id
       from raids
       where guild_id = $1 and external_raid_id = $2
       limit 1`,
      [guildId, externalRaidId]
    );
    const existingRaid = existing.rows[0] || null;
    const existingDateIso = scheduleDateIso(existingRaid?.raid_date);
    const dateChanged = Boolean(existingRaid && existingDateIso && existingDateIso !== nextDateIso);
    const nextPostDateIso = scheduleDateIso(schedule.next_post_date || schedule.next_raid_date || nextDateIso);
    const postDue = schedulePostIsDue({
      postDate: nextPostDateIso,
      postTime: schedule.post_time,
      force
    });
    if (!postDue) {
      processed.push({
        scheduleId: schedule.id,
        raidId: externalRaidId,
        skipped: true,
        reason: "not_due",
        nextRaidDate: nextDateIso,
        nextPostDate: nextPostDateIso,
        postTime: schedule.post_time || ""
      });
      continue;
    }

    if (dateChanged) {
      await query(
        `delete from raid_signups rs
         using raids r
         where r.id = rs.raid_id
           and r.guild_id = $1
           and rs.raid_id = $2`,
        [guildId, existingRaid.id]
      );
      await query("delete from raid_external_signups where guild_id = $1 and raid_id = $2", [guildId, existingRaid.id]);
      await query(
        `update raids
         set discord_message_id = null, updated_at = now()
         where guild_id = $1 and id = $2`,
        [guildId, existingRaid.id]
      );
    }

    const created = await createRaidRecord({
      guildId,
      query: {
        raidId: externalRaidId,
        raid: schedule.raid_type,
        raidName: schedule.title,
        raidDate: nextDateIso,
        raidTime: schedule.raid_time,
        guild: "Lichtbringer",
        playerPin: dateChanged || !existingRaid?.raid_pin ? randomRaidCode(3) : existingRaid.raid_pin,
        leadPin: dateChanged || !existingRaid?.lead_pin ? randomRaidCode(4) : existingRaid.lead_pin,
        status: "geschlossen",
        p0PlusFreigabe: "geöffnet",
        createdBy: schedule.created_by || "Gildenleitung",
        raidHelperEnabled: "true",
        maxPlayers: schedule.max_players,
        tankSlots: schedule.tank_slots,
        healSlots: schedule.heal_slots,
        ddSlots: schedule.dd_slots,
        signupDeadline: schedule.signup_deadline,
        discordChannelId: schedule.discord_channel_id,
        description: schedule.description,
        raidImageUrl: schedule.raid_image_url
      }
    });

    await query(
      `update raid_helper_schedules
       set next_raid_date = $2,
           next_post_date = coalesce(next_post_date, $2),
           last_raid_date = case when $3::boolean then $4::date else last_raid_date end,
           last_raid_id = $5,
           updated_at = now()
       where guild_id = $1 and id = $6`,
      [guildId, nextDateIso, dateChanged, existingDateIso || null, created.id || created.raidId || null, schedule.id]
    );

    const shouldQueuePost = clean(schedule.discord_channel_id) && (force || dateChanged || !existingRaid?.discord_message_id);
    if (shouldQueuePost) {
      await enqueueBotUpdate({
        guildId,
        type: "raid_announcement",
        payload: {
          raidId: externalRaidId,
          channelId: schedule.discord_channel_id,
          discordChannelId: schedule.discord_channel_id,
          source: "raid_helper_schedule"
        }
      }).catch(error => console.warn("Geplanter Raid-Anmelder konnte nicht queued werden:", error.message || error));
    }

    processed.push({
      scheduleId: schedule.id,
      raidId: externalRaidId,
      raidUuid: created.id || "",
      nextRaidDate: nextDateIso,
      nextPostDate: nextPostDateIso,
      postTime: schedule.post_time || "",
      queued: Boolean(shouldQueuePost),
      advanced: dateChanged
    });
  }

  return processed;
}

async function getRaidHelperSchedules({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  await processRaidHelperSchedules({ guildId });
  const result = await query(
    `select *
     from raid_helper_schedules
     where guild_id = $1
     order by enabled desc, next_raid_date nulls last, raid_time, lower(title)`,
    [guildId]
  );
  return { success: true, schedules: result.rows.map(normalizeRaidHelperScheduleRow) };
}

async function saveRaidHelperSchedule({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  await ensureRaidHelperScheduleSchema();
  const scheduleId = clean(params.scheduleId || params.id);
  const raidType = normalizeRaidType(params.raid || params.raidType || params.raidName);
  const title = clean(params.title || params.name);
  const weekday = Math.min(7, Math.max(1, Number(params.weekday || 3) || 3));
  const intervalWeeks = Math.min(12, Math.max(1, Number(params.intervalWeeks || 1) || 1));
  const raidTime = clean(params.raidTime || params.time || "20:00") || "20:00";
  const postTime = clean(params.postTime || params.posterTime || params.autoPostTime || "09:00") || "09:00";

  if (!raidType || !title) {
    const error = new Error("Raid und Titel sind für den Rhythmus erforderlich.");
    error.statusCode = 400;
    throw error;
  }

  const scheduleKey =
    clean(params.scheduleKey || params.key) ||
    `${raidType}-${weekday}-${raidTime}`.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");

  const values = [
    guildId,
    scheduleKey,
    params.enabled === false || clean(params.enabled).toLowerCase() === "false" ? false : true,
    raidType,
    title,
    clean(params.description || params.text),
    parseOptionalInteger(params.maxPlayers),
    parseOptionalInteger(params.tankSlots),
    parseOptionalInteger(params.healSlots),
    parseOptionalInteger(params.ddSlots),
    clean(params.signupDeadline || params.deadline),
    clean(params.discordChannelId || params.channelId),
    clean(params.raidImageUrl || params.imageUrl),
    clean(params.createdBy || params.raidlead || params.lead) || "Gildenleitung",
    "weekly",
    intervalWeeks,
    weekday,
    raidTime,
    postTime,
    parseDateValue(params.nextRaidDate || params.raidDate || params.date),
    parseDateValue(params.nextPostDate || params.postDate || params.posterDate || params.autoPostDate || params.nextRaidDate || params.raidDate || params.date)
  ];

  let result;
  if (scheduleId && isUuid(scheduleId)) {
    result = await query(
      `update raid_helper_schedules
       set schedule_key = $2,
           enabled = $3,
           raid_type = $4,
           title = $5,
           description = $6,
           max_players = $7,
           tank_slots = $8,
           heal_slots = $9,
           dd_slots = $10,
           signup_deadline = $11,
           discord_channel_id = $12,
           raid_image_url = $13,
           created_by = $14,
           recurrence = $15,
           interval_weeks = $16,
           weekday = $17,
           raid_time = $18,
           post_time = $19,
           next_raid_date = coalesce($20, next_raid_date),
           next_post_date = coalesce($21, next_post_date),
           updated_at = now()
       where guild_id = $1 and id = $22
       returning *`,
      [...values, scheduleId]
    );
  } else {
    result = await query(
      `insert into raid_helper_schedules (
         guild_id, schedule_key, enabled, raid_type, title, description,
         max_players, tank_slots, heal_slots, dd_slots, signup_deadline,
         discord_channel_id, raid_image_url, created_by, recurrence,
         interval_weeks, weekday, raid_time, post_time, next_raid_date, next_post_date
       )
       values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21)
       on conflict (guild_id, schedule_key)
       do update set
         enabled = excluded.enabled,
         raid_type = excluded.raid_type,
         title = excluded.title,
         description = excluded.description,
         max_players = excluded.max_players,
         tank_slots = excluded.tank_slots,
         heal_slots = excluded.heal_slots,
         dd_slots = excluded.dd_slots,
         signup_deadline = excluded.signup_deadline,
         discord_channel_id = excluded.discord_channel_id,
         raid_image_url = excluded.raid_image_url,
         created_by = excluded.created_by,
         recurrence = excluded.recurrence,
         interval_weeks = excluded.interval_weeks,
         weekday = excluded.weekday,
         raid_time = excluded.raid_time,
         post_time = excluded.post_time,
         next_raid_date = coalesce(excluded.next_raid_date, raid_helper_schedules.next_raid_date),
         next_post_date = coalesce(excluded.next_post_date, raid_helper_schedules.next_post_date),
         updated_at = now()
       returning *`,
      values
    );
  }

  const savedSchedule = normalizeRaidHelperScheduleRow(result.rows[0]);
  const firstRun = !result.rows[0].last_raid_id;
  const processed = await processRaidHelperSchedules({
    guildId,
    force: firstRun,
    scheduleId: result.rows[0].id
  });
  return {
    success: true,
    schedule: savedSchedule,
    firstRaidCreated: firstRun,
    processed
  };
}

async function deleteRaidHelperSchedule({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  await ensureRaidHelperScheduleSchema();
  const scheduleId = clean(params.scheduleId || params.id);
  if (!isUuid(scheduleId)) {
    const error = new Error("Schedule-ID fehlt.");
    error.statusCode = 400;
    throw error;
  }
  const result = await query(
    `delete from raid_helper_schedules
     where guild_id = $1 and id = $2`,
    [guildId, scheduleId]
  );
  return { success: true, deleted: result.rowCount };
}

function parseRaidHistoryImportEntries(raw) {
  const text = clean(raw);
  if (!text) return [];
  try {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed)) return parsed;
  } catch {}
  return text
    .split(/\r?\n/g)
    .map(line => line.trim())
    .filter(Boolean)
    .map(line => {
      const parts = line.split(/[;\t,]/g).map(part => part.trim());
      return {
        raid: parts[0],
        date: parts[1],
        time: parts[2],
        title: parts.slice(3).join(" ").trim()
      };
    });
}

async function findRaidForHistoryImport(guildId, raidType, raidDate, raidTime) {
  const result = await query(
    `select r.*,
            (select count(*)::int from prios pr where pr.raid_id = r.id) as prio_count,
            (
              select count(*)::int
              from raid_signups rs
              where rs.raid_id = r.id
            ) +
            (
              select count(*)::int
              from raid_external_signups res
              where res.guild_id = r.guild_id and res.raid_id = r.id
            ) as signup_count
     from raids r
     where r.guild_id = $1
       and lower(r.raid_type) = any($2)
       and r.raid_date = $3
     order by
       case when (select count(*) from prios pr where pr.raid_id = r.id) > 0 then 0 else 1 end,
       case when coalesce(r.created_by, '') = 'History-Import' then 1 else 0 end,
       case when $4 = '' or coalesce(r.raid_time, '') = $4 then 0 else 1 end,
       r.created_at asc
     limit 1`,
    [guildId, raidTypeSearchValues(raidType), raidDate, clean(raidTime)]
  );
  return result.rows[0] || null;
}

async function importRaidHelperHistory({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  const entries = parseRaidHistoryImportEntries(params.entries || params.raids || params.importText);
  const imported = [];
  const skipped = [];
  const warnings = [];
  for (const entry of entries) {
    const raidType = normalizeRaidType(entry.raid || entry.raidType || entry.type);
    const raidDate = parseDateValue(entry.date || entry.raidDate || entry.datum);
    const raidTime = clean(entry.time || entry.raidTime || entry.uhrzeit || "20:00") || "20:00";
    if (!raidType || !raidDate) {
      skipped.push(entry);
      continue;
    }
    const raidId = `history-${raidType}-${raidDate}-${raidTime}`.toLowerCase().replace(/[^a-z0-9-]+/g, "-");
    const matchedExisting = await findRaidForHistoryImport(guildId, raidType, raidDate, raidTime);
    let created = null;
    if (!matchedExisting) {
      created = await createRaidRecord({
        guildId,
        query: {
          raidId,
          raid: raidType,
          raidName: clean(entry.title || entry.raidName || entry.name) || `${displayRaidName(raidType)} ${raidDate}`,
          raidDate,
          raidTime,
          guild: "Lichtbringer",
          playerPin: clean(entry.playerPin || "") || randomRaidCode(3),
          leadPin: clean(entry.leadPin || "") || randomRaidCode(4),
          status: clean(entry.status || "archiviert"),
          p0PlusFreigabe: "geschlossen",
          createdBy: clean(entry.createdBy || "History-Import"),
          raidHelperEnabled: "true",
          maxPlayers: parseOptionalInteger(entry.maxPlayers) || (["zg", "aq20"].includes(raidType) ? 20 : 40),
          tankSlots: parseOptionalInteger(entry.tankSlots) || (["zg", "aq20"].includes(raidType) ? 1 : 2),
          healSlots: parseOptionalInteger(entry.healSlots) || (["zg", "aq20"].includes(raidType) ? 4 : 8),
          ddSlots: parseOptionalInteger(entry.ddSlots) || (["zg", "aq20"].includes(raidType) ? 15 : 30),
          description: clean(entry.description || "Vergangener Termin aus History-Import.")
        }
      });
    }
    const raid = matchedExisting || await findRaid(guildId, { raidId: created.raidId || raidId });
    const targetRaidId = raidPublicId(raid);
    let signupsWritten = 0;
    const signups = Array.isArray(entry.signups) ? entry.signups : [];
    if (raid && signups.length) {
      for (const signup of signups) {
        const playerName = clean(signup.player || signup.char || signup.name || signup.spieler);
        if (!playerName) continue;
        const source = clean(signup.source || `history-import:${raidId}`);
        const values = [
          raid.id,
          guildId,
          raidType,
          raidDate,
          raidTime,
          playerName,
          clean(signup.className || signup.klasse),
          normalizeSignupRole(signup.role || signup.rolle || "flex"),
          normalizeSignupStatus(signup.status || "signed"),
          source,
          clean(signup.discordUserId),
          clean(signup.discordName || signup.discord),
          clean(signup.note || "History-Import")
        ];
        const updateResult = await query(
          `update raid_external_signups
           set raid_date = $4,
               raid_time = $5,
               raid_type = $3,
               class_name = coalesce(nullif($7, ''), class_name),
               role = $8,
               status = $9,
               discord_user_id = coalesce(nullif($11, ''), discord_user_id),
               discord_name = coalesce(nullif($12, ''), discord_name),
               note = $13,
               updated_at = now()
           where raid_id = $1
             and guild_id = $2
             and lower(player_name) = lower($6)
             and source = $10`,
          values
        );
        if (!updateResult.rowCount) {
          await query(
            `insert into raid_external_signups (
               raid_id, guild_id, raid_type, raid_date, raid_time, player_name,
               class_name, role, status, source, discord_user_id, discord_name, note
             )
             values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)`,
            values
          );
        }
        signupsWritten += 1;
      }
    }
    const prioCountResult = raid
      ? await query("select count(*)::int as count from prios where raid_id = $1", [raid.id])
      : { rows: [{ count: 0 }] };
    const prioCount = Number(prioCountResult.rows[0]?.count || 0);
    if (signupsWritten > 0 && prioCount === 0) {
      warnings.push({
        raidId: targetRaidId || raidId,
        raid: raidType,
        raidDate,
        raidTime,
        message: "Attendance importiert, aber keine Prioliste an diesem Raid gefunden."
      });
    }
    imported.push({
      raidId: targetRaidId || raidId,
      raid: raidType,
      raidDate,
      raidTime,
      signupsWritten,
      prioCount,
      reusedExistingRaid: Boolean(matchedExisting)
    });
  }
  return { success: true, imported, skipped, warnings };
}

async function getRaidHelperTemplates({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  await ensureRaidHelperTemplateSchema();
  const result = await query(
    `select *
     from raid_helper_templates
     where guild_id = $1
     order by lower(raid_type), lower(title)`,
    [guildId]
  );
  return { success: true, templates: result.rows.map(normalizeRaidHelperTemplateRow) };
}

async function saveRaidHelperTemplate({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  await ensureRaidHelperTemplateSchema();
  const templateId = clean(params.templateId || params.id);
  const templateKey = clean(params.templateKey || params.key);
  const raidType = normalizeRaidType(params.raid || params.raidType || params.raidName);
  const title = clean(params.title || params.name);

  if (!raidType || !title) {
    const error = new Error("Raid und Titel sind für die Vorlage erforderlich.");
    error.statusCode = 400;
    throw error;
  }

  const values = [
    guildId,
    templateKey || `${raidType}-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "")}`,
    raidType,
    title,
    clean(params.description || params.text),
    parseOptionalInteger(params.maxPlayers),
    parseOptionalInteger(params.tankSlots),
    parseOptionalInteger(params.healSlots),
    parseOptionalInteger(params.ddSlots),
    clean(params.signupDeadline || params.deadline),
    clean(params.discordChannelId || params.channelId),
    clean(params.raidImageUrl || params.imageUrl)
  ];

  let result;
  if (templateId && isUuid(templateId)) {
    result = await query(
      `update raid_helper_templates
       set template_key = $2,
           raid_type = $3,
           title = $4,
           description = $5,
           max_players = $6,
           tank_slots = $7,
           heal_slots = $8,
           dd_slots = $9,
           signup_deadline = $10,
           discord_channel_id = $11,
           raid_image_url = $12,
           updated_at = now()
       where guild_id = $1 and id = $13
       returning *`,
      [...values, templateId]
    );
  } else {
    const existing = await query(
      `select id
       from raid_helper_templates
       where guild_id = $1 and lower(template_key) = lower($2)
       limit 1`,
      [guildId, values[1]]
    );
    if (existing.rows[0]) {
      result = await query(
        `update raid_helper_templates
         set template_key = $2,
             raid_type = $3,
             title = $4,
             description = $5,
             max_players = $6,
             tank_slots = $7,
             heal_slots = $8,
             dd_slots = $9,
             signup_deadline = $10,
             discord_channel_id = $11,
             raid_image_url = $12,
             updated_at = now()
         where guild_id = $1 and id = $13
         returning *`,
        [...values, existing.rows[0].id]
      );
    } else {
      result = await query(
        `insert into raid_helper_templates (
           guild_id, template_key, raid_type, title, description, max_players,
           tank_slots, heal_slots, dd_slots, signup_deadline, discord_channel_id, raid_image_url
         )
         values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
         returning *`,
        values
      );
    }
  }

  return { success: true, template: normalizeRaidHelperTemplateRow(result.rows[0]) };
}

async function deleteRaidHelperTemplate({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  await ensureRaidHelperTemplateSchema();
  const templateId = clean(params.templateId || params.id);
  if (!isUuid(templateId)) {
    const error = new Error("Vorlagen-ID fehlt.");
    error.statusCode = 400;
    throw error;
  }
  const result = await query(
    `delete from raid_helper_templates
     where guild_id = $1 and id = $2`,
    [guildId, templateId]
  );
  return { success: true, deleted: result.rowCount };
}

async function queueRaidAnnouncement({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  const raidId = clean(params.raidId || params.id || "");
  if (!raidId) return { success: false, error: "Raid-ID fehlt." };
  const channelId = clean(params.channelId || params.discordChannelId);
  let followupPoPost = params.followupPoPost || null;
  if (typeof followupPoPost === "string") {
    try {
      followupPoPost = JSON.parse(followupPoPost);
    } catch {
      followupPoPost = null;
    }
  }
  let snapshot = null;
  try {
    snapshot = await getRaidHelper({ guildId, query: { ...params, raidId, playerPin: params.playerPin || params.prioPin || params.raidPin || "" } });
  } catch {
    snapshot = null;
  }
  const statusNotifyTargets = (() => {
    const raw = params.statusNotifyTargets ?? snapshot?.raid?.statusNotifyTargets ?? [];
    if (Array.isArray(raw)) return raw;
    try { const parsed = JSON.parse(raw); return Array.isArray(parsed) ? parsed : []; } catch { return []; }
  })();
  const announcementNotifyTargets = (() => {
    const raw = params.announcementNotifyTargets ?? snapshot?.raid?.announcementNotifyTargets ?? [];
    if (Array.isArray(raw)) return raw;
    try { const parsed = JSON.parse(raw); return Array.isArray(parsed) ? parsed : []; } catch { return []; }
  })();
  const announcement = await queueBotUpdate({
    guildId,
    query: {
      ...params,
      type: "raid_announcement",
      payload: {
        raidId,
        playerPin: clean(params.playerPin || params.prioPin || params.raidPin || snapshot?.raid?.playerPin || ""),
        prioPin: clean(params.playerPin || params.prioPin || params.raidPin || snapshot?.raid?.playerPin || ""),
        raid: clean(params.raid || snapshot?.raid?.raid || ""),
        raidName: clean(params.raidName || snapshot?.raid?.raidName || ""),
        raidDate: clean(params.raidDate || snapshot?.raid?.raidDate || ""),
        raidTime: clean(params.raidTime || snapshot?.raid?.raidTime || ""),
        createdBy: clean(params.createdBy || snapshot?.raid?.createdBy || snapshot?.raid?.erstelltVon || ""),
        guild: clean(params.guild || snapshot?.raid?.guild || ""),
        guildSlug: clean(params.guildSlug || params.guild || snapshot?.raid?.guildSlug || ""),
        guildName: clean(params.guildName || snapshot?.raid?.guildName || ""),
        maxPlayers: clean(params.maxPlayers || snapshot?.raid?.maxPlayers || ""),
        tankSlots: clean(params.tankSlots || snapshot?.raid?.tankSlots || ""),
        healSlots: clean(params.healSlots || snapshot?.raid?.healSlots || ""),
        ddSlots: clean(params.ddSlots || snapshot?.raid?.ddSlots || ""),
        signupDeadline: clean(params.signupDeadline || snapshot?.raid?.signupDeadline || snapshot?.raid?.signup_deadline || ""),
        lootMaster: clean(params.lootMaster || params.pluendermeister || snapshot?.raid?.lootMaster || snapshot?.raid?.pluendermeister || ""),
        pluendermeister: clean(params.pluendermeister || params.lootMaster || snapshot?.raid?.pluendermeister || snapshot?.raid?.lootMaster || ""),
        statusNotifyTargets,
        announcementNotifyTargets,
        description: clean(params.description || snapshot?.raid?.description || ""),
        raidImageUrl: clean(params.raidImageUrl || snapshot?.raid?.raidImageUrl || snapshot?.raid?.imageUrl || ""),
        channelId,
        discordChannelId: channelId,
        messageId: clean(params.messageId || params.discordMessageId || snapshot?.raid?.discordMessageId || ""),
        discordMessageId: clean(params.messageId || params.discordMessageId || snapshot?.raid?.discordMessageId || ""),
        raidSnapshot: snapshot?.raid || null,
        signups: snapshot?.signups || [],
        externalSignups: snapshot?.externalSignups || [],
        followupPoPost: followupPoPost && typeof followupPoPost === "object" ? followupPoPost : null,
        source: "gildenleitung"
      }
    }
  });
  const announcementTargets = announcementNotifyTargets.filter(target => ["role", "name"].includes(clean(target?.type).toLowerCase()) && clean(target?.value));
  let roleNoticeQueued = false;
  if (announcement?.success && announcementTargets.length) {
    const notice = await enqueueBotUpdate({
      guildId,
      type: "raid_announcement_role_notice",
      payload: {
        raidId,
        raidName: clean(params.raidName || snapshot?.raid?.raidName || "Raid"),
        raidDate: clean(params.raidDate || snapshot?.raid?.raidDate || ""),
        raidTime: clean(params.raidTime || snapshot?.raid?.raidTime || ""),
        channelId: channelId || clean(snapshot?.raid?.discordChannelId || ""),
        targets: announcementTargets,
        signupUrl: `https://lichtloot.de/?raidId=${encodeURIComponent(raidId)}`
      }
    }).catch(() => null);
    roleNoticeQueued = Boolean(notice?.success);
  }
  return { ...announcement, roleNoticeQueued };
}

async function queueRaidAnnouncementNotice({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  const raidId = clean(params.raidId || params.id || "");
  if (!raidId) return { success: false, error: "Raid-ID fehlt." };
  const snapshot = await getRaidHelper({ guildId, query: { ...params, raidId, playerPin: raidId } });
  const raid = snapshot?.raid || {};
  let targets = params.announcementNotifyTargets ?? raid.announcementNotifyTargets ?? [];
  if (typeof targets === "string") {
    try { targets = JSON.parse(targets); } catch { targets = []; }
  }
  targets = Array.isArray(targets) ? targets.filter(target => ["role", "name"].includes(clean(target?.type).toLowerCase()) && clean(target?.value)) : [];
  if (!targets.length) return { success: false, error: "Keine Empfänger für die Erstellungs-DM ausgewählt." };
  return enqueueBotUpdate({
    guildId,
    type: "raid_announcement_role_notice",
    payload: {
      raidId,
      raidName: clean(raid.raidName || params.raidName || "Raid"),
      raidDate: clean(raid.raidDate || params.raidDate || ""),
      raidTime: clean(raid.raidTime || params.raidTime || ""),
      channelId: clean(raid.discordChannelId || params.channelId || params.discordChannelId || ""),
      targets,
      signupUrl: `https://lichtloot.de/?raidId=${encodeURIComponent(raidId)}`
    }
  });
}

async function queueRaidAnnouncementRefresh({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  const raidId = clean(params.raidId || params.id || "");
  if (!raidId) return { success: false, error: "Raid-ID fehlt." };
  let snapshot = null;
  try {
    snapshot = await getRaidHelper({ guildId, query: { ...params, raidId, playerPin: params.playerPin || params.prioPin || params.raidPin || "" } });
  } catch {
    snapshot = null;
  }
  return queueBotUpdate({
    guildId,
    query: {
      ...params,
      type: "raid_announcement_refresh",
      payload: {
        raidId,
        playerPin: clean(params.playerPin || params.prioPin || params.raidPin || snapshot?.raid?.playerPin || ""),
        prioPin: clean(params.playerPin || params.prioPin || params.raidPin || snapshot?.raid?.playerPin || ""),
        raid: clean(params.raid || snapshot?.raid?.raid || ""),
        raidDate: clean(params.raidDate || snapshot?.raid?.raidDate || ""),
        raidTime: clean(params.raidTime || snapshot?.raid?.raidTime || ""),
        channelId: clean(params.channelId || params.discordChannelId),
        messageId: clean(params.messageId || params.discordMessageId || params.raidHelperMessageId),
        raidSnapshot: snapshot?.raid || null,
        signups: snapshot?.signups || [],
        externalSignups: snapshot?.externalSignups || [],
        source: "gildenleitung"
      }
    }
  });
}

async function resolveGuildPoPostChannelId({ guildId, requestedChannelId = "", raid = "" }) {
  await ensureDiscordChannelSchema();
  const requested = clean(requestedChannelId);
  if (requested) {
    const existing = await query(
      `select channel_id
       from discord_bot_channels
       where guild_id = $1
         and channel_id = $2
         and can_send = true
       limit 1`,
      [guildId, requested]
    );
    if (existing.rows[0]?.channel_id) return requested;
  }

  const raidKey = clean(normalizeRaidType(raid)).toLowerCase();
  const result = await query(
    `select channel_id
     from (
       select channel_id, channel_name, category_name, position,
         case
           when $2 <> ''
             and lower(coalesce(channel_name, '') || ' ' || coalesce(category_name, '')) like '%' || $2 || '%'
             and lower(coalesce(channel_name, '') || ' ' || coalesce(category_name, '')) like '%po%'
             and lower(coalesce(channel_name, '') || ' ' || coalesce(category_name, '')) like '%anmeld%' then 0
           when lower(coalesce(channel_name, '') || ' ' || coalesce(category_name, '')) like '%po%'
             and lower(coalesce(channel_name, '') || ' ' || coalesce(category_name, '')) like '%anmeld%' then 1
           when $2 <> ''
             and lower(coalesce(channel_name, '') || ' ' || coalesce(category_name, '')) like '%' || $2 || '%'
             and lower(coalesce(channel_name, '') || ' ' || coalesce(category_name, '')) like '%po%' then 2
           when lower(coalesce(channel_name, '') || ' ' || coalesce(category_name, '')) like '%po%' then 3
           when $2 <> ''
             and lower(coalesce(channel_name, '') || ' ' || coalesce(category_name, '')) like '%' || $2 || '%' then 4
           else 99
         end as po_rank
       from discord_bot_channels
       where guild_id = $1
         and can_send = true
     ) ranked_channels
     where po_rank < 99
     order by
       po_rank,
       coalesce(position, 999999),
       lower(channel_name)
     limit 1`,
    [guildId, raidKey]
  );
  return clean(result.rows[0]?.channel_id) || requested;
}

async function queuePoPost({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensurePoPostEntriesSchema();
  const requestedSourceChannelId = clean(params.sourceChannelId || params.sourceChannel || params.channelId);
  const requestedTargetChannelId = clean(params.targetChannelId || params.targetChannel || params.discordChannelId) || requestedSourceChannelId;
  const raid = clean(params.raid || params.raidName);
  const targetChannelId = await resolveGuildPoPostChannelId({
    guildId,
    requestedChannelId: requestedTargetChannelId,
    raid
  });
  const sourceChannelId = requestedSourceChannelId === requestedTargetChannelId
    ? targetChannelId
    : await resolveGuildPoPostChannelId({
        guildId,
        requestedChannelId: requestedSourceChannelId,
        raid
      });
  const reviewRecipient = clean(params.reviewRecipient || params.reviewUserId || params.approvalUserId || params.freigabeAn);
  const postKey = clean(params.postKey || params.poPostKey || params.postId || params.id);
  if (!sourceChannelId) {
    const error = new Error("PO-Quellchannel fehlt.");
    error.statusCode = 400;
    throw error;
  }
  if (!targetChannelId) {
    const error = new Error("PO-Zielchannel fehlt.");
    error.statusCode = 400;
    throw error;
  }
  const limit = Math.max(50, Math.min(2000, Number(params.limit || 800) || 800));
  let restoredEntries = 0;
  if (["1", "true", "yes", "ja"].includes(clean(params.restoreArchived || params.restore || params.repost || "").toLowerCase())) {
    const restoreResult = await query(
      `update po_post_entries
       set archived_at = null,
           source_channel_id = coalesce(nullif($3, ''), source_channel_id),
           target_channel_id = coalesce(nullif($4, ''), target_channel_id),
           raid = coalesce(nullif($5, ''), raid),
           raid_date = coalesce(nullif($6, ''), raid_date),
           raid_time = coalesce(nullif($7, ''), raid_time),
           mode = coalesce(nullif($8, ''), mode),
           updated_at = now()
       where guild_id = $1
         and post_key = $2
         and archived_at is not null`,
      [
        guildId,
        postKey,
        sourceChannelId,
        targetChannelId,
        raid,
        clean(params.raidDate || params.date || params.datum),
        clean(params.raidTime || params.time || params.uhrzeit),
        clean(params.mode || params.poMode) || "signup"
      ]
    );
    restoredEntries = restoreResult.rowCount || 0;
  }
  await query(
    `insert into po_post_entries (
       guild_id, post_key, source_channel_id, target_channel_id, discord_message_id,
       raid, title, raid_pin, raid_date, raid_time, mode, config_only
     )
     select $1,$2,$3,$4,'',$5,$6,$7,$8,$9,$10,true
     where not exists (
       select 1
       from po_post_entries
       where guild_id = $1
         and post_key = $2
         and archived_at is null
     )`,
    [
      guildId,
      postKey,
      sourceChannelId,
      targetChannelId,
      normalizeRaidType(raid).toUpperCase(),
      clean(params.title) || "PO Liste",
      clean(params.lichtlootPlayerPin || params.lichtlootPrioPin || params.prioPin || params.raidPin || params.lichtlootRaidId || params.lichtlootRaid),
      clean(params.raidDate || params.date || params.datum),
      clean(params.raidTime || params.time || params.uhrzeit),
      clean(params.mode || params.poMode) || "signup"
    ]
  );
  const queued = await enqueueBotUpdate({
    guildId,
    type: "po_post",
    payload: {
      sourceChannelId,
      targetChannelId,
      reviewRecipient,
      postKey,
      title: clean(params.title) || "PO Liste",
      raid,
      raidDate: clean(params.raidDate || params.date || params.datum),
      raidTime: clean(params.raidTime || params.time || params.uhrzeit),
      guildName: clean(params.guildName || params.displayGuild || params.guild || params.gilde),
      createdBy: clean(params.createdBy || params.created_by || params.erstelltVon || params.ersteller) || "Gildenleitung",
      note: clean(params.note || params.message || params.raidleadMessage || params.extraMessage),
      mode: clean(params.mode || params.poMode) || "signup",
      groupBy: clean(params.groupBy || params.poGroupBy || params.sortBy),
      itemOptions: clean(params.itemOptions || params.items || params.itemList),
      postedEntries: typeof params.postedEntries === "string" ? params.postedEntries : JSON.stringify(params.postedEntries || []),
      restoreArchived: ["1", "true", "yes", "ja"].includes(clean(params.restoreArchived || params.restore || params.repost || "").toLowerCase()) ? "true" : "",
      forceNewMessage: ["1", "true", "yes", "ja"].includes(clean(params.forceNewMessage || params.forceRepost || "").toLowerCase()) ? "true" : "",
      createLichtlootRaid: clean(params.createLichtlootRaid || params.createRaid || ""),
      lichtlootRaidId: clean(params.lichtlootRaidId || params.lichtlootRaid || params.raidId || ""),
      lichtlootPlayerPin: clean(params.lichtlootPlayerPin || params.lichtlootPrioPin || params.prioPin || params.raidPin || ""),
      lichtlootLeadPin: clean(params.lichtlootLeadPin || params.leadPin || ""),
      limit,
      source: "gildenleitung"
    }
  });
  return { ...queued, restoredEntries };
}

async function ensurePoPostEntriesSchema() {
  await query(
    `create table if not exists po_post_entries (
       id uuid primary key default gen_random_uuid(),
       guild_id uuid not null references guilds(id) on delete cascade,
       post_key text not null default '',
       source_channel_id text not null default '',
       target_channel_id text not null default '',
       discord_message_id text not null default '',
       raid text not null default '',
       title text not null default 'PO Liste',
       player_name text not null default '',
       item_name text not null default '',
       discord_user_id text not null default '',
       discord_name text not null default '',
       po_message_id text not null default '',
       po_created_at timestamptz,
       approval_status text not null default 'pending',
       approved_by text not null default '',
       approved_at timestamptz,
       archived_at timestamptz,
       created_at timestamptz not null default now(),
       updated_at timestamptz not null default now()
     )`
  );
  await query(`alter table po_post_entries add column if not exists discord_user_id text not null default ''`);
  await query(`alter table po_post_entries add column if not exists discord_name text not null default ''`);
  await query(`alter table po_post_entries add column if not exists class_name text not null default ''`);
  await query(`alter table po_post_entries add column if not exists approval_status text not null default 'pending'`);
  await query(`alter table po_post_entries add column if not exists approved_by text not null default ''`);
  await query(`alter table po_post_entries add column if not exists approved_at timestamptz`);
  await query(`alter table po_post_entries add column if not exists rejection_reason text not null default ''`);
  await query(`alter table po_post_entries add column if not exists luck_by text not null default ''`);
  await query(`alter table po_post_entries add column if not exists luck_by_discord_id text not null default ''`);
  await query(`alter table po_post_entries add column if not exists luck_at timestamptz`);
  await query(`alter table po_post_entries add column if not exists archived_at timestamptz`);
  await query(`alter table po_post_entries add column if not exists created_at timestamptz not null default now()`);
  await query(`alter table po_post_entries add column if not exists raid_pin text not null default ''`);
  await query(`alter table po_post_entries add column if not exists item_game_id text not null default ''`);
  await query(`alter table po_post_entries add column if not exists item_slot text not null default ''`);
  await query(`alter table po_post_entries add column if not exists item_boss text not null default ''`);
  await query(`alter table po_post_entries add column if not exists raid_date text not null default ''`);
  await query(`alter table po_post_entries add column if not exists raid_time text not null default ''`);
  await query(`alter table po_post_entries add column if not exists mode text not null default ''`);
  await query(`alter table po_post_entries add column if not exists config_only boolean not null default false`);
  await query(`create index if not exists idx_po_post_entries_guild on po_post_entries(guild_id, post_key, source_channel_id)`);
  await query(`create index if not exists idx_po_post_entries_active_raid on po_post_entries(guild_id, lower(raid)) where archived_at is null`);
}

async function resolvePoPostPlayerName(client, guildId, entry) {
  const fallback = clean(entry.player || entry.char || entry.name);
  const discordUserId = clean(entry.discordUserId || entry.discord_user_id);
  if (entry.preservePlayerName === true || clean(entry.preservePlayerName).toLowerCase() === "true") return fallback;
  if (fallback) return fallback;
  if (!discordUserId) return fallback;
  const linked = await client.query(
    `select c.name
     from discord_player_links dpl
     join characters c on c.id = dpl.character_id
     join players p on p.id = c.player_id
     where dpl.guild_id = $1
       and dpl.discord_user_id = $2
       and p.guild_id = $1
     order by coalesce(c.is_main, false) desc, dpl.updated_at desc, c.name asc
     limit 1`,
    [guildId, discordUserId]
  );
  return clean(linked.rows[0]?.name) || fallback;
}

async function savePoPostEntries({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensurePoPostEntriesSchema();
  const postKey = clean(params.postKey || params.poPostKey || params.postId || "po-liste");
  const sourceChannelId = clean(params.sourceChannelId || params.sourceChannel || "");
  const targetChannelId = clean(params.targetChannelId || params.targetChannel || params.discordChannelId || "");
  const raidKey = normalizeRaidType(params.raid || params.raidName).toLowerCase();
  const raidDate = clean(params.raidDate || params.date || params.datum);
  const raidTime = clean(params.raidTime || params.time || params.uhrzeit);
  const mode = clean(params.mode || params.poMode);
  const raidPin = clean(params.raidPin || params.prioPin || params.lichtlootPlayerPin || params.lichtlootRaidId || params.playerLinkPin);
  let releaseNames = new Set();
  try {
    const releaseResult = await getP0ReleaseList(guildId);
    releaseNames = new Set((releaseResult.releases?.[raidKey] || []).map(name => clean(name).toLowerCase()).filter(Boolean));
  } catch (error) {
    console.warn("P0-Freigabeliste konnte fuer PO-Post nicht geladen werden:", error.message || error);
  }
  let entries = params.entries || [];
  if (typeof entries === "string") {
    try { entries = JSON.parse(entries || "[]"); } catch { entries = []; }
  }
  if (!Array.isArray(entries)) entries = [];

  const client = await pool.connect();
  try {
    await client.query("begin");
    const approvalResult = await client.query(
      `select po_message_id, player_name, item_name, class_name, approval_status, approved_by, approved_at,
              luck_by, luck_by_discord_id, luck_at
       from po_post_entries
       where guild_id = $1 and post_key = $2 and source_channel_id = $3 and target_channel_id = $4 and archived_at is null`,
      [guildId, postKey, sourceChannelId, targetChannelId]
    );
    const approvalByKey = new Map();
    for (const row of approvalResult.rows) {
      const status = {
        approvalStatus: row.approval_status || "pending",
        className: row.class_name || "",
        approvedBy: row.approved_by || "",
        approvedAt: row.approved_at || null,
        luckBy: row.luck_by || "",
        luckByDiscordId: row.luck_by_discord_id || "",
        luckAt: row.luck_at || null
      };
      const poMessageId = clean(row.po_message_id);
      if (poMessageId) approvalByKey.set(poMessageId, status);
      approvalByKey.set(`${clean(row.player_name).toLowerCase()}|${normalizePoItemName(row.item_name).toLowerCase()}`, status);
    }
    await client.query(
      `delete from po_post_entries
       where guild_id = $1 and post_key = $2 and source_channel_id = $3 and target_channel_id = $4 and archived_at is null`,
      [guildId, postKey, sourceChannelId, targetChannelId]
    );
    const seenPlayers = new Set();
    let savedCount = 0;
    for (const entry of entries) {
      const playerName = await resolvePoPostPlayerName(client, guildId, entry);
      const itemName = normalizePoItemName(entry.item || entry.itemName);
      const playerKey = clean(playerName).toLowerCase();
      if (!playerKey || seenPlayers.has(playerKey)) {
        continue;
      }
      seenPlayers.add(playerKey);
      const poMessageId = clean(entry.messageId || entry.discordMessageId);
      const approval = approvalByKey.get(poMessageId)
        || approvalByKey.get(`${playerName.toLowerCase()}|${itemName.toLowerCase()}`)
        || (
          releaseNames.has(playerName.toLowerCase())
            ? { approvalStatus: "approved", approvedBy: "P0-Freigabeliste", approvedAt: new Date().toISOString() }
            : { approvalStatus: "pending", approvedBy: "", approvedAt: null }
        );
      await client.query(
        `insert into po_post_entries (
           guild_id, post_key, source_channel_id, target_channel_id, discord_message_id,
           raid, title, player_name, item_name, discord_user_id, discord_name, class_name, po_message_id, po_created_at,
           approval_status, approved_by, approved_at, luck_by, luck_by_discord_id, luck_at, raid_pin, raid_date, raid_time, mode, config_only
         )
         values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,false)`,
        [
          guildId,
          postKey,
          sourceChannelId,
          targetChannelId,
          clean(params.messageId || params.discordMessageId),
          raidKey.toUpperCase(),
          clean(params.title) || "PO Liste",
          playerName,
          itemName,
          clean(entry.discordUserId || entry.discord_user_id),
          clean(entry.discordName || entry.discord_name),
          clean(entry.className || entry.class_name || entry.klasse || approval.className || ""),
          poMessageId,
          clean(entry.createdAt) || null,
          approval.approvalStatus || "pending",
          approval.approvedBy || "",
          approval.approvedAt || null,
          approval.luckBy || "",
          approval.luckByDiscordId || "",
          approval.luckAt || null,
          raidPin,
          raidDate,
          raidTime,
          mode
        ]
      );
      savedCount += 1;
    }
    await client.query("commit");
    return { success: true, saved: savedCount };
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function getPoPostEntries({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensurePoPostEntriesSchema();
  const rawRaidKey = clean(params.raid || params.raidName);
  const raidKey = rawRaidKey ? normalizeRaidType(rawRaidKey).toLowerCase() : "";
  const postKey = clean(params.postKey || params.poPostKey || params.postId);
  const sourceChannelId = clean(params.sourceChannelId || params.sourceChannel || params.channelId);
  const targetChannelId = clean(params.targetChannelId || params.targetChannel || params.discordChannelId);
  const includeArchived = ["1", "true", "yes", "ja"].includes(clean(params.includeArchived || params.archived || "").toLowerCase());
  const values = [guildId];
  const clauses = ["guild_id = $1"];
  if (!includeArchived) clauses.push("archived_at is null");
  if (raidKey) {
    values.push(raidKey);
    clauses.push(`lower(raid) = $${values.length}`);
  }
  if (postKey) {
    values.push(postKey);
    clauses.push(`post_key = $${values.length}`);
  }
  if (sourceChannelId) {
    values.push(sourceChannelId);
    clauses.push(`source_channel_id = $${values.length}`);
  }
  if (targetChannelId) {
    values.push(targetChannelId);
    clauses.push(`target_channel_id = $${values.length}`);
  }
  const result = await query(
    `select *
     from po_post_entries
     where ${clauses.join(" and ")}
     order by updated_at desc, lower(player_name) asc, lower(item_name) asc
     limit 500`,
    values
  );
  return {
    success: true,
    entries: result.rows.map(row => ({
      id: row.id || "",
      postKey: row.post_key || "",
      sourceChannelId: row.source_channel_id || "",
      targetChannelId: row.target_channel_id || "",
      raid: row.raid || "",
      title: row.title || "PO Liste",
      mode: row.mode || "",
      raidDate: row.raid_date || "",
      raidTime: row.raid_time || "",
      raidPin: row.raid_pin || "",
      prioPin: row.raid_pin || "",
      lichtlootRaidId: row.raid_pin || "",
      lichtlootPlayerPin: row.raid_pin || "",
      player: row.player_name || "",
      className: row.class_name || "",
      Klasse: row.class_name || "",
      item: normalizePoItemName(row.item_name || ""),
      itemId: row.item_game_id || "",
      itemSlot: row.item_slot || "",
      itemBoss: row.item_boss || "",
      discordUserId: row.discord_user_id || "",
      discordName: row.discord_name || "",
      discordMessageId: row.discord_message_id || "",
      messageId: row.po_message_id || "",
      createdAt: row.po_created_at || row.updated_at || "",
      poCreatedAt: row.po_created_at || "",
      approvalStatus: row.approval_status || "pending",
      approved: row.approval_status === "approved",
      approvedBy: row.approved_by || "",
      approvedAt: row.approved_at || "",
      rejectionReason: row.rejection_reason || "",
      luckBy: row.luck_by || "",
      luckByDiscordId: row.luck_by_discord_id || "",
      luckAt: row.luck_at || "",
      archivedAt: row.archived_at || "",
      updatedAt: row.updated_at,
      configOnly: Boolean(row.config_only)
    }))
  };
}

async function setPoPostDiscordMessage({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensurePoPostEntriesSchema();
  const postKey = clean(params.postKey || params.poPostKey || params.postId || "");
  const sourceChannelId = clean(params.sourceChannelId || params.sourceChannel || "");
  const targetChannelId = clean(params.targetChannelId || params.targetChannel || params.discordChannelId || "");
  const discordMessageId = clean(params.discordMessageId || params.messageId || "");
  const raidKey = normalizeRaidType(params.raid || params.raidName).toUpperCase();
  const title = clean(params.title) || "PO-Anmelder";
  const raidPin = clean(params.raidPin || params.prioPin || params.lichtlootPlayerPin || params.lichtlootRaidId || params.playerLinkPin);
  const raidDate = clean(params.raidDate || params.date || params.datum);
  const raidTime = clean(params.raidTime || params.time || params.uhrzeit);
  const mode = clean(params.mode || params.poMode || "signup");
  if (!postKey || !discordMessageId) {
    const error = new Error("PO-Post-ID oder Discord-Nachricht fehlt.");
    error.statusCode = 400;
    throw error;
  }
  const values = [guildId, postKey, discordMessageId, raidKey, title, raidPin, raidDate, raidTime, mode];
  const clauses = ["guild_id = $1", "post_key = $2", "archived_at is null"];
  if (sourceChannelId) {
    values.push(sourceChannelId);
    clauses.push(`source_channel_id = $${values.length}`);
  }
  if (targetChannelId) {
    values.push(targetChannelId);
    clauses.push(`target_channel_id = $${values.length}`);
  }
  const result = await query(
    `update po_post_entries
     set discord_message_id = $3,
         raid = coalesce(nullif($4, ''), raid),
         title = coalesce(nullif($5, ''), title),
         raid_pin = coalesce(nullif($6, ''), raid_pin),
         raid_date = coalesce(nullif($7, ''), raid_date),
         raid_time = coalesce(nullif($8, ''), raid_time),
         mode = coalesce(nullif($9, ''), mode),
         updated_at = now()
     where ${clauses.join(" and ")}`,
    values
  );
  if (!result.rowCount) {
    await query(
      `insert into po_post_entries (
         guild_id, post_key, source_channel_id, target_channel_id, discord_message_id,
         raid, title, raid_pin, raid_date, raid_time, mode, config_only
       )
       values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,true)`,
      [guildId, postKey, sourceChannelId, targetChannelId || sourceChannelId, discordMessageId, raidKey, title, raidPin, raidDate, raidTime, mode]
    );
  }
  return {
    success: true,
    updated: result.rowCount || 0,
    insertedConfig: !result.rowCount,
    postKey,
    discordMessageId
  };
}

async function getPoPostApprovals({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensurePoPostEntriesSchema();
  const postKey = clean(params.postKey || params.poPostKey || params.postId || "");
  const sourceChannelId = clean(params.sourceChannelId || params.sourceChannel || "");
  const targetChannelId = clean(params.targetChannelId || params.targetChannel || params.discordChannelId || "");
  const values = [guildId];
  const clauses = ["guild_id = $1"];
  if (postKey) {
    values.push(postKey);
    clauses.push(`post_key = $${values.length}`);
  }
  if (sourceChannelId) {
    values.push(sourceChannelId);
    clauses.push(`source_channel_id = $${values.length}`);
  }
  if (targetChannelId) {
    values.push(targetChannelId);
    clauses.push(`target_channel_id = $${values.length}`);
  }
  const result = await query(
    `select *
     from po_post_entries
     where ${clauses.join(" and ")} and archived_at is null and coalesce(config_only, false) = false`,
    values
  );
  return {
    success: true,
    entries: result.rows.map(row => ({
      id: row.id || "",
      player: row.player_name || "",
      className: row.class_name || "",
      Klasse: row.class_name || "",
      item: normalizePoItemName(row.item_name || ""),
      messageId: row.po_message_id || "",
      approvalStatus: row.approval_status || "pending",
      approved: row.approval_status === "approved",
      rejectionReason: row.rejection_reason || "",
      luckBy: row.luck_by || "",
      luckByDiscordId: row.luck_by_discord_id || "",
      luckAt: row.luck_at || ""
    }))
  };
}

async function canReviewPoPost({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensurePlayerRoleSchema();
  await ensureRaidSchema();
  const discordUserId = clean(params.discordUserId || params.userId);
  const discordName = clean(params.discordName || params.userName || params.displayName);
  const normalizedDiscordName = normalizeReviewName(discordName);
  const allowlistedByName = Boolean(normalizedDiscordName && poReviewOfficerNames.has(normalizedDiscordName));
  if (!discordUserId && !discordName) return { success: true, allowed: false, roles: [], roleLabels: [] };
  const values = [guildId];
  const clauses = [];
  if (discordUserId) {
    values.push(discordUserId);
    clauses.push(`dpl.discord_user_id = $${values.length}`);
  }
  if (discordName) {
    values.push(discordName);
    clauses.push(`regexp_replace(lower(c.name), '[^a-z0-9]+', '', 'g') = regexp_replace(lower($${values.length}), '[^a-z0-9]+', '', 'g')`);
  }
  const result = await query(
    `select distinct p.role
     from characters c
     join players p on p.id = c.player_id
     left join discord_player_links dpl on dpl.character_id = c.id and dpl.guild_id = $1
     where p.guild_id = $1
       and (${clauses.join(" or ")})`,
    values
  );
  const roles = result.rows.map(row => normalizePlayerRole(row.role)).filter(Boolean);
  const allowedByRole = roles.some(role => raidCreateRoles.has(role));
  return {
    success: true,
    allowed: allowedByRole || allowlistedByName,
    roles: allowlistedByName && !roles.length ? ["offiziersliste"] : roles,
    roleLabels: allowlistedByName && !roles.length ? ["Offiziersliste"] : roles.map(role => playerRoleLabel(role)),
    allowlistedByName
  };
}

async function resolvePoPostPlayers({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensurePoPostEntriesSchema();
  let entries = params.entries || [];
  if (typeof entries === "string") {
    try { entries = JSON.parse(entries || "[]"); } catch { entries = []; }
  }
  if (!Array.isArray(entries)) entries = [];
  const client = await pool.connect();
  try {
    const resolved = [];
    for (const entry of entries.slice(0, 500)) {
      const player = await resolvePoPostPlayerName(client, guildId, entry);
      const copy = { ...entry, player };
      if (player && clean(entry.player) && player.toLowerCase() !== clean(entry.player).toLowerCase()) {
        copy.originalPlayer = clean(entry.player);
      }
      resolved.push(copy);
    }
    return { success: true, entries: resolved };
  } finally {
    client.release();
  }
}

async function reviewPoPostEntry({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensurePoPostEntriesSchema();
  const id = clean(params.id || params.entryId);
  const messageId = clean(params.messageId || params.poMessageId || params.discordMessageId);
  const postKey = clean(params.postKey || params.poPostKey || "");
  const sourceChannelId = clean(params.sourceChannelId || "");
  const targetChannelId = clean(params.targetChannelId || "");
  const playerName = clean(params.player || params.playerName || params.character || params.char);
  const itemName = normalizePoItemName(params.item || params.itemName || "");
  const raidPin = clean(params.raidPin || params.prioPin || params.lichtlootPlayerPin || params.lichtlootRaidId || params.playerLinkPin);
  const rawStatus = clean(params.status || params.value || "approved").toLowerCase();
  const approvalStatus = ["rejected", "invalid", "ungueltig", "ungültig", "nein"].includes(rawStatus) ? "rejected" : "approved";
  const rejectionReason = approvalStatus === "rejected" ? clean(params.reason || params.rejectionReason || params.message || params.note) : "";
  if (approvalStatus === "rejected" && !rejectionReason) {
    const error = new Error("Bitte einen Grund für die Ablehnung eingeben.");
    error.statusCode = 400;
    throw error;
  }
  let result = { rows: [] };
  if (id && isUuid(id)) {
    result = await query(
      `update po_post_entries
       set approval_status = $2,
           approved_by = $3,
           approved_at = case when $2 = 'approved' then now() else null end,
           rejection_reason = case when $2 = 'rejected' then $4 else '' end,
           raid_pin = coalesce(nullif($5, ''), raid_pin),
           updated_at = now()
       where guild_id = $1
         and id = $6
         and archived_at is null
       returning *`,
      [guildId, approvalStatus, clean(params.reviewer || params.discordName || "Gildenleitung"), rejectionReason, raidPin, id]
    );
  }
  if (!result.rows[0] && messageId) {
    result = await query(
      `update po_post_entries
       set approval_status = $6,
           approved_by = $7,
           approved_at = case when $6 = 'approved' then now() else null end,
           rejection_reason = case when $6 = 'rejected' then $8 else '' end,
           raid_pin = coalesce(nullif($9, ''), raid_pin),
           updated_at = now()
       where guild_id = $1
         and post_key = $2
         and source_channel_id = $3
         and target_channel_id = $4
         and po_message_id = $5
         and archived_at is null
       returning *`,
      [guildId, postKey, sourceChannelId, targetChannelId, messageId, approvalStatus, clean(params.reviewer || params.discordName || "Gildenleitung"), rejectionReason, raidPin]
    );
  }
  if (!result.rows[0] && playerName && itemName) {
    result = await query(
      `update po_post_entries
       set approval_status = $6,
           approved_by = $7,
           approved_at = case when $6 = 'approved' then now() else null end,
           rejection_reason = case when $6 = 'rejected' then $9 else '' end,
           raid_pin = coalesce(nullif($10, ''), raid_pin),
           updated_at = now()
       where guild_id = $1
         and post_key = $2
         and source_channel_id = $3
         and target_channel_id = $4
         and lower(player_name) = lower($5)
         and lower(item_name) = lower($8)
         and archived_at is null
       returning *`,
      [guildId, postKey, sourceChannelId, targetChannelId, playerName, approvalStatus, clean(params.reviewer || params.discordName || "Gildenleitung"), itemName, rejectionReason, raidPin]
    );
  }
  if (!result.rows[0] && raidPin && playerName && itemName) {
    result = await query(
      `update po_post_entries
       set approval_status = $5,
           approved_by = $6,
           approved_at = case when $5 = 'approved' then now() else null end,
           rejection_reason = case when $5 = 'rejected' then $7 else '' end,
           updated_at = now()
       where id = (
         select id
         from po_post_entries
         where guild_id = $1
           and raid_pin = $2
           and lower(player_name) = lower($3)
           and lower(item_name) = lower($4)
           and archived_at is null
         order by updated_at desc nulls last, created_at desc
         limit 1
       )
       returning *`,
      [guildId, raidPin, playerName, itemName, approvalStatus, clean(params.reviewer || params.discordName || "Gildenleitung"), rejectionReason]
    );
  }
  const row = result.rows[0];
  if (!row) {
    const error = new Error("PO-Eintrag wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }
  let prioDelete = null;
  if (approvalStatus === "rejected") {
    prioDelete = await deletePoSignupPrioForEntry(guildId, row, params).catch(error => ({
      success: false,
      deleted: 0,
      error: error.message || String(error)
    }));
  }

  await enqueueBotUpdate({
    guildId,
    type: "po_post",
    payload: {
      postKey: row.post_key,
      sourceChannelId: row.source_channel_id,
      targetChannelId: row.target_channel_id,
      messageId: row.discord_message_id || clean(params.discordMessageId || ""),
      discordMessageId: row.discord_message_id || clean(params.discordMessageId || ""),
      raid: row.raid,
      raidPin: row.raid_pin || raidPin,
      prioPin: row.raid_pin || raidPin,
      lichtlootRaidId: row.raid_pin || raidPin,
      lichtlootPlayerPin: row.raid_pin || raidPin,
      title: row.title,
      mode: clean(params.mode || params.poMode) || "signup",
      note: clean(params.note || params.message || params.raidleadMessage),
      itemOptions: clean(params.itemOptions || params.items || params.itemList),
      source: "po_review",
      reviewMessageId: row.po_message_id,
      reviewStatus: approvalStatus,
      rejectionReason,
      queuedAt: new Date().toISOString()
    }
  }).catch(error => console.warn("PO-Post konnte nach Freigabe nicht queued werden:", error.message || error));
  const linkedRaid = await findRaid(guildId, {
    raidId: row.post_key || postKey,
    raid: row.raid || params.raid || params.raidName,
    raidDate: row.raid_date || params.raidDate || params.date || params.datum,
    raidTime: row.raid_time || params.raidTime || params.time || params.uhrzeit,
    raidPin: row.raid_pin || raidPin,
    prioPin: row.raid_pin || raidPin,
    playerPin: row.raid_pin || raidPin
  }).catch(() => null);
  const raidAnnouncementRefresh = await enqueueRaidAnnouncementRefreshAfterPrioChange(
    guildId,
    linkedRaid,
    approvalStatus === "approved" ? "po_approved" : "po_rejected"
  );
  const rejectionNoticeHandled = ["1", "true", "yes", "ja"].includes(
    clean(params.rejectionNoticeHandled || params.notificationHandled).toLowerCase()
  );
  if (approvalStatus === "rejected" && clean(row.discord_user_id) && !rejectionNoticeHandled) {
    await enqueueBotUpdate({
      guildId,
      type: "po_rejection_notice",
      payload: {
        discordUserId: row.discord_user_id,
        player: row.player_name || "",
        item: normalizePoItemName(row.item_name || ""),
        raid: row.raid || "",
        reason: rejectionReason,
        reviewer: clean(params.reviewer || params.discordName || "Gildenleitung"),
        source: "po_review"
      }
    }).catch(error => console.warn("PO-Ablehnungsnachricht konnte nicht queued werden:", error.message || error));
  }
  const approvalNoticeHandled = ["1", "true", "yes", "ja"].includes(
    clean(params.approvalNoticeHandled || params.notificationHandled).toLowerCase()
  );
  if (approvalStatus === "approved" && clean(row.discord_user_id) && !approvalNoticeHandled) {
    await enqueueBotUpdate({
      guildId,
      type: "po_approval_notice",
      payload: {
        discordUserId: row.discord_user_id,
        player: row.player_name || "",
        item: normalizePoItemName(row.item_name || ""),
        raid: row.raid || "",
        reviewer: clean(params.reviewer || params.discordName || "Gildenleitung"),
        source: "po_review"
      }
    }).catch(error => console.warn("PO-Freigabenachricht konnte nicht queued werden:", error.message || error));
  }
  return {
    success: true,
    entry: {
      id: row.id || "",
      postKey: row.post_key || "",
      sourceChannelId: row.source_channel_id || "",
      targetChannelId: row.target_channel_id || "",
      raid: row.raid || "",
      title: row.title || "PO Liste",
      raidPin: row.raid_pin || "",
      prioPin: row.raid_pin || "",
      lichtlootRaidId: row.raid_pin || "",
      lichtlootPlayerPin: row.raid_pin || "",
      player: row.player_name || "",
      className: row.class_name || "",
      Klasse: row.class_name || "",
      item: normalizePoItemName(row.item_name || ""),
      messageId: row.po_message_id || "",
      discordMessageId: row.discord_message_id || "",
      discordUserId: row.discord_user_id || "",
      approvalStatus: row.approval_status || "pending",
      approved: row.approval_status === "approved",
      approvedBy: row.approved_by || "",
      approvedAt: row.approved_at || "",
      rejectionReason: row.rejection_reason || rejectionReason || ""
    },
    prioDelete,
    raidAnnouncementRefresh
  };
}

async function deletePoSignupPrioForEntry(guildId, entry, params = {}) {
  await ensurePrioSchema();
  const playerName = clean(entry.player_name || entry.player || params.player || params.char || params.spieler);
  const itemName = normalizePoItemName(entry.item_name || entry.item || params.item || params.itemName);
  if (!playerName || !itemName) return { success: true, deleted: 0, reason: "missing_player_or_item" };

  const raid = await findRaid(guildId, {
    ...params,
    raidId: entry.post_key || params.raidId || params.postKey,
    raid: entry.raid || params.raid || params.raidName,
    raidDate: entry.raid_date || params.raidDate || params.date || params.datum,
    raidTime: entry.raid_time || params.raidTime || params.time || params.uhrzeit,
    prioPin: entry.raid_pin || params.raidPin || params.prioPin || params.playerPin,
    raidPin: entry.raid_pin || params.raidPin || params.prioPin || params.playerPin,
    playerPin: entry.raid_pin || params.raidPin || params.prioPin || params.playerPin
  });
  if (!raid) return { success: true, deleted: 0, reason: "raid_not_found" };

  const values = [guildId, raid.id, playerName];
  const itemClauses = [];
  for (const variant of poItemAliasVariants(itemName)) {
    values.push(variant);
    itemClauses.push(`regexp_replace(lower(i.name), '[^a-z0-9]+', '', 'g') = regexp_replace(lower($${values.length}), '[^a-z0-9]+', '', 'g')`);
  }
  const itemMatchClause = itemClauses.length ? itemClauses.join(" or ") : "false";

  const result = await query(
    `delete from prios pr
     using characters c
     where pr.character_id = c.id
       and pr.raid_id = $2
       and c.player_id in (select id from players where guild_id = $1)
       and regexp_replace(lower(c.name), '[^a-z0-9]+', '', 'g') = regexp_replace(lower($3), '[^a-z0-9]+', '', 'g')
       and (
         coalesce(pr.comment, '') ilike '%"source":"po-bot"%'
         or coalesce(pr.comment, '') ilike '%po-bot%'
         or (
           pr.p1_item_id is not null
           and pr.p1_item_id = pr.p2_item_id
           and pr.p2_item_id = pr.p3_item_id
           and exists (
             select 1
             from items i
             where i.id = pr.p1_item_id
               and (${itemMatchClause})
           )
         )
       )
     returning pr.id`,
    values
  );

  return {
    success: true,
    deleted: result.rowCount || 0,
    raidId: raidPublicId(raid),
    player: playerName,
    item: itemName
  };
}

async function updatePoPostEntry({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensurePoPostEntriesSchema();
  const id = clean(params.id || params.entryId);
  const postKey = clean(params.postKey || params.poPostKey || "");
  const sourceChannelId = clean(params.sourceChannelId || "");
  const targetChannelId = clean(params.targetChannelId || "");
  const messageId = clean(params.messageId || params.poMessageId);
  const discordMessageId = clean(params.discordMessageId);
  const previousPlayer = clean(params.player || params.playerName || params.char);
  const previousItem = normalizePoItemName(params.item || params.itemName);
  const characterId = clean(params.characterId || params.character_id);
  const correctedItem = normalizePoItemName(params.correctedItem || params.correctedItemName || params.newItem || params.itemName);
  const correctedItemId = clean(params.correctedItemId || params.correctedItemGameId || params.itemId || params.itemGameId || params.item_id);
  let correctedItemSlot = clean(params.correctedItemSlot || params.itemSlot || params.slot);
  let correctedItemBoss = clean(params.correctedItemBoss || params.itemBoss || params.boss);
  const raidKey = normalizeRaidType(params.raid || params.raidName).toUpperCase();
  const raidPin = clean(params.raidPin || params.prioPin || params.lichtlootPlayerPin || params.lichtlootRaidId || params.playerLinkPin);

  if (!characterId || !correctedItem) {
    const error = new Error("Spielerlogin oder Item fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const characterResult = await query(
    `select c.id, c.name, c.server, c.class_name, p.player_pin, p.approval_status, p.is_blocked
     from characters c
     join players p on p.id = c.player_id
     where p.guild_id = $1
       and c.id = $2
       and p.approval_status = 'approved'
       and coalesce(p.is_blocked, false) = false
     limit 1`,
    [guildId, characterId]
  );
  const character = characterResult.rows[0];
  if (!character) {
    const error = new Error("Spielerlogin/Charakter wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const values = [
    guildId,
    character.name,
    correctedItem,
    character.class_name || "",
    raidKey,
    raidPin
  ];
  const clauses = ["guild_id = $1", "archived_at is null"];
  let hasEntryLocator = false;
  if (id && isUuid(id)) {
    values.push(id);
    clauses.push(`id = $${values.length}`);
    hasEntryLocator = true;
  } else {
    if (postKey) {
      values.push(postKey);
      clauses.push(`post_key = $${values.length}`);
    }
    if (sourceChannelId) {
      values.push(sourceChannelId);
      clauses.push(`source_channel_id = $${values.length}`);
    }
    if (targetChannelId) {
      values.push(targetChannelId);
      clauses.push(`target_channel_id = $${values.length}`);
    }
    if (messageId) {
      values.push(messageId);
      clauses.push(`po_message_id = $${values.length}`);
      hasEntryLocator = true;
    } else if (previousPlayer && previousItem) {
      values.push(previousPlayer);
      clauses.push(`lower(player_name) = lower($${values.length})`);
      values.push(previousItem);
      clauses.push(`lower(item_name) = lower($${values.length})`);
      hasEntryLocator = true;
    }
  }

  if (!hasEntryLocator) {
    const error = new Error("PO-Eintrag konnte nicht eindeutig zugeordnet werden.");
    error.statusCode = 400;
    throw error;
  }

  if (correctedItemId && (!correctedItemSlot || !correctedItemBoss)) {
    const itemDetail = await query(
      `select slot, boss
       from items
       where lower(raid_type) = any($1)
         and item_id = $2
       limit 1`,
      [raidTypeSearchValues(raidKey), correctedItemId]
    );
    correctedItemSlot = correctedItemSlot || clean(itemDetail.rows[0]?.slot);
    correctedItemBoss = correctedItemBoss || clean(itemDetail.rows[0]?.boss);
  }

  values.push(correctedItemId, correctedItemSlot, correctedItemBoss);
  const itemIdParam = values.length - 2;
  const itemSlotParam = values.length - 1;
  const itemBossParam = values.length;

  const result = await query(
    `update po_post_entries
     set player_name = $2,
         item_name = $3,
         class_name = $4,
         raid = coalesce(nullif($5, ''), raid),
         raid_pin = coalesce(nullif($6, ''), raid_pin),
         item_game_id = $${itemIdParam},
         item_slot = $${itemSlotParam},
         item_boss = $${itemBossParam},
         updated_at = now()
     where ${clauses.join(" and ")}
     returning *`,
    values
  );
  const row = result.rows[0];
  if (!row) {
    const error = new Error("PO-Eintrag wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  let prioSync = null;
  const rowRaidPin = row.raid_pin || raidPin;
  if (row.approval_status === "approved" && rowRaidPin) {
    try {
      prioSync = await savePoSignupPrioFromBot({
        guildId,
        query: {
          ...params,
          raidPin: rowRaidPin,
          prioPin: rowRaidPin,
          playerPin: character.player_pin,
          spielerLogin: character.player_pin,
          player: row.player_name,
          char: row.player_name,
          item: row.item_name,
          itemName: row.item_name,
          itemId: row.item_game_id,
          itemSlot: row.item_slot,
          itemBoss: row.item_boss,
          server: character.server || clean(params.server || "Everlook"),
          className: row.class_name,
          masterCode: params.masterCode
        }
      });
    } catch (error) {
      prioSync = { success: false, error: error.message || String(error) };
    }
  }

  await enqueueBotUpdate({
    guildId,
    type: "po_post",
    payload: {
      postKey: row.post_key,
      sourceChannelId: row.source_channel_id,
      targetChannelId: row.target_channel_id,
      messageId: row.discord_message_id || discordMessageId,
      discordMessageId: row.discord_message_id || discordMessageId,
      raid: row.raid,
      raidPin: rowRaidPin,
      prioPin: rowRaidPin,
      lichtlootRaidId: rowRaidPin,
      lichtlootPlayerPin: rowRaidPin,
      title: row.title,
      mode: clean(params.mode || params.poMode) || "signup",
      source: "po_correction",
      queuedAt: new Date().toISOString()
    }
  }).catch(error => console.warn("PO-Post konnte nach Korrektur nicht queued werden:", error.message || error));

  return {
    success: true,
    prioSync,
    entry: {
      id: row.id || "",
      postKey: row.post_key || "",
      sourceChannelId: row.source_channel_id || "",
      targetChannelId: row.target_channel_id || "",
      raid: row.raid || "",
      title: row.title || "PO Liste",
      raidPin: rowRaidPin || "",
      prioPin: rowRaidPin || "",
      lichtlootRaidId: rowRaidPin || "",
      lichtlootPlayerPin: rowRaidPin || "",
      player: row.player_name || "",
      className: row.class_name || "",
      Klasse: row.class_name || "",
      item: normalizePoItemName(row.item_name || ""),
      messageId: row.po_message_id || "",
      discordMessageId: row.discord_message_id || "",
      approvalStatus: row.approval_status || "pending",
      approved: row.approval_status === "approved",
      approvedBy: row.approved_by || "",
      approvedAt: row.approved_at || "",
      rejectionReason: row.rejection_reason || ""
    }
  };
}

async function deletePoPostEntry({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensurePoPostEntriesSchema();
  const postKey = clean(params.postKey || params.poPostKey || "");
  const sourceChannelId = clean(params.sourceChannelId || "");
  const targetChannelId = clean(params.targetChannelId || "");
  const discordUserId = clean(params.discordUserId || params.userId);
  const itemName = normalizePoItemName(params.item || params.itemName);
  const playerName = clean(params.player || params.char || params.spieler);
  const playerPin = normalizePin(params.playerPin || params.pin || params.spielerLogin);
  const server = clean(params.server);

  if (!discordUserId && !playerName) {
    const error = new Error("Discord-User oder Spieler fehlt.");
    error.statusCode = 400;
    throw error;
  }
  if (!itemName) {
    const error = new Error("Item fehlt.");
    error.statusCode = 400;
    throw error;
  }
  if (playerPin && playerName) {
    const character = await findCharacterForPin(guildId, playerPin, playerName, server);
    if (!character) {
      const error = new Error("Spielerlogin passt nicht zu diesem Charakter.");
      error.statusCode = 403;
      throw error;
    }
  }

  const values = [guildId];
  const clauses = ["guild_id = $1", "archived_at is null"];
  if (playerName) {
    values.push(playerName);
    clauses.push(`regexp_replace(lower(player_name), '[^a-z0-9]+', '', 'g') = regexp_replace(lower($${values.length}), '[^a-z0-9]+', '', 'g')`);
  } else if (discordUserId) {
    values.push(discordUserId);
    clauses.push(`discord_user_id = $${values.length}`);
  }
  if (postKey) {
    values.push(postKey);
    clauses.push(`post_key = $${values.length}`);
  }
  if (sourceChannelId) {
    values.push(sourceChannelId);
    clauses.push(`source_channel_id = $${values.length}`);
  }
  if (targetChannelId) {
    values.push(targetChannelId);
    clauses.push(`target_channel_id = $${values.length}`);
  }
  if (itemName) {
    const itemClauses = [];
    for (const variant of poItemAliasVariants(itemName)) {
      values.push(variant);
      itemClauses.push(`regexp_replace(lower(item_name), '[^a-z0-9]+', '', 'g') = regexp_replace(lower($${values.length}), '[^a-z0-9]+', '', 'g')`);
    }
    clauses.push(`(${itemClauses.join(" or ")})`);
  }

  const result = await query(
    `delete from po_post_entries
     where ${clauses.join(" and ")}
     returning *`,
    values
  );

  const payloads = new Map();
  let deletedPrios = 0;
  const prioDeleteResults = [];
  for (const row of result.rows || []) {
    const prioDelete = await deletePoSignupPrioForEntry(guildId, row, params).catch(error => ({
      success: false,
      deleted: 0,
      error: error.message || String(error)
    }));
    deletedPrios += Number(prioDelete.deleted || 0);
    prioDeleteResults.push(prioDelete);
    const key = [row.post_key, row.source_channel_id, row.target_channel_id].join("|");
    payloads.set(key, {
      postKey: row.post_key || postKey,
      sourceChannelId: row.source_channel_id || sourceChannelId,
      targetChannelId: row.target_channel_id || targetChannelId || row.source_channel_id || sourceChannelId,
      messageId: row.discord_message_id || clean(params.discordMessageId || ""),
      discordMessageId: row.discord_message_id || clean(params.discordMessageId || ""),
      raid: row.raid || "",
      raidPin: row.raid_pin || clean(params.raidPin || params.prioPin || ""),
      prioPin: row.raid_pin || clean(params.raidPin || params.prioPin || ""),
      title: row.title || "PO Liste",
      source: "po_entry_delete",
      queuedAt: new Date().toISOString()
    });
  }
  for (const payload of payloads.values()) {
    await enqueueBotUpdate({ guildId, type: "po_post", payload })
      .catch(error => console.warn("PO-Post konnte nach Eintrag-Löschung nicht queued werden:", error.message || error));
  }

  return {
    success: true,
    deleted: result.rowCount || 0,
    deletedPrios,
    prioDeleteResults,
    queued: payloads.size,
    entries: result.rows.map(row => ({
      postKey: row.post_key || "",
      sourceChannelId: row.source_channel_id || "",
      targetChannelId: row.target_channel_id || "",
      raid: row.raid || "",
      title: row.title || "PO Liste",
      player: row.player_name || "",
      item: normalizePoItemName(row.item_name || ""),
      messageId: row.po_message_id || "",
      discordMessageId: row.discord_message_id || ""
    }))
  };
}

async function setPoPostEntryLuck({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensurePoPostEntriesSchema();
  const postKey = clean(params.postKey || params.poPostKey || "");
  const sourceChannelId = clean(params.sourceChannelId || "");
  const targetChannelId = clean(params.targetChannelId || "");
  const playerName = clean(params.player || params.char || params.spieler);
  const itemName = normalizePoItemName(params.item || params.itemName);
  const luckBy = clean(params.luckBy || params.discordName || params.userName || "");
  const luckByDiscordId = clean(params.luckByDiscordId || params.discordUserId || params.userId || "");

  if (!postKey || !sourceChannelId || !targetChannelId || !playerName || !itemName) {
    const error = new Error("PO-Eintrag für Kleeblatt fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const result = await query(
    `update po_post_entries
     set luck_by = $6,
         luck_by_discord_id = $7,
         luck_at = now(),
         updated_at = now()
     where guild_id = $1
       and post_key = $2
       and source_channel_id = $3
       and target_channel_id = $4
       and regexp_replace(lower(player_name), '[^a-z0-9]+', '', 'g') = regexp_replace(lower($5), '[^a-z0-9]+', '', 'g')
       and regexp_replace(lower(item_name), '[^a-z0-9]+', '', 'g') = regexp_replace(lower($8), '[^a-z0-9]+', '', 'g')
       and archived_at is null
     returning *`,
    [guildId, postKey, sourceChannelId, targetChannelId, playerName, luckBy, luckByDiscordId, itemName]
  );
  const row = result.rows[0];
  if (!row) {
    const error = new Error("PO-Eintrag wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }
  await enqueueBotUpdate({
    guildId,
    type: "po_post",
    payload: {
      postKey: row.post_key,
      sourceChannelId: row.source_channel_id,
      targetChannelId: row.target_channel_id,
      messageId: row.discord_message_id || clean(params.discordMessageId || ""),
      discordMessageId: row.discord_message_id || clean(params.discordMessageId || ""),
      raid: row.raid,
      title: row.title,
      source: "po_luck",
      queuedAt: new Date().toISOString()
    }
  }).catch(error => console.warn("PO-Post konnte nach Kleeblatt nicht queued werden:", error.message || error));
  return {
    success: true,
    entry: {
      postKey: row.post_key || "",
      sourceChannelId: row.source_channel_id || "",
      targetChannelId: row.target_channel_id || "",
      raid: row.raid || "",
      title: row.title || "PO Liste",
      player: row.player_name || "",
      item: normalizePoItemName(row.item_name || ""),
      messageId: row.po_message_id || "",
      discordMessageId: row.discord_message_id || "",
      luckBy: row.luck_by || "",
      luckByDiscordId: row.luck_by_discord_id || "",
      luckAt: row.luck_at || ""
    }
  };
}

async function deletePoPost({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensurePoPostEntriesSchema();
  const postKey = clean(params.postKey || params.poPostKey || params.postId || "");
  const sourceChannelId = clean(params.sourceChannelId || "");
  const targetChannelId = clean(params.targetChannelId || "");

  if (!postKey) {
    const error = new Error("Post-ID fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const values = [guildId, postKey];
  const clauses = ["guild_id = $1", "post_key = $2", "archived_at is null"];
  if (sourceChannelId) {
    values.push(sourceChannelId);
    clauses.push(`source_channel_id = $${values.length}`);
  }
  if (targetChannelId) {
    values.push(targetChannelId);
    clauses.push(`target_channel_id = $${values.length}`);
  }

  const result = await query(
    `update po_post_entries
     set archived_at = now(), updated_at = now()
     where ${clauses.join(" and ")}
     returning post_key, source_channel_id, target_channel_id, discord_message_id, title, raid, raid_pin, raid_date, raid_time, mode, item_game_id`,
    values
  );

  const payloads = new Map();
  for (const row of result.rows || []) {
    const key = [
      row.post_key || postKey,
      row.source_channel_id || sourceChannelId,
      row.target_channel_id || targetChannelId,
      row.discord_message_id || ""
    ].join("|");
    payloads.set(key, {
      postKey: row.post_key || postKey,
      sourceChannelId: row.source_channel_id || sourceChannelId,
      targetChannelId: row.target_channel_id || targetChannelId || row.source_channel_id || sourceChannelId,
      messageId: row.discord_message_id || "",
      title: row.title || "PO Liste",
      raid: row.raid || "",
      source: "gildenleitung"
    });
  }
  if (!payloads.size) {
    payloads.set(postKey, {
      postKey,
      sourceChannelId,
      targetChannelId: targetChannelId || sourceChannelId,
      messageId: "",
      title: clean(params.title) || "PO Liste",
      raid: clean(params.raid || params.raidName),
      source: "gildenleitung"
    });
  }

  for (const payload of payloads.values()) {
    await enqueueBotUpdate({ guildId, type: "po_post_delete", payload });
  }

  return {
    success: true,
    deleted: result.rowCount || 0,
    queued: payloads.size,
    postKey
  };
}

async function restorePoPost({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  await ensurePoPostEntriesSchema();
  const postKey = clean(params.postKey || params.poPostKey || params.postId || "");
  const sourceChannelId = clean(params.sourceChannelId || "");
  const targetChannelId = clean(params.targetChannelId || "");

  if (!postKey) {
    const error = new Error("Post-ID fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const values = [guildId, postKey];
  const clauses = ["guild_id = $1", "post_key = $2", "archived_at is not null"];
  if (sourceChannelId) {
    values.push(sourceChannelId);
    clauses.push(`source_channel_id = $${values.length}`);
  }
  if (targetChannelId) {
    values.push(targetChannelId);
    clauses.push(`target_channel_id = $${values.length}`);
  }

  const result = await query(
    `update po_post_entries
     set archived_at = null, updated_at = now()
     where ${clauses.join(" and ")}
     returning post_key, source_channel_id, target_channel_id, discord_message_id, title, raid`,
    values
  );

  const payloads = new Map();
  for (const row of result.rows || []) {
    const key = [
      row.post_key || postKey,
      row.source_channel_id || sourceChannelId,
      row.target_channel_id || targetChannelId,
      row.discord_message_id || ""
    ].join("|");
    payloads.set(key, {
      postKey: row.post_key || postKey,
      sourceChannelId: row.source_channel_id || sourceChannelId,
      targetChannelId: row.target_channel_id || targetChannelId || row.source_channel_id || sourceChannelId,
      messageId: row.discord_message_id || "",
      discordMessageId: row.discord_message_id || "",
      title: row.title || "PO Liste",
      raid: row.raid || "",
      raidPin: row.raid_pin || "",
      prioPin: row.raid_pin || "",
      lichtlootRaidId: row.raid_pin || "",
      lichtlootPlayerPin: row.raid_pin || "",
      raidDate: row.raid_date || "",
      raidTime: row.raid_time || "",
      mode: row.mode || "signup",
      source: "gildenleitung_restore"
    });
  }

  for (const payload of payloads.values()) {
    await enqueueBotUpdate({ guildId, type: "po_post", payload });
  }

  return {
    success: true,
    restored: result.rowCount || 0,
    queued: payloads.size,
    postKey
  };
}

async function savePoPostEntry({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensurePoPostEntriesSchema();
  const postKey = clean(params.postKey || params.poPostKey || "");
  const sourceChannelId = clean(params.sourceChannelId || "");
  const targetChannelId = clean(params.targetChannelId || "");
  const raidKey = normalizeRaidType(params.raid || params.raidName).toUpperCase();
  const title = clean(params.title) || "PO Liste";
  const player = clean(params.player || params.char || params.spieler);
  const server = clean(params.server);
  const playerPin = normalizePin(params.playerPin || params.pin || params.spielerLogin);
  const raidPin = clean(params.raidPin || params.prioPin || params.lichtlootPlayerPin || params.lichtlootRaidId || params.playerLinkPin);
  const itemName = normalizePoItemName(params.item || params.itemName);
  const itemGameId = clean(params.itemId || params.itemGameId || params.item_id);
  let itemSlot = clean(params.itemSlot || params.slot);
  let itemBoss = clean(params.itemBoss || params.boss);
  const discordUserId = clean(params.discordUserId || params.userId);
  const discordName = clean(params.discordName || params.userName);
  const className = clean(params.className || params.class || params.klasse);

  if (!postKey || !sourceChannelId || !targetChannelId) {
    const error = new Error("PO-Post-Konfiguration fehlt.");
    error.statusCode = 400;
    throw error;
  }
  if (!player || !playerPin || !itemName || !discordUserId) {
    const error = new Error("Charakter, SpielerLogin, Item oder Discord-User fehlt.");
    error.statusCode = 400;
    throw error;
  }

  await ensureCrossGuildPlayerLogin(guildId, playerPin);
  const character = await findCharacterForPin(guildId, playerPin, player, server);
  if (!character) {
    const error = new Error("SpielerLogin passt nicht zu diesem Charakter.");
    error.statusCode = 403;
    throw error;
  }
  if (normalizePlayerApprovalStatus(character.approval_status) !== "approved") {
    const error = new Error("Dieser SpielerLogin wartet noch auf Freigabe durch die Gildenleitung.");
    error.statusCode = 403;
    throw error;
  }

  const releaseRaid = normalizePoReleaseRaid(raidKey);
  if (releaseRaid) {
    const release = await checkCharacterPoRelease({
      guildId,
      query: {
        ...params,
        raid: releaseRaid,
        playerPin,
        player: character.name,
        server: character.server
      }
    });
    if (!release.allowed) {
      const error = new Error(
        `Dieser Charakter hat für ${releaseRaid.toUpperCase()} keine PO-Freigabe bei dieser Gilde.`
      );
      error.statusCode = 403;
      throw error;
    }
  }

  const client = await pool.connect();
  try {
    await client.query("begin");
    if (itemGameId && (!itemSlot || !itemBoss)) {
      const itemDetail = await client.query(
        `select slot, boss
         from items
         where lower(raid_type) = any($1)
           and item_id = $2
         limit 1`,
        [raidTypeSearchValues(raidKey), itemGameId]
      );
      itemSlot = itemSlot || clean(itemDetail.rows[0]?.slot);
      itemBoss = itemBoss || clean(itemDetail.rows[0]?.boss);
    }
    await client.query(
      `insert into discord_player_links (guild_id, discord_user_id, character_id, discord_name, source)
       values ($1, $2, $3, $4, 'discord-po')
       on conflict (guild_id, discord_user_id, character_id) do update
         set discord_name = coalesce(nullif(excluded.discord_name, ''), discord_player_links.discord_name),
             updated_at = now()`,
      [guildId, discordUserId, character.id, discordName]
    );
    const existingEntries = await client.query(
      `select *
       from po_post_entries
       where guild_id = $1
         and post_key = $2
         and source_channel_id = $3
         and target_channel_id = $4
         and (
           discord_user_id = $5
           or regexp_replace(lower(player_name), '[^a-z0-9]+', '', 'g') = regexp_replace(lower($6), '[^a-z0-9]+', '', 'g')
         )
         and archived_at is null
       order by updated_at desc, po_created_at desc nulls last`,
      [guildId, postKey, sourceChannelId, targetChannelId, discordUserId, character.name]
    );
    const existingEntry = existingEntries.rows[0] || null;
    const duplicateIds = existingEntries.rows.slice(1).map(row => row.id).filter(Boolean);
    if (duplicateIds.length) {
      await client.query(
        `update po_post_entries
         set archived_at = now(), updated_at = now()
         where id = any($1::uuid[])`,
        [duplicateIds]
      );
    }

    const result = existingEntry
      ? await client.query(
          `update po_post_entries
           set discord_message_id = $2,
               raid = $3,
               title = $4,
               player_name = $5,
               item_name = $6,
               discord_user_id = $7,
               discord_name = $8,
               class_name = $9,
               po_created_at = now(),
               approval_status = 'pending',
               approved_by = '',
               approved_at = null,
               raid_pin = $10,
               item_game_id = $11,
               item_slot = $12,
               item_boss = $13,
               updated_at = now()
           where id = $1
           returning *`,
          [
            existingEntry.id,
            clean(params.discordMessageId || params.messageId),
            raidKey,
            title,
            character.name,
            itemName,
            discordUserId,
            discordName,
            className || character.class_name || "",
            raidPin,
            itemGameId,
            itemSlot,
            itemBoss
          ]
        )
      : await client.query(
          `insert into po_post_entries (
             guild_id, post_key, source_channel_id, target_channel_id, discord_message_id,
             raid, title, player_name, item_name, discord_user_id, discord_name, class_name,
             po_message_id, po_created_at, approval_status, approved_by, approved_at, raid_pin,
             item_game_id, item_slot, item_boss
           )
           values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'',now(),'pending','',null,$13,$14,$15,$16)
           returning *`,
          [
            guildId,
            postKey,
            sourceChannelId,
            targetChannelId,
            clean(params.discordMessageId || params.messageId),
            raidKey,
            title,
            character.name,
            itemName,
            discordUserId,
            discordName,
            className || character.class_name || "",
            raidPin,
            itemGameId,
            itemSlot,
            itemBoss
          ]
        );
    await client.query("commit");
    const row = result.rows[0];
    const poNotificationKey = `notify_po_releases:${clean(raidKey).toLowerCase()}`;
    const notificationTargets = await notificationTargetsForPermissions(guildId, poNotificationKey).catch(() => []);
    if (notificationTargets.length) {
      const messageTemplate =
        (await notificationMessageTemplate(guildId, poNotificationKey).catch(() => "")) ||
        (await notificationMessageTemplate(guildId, "notify_po_releases").catch(() => ""));
      await enqueueBotUpdate({
        guildId,
        type: "po_release_request_notice",
        payload: {
          targets: notificationTargets,
          messageTemplate,
          character: row.player_name || character.name || "",
          server: character.server || server || "",
          className: row.class_name || character.class_name || "",
          requestType: "po",
          raid: raidKey,
          requestId: row.id,
          postKey: row.post_key || postKey,
          item: row.item_name || itemName
        }
      }).catch(error => console.warn("PO-Freigabehinweis konnte nicht queued werden:", error.message || error));
    }
    return {
      success: true,
      entry: {
        postKey: row.post_key || "",
        sourceChannelId: row.source_channel_id || "",
        targetChannelId: row.target_channel_id || "",
        raid: row.raid || "",
        title: row.title || "PO Liste",
        raidPin: row.raid_pin || "",
        prioPin: row.raid_pin || "",
        lichtlootRaidId: row.raid_pin || "",
        lichtlootPlayerPin: row.raid_pin || "",
        player: row.player_name || "",
        className: row.class_name || "",
        Klasse: row.class_name || "",
        item: normalizePoItemName(row.item_name || ""),
        itemId: row.item_game_id || "",
        itemSlot: row.item_slot || "",
        itemBoss: row.item_boss || "",
        discordUserId: row.discord_user_id || "",
        discordName: row.discord_name || "",
        approvalStatus: row.approval_status || "pending",
        createdAt: row.po_created_at || row.updated_at || "",
        poCreatedAt: row.po_created_at || "",
        updatedAt: row.updated_at || ""
      }
    };
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function syncPoPostEntryFromPrio(client, guildId, { raid, character, item, source = "lichtloot_prio_saved" }) {
  const raidPin = clean(raid?.raid_pin || raid?.player_link || "");
  if (!raidPin || !character?.id || !item?.id) return [];

  const configsResult = await client.query(
    `select distinct on (post_key, source_channel_id, target_channel_id)
       post_key, source_channel_id, target_channel_id, raid, title, raid_pin, discord_message_id
     from po_post_entries
     where guild_id = $1
       and raid_pin = $2
       and archived_at is null
     order by post_key, source_channel_id, target_channel_id, updated_at desc`,
    [guildId, raidPin]
  );

  const payloads = [];
  const markApproved = clean(source).toLowerCase() !== "po_bot_prio_saved";
  for (const config of configsResult.rows) {
    const existingResult = await client.query(
      `select *
       from po_post_entries
       where guild_id = $1
         and post_key = $2
         and source_channel_id = $3
         and target_channel_id = $4
         and regexp_replace(lower(player_name), '[^a-z0-9]+', '', 'g') = regexp_replace(lower($5), '[^a-z0-9]+', '', 'g')
         and archived_at is null
       order by updated_at desc, po_created_at desc nulls last`,
      [guildId, config.post_key, config.source_channel_id, config.target_channel_id, character.name]
    );

    const keep = existingResult.rows[0] || null;
    const duplicateIds = existingResult.rows.slice(1).map(row => row.id).filter(Boolean);
    if (duplicateIds.length) {
      await client.query(
        `update po_post_entries
         set archived_at = now(), updated_at = now()
         where id = any($1::uuid[])`,
        [duplicateIds]
      );
    }

    if (keep) {
      await client.query(
        `update po_post_entries
         set player_name = $2,
             item_name = $3,
             class_name = $4,
             raid = coalesce(nullif($5, ''), raid),
             raid_pin = $6,
             item_game_id = $7,
             item_slot = $8,
             item_boss = $9,
             approval_status = case when $11 then 'approved' else approval_status end,
             approved_by = case when $11 then coalesce(nullif(approved_by, ''), $10) else approved_by end,
             approved_at = case when $11 then coalesce(approved_at, now()) else approved_at end,
             updated_at = now()
         where id = $1`,
        [
          keep.id,
          character.name,
          item.name,
          character.class_name || "",
          normalizeRaidType(raid?.raid_type || config.raid).toUpperCase(),
          raidPin,
          clean(item.item_id),
          clean(item.slot),
          clean(item.boss),
          "LichtLoot",
          markApproved
        ]
      );
    } else {
      await client.query(
        `insert into po_post_entries (
           guild_id, post_key, source_channel_id, target_channel_id, discord_message_id,
           raid, title, player_name, item_name, discord_user_id, discord_name, class_name,
           po_message_id, po_created_at, approval_status, approved_by, approved_at, raid_pin,
           item_game_id, item_slot, item_boss
         )
         values ($1,$2,$3,$4,$5,$6,$7,$8,$9,'','LichtLoot',$10,'',now(),$15,$16,$17,$11,$12,$13,$14)`,
        [
          guildId,
          config.post_key,
          config.source_channel_id,
          config.target_channel_id,
          clean(config.discord_message_id),
          normalizeRaidType(raid?.raid_type || config.raid).toUpperCase(),
          config.title || "PO Liste",
          character.name,
          item.name,
          character.class_name || "",
          raidPin,
          clean(item.item_id),
          clean(item.slot),
          clean(item.boss),
          markApproved ? "approved" : "pending",
          markApproved ? "LichtLoot" : "",
          markApproved ? new Date().toISOString() : null
        ]
      );
    }

    payloads.push({
      postKey: config.post_key,
      sourceChannelId: config.source_channel_id,
      targetChannelId: config.target_channel_id,
      messageId: clean(config.discord_message_id),
      discordMessageId: clean(config.discord_message_id),
      raid: normalizeRaidType(raid?.raid_type || config.raid).toUpperCase(),
      raidPin,
      prioPin: raidPin,
      lichtlootRaidId: raidPin,
      lichtlootPlayerPin: raidPin,
      title: config.title || "PO Liste",
      mode: "signup",
      source,
      queuedAt: new Date().toISOString()
    });
  }

  return payloads;
}

async function enqueuePoPostRefreshPayloads(guildId, payloads, source) {
  const queued = [];
  for (const payload of payloads || []) {
    const result = await enqueueBotUpdate({
      guildId,
      type: "po_post",
      payload: {
        ...payload,
        source: payload.source || source || "po_post_refresh"
      }
    }).catch(error => ({ success: false, error: error.message || String(error), payload }));
    queued.push(result);
  }
  return {
    success: queued.every(result => result && result.success),
    queued: queued.filter(result => result && result.success && !result.skipped).length,
    skipped: queued.filter(result => result && result.skipped).length,
    results: queued
  };
}

async function archivePoPostEntriesForRaid(client, guildId, raidType) {
  await ensurePoPostEntriesSchema();
  const raidKey = normalizeRaidType(raidType).toLowerCase();
  if (!raidKey) return 0;
  const result = await client.query(
    `update po_post_entries
     set archived_at = now(),
         updated_at = now()
     where guild_id = $1
       and lower(raid) = $2
       and archived_at is null`,
    [guildId, raidKey]
  );
  return result.rowCount || 0;
}

async function setRaidDiscordMessage({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  const raid = await findRaid(guildId, params);
  if (!raid) {
    const error = new Error("Raid wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }
  const result = await query(
    `update raids
     set discord_channel_id = coalesce(nullif($3, ''), discord_channel_id),
         discord_message_id = coalesce(nullif($4, ''), discord_message_id),
         updated_at = now()
     where guild_id = $1 and id = $2
     returning *`,
    [
      guildId,
      raid.id,
      clean(params.discordChannelId || params.channelId),
      clean(params.discordMessageId || params.messageId || params.raidHelperMessageId)
    ]
  );
  return { success: true, raid: normalizeRaidRow(result.rows[0]) };
}

async function queueLogAnalysisDiscordPost({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  await ensureLogAnalysesTable();

  const id = clean(params.id || params.analysisId);
  const type = clean(params.type || params.analysisType).toLowerCase();
  if (!isUuid(id) || !["cla", "rpb"].includes(type)) {
    const error = new Error("Loganalyse-ID oder Typ fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const result = await query(
    `select *
     from log_analyses
     where guild_id = $1 and id = $2
     limit 1`,
    [guildId, id]
  );
  if (!result.rows.length) {
    const error = new Error("Loganalyse wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const analysis = normalizeLogAnalysis(result.rows[0]);
  const raid = normalizeLogRaidType(analysis.raid || analysis.summary?.raid || analysis.title || "");
  const channelId = await resolveLogAnalysisPostChannelId(guildId, raid);
  if (!channelId) {
    const error = new Error("Für diesen Raid ist kein Log-Post-Channel hinterlegt.");
    error.statusCode = 400;
    throw error;
  }

  const sheetUrl = type === "cla"
    ? clean(analysis.claDownloadUrl || analysis.summary?.claDownloadUrl)
    : clean(analysis.rpbDownloadUrl || analysis.summary?.rpbDownloadUrl);
  if (!/^https:\/\/docs\.google\.com\/spreadsheets\/d\//i.test(sheetUrl)) {
    const error = new Error(`${type.toUpperCase()} ist noch nicht fertig.`);
    error.statusCode = 400;
    throw error;
  }

  const queued = await enqueueBotUpdate({
    guildId,
    type: "log_analysis_post",
    payload: {
      analysisId: analysis.id,
      analysisType: type,
      raid,
      raidDate: analysis.raidDate || analysis.summary?.raidDate || "",
      reportCode: analysis.reportCode || "",
      reportUrl: analysis.reportUrl || "",
      sheetUrl,
      channelId
    }
  });

  return {
    ...queued,
    success: true,
    channelId
  };
}

async function resolveBotQueue({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  const rowNumber = clean(params.rowNumber);
  if (!isUuid(rowNumber)) return { success: true };
  await query(
    `update bot_update_queue
     set status = 'done', resolved_at = now()
     where guild_id = $1 and id = $2`,
    [guildId, rowNumber]
  );
  return { success: true };
}

async function claimBotQueue({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  const rowNumber = clean(params.rowNumber);
  if (!isUuid(rowNumber)) return { success: false, claimed: false };
  await query(`alter table bot_update_queue add column if not exists claimed_at timestamptz`);
  const result = await query(
    `update bot_update_queue
     set status = 'processing', claimed_at = now()
     where guild_id = $1
       and id = $2
       and (
         status = 'open'
         or (status = 'processing' and claimed_at < now() - interval '5 minutes')
       )
     returning id`,
    [guildId, rowNumber]
  );
  return { success: true, claimed: result.rowCount === 1 };
}

async function findCharacterForPin(guildId, pin, charName, server) {
  const normalizedPin = normalizePin(pin);
  const characterName = clean(charName);
  const result = await query(
    `select c.id, c.name, c.server, c.class_name, c.created_at,
            c.recruit_status_lifted, c.recruit_status_lifted_at, c.recruit_status_lifted_by,
            p.id as player_id, p.player_pin, p.approval_status, p.is_blocked
     from players p
     join characters c on c.player_id = p.id
     where p.guild_id = $1
       and p.player_pin = $2
       and coalesce(p.is_blocked, false) = false
       and lower(c.name) = lower($3)
     order by
       case when lower(c.server) = lower($4) then 0 else 1 end,
       c.created_at asc
     limit 1`,
    [guildId, normalizedPin, characterName, clean(server)]
  );
  return result.rows[0] || null;
}

async function upsertItem(client, raidType, itemName, itemGameId = "") {
  const name = clean(itemName);
  const itemId = clean(itemGameId);
  const itemRaidType = normalizeRaidType(raidType);
  const sourceRaidType = lootSourceRaidType(itemRaidType);
  if (!name || name === "-") return null;

  if (itemId) {
    const existingById = await client.query(
      `select *
       from items
       where lower(raid_type) = any($1)
         and item_id = $2
       order by created_at asc
       limit 1`,
      [raidTypeSearchValues(itemRaidType), itemId]
    );
    if (existingById.rows.length) return existingById.rows[0];
    const sourceById = await client.query(
      `select *
       from items
       where lower(raid_type) = any($1)
         and item_id = $2
       order by created_at asc
       limit 1`,
      [raidTypeSearchValues(sourceRaidType), itemId]
    );
    return upsertLootItemRecord(client, {
      ...(sourceById.rows[0] || {}),
      raid: itemRaidType,
      raid_type: itemRaidType,
      name,
      itemId
    });
  }

  const existing = await client.query(
    `select *
     from items
     where lower(raid_type) = any($1)
       and lower(name) = lower($2)
     order by
       case when item_id is null then 1 else 0 end,
       created_at asc
     limit 1`,
    [raidTypeSearchValues(itemRaidType), name]
  );
  if (existing.rows.length) return existing.rows[0];

  const sourceItem = await findExistingItemByLookupName(client, sourceRaidType, name);
  if (sourceItem) {
    const sourceDetails = await client.query(`select * from items where id = $1 limit 1`, [sourceItem.id]);
    return upsertLootItemRecord(client, {
      ...(sourceDetails.rows[0] || sourceItem),
      raid: itemRaidType,
      raid_type: itemRaidType,
      name
    });
  }

  const error = new Error(`Item "${name}" wurde nicht in der ${displayRaidName(raidType)}-Datenbank gefunden.`);
  error.statusCode = 400;
  throw error;
}

function normalizePrioCharacterKey(value) {
  return clean(value)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
}

async function removeDuplicatePriosForCharacterName(client, raidId, character) {
  const playerName = clean(character?.name);
  if (!raidId || !character?.id || !playerName) return 0;

  const targetKey = normalizePrioCharacterKey(playerName);
  if (!targetKey) return 0;

  const existing = await client.query(
    `select pr.id, c.name
     from prios pr
     join characters c on c.id = pr.character_id
     where pr.raid_id = $1
       and pr.character_id <> $2`,
    [raidId, character.id]
  );
  const duplicateIds = existing.rows
    .filter(row => normalizePrioCharacterKey(row.name) === targetKey)
    .map(row => row.id)
    .filter(Boolean);

  if (!duplicateIds.length) return 0;

  const deleted = await client.query(
    `delete from prios
     where id = any($1::uuid[])
     returning id`,
    [duplicateIds]
  );
  return deleted.rowCount || 0;
}

async function savePrio({ guildId, query: params }) {
  await ensurePoPostEntriesSchema();
  await ensurePrioSchema();
  // Schema work must finish before opening the save transaction. Running ALTER
  // statements through the pool while this transaction already holds raid locks
  // makes the request wait on itself until PostgreSQL cancels it.
  await ensureCharacterPoReleaseSchema();
  const pin = params.playerPin || params.characterPin || params.masterCharacterPin || params.pin;
  const player = params.player || params.char || params.spieler;
  const server = params.server;
  const character = await findCharacterForPin(guildId, pin, player, server);

  if (!character) {
    const error = new Error("Dieser Charakter gehört nicht zu diesem SpielerPin.");
    error.statusCode = 403;
    throw error;
  }

  const raidType = normalizeRaidType(params.raid || params.raidName);
  const incomingRaidName = clean(params.raidName);
  const defaultRaidName = displayRaidName(raidType);
  const raidName = incomingRaidName && incomingRaidName !== defaultRaidName ? incomingRaidName : "";
  const externalRaidId = clean(params.raidId || params.RaidID || params.raidID);
  const prioPin = clean(params.raidPin || params.prioPin || params.PrioPIN || params.playerLinkPin);
  const p0Plus = clean(params.p0Plus).toLowerCase();
  const client = await pool.connect();

  try {
    await client.query("begin");

    let raidResult;
    if (externalRaidId) {
      raidResult = await client.query(
        `update raids
         set name = coalesce(nullif($3, ''), name),
             raid_pin = coalesce(nullif($4, ''), raid_pin),
             raid_time = coalesce(nullif($5, ''), raid_time),
             guild_name = coalesce(nullif($6, ''), guild_name),
             p0plus_freigabe = coalesce(nullif($7, ''), p0plus_freigabe),
             updated_at = now()
         where guild_id = $1
           and (external_raid_id = $2 or id::text = $2)
         returning id, external_raid_id, name, raid_type, raid_date, raid_time, raid_pin, player_link, discord_channel_id, status`,
        [
          guildId,
          externalRaidId,
          raidName,
          prioPin || "",
          clean(params.raidTime || params.uhrzeit),
          clean(params.guild || params.gilde),
          clean(params.p0PlusFreigabe || params.p0PlusOverride)
        ]
      );
    }

    if ((!raidResult || !raidResult.rows.length) && prioPin) {
      raidResult = await client.query(
        `update raids
         set name = coalesce(nullif($3, ''), name),
             raid_pin = coalesce(nullif($4, ''), raid_pin),
             raid_time = coalesce(nullif($5, ''), raid_time),
             guild_name = coalesce(nullif($6, ''), guild_name),
             p0plus_freigabe = coalesce(nullif($7, ''), p0plus_freigabe),
             updated_at = now()
         where guild_id = $1
           and raid_pin = $2
           and lower(raid_type) = any($8)
         returning id, external_raid_id, name, raid_type, raid_date, raid_time, raid_pin, player_link, discord_channel_id, status`,
        [
          guildId,
          prioPin,
          raidName,
          prioPin || "",
          clean(params.raidTime || params.uhrzeit),
          clean(params.guild || params.gilde),
          clean(params.p0PlusFreigabe || params.p0PlusOverride),
          raidTypeSearchValues(raidType)
        ]
      );
    }

    if ((!raidResult || !raidResult.rows.length) && prioPin) {
      raidResult = await client.query(
        `update raids
         set name = coalesce(nullif($3, ''), name),
             raid_pin = coalesce(nullif($4, ''), raid_pin),
             raid_time = coalesce(nullif($5, ''), raid_time),
             guild_name = coalesce(nullif($6, ''), guild_name),
             p0plus_freigabe = coalesce(nullif($7, ''), p0plus_freigabe),
             updated_at = now()
         where guild_id = $1
           and raid_pin = $2
         returning id, external_raid_id, name, raid_type, raid_date, raid_time, raid_pin, player_link, discord_channel_id, status`,
        [
          guildId,
          prioPin,
          raidName,
          prioPin || "",
          clean(params.raidTime || params.uhrzeit),
          clean(params.guild || params.gilde),
          clean(params.p0PlusFreigabe || params.p0PlusOverride)
        ]
      );
    }

    if (!raidResult || !raidResult.rows.length) {
      const error = new Error("Raid oder Prio-PIN wurde nicht gefunden. Bitte nutze den aktuellen Raid-Link.");
      error.statusCode = 404;
      throw error;
    }

    const p0Selected = p0Plus === "ja" || p0Plus === "true";
    const releaseRaid = normalizePoReleaseRaid(raidResult.rows[0].raid_type || raidType);
    let nachtlootRecruitRestricted = false;
    if (isNachtlootRecruitRaid(releaseRaid)) {
      const recruitResult = await client.query(
        `select lower(g.slug) as guild_slug,
                exists(select 1 from character_recruit_releases crr where crr.guild_id=$1 and crr.character_id=$2 and crr.raid_type=$3) as recruit_status_lifted
         from guilds g
         join characters c on c.id = $2
         where g.id = $1
         limit 1`,
        [guildId, character.id, releaseRaid]
      );
      nachtlootRecruitRestricted = recruitResult.rows[0]?.guild_slug === "nachtloot"
        && !Boolean(recruitResult.rows[0]?.recruit_status_lifted);
    }
    if (nachtlootRecruitRestricted && p0Selected) {
      const error = new Error("Als Nachtwächter-Rekrut kannst du kein P0+ und keine P1 setzen. P1 wird automatisch mit Kaese belegt.");
      error.statusCode = 403;
      throw error;
    }
    if (p0Selected && releaseRaid) {
      const releaseResult = await client.query(
        `select 1
         from character_po_releases
         where guild_id = $1
           and character_id = $2
           and raid_type = $3
         limit 1`,
        [guildId, character.id, releaseRaid]
      );
      if (!releaseResult.rows[0]) {
        const error = new Error("Du hast keine P0+-Berechtigung für diesen Raid.");
        error.statusCode = 403;
        throw error;
      }
    }
    if (nachtlootRecruitRestricted && (!clean(params.p2) || !clean(params.p3))) {
      const error = new Error("Als Nachtwächter-Rekrut musst du P2 und P3 auswählen. P1 wird automatisch mit Kaese belegt.");
      error.statusCode = 400;
      throw error;
    }
    const p0ItemName = clean(params.p0Item || params.P0Item || params.p1 || params.p2 || params.p3);
    const p0ItemId = clean(params.p0ItemId || params.P0ItemId || params.p1ItemId || params.p1_item_id || params.p1ItemID);
    const p1 = await upsertItem(
      client,
      raidType,
      nachtlootRecruitRestricted ? "Kaese" : (p0Selected ? p0ItemName : params.p1),
      nachtlootRecruitRestricted ? "133993" : (p0Selected ? p0ItemId : (params.p1ItemId || params.p1_item_id || params.p1ItemID))
    );
    const p2 = await upsertItem(client, raidType, p0Selected ? p0ItemName : params.p2, p0Selected ? p0ItemId : (params.p2ItemId || params.p2_item_id || params.p2ItemID));
    const p3 = await upsertItem(client, raidType, p0Selected ? p0ItemName : params.p3, p0Selected ? p0ItemId : (params.p3ItemId || params.p3_item_id || params.p3ItemID));
    if (p0Selected) {
      await requireGuildPoItem(guildId, p1?.id || p0ItemId, p1?.name || p0ItemName);
    }
    await removeDuplicatePriosForCharacterName(client, raidResult.rows[0].id, character);
    const comment = JSON.stringify({
      p0Plus: p0Selected ? "ja" : "nein",
      p0Item: p0Selected ? (p1?.name || "") : "",
      raidTime: clean(params.raidTime || params.uhrzeit),
      source: "railway"
    });

    const prioResult = await client.query(
      `insert into prios (raid_id, character_id, p1_item_id, p2_item_id, p3_item_id, comment)
       values ($1, $2, $3, $4, $5, $6)
       on conflict (raid_id, character_id) do update
         set p1_item_id = excluded.p1_item_id,
             p2_item_id = excluded.p2_item_id,
             p3_item_id = excluded.p3_item_id,
             comment = excluded.comment,
             updated_at = now()
       returning id, created_at, updated_at`,
      [raidResult.rows[0].id, character.id, p1?.id || null, p2?.id || null, p3?.id || null, comment]
    );

    const savedRaid = raidResult.rows[0];
    const poPostRefreshPayloads = p0Selected && p1
      ? await syncPoPostEntryFromPrio(client, guildId, {
          raid: savedRaid,
          character,
          item: p1,
          source: "lichtloot_prio_saved"
        })
      : [];
    await client.query("commit");
    const p0PostRefresh = await enqueueP0PostRefreshForRaid(guildId, savedRaid, "lichtloot_prio_saved")
      .catch(error => ({ success: false, error: error.message || String(error) }));
    const poPostRefresh = await enqueuePoPostRefreshPayloads(guildId, poPostRefreshPayloads, "lichtloot_prio_saved");
    return {
      success: true,
      characterPin: normalizePin(pin),
      playerPin: normalizePin(pin),
      tempPin: normalizePin(pin),
      prioId: prioResult.rows[0].id,
      raidId: savedRaid.external_raid_id || savedRaid.id,
      p0PostRefreshQueued: Boolean(p0PostRefresh && p0PostRefresh.success && !p0PostRefresh.skipped),
      p0PostRefresh,
      poPostRefresh
    };
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function findOrCreateRaidleadCharacter(client, guildId, params) {
  const player = clean(params.player || params.char || params.spieler);
  const server = clean(params.server) || "Everlook";
  const className = clean(params.className || params.class || params.klasse);

  if (!player || !server || !className) {
    const error = new Error("Spieler, Server oder Klasse fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const existing = await client.query(
    `select c.id, c.name, c.server, c.class_name, c.created_at, p.player_pin
     from characters c
     join players p on p.id = c.player_id
     where p.guild_id = $1
       and lower(c.name) = lower($2)
       and lower(c.server) = lower($3)
     order by c.created_at asc
     limit 1`,
    [guildId, player, server]
  );

  if (existing.rows.length) {
    const character = existing.rows[0];
    if (className && clean(character.class_name).toLowerCase() !== className.toLowerCase()) {
      const updated = await client.query(
        `update characters
         set class_name = $1, updated_at = now()
         where id = $2
         returning id, name, server, class_name, created_at`,
        [className, character.id]
      );
      return updated.rows[0];
    }
    return character;
  }

  let createdPlayer = null;
  for (let attempt = 0; attempt < 5 && !createdPlayer; attempt++) {
    const generatedPin = normalizePin(
      "RL" +
      Date.now().toString(36) +
      Math.random().toString(36).slice(2, 8)
    );

    const playerResult = await client.query(
      `insert into players (guild_id, player_pin, security_question, security_answer)
       values ($1, $2, $3, $4)
       on conflict (guild_id, player_pin) do nothing
       returning id, player_pin`,
      [guildId, generatedPin, "Raidlead-Eintrag", "Raidlead-Eintrag"]
    );
    createdPlayer = playerResult.rows[0] || null;
  }

  if (!createdPlayer) {
    const error = new Error("Interner SpielerLogin konnte nicht erzeugt werden.");
    error.statusCode = 500;
    throw error;
  }

  const characterResult = await client.query(
    `insert into characters (player_id, name, server, class_name, is_main)
     values ($1, $2, $3, $4, true)
     returning id, name, server, class_name, created_at`,
    [createdPlayer.id, player, server, className]
  );

  return characterResult.rows[0];
}

async function savePrioAsRaidlead({ guildId, query: params }) {
  await ensurePoPostEntriesSchema();
  await ensurePrioSchema();
  const raid = await findRaid(guildId, params);
  if (!raid) {
    const error = new Error("Raid wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const leadPin = clean(params.leadPin || params.raidleadPin);
  if (!leadPin || !raid.lead_pin || leadPin !== raid.lead_pin) {
    const error = new Error("LeadPIN passt nicht zu diesem Raid.");
    error.statusCode = 403;
    throw error;
  }

  const raidType = normalizeRaidType(raid.raid_type || params.raid || params.raidName);
  if (!clean(params.p1)) {
    const error = new Error("P1 fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const client = await pool.connect();

  try {
    await client.query("begin");

    const character = await findOrCreateRaidleadCharacter(client, guildId, params);
    const p1 = await upsertItem(client, raidType, params.p1, params.p1ItemId || params.p1_item_id || params.p1ItemID);
    const p2 = await upsertItem(client, raidType, params.p2, params.p2ItemId || params.p2_item_id || params.p2ItemID);
    const p3 = await upsertItem(client, raidType, params.p3, params.p3ItemId || params.p3_item_id || params.p3ItemID);
    await removeDuplicatePriosForCharacterName(client, raid.id, character);
    const comment = JSON.stringify({
      p0Plus: clean(params.p0Plus).toLowerCase() === "ja" ? "ja" : "nein",
      p0Item: clean(params.p0Plus).toLowerCase() === "ja" ? (p1?.name || "") : "",
      raidTime: clean(params.raidTime || params.uhrzeit) || raid.raid_time || "",
      source: "raidlead"
    });

    const prioResult = await client.query(
      `insert into prios (raid_id, character_id, p1_item_id, p2_item_id, p3_item_id, comment)
       values ($1, $2, $3, $4, $5, $6)
       on conflict (raid_id, character_id) do update
         set p1_item_id = excluded.p1_item_id,
             p2_item_id = excluded.p2_item_id,
             p3_item_id = excluded.p3_item_id,
             comment = excluded.comment,
             updated_at = now()
       returning id, created_at, updated_at`,
      [raid.id, character.id, p1?.id || null, p2?.id || null, p3?.id || null, comment]
    );

    const poPostRefreshPayloads = clean(params.p0Plus).toLowerCase() === "ja" && p1
      ? await syncPoPostEntryFromPrio(client, guildId, {
          raid,
          character,
          item: p1,
          source: "raidlead_prio_saved"
        })
      : [];
    await client.query("commit");
    const p0PostRefresh = await enqueueP0PostRefreshForRaid(guildId, raid, "raidlead_prio_saved")
      .catch(error => ({ success: false, error: error.message || String(error) }));
    const poPostRefresh = await enqueuePoPostRefreshPayloads(guildId, poPostRefreshPayloads, "raidlead_prio_saved");
    return {
      success: true,
      prioId: prioResult.rows[0].id,
      raidId: raidPublicId(raid),
      player: character.name,
      server: character.server,
      className: character.class_name,
      p0PostRefreshQueued: Boolean(p0PostRefresh && p0PostRefresh.success && !p0PostRefresh.skipped),
      p0PostRefresh,
      poPostRefresh
    };
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function importEmergencyPrios({ guild, query: params }) {
  requireMasterCodeForGuild(guild, params.masterCode);
  let entries = params.entries;
  if (typeof entries === "string") {
    try { entries = JSON.parse(entries); } catch { entries = []; }
  }
  if (!Array.isArray(entries) || !entries.length) {
    const error = new Error("Die Notfall-CSV enthält keine Prio-Einträge.");
    error.statusCode = 400;
    throw error;
  }

  const raidId = clean(params.raidId);
  const raidResult = await query(
    `select id, external_raid_id, raid_pin, lead_pin, raid_type, raid_time
     from raids
     where guild_id = $1 and (id::text = $2 or external_raid_id = $2)
     limit 1`,
    [guild.id, raidId]
  );
  const raid = raidResult.rows[0];
  if (!raid) {
    const error = new Error("Der ausgewählte Raid wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const imported = [];
  const failed = [];
  const emergencyItemName = value => clean(value).replace(/-\d+\s*$/, "").trim();
  for (const entry of entries) {
    try {
      const result = await savePrioAsRaidlead({
        guildId: guild.id,
        query: {
          raidId: raid.external_raid_id || raid.id,
          raid: raid.raid_type,
          leadPin: raid.lead_pin,
          player: entry.player || entry.Charakter,
          server: entry.server || entry.Server || "Everlook",
          className: entry.className || entry.Klasse,
          p1: emergencyItemName(entry.p1 || entry["Prio 1"]),
          p2: emergencyItemName(entry.p2 || entry["Prio 2"]),
          p3: emergencyItemName(entry.p3 || entry["Prio 3"]),
          p0Plus: entry.p0Plus || entry["PO+"] || "nein",
          raidTime: raid.raid_time
        }
      });
      imported.push({ player: entry.player || entry.Charakter, prioId: result.prioId });
    } catch (error) {
      failed.push({ player: entry.player || entry.Charakter || "", error: error.message || String(error) });
    }
  }
  return { success: failed.length === 0, imported, failed, importedCount: imported.length, failedCount: failed.length };
}

async function savePoSignupPrioFromBot({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensurePoPostEntriesSchema();
  await ensurePrioSchema();
  const postKey = clean(params.postKey || params.poPostKey || params.postId);
  let raid = await findRaid(guildId, {
    ...params,
    raidId: params.raidId || postKey,
    prioPin: params.raidPin || params.prioPin || params.playerPin,
    playerPin: params.raidPin || params.prioPin || params.playerPin
  });

  if (!raid && postKey) {
    const postConfig = await query(
      `select raid, title, raid_pin, raid_date, raid_time
       from po_post_entries
       where guild_id = $1
         and post_key = $2
         and archived_at is null
       order by config_only desc, updated_at desc, created_at desc
       limit 1`,
      [guildId, postKey]
    );
    const row = postConfig.rows[0] || {};
    raid = await findRaid(guildId, {
      ...params,
      raidId: postKey,
      raid: row.raid || params.raid || params.raidName,
      raidDate: row.raid_date || params.raidDate || params.date || params.datum,
      raidTime: row.raid_time || params.raidTime || params.time || params.uhrzeit,
      prioPin: row.raid_pin || params.raidPin || params.prioPin,
      playerPin: row.raid_pin || params.raidPin || params.prioPin
    });
  }

  if (!raid) {
    const error = new Error("Raid wurde für diese LichtLoot-ID nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const raidType = normalizeRaidType(raid.raid_type || params.raid || params.raidName);
  const itemName = clean(params.item || params.itemName || params.p1);
  if (!itemName) {
    const error = new Error("Item fehlt.");
    error.statusCode = 400;
    throw error;
  }
  const playerPin = normalizePin(params.playerPin || params.pin || params.spielerLogin);
  if (!playerPin) {
    const error = new Error("SpielerLogin fehlt. Eine PO kann nur mit freigegebenem SpielerLogin eingetragen werden.");
    error.statusCode = 400;
    throw error;
  }

  await ensureCrossGuildPlayerLogin(guildId, playerPin);
  const verifiedCharacter = await findCharacterForPin(
    guildId,
    playerPin,
    params.player || params.char || params.spieler,
    params.server
  );
  if (!verifiedCharacter) {
    const error = new Error("SpielerLogin passt nicht zu diesem Charakter oder ist gesperrt.");
    error.statusCode = 403;
    throw error;
  }
  if (normalizePlayerApprovalStatus(verifiedCharacter.approval_status) !== "approved") {
    const error = new Error("Dieser SpielerLogin wartet noch auf Freigabe durch die Gildenleitung.");
    error.statusCode = 403;
    throw error;
  }

  const releaseRaid = normalizePoReleaseRaid(raidType);
  if (releaseRaid) {
    const release = await checkCharacterPoRelease({
      guildId,
      query: {
        ...params,
        raid: releaseRaid,
        playerPin,
        player: verifiedCharacter.name,
        server: verifiedCharacter.server
      }
    });
    if (!release.allowed) {
      const error = new Error(
        `Dieser Charakter hat für ${releaseRaid.toUpperCase()} keine PO-Freigabe bei dieser Gilde.`
      );
      error.statusCode = 403;
      throw error;
    }
  }

  const client = await pool.connect();

  try {
    await client.query("begin");

    const character = await findOrCreateRaidleadCharacter(client, guildId, params);
    const item = await upsertItem(client, raidType, itemName, params.itemId || params.itemGameId || params.p1ItemId);
    if (!item) {
      const error = new Error("Item wurde nicht gefunden.");
      error.statusCode = 404;
      throw error;
    }
    await requireGuildPoItem(guildId, item.id, item.name);
    await removeDuplicatePriosForCharacterName(client, raid.id, character);

    const existing = await client.query(
      `select p1_item_id, p2_item_id, p3_item_id, comment
       from prios
       where raid_id = $1 and character_id = $2
       limit 1`,
      [raid.id, character.id]
    );
    const previousMeta = commentMeta(existing.rows[0]?.comment);
    const comment = JSON.stringify({
      ...previousMeta,
      p0Plus: "ja",
      p0Item: item.name,
      raidTime: raid.raid_time || clean(params.raidTime || params.uhrzeit),
      source: "po-bot",
      discordUserId: clean(params.discordUserId)
    });

    const prioResult = await client.query(
      `insert into prios (raid_id, character_id, p1_item_id, p2_item_id, p3_item_id, comment)
       values ($1, $2, $3, $3, $3, $4)
       on conflict (raid_id, character_id) do update
         set p1_item_id = excluded.p1_item_id,
             p2_item_id = excluded.p2_item_id,
             p3_item_id = excluded.p3_item_id,
             comment = excluded.comment,
             updated_at = now()
       returning id`,
      [raid.id, character.id, item.id, comment]
    );

    const poPostRefreshPayloads = await syncPoPostEntryFromPrio(client, guildId, {
      raid,
      character,
      item,
      source: "po_bot_prio_saved"
    });
    await client.query("commit");
    const poPostRefresh = await enqueuePoPostRefreshPayloads(guildId, poPostRefreshPayloads, "po_bot_prio_saved");
    return {
      success: true,
      prioId: prioResult.rows[0].id,
      raidId: raidPublicId(raid),
      player: character.name,
      server: character.server,
      className: character.class_name,
      item: item.name,
      poPostRefresh
    };
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function syncPoSignupPrios({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  await ensurePoPostEntriesSchema();
  const postKey = clean(params.postKey || params.poPostKey || params.postId);
  const raidPin = clean(params.raidPin || params.prioPin || params.playerPin || params.pin);
  if (!postKey) {
    const error = new Error("PO-Anmelder-ID fehlt.");
    error.statusCode = 400;
    throw error;
  }
  if (!raidPin) {
    const error = new Error("LichtLoot Prio-ID/PIN fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const entriesResult = await query(
    `select ppe.*, approved_player.player_pin
     from po_post_entries ppe
     left join lateral (
       select p.player_pin
       from characters c
       join players p on p.id = c.player_id
       where p.guild_id = ppe.guild_id
         and lower(c.name) = lower(ppe.player_name)
         and p.approval_status = 'approved'
         and coalesce(p.is_blocked, false) = false
       order by c.is_main desc, c.created_at asc
       limit 1
     ) approved_player on true
     where ppe.guild_id = $1
       and ppe.post_key = $2
       and ppe.approval_status = 'approved'
       and ppe.archived_at is null
     order by ppe.updated_at asc, lower(ppe.player_name) asc, lower(ppe.item_name) asc`,
    [guildId, postKey]
  );

  let synced = 0;
  const errors = [];
  for (const entry of entriesResult.rows) {
    try {
      await savePoSignupPrioFromBot({
        guildId,
        query: {
          ...params,
          raidPin,
          prioPin: raidPin,
          playerPin: entry.player_pin,
          spielerLogin: entry.player_pin,
          player: entry.player_name,
          char: entry.player_name,
          item: entry.item_name,
          itemName: entry.item_name,
          itemId: entry.item_game_id,
          itemSlot: entry.item_slot,
          itemBoss: entry.item_boss,
          server: clean(params.server || entry.server || "Everlook"),
          className: entry.class_name,
          discordUserId: entry.discord_user_id,
          discordName: entry.discord_name,
          masterCode: params.masterCode
        }
      });
      synced += 1;
    } catch (error) {
      errors.push({
        player: entry.player_name || "",
        item: entry.item_name || "",
        error: error.message || String(error)
      });
    }
  }

  return {
    success: true,
    postKey,
    raidPin,
    total: entriesResult.rows.length,
    synced,
    failed: errors.length,
    errors
  };
}

function commentMeta(comment) {
  try {
    return JSON.parse(comment || "{}") || {};
  } catch {
    return {};
  }
}

async function getPlayerPrioHistory(guildId, params) {
  await ensureCharacterPoReleaseSchema();
  const pin = params.pin || params.playerPin || params.characterPin || params.masterCharacterPin;
  const charName = params.char || params.player || params.spieler;
  const character = await findCharacterForPin(guildId, pin, charName, params.server);

  if (!character) {
    const error = new Error("Dieser Charakter gehört nicht zu diesem SpielerPin.");
    error.statusCode = 403;
    throw error;
  }

  const historyParams = [guildId, character.name];
  let historyServerClause = "";
  if (clean(character.server)) {
    historyParams.push(character.server);
    historyServerClause = `and lower(c.server) = lower($${historyParams.length})`;
  }

  const result = await query(
    `select
       pr.id,
       pr.comment,
       pr.created_at,
       pr.updated_at,
       r.id as raid_id,
       r.external_raid_id,
       r.raid_pin,
       r.name as raid_name,
       r.raid_type,
       r.raid_date,
       r.raid_time,
       r.guild_name,
       i1.name as p1,
       i2.name as p2,
       i3.name as p3
     from prios pr
     join raids r on r.id = pr.raid_id
     left join items i1 on i1.id = pr.p1_item_id
     left join items i2 on i2.id = pr.p2_item_id
     left join items i3 on i3.id = pr.p3_item_id
     join characters c on c.id = pr.character_id
     join players p on p.id = c.player_id
     where p.guild_id = $1
       and lower(c.name) = lower($2)
       ${historyServerClause}
     order by r.raid_date desc, pr.updated_at desc
     limit 100`,
    historyParams
  );

  const pointsParams = [guildId, character.name];
  let pointsServerClause = "";
  if (clean(character.server)) {
    pointsParams.push(character.server);
    pointsServerClause = `and lower(c.server) = lower($${pointsParams.length})`;
  }
  const pointsResult = await query(
    `select
       coalesce(i.raid_type, 'Raid') as raid,
       coalesce(i.name, pp.note, 'P0/P0+') as item,
       coalesce(i.quality, '') as quality,
       sum(pp.points)::numeric as points,
       pp.source,
       pp.note,
       max(pp.created_at) as created_at
     from p0plus_points pp
     join characters c on c.id = pp.character_id
     join players p on p.id = c.player_id and p.guild_id = $1
     left join items i on i.id = pp.item_id
     where pp.guild_id = $1
       and lower(c.name) = lower($2)
       ${pointsServerClause}
     group by
       coalesce(i.raid_type, 'Raid'),
       coalesce(i.name, pp.note, 'P0/P0+'),
       coalesce(i.quality, ''),
       pp.source,
       pp.note
     order by raid asc, item asc`,
    pointsParams
  );

  await ensureCharacterPoReleaseSchema();
  const releaseResult = await query(
    `select raid_type, approved_by, approved_at
     from character_po_releases
     where guild_id = $1 and character_id = $2`,
    [guildId, character.id]
  );
  const poReleases = poReleaseFlagsFromRows(releaseResult.rows);
  const recruitReleaseResult=await query(`select raid_type,approved_by,approved_at from character_recruit_releases where guild_id=$1 and character_id=$2`,[guildId,character.id]);
  const recruitReleases={mc:false,bwl:false,aq40:false,naxx:false,"zg-mittwoch":false,"zg-prime":false,"zg-late":false};
  for(const row of recruitReleaseResult.rows){const raid=normalizePoReleaseRaid(row.raid_type);if(raid&&raid!=="p1p3")recruitReleases[raid]=true;}

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const entries = result.rows.map(row => {
    const meta = commentMeta(row.comment);
    const raidDate = row.raid_date ? row.raid_date.toISOString().slice(0, 10) : "";
    const raidDay = raidDate ? new Date(`${raidDate}T00:00:00`) : null;

    return {
      id: row.id,
      raidId: row.raid_id,
      externalRaidId: row.external_raid_id || "",
      raidPin: row.raid_pin || "",
      prioPin: row.raid_pin || "",
      raid: row.raid_type,
      raidName: row.raid_name || displayRaidName(row.raid_type),
      raidDate,
      raidTime: row.raid_time || meta.raidTime || "",
      guild: row.guild_name || "",
      createdAt: row.updated_at || row.created_at,
      player: character.name,
      server: character.server,
      className: character.class_name,
      p1: row.p1 || "",
      p2: row.p2 || "",
      p3: row.p3 || "",
      p0Plus: meta.p0Plus || "nein",
      current: raidDay ? raidDay >= today : true,
      pinType: "Railway"
    };
  });

  return {
    success: true,
    guild: defaultGuildSlug,
    player: character.name,
    server: character.server,
    className: character.class_name,
    entries,
    poReleases,
    recruitReleases,
    characterId: character.id,
    poReleaseDetails: releaseResult.rows.map(row => ({
      raid: normalizePoReleaseRaid(row.raid_type),
      approvedBy: row.approved_by || "",
      approvedAt: row.approved_at || ""
    })),
    recruitStatusLifted: Boolean(character.recruit_status_lifted),
    recruitStatusLiftedAt: character.recruit_status_lifted_at || "",
    recruitStatusLiftedBy: character.recruit_status_lifted_by || "",
    ownP0PlusPoints: pointsResult.rows.map(row => ({
      raid: row.raid,
      item: row.item,
      quality: row.quality || "",
      slot: "",
      count: row.points,
      source: row.source || "",
      note: row.note || "",
      createdAt: row.created_at
    }))
  };
}

async function deletePrio({ guildId, query: params }) {
  const pin = params.pin || params.playerPin || params.characterPin || params.masterCharacterPin;
  const player = params.player || params.char || params.spieler;
  const raidId = clean(params.raidId);
  const prioId = clean(params.prioId || params.prio_id || params.id);
  const leadPin = clean(params.leadPin || params.raidleadPin);

  if (leadPin && raidId && player) {
    const raid = await findRaid(guildId, { raidId, leadPin });
    if (!raid) {
      const error = new Error("RaidID oder LeadPIN nicht gefunden.");
      error.statusCode = 403;
      throw error;
    }

    const values = [guildId, raid.id, clean(player)];
    let serverClause = "";
    if (clean(params.server)) {
      values.push(clean(params.server));
      serverClause = `and lower(c.server) = lower($${values.length})`;
    }

    const result = await query(
      `delete from prios pr
       using characters c
       where pr.character_id = c.id
         and pr.raid_id = $2
         and c.player_id in (select id from players where guild_id = $1)
         and lower(c.name) = lower($3)
         ${serverClause}
       returning pr.id, pr.raid_id`,
      values
    );

    const refresh = await enqueueRaidAnnouncementRefreshAfterPrioChange(guildId, raid, "raidlead_prio_deleted");
    return { success: true, deleted: result.rowCount, raidAnnouncementRefresh: refresh };
  }

  const character = await findCharacterForPin(guildId, pin, player, params.server);

  if (!character) {
    const error = new Error("Dieser Charakter gehört nicht zu diesem SpielerPin.");
    error.statusCode = 403;
    throw error;
  }

  const directRaidPin = clean(params.prioPin || params.raidPin);
  if (directRaidPin && clean(player)) {
    const directRaid = await findRaid(guildId, {
      prioPin: directRaidPin,
      raid: clean(params.raid)
    });
    if (directRaid) {
      let directPrio = await findPrioForRaidAndPlayer(directRaid.id, player, params.server);
      if (!directPrio && clean(params.server)) {
        directPrio = await findPrioForRaidAndPlayer(directRaid.id, player, "");
      }
      if (directPrio) {
        const directDelete = await query(
          "delete from prios where id = $1 returning id, raid_id",
          [directPrio.id]
        );
        const refresh = await enqueueRaidAnnouncementRefreshAfterPrioChange(
          guildId,
          directRaid,
          "player_prio_deleted"
        );
        return {
          success: true,
          deleted: directDelete.rowCount,
          raidAnnouncementRefreshes: [refresh]
        };
      }
    }
  }

  const exactPrioId = isUuid(prioId);
  const values = [guildId, exactPrioId ? character.player_id : character.name];
  const characterIdentityClause = exactPrioId
    ? `and exists (
         select 1
         from characters owned_character
         where owned_character.player_id = $2
           and lower(owned_character.name) = lower(c.name)
       )`
    : "and lower(c.name) = lower($2)";
  let characterServerClause = "";
  if (!exactPrioId && clean(character.server)) {
    values.push(character.server);
    characterServerClause = `and lower(c.server) = lower($${values.length})`;
  }
  let prioClause = "";
  if (exactPrioId) {
    values.push(prioId);
    prioClause = `and pr.id = $${values.length}`;
  }
  let raidClause = "";

  let resolvedDeleteRaid = null;
  if (raidId && !exactPrioId) {
    resolvedDeleteRaid = await findRaid(guildId, { raidId });
    if (!resolvedDeleteRaid && clean(params.raid) && clean(params.raidDate)) {
      resolvedDeleteRaid = await findRaid(guildId, {
        raid: clean(params.raid),
        raidDate: clean(params.raidDate),
        raidTime: clean(params.raidTime)
      });
    }
    if (!resolvedDeleteRaid && clean(params.prioPin || params.raidPin)) {
      resolvedDeleteRaid = await findRaid(guildId, { prioPin: clean(params.prioPin || params.raidPin) });
    }
    if (!resolvedDeleteRaid && clean(params.raid)) {
      const legacyRaidDate = raidId.match(/(?:^|-)(\d{4}-\d{2}-\d{2})(?:-|$)/)?.[1] || "";
      if (legacyRaidDate) {
        resolvedDeleteRaid = await findRaid(guildId, {
          raid: clean(params.raid),
          raidDate: legacyRaidDate
        });
      }
    }
    if (!resolvedDeleteRaid && clean(params.createdAt)) {
      const prioRaidResult = await query(
        `select r.*
         from prios pr
         join raids r on r.id = pr.raid_id
         join characters c on c.id = pr.character_id
         join players p on p.id = c.player_id
         where p.guild_id = $1
           and lower(c.name) = lower($2)
           and r.guild_id = $1
           and pr.created_at = $3::timestamptz
         order by pr.created_at desc
         limit 1`,
        [guildId, character.name, clean(params.createdAt)]
      );
      resolvedDeleteRaid = prioRaidResult.rows[0] || null;
    }
    if (!resolvedDeleteRaid) {
      const error = new Error("Der zugehörige Raid wurde nicht gefunden. Bitte die Raidseite neu laden und erneut versuchen.");
      error.statusCode = 404;
      throw error;
    }
  }
  if (resolvedDeleteRaid?.id) {
    values.push(resolvedDeleteRaid.id);
    raidClause = `and pr.raid_id = $${values.length}`;
  } else if (!exactPrioId && clean(params.raid)) {
    values.push(normalizeRaidType(params.raid));
    raidClause = `and r.raid_type = $${values.length}`;
  }

  let result = await query(
    `delete from prios pr
     using raids r, characters c, players p
     where pr.raid_id = r.id
       and pr.character_id = c.id
       and c.player_id = p.id
       and p.guild_id = $1
       ${characterIdentityClause}
       ${characterServerClause}
       ${prioClause}
       ${raidClause}
     returning pr.id, pr.raid_id`,
    values
  );

  if (!result.rowCount && exactPrioId && clean(params.prioPin || params.raidPin)) {
    const pinRaid = await findRaid(guildId, {
      prioPin: clean(params.prioPin || params.raidPin),
      raid: clean(params.raid)
    });
    if (pinRaid) {
      result = await query(
        `delete from prios pr
         using characters c, players p
         where pr.character_id = c.id
           and c.player_id = p.id
           and p.guild_id = $1
           and lower(c.name) = lower($2)
           and pr.raid_id = $3
         returning pr.id, pr.raid_id`,
        [guildId, clean(player), pinRaid.id]
      );
    }
  }

  if (!result.rowCount && resolvedDeleteRaid?.id) {
    result = await query(
      `delete from prios pr
       using characters c, players p
       where pr.character_id = c.id
         and c.player_id = p.id
         and p.guild_id = $1
         and lower(c.name) = lower($2)
         and pr.raid_id = $3
       returning pr.id, pr.raid_id`,
      [guildId, character.name, resolvedDeleteRaid.id]
    );
  }

  if (!result.rowCount) {
    const error = new Error("Die Prio wurde nicht gefunden und deshalb nicht gelöscht. Bitte die Raidseite neu laden und erneut versuchen.");
    error.statusCode = 404;
    throw error;
  }

  const raidIds = Array.from(new Set(result.rows.map(row => clean(row.raid_id)).filter(Boolean)));
  const refreshes = [];
  for (const deletedRaidId of raidIds) {
    const deletedRaid = await findRaid(guildId, { raidId: deletedRaidId });
    if (deletedRaid) {
      refreshes.push(await enqueueRaidAnnouncementRefreshAfterPrioChange(guildId, deletedRaid, "player_prio_deleted"));
    }
  }
  return { success: true, deleted: result.rowCount, raidAnnouncementRefreshes: refreshes };
}

async function enqueueRaidAnnouncementRefreshAfterPrioChange(guildId, raid, source) {
  if (!raid) return { success: true, skipped: true, reason: "raid_not_found" };
  const channelId = clean(raid.discord_channel_id || raid.discordChannelId);
  const messageId = clean(raid.discord_message_id || raid.discordMessageId);
  if (!channelId || !messageId) {
    return { success: true, skipped: true, reason: "discord_message_not_linked" };
  }
  return enqueueBotUpdate({
    guildId,
    type: "raid_announcement_refresh",
    payload: {
      raidId: raid.external_raid_id || raid.id,
      playerPin: raid.raid_pin || "",
      prioPin: raid.raid_pin || "",
      raid: raid.raid_type || "",
      channelId,
      discordChannelId: channelId,
      messageId,
      discordMessageId: messageId,
      source
    }
  }).catch(error => ({ success: false, error: error.message || String(error) }));
}

async function getGuildLeadershipOverview(guildId, params) {
  requireMasterCode(params.masterCode);
  await ensurePlayerRoleSchema();
  const repairedLogins = await repairEmptyCrossGuildPlayerLogins(guildId);
  if (repairedLogins) {
    console.log(`${repairedLogins} leer(e) gildenuebergreifende SpielerLogin(s) repariert.`);
  }
  await processRaidHelperSchedules({ guildId }).catch(error => {
    console.warn("RaidHelper-Schedules konnten nicht verarbeitet werden:", error.message || error);
  });

  const raidsResult = await query(
    `select r.*,
            (
              select count(*)
              from p0plus_points pp
              where pp.guild_id = r.guild_id
                and pp.source = 'Raidlead Transfer'
                and pp.note in (
                  concat('RaidID: ', coalesce(r.external_raid_id, r.id::text)),
                  concat('RaidID: ', r.id::text),
                  concat('RaidID: ', r.raid_pin)
                )
            ) as p0plus_transfer_count
     from raids r
     where r.guild_id = $1
     order by raid_date desc, coalesce(raid_time, '') desc, created_at desc`,
    [guildId]
  );

  const playersResult = await query(
    `select
       c.id,
       c.name,
       c.server,
       c.class_name,
       c.is_main,
       c.created_at,
       p.id as player_id,
       p.player_pin,
       p.role as player_role,
       p.discord_role_ids,
       p.permissions,
       p.approval_status,
       p.approved_at,
       p.approved_by,
       p.is_blocked,
       p.blocked_at,
       p.blocked_reason,
       count(*) over (partition by p.id) as linked_characters,
       first_value(c.name) over (
         partition by p.id
         order by coalesce(c.is_main, false) desc, c.created_at asc nulls last
       ) as main_char
     from players p
     left join characters c on c.player_id = p.id
     where p.guild_id = $1
     order by coalesce(c.name, p.player_pin) asc`,
    [guildId]
  );

  return {
    success: true,
    raids: raidsResult.rows.map(normalizeRaidRow),
    players: playersResult.rows.map((row, index) => ({
      id: row.id,
      playerId: row.player_id,
      rowNumber: index + 1,
      char: row.name || `SpielerLogin ${row.player_pin || ""}`.trim(),
      name: row.name || `SpielerLogin ${row.player_pin || ""}`.trim(),
      server: row.server || "",
      className: row.class_name,
      Klasse: row.class_name,
      mainChar: row.main_char || row.name || `SpielerLogin ${row.player_pin || ""}`.trim(),
      playerPin: row.player_pin || "",
      role: normalizePlayerRole(row.player_role),
      playerRole: normalizePlayerRole(row.player_role),
      playerRoleLabel: playerRoleLabel(row.player_role),
      canCreateRaid: canPlayerRoleCreateRaid(row.player_role),
      discordRoleIds: Array.isArray(row.discord_role_ids) ? row.discord_role_ids : [],
      permissions: Array.isArray(row.permissions) ? row.permissions : [],
      notificationDiscordNames: Array.isArray(row.notification_discord_names) ? row.notification_discord_names : [],
      approvalStatus: normalizePlayerApprovalStatus(row.approval_status),
      playerApprovalStatus: normalizePlayerApprovalStatus(row.approval_status),
      approvalLabel: playerApprovalLabel(row.approval_status),
      isApproved: normalizePlayerApprovalStatus(row.approval_status) === "approved",
      approvedAt: row.approved_at || null,
      approvedBy: row.approved_by || "",
      isBlocked: Boolean(row.is_blocked),
      blocked: Boolean(row.is_blocked),
      blockedAt: row.blocked_at || null,
      blockedReason: row.blocked_reason || "",
      linkedCharacters: Number(row.linked_characters || 1),
      createdAt: row.created_at
    }))
  };
}

function normalizeLogAnalysis(row) {
  const summary = row.summary || {};
  return {
    id: row.id,
    reportCode: row.report_code || "",
    reportUrl: row.report_url || "",
    title: row.title || "",
    raid: row.raid || "",
    raidDate: row.raid_date ? new Date(row.raid_date).toISOString().slice(0, 10) : "",
    status: row.status || "pending",
    summary,
    rpbSheetCount: Number(row.rpb_sheet_count || summary.rpbSheetCount || 0),
    claSheetCount: Number(row.cla_sheet_count || summary.claSheetCount || 0),
    claDownloadUrl: summary.claDownloadUrl || "",
    rpbDownloadUrl: summary.rpbDownloadUrl || "",
    discordChannelId: row.discord_channel_id || "",
    discordMessageId: row.discord_message_id || "",
    discordAuthor: row.discord_author || "",
    postedAt: row.posted_at,
    analyzedAt: row.analyzed_at,
    createdAt: row.created_at,
    updatedAt: row.updated_at
  };
}

const logAnalysisRaidRoleOptions = [
  { value: "", label: "Automatisch" },
  { value: "main_tank", label: "Main Tank" },
  { value: "off_tank", label: "Off Tank" },
  { value: "tank", label: "Tank" },
  { value: "healer", label: "Heiler" },
  { value: "cat", label: "Katze" },
  { value: "owl", label: "Eule" },
  { value: "melee", label: "Nahkampf" },
  { value: "caster", label: "Caster" },
  { value: "hunter", label: "Jäger" },
  { value: "shadow", label: "Shadow" },
  { value: "support", label: "Support" },
  { value: "ignore", label: "Ignorieren" }
];

function normalizeLogAnalysisRaidRole(value) {
  const role = clean(value).toLowerCase().replace(/\s+/g, "_").replace(/-/g, "_");
  const aliases = {
    maintank: "main_tank",
    mt: "main_tank",
    offtank: "off_tank",
    ot: "off_tank",
    feral_tank: "tank",
    bear: "tank",
    baer: "tank",
    bär: "tank",
    resto: "healer",
    heal: "healer",
    heiler: "healer",
    katze: "cat",
    feral: "cat",
    dd: "melee",
    melee_dd: "melee",
    nahkampf: "melee",
    eule: "owl",
    boomkin: "owl",
    moonkin: "owl",
    jaeger: "hunter",
    jäger: "hunter",
    hunter_dd: "hunter",
    schatten: "shadow",
    shadow_priest: "shadow",
    shadowpriest: "shadow",
    caster_dd: "caster",
    bench: "ignore"
  };
  const normalized = aliases[role] || role;
  return logAnalysisRaidRoleOptions.some(option => option.value === normalized) ? normalized : "";
}

function csvCell(value) {
  const text = String(value ?? "");
  if (/[;"\n\r]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

function buildCsv(rows) {
  return `\uFEFF${rows.map(row => row.map(csvCell).join(";")).join("\n")}\n`;
}

function slugPart(value) {
  return clean(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80) || "log";
}

function buildLogAnalysisDownloadUrl({ id, type, token }) {
  const params = new URLSearchParams({
    action: "guildDownloadLogAnalysis",
    id,
    type,
    token
  });
  const apiBase = clean(process.env.LICHTLOOT_API_URL || process.env.PUBLIC_API_URL) || "https://lichtloot-production.up.railway.app";
  const apiUrl = buildLogAnalysisCallbackUrl(apiBase);
  return `${apiUrl}?${params.toString()}`;
}

function parseWarcraftLogsEventsData(raw) {
  if (!raw) return [];
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed;
      if (Array.isArray(parsed?.data)) return parsed.data;
      return [];
    } catch {
      return [];
    }
  }
  if (Array.isArray(raw?.data)) return raw.data;
  return Array.isArray(raw) ? raw : [];
}

function parseWarcraftLogsTableData(raw) {
  if (!raw) return {};
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  }
  return raw && typeof raw === "object" ? raw : {};
}

function normalizeRpbClassName(value) {
  const text = clean(value);
  if (!text || /^unknown$/i.test(text) || /^player$/i.test(text)) return "";
  const lower = text.toLowerCase();
  const aliases = {
    druide: "Druid",
    druid: "Druid",
    jäger: "Hunter",
    jaeger: "Hunter",
    hunter: "Hunter",
    magier: "Mage",
    mage: "Mage",
    paladin: "Paladin",
    priester: "Priest",
    priest: "Priest",
    schurke: "Rogue",
    schurken: "Rogue",
    rogue: "Rogue",
    schamane: "Shaman",
    schamanen: "Shaman",
    shaman: "Shaman",
    hexenmeister: "Warlock",
    warlock: "Warlock",
    krieger: "Warrior",
    warrior: "Warrior"
  };
  return aliases[lower] || (rpbClassOrder.includes(text) ? text : "");
}

function playerActorsFromReport(report) {
  const actors = Array.isArray(report?.masterData?.actors) ? report.masterData.actors : [];
  return actors
    .filter(actor => clean(actor.type).toLowerCase() === "player" || normalizeRpbClassName(actor.subType || actor.type))
    .map(actor => ({
      id: Number(actor.id),
      name: clean(actor.name),
      server: clean(actor.server),
      className: normalizeRpbClassName(actor.subType || actor.type)
    }))
    .filter(actor => actor.id && actor.name)
    .sort((a, b) => a.name.localeCompare(b.name, "de"));
}

function rpbIncludedFightsForAnalysis(fights) {
  return (Array.isArray(fights) ? fights : []).filter(fight => {
    const encounterId = Number(fight?.encounterID || 0);
    const isBoss = encounterId > 0;
    if (!isBoss) return true;
    return fight.kill !== false;
  });
}

function actorNameById(players) {
  const map = new Map();
  players.forEach(player => map.set(Number(player.id), player.name));
  return map;
}

function actorById(players) {
  const map = new Map();
  players.forEach(player => map.set(Number(player.id), player));
  return map;
}

async function getGuildClassMap(guildId) {
  const result = await query(
    `select c.name, c.class_name
     from characters c
     join players p on p.id = c.player_id
     where p.guild_id = $1`,
    [guildId]
  );
  const map = new Map();
  result.rows.forEach(row => {
    const className = normalizeRpbClassName(row.class_name);
    if (row.name && className) map.set(clean(row.name).toLowerCase(), className);
  });
  return map;
}

async function fetchReportBaseForAnalysis(reportCode) {
  const token = await getWarcraftLogsAccessToken();
  const gqlQuery =
    "query($code:String!){"+
    "reportData{report(code:$code){"+
    "title startTime endTime zone{name}"+
    "fights{ id name startTime endTime encounterID kill }"+
    "masterData{actors{ id name server type subType }}"+
    "}}}";
  const data = await warcraftLogsGraphql(token, gqlQuery, { code: reportCode });
  const report = data.reportData?.report || {};
  const fights = (Array.isArray(report.fights) ? report.fights : [])
    .filter(fight => Number(fight.id) && Number(fight.endTime) > Number(fight.startTime));
  return {
    token,
    report,
    players: playerActorsFromReport(report),
    fights,
    fightIds: fights.map(fight => Number(fight.id))
  };
}

async function fetchReportEventsForAnalysis(token, reportCode, dataType, fightIds) {
  const hasFightScope = Array.isArray(fightIds);
  const hasTimeScope = fightIds && typeof fightIds === "object" && !Array.isArray(fightIds);
  if (hasFightScope && !fightIds.length) return [];
  const gqlQuery = hasFightScope
    ? "query($code:String!,$fightIDs:[Int],$startTime:Float){"+
      "reportData{report(code:$code){events(dataType:"+dataType+",fightIDs:$fightIDs,startTime:$startTime,limit:10000){data nextPageTimestamp}}}"+
      "}"
    : hasTimeScope
      ? "query($code:String!,$startTime:Float,$endTime:Float){"+
        "reportData{report(code:$code){events(dataType:"+dataType+",startTime:$startTime,endTime:$endTime,limit:10000){data nextPageTimestamp}}}"+
        "}"
    : "query($code:String!,$startTime:Float){"+
      "reportData{report(code:$code){events(dataType:"+dataType+",startTime:$startTime,limit:10000){data nextPageTimestamp}}}"+
      "}";
  const allEvents = [];
  let startTime = null;
  try {
    for (let page = 0; page < 50; page++) {
      const variables = hasFightScope
        ? { code: reportCode, fightIDs: fightIds, startTime }
        : hasTimeScope
          ? { code: reportCode, startTime: startTime ?? Number(fightIds.startTime || 0), endTime: Number(fightIds.endTime || 999999999999) }
          : { code: reportCode, startTime };
      const data = await warcraftLogsGraphql(token, gqlQuery, variables);
      const events = data.reportData?.report?.events || {};
      allEvents.push(...parseWarcraftLogsEventsData(events.data));
      if (!events.nextPageTimestamp || events.nextPageTimestamp === startTime) break;
      startTime = Number(events.nextPageTimestamp);
    }
    return allEvents;
  } catch (error) {
    console.warn(`Warcraft-Logs-${dataType}-Events konnten nicht geladen werden:`, error.message || error);
    return allEvents;
  }
}

async function fetchReportTableForAnalysis(token, reportCode, dataType, fightIds, sourceId = null) {
  const hasFightScope = Array.isArray(fightIds);
  const hasTimeScope = fightIds && typeof fightIds === "object" && !Array.isArray(fightIds);
  if (hasFightScope && !fightIds.length) return {};
  const options = sourceId && typeof sourceId === "object" ? sourceId : { sourceId };
  const hasSource = Number(options.sourceId) > 0;
  const hasTarget = Number(options.targetId) > 0;
  const sourceArg = hasSource ? ",sourceID:$sourceID" : "";
  const targetArg = hasTarget ? ",targetID:$targetID" : "";
  const fightArg = hasFightScope ? ",fightIDs:$fightIDs" : "";
  const timeArg = hasTimeScope ? ",startTime:$startTime,endTime:$endTime" : "";
  const queryVars = `$code:String!${hasFightScope ? ",$fightIDs:[Int]" : ""}${hasTimeScope ? ",$startTime:Float,$endTime:Float" : ""}${hasSource ? ",$sourceID:Int" : ""}${hasTarget ? ",$targetID:Int" : ""}`;
  const gqlQuery =
    "query("+queryVars+"){"+
    "reportData{report(code:$code){table(dataType:"+dataType+fightArg+timeArg+sourceArg+targetArg+")}}"+
    "}";
  try {
    const variables = { code: reportCode };
    if (hasFightScope) variables.fightIDs = fightIds;
    if (hasTimeScope) {
      variables.startTime = Number(fightIds.startTime || 0);
      variables.endTime = Number(fightIds.endTime || 999999999999);
    }
    if (hasSource) variables.sourceID = Number(options.sourceId);
    if (hasTarget) variables.targetID = Number(options.targetId);
    const data = await warcraftLogsGraphql(token, gqlQuery, variables);
    return parseWarcraftLogsTableData(data.reportData?.report?.table);
  } catch (error) {
    console.warn(`Warcraft-Logs-${dataType}-Tabelle konnte nicht geladen werden:`, error.message || error);
    if (options.strict) throw error;
    return {};
  }
}

async function getRaidAnalysisItemMetadataByIds(itemIds) {
  const ids = Array.from(new Set((itemIds || []).map(id => clean(id)).filter(Boolean)));
  if (!ids.length) return new Map();
  try {
    const result = await query(
      `select item_id, name, quality, icon_url, slot, type, boss, category,
              wowhead, stats_text, tooltip, needed, equip
       from items
       where item_id = any($1::text[])`,
      [ids]
    );
    const map = new Map();
    result.rows.forEach(row => {
      if (!row.item_id) return;
      map.set(String(row.item_id), {
        itemId: row.item_id,
        name: row.name || "",
        quality: row.quality || "",
        iconUrl: row.icon_url || "",
        slot: row.slot || "",
        type: row.type || "",
        boss: row.boss || "",
        category: row.category || "",
        wowhead: row.wowhead || "",
        statsText: row.stats_text || "",
        tooltip: row.tooltip || "",
        needed: row.needed || "",
        equip: row.equip || ""
      });
    });
    return map;
  } catch (error) {
    console.warn("Item-Metadaten für Raid-Auswertung konnten nicht geladen werden:", error.message || error);
    return new Map();
  }
}

function abilityName(event) {
  return clean(event?.ability?.name || event?.ability || event?.sourceAbility?.name || "");
}

function abilityId(event) {
  return Number(
    event?.abilityGameID ||
    event?.abilityGameId ||
    event?.ability?.guid ||
    event?.ability?.id ||
    event?.sourceAbilityGameID ||
    event?.sourceAbility?.guid ||
    event?.sourceAbility?.id ||
    0
  );
}

function abilityIdFromTableEntry(entry) {
  return Number(
    entry?.guid ||
    entry?.abilityGameID ||
    entry?.abilityGameId ||
    entry?.ability?.guid ||
    entry?.ability?.id ||
    entry?.id ||
    0
  );
}

function extraAbilityName(event) {
  return clean(event?.extraAbility?.name || event?.extraAbility || "");
}

function extraAbilityId(event) {
  return Number(
    event?.extraAbilityGameID ||
    event?.extraAbilityGameId ||
    event?.extraAbility?.guid ||
    event?.extraAbility?.id ||
    0
  );
}

function eventSourceId(event) {
  return Number(event?.sourceID || event?.sourceId || event?.source?.id || 0);
}

function eventTargetId(event) {
  return Number(event?.targetID || event?.targetId || event?.target?.id || 0);
}

function addPlayerAmount(table, player, key, amount = 1) {
  if (!player || !key) return;
  if (!table[key]) table[key] = {};
  table[key][player] = (Number(table[key][player] || 0) || 0) + amount;
}

function formatCountValue(value) {
  const number = Number(value || 0);
  return number ? String(Math.round(number)) : "";
}

const claExcludedGear = [
  [15138, "Onyxia Scale Cloak"],
  [20538, "Runed Stygian Leggings"],
  [20699, "Cenarion Reservist's Legplates"],
  [20700, "Cenarion Reservist's Legplates"],
  [20701, "Cenarion Reservist's Legguards"],
  [20702, "Cenarion Reservist's Legguards"],
  [20703, "Cenarion Reservist's Leggings"],
  [20704, "Cenarion Reservist's Leggings"],
  [20705, "Cenarion Reservist's Pants"],
  [20706, "Cenarion Reservist's Pants"],
  [20707, "Cenarion Reservist's Pants"],
  [15072, "Chimeric Leggings"],
  [15075, "Chimeric Vest"],
  [13531, "Crypt Stalker Leggings"],
  [17746, "Noxxion's Shackles"],
  [21691, "Ooze-Ridden Gauntlets"],
  [20476, "Sandstalker Bracers"],
  [20478, "Sandstalker Breastplate"],
  [21626, "Slime-Coated Leggings"],
  [18344, "Stonebark Gauntlets"],
  [9449, "Manual Crowd Pummeler"]
];

const rpbConsumables = [
  ["Greater Stoneshield Potion", ["Greater Stoneshield Potion"], [17540]],
  ["Limited Invulnerability Potion", ["Limited Invulnerability Potion"], [3169]],
  ["Living/Free Action Potion", ["Living Action Potion", "Free Action Potion"], [24364, 6615]],
  ["Great Rage Potion", ["Great Rage Potion"], [6613]],
  ["Mighty Rage Potion", ["Mighty Rage Potion"], [17528]],
  ["Major Healing Potion", ["Major Healing Potion"], [17534]],
  ["Major Mana Potion", ["Major Mana Potion"], [17531]],
  ["all other Mana Potions", ["Superior Mana Potion", "Greater Mana Potion", "Mana Potion"], [11903, 17530, 13443]],
  ["Demonic Rune/Dark Rune", ["Demonic Rune", "Dark Rune"], [16666, 27869]],
  ["Major/Greater Healthstone", ["Major Healthstone", "Greater Healthstone", "Healthstone"], [23477, 23476, 23475, 11732]],
  ["Mana Ruby", ["Mana Ruby"], [10058]],
  ["all other Mana Gems", ["Mana Citrine", "Mana Jade", "Mana Agate"], [5405, 10052, 10057]],
  ["Thistle Tea", ["Thistle Tea"], [9512]],
  ["Elixir of Poison Resistance", ["Elixir of Poison Resistance"], [26677]],
  ["Heavy Runecloth Bandage", ["Heavy Runecloth Bandage"], [18610]]
];

const rpbAbsorbs = [
  ["Greater Nature Protection Potion", ["Greater Nature Protection Potion"], [17546]],
  ["Nature Protection Potion", ["Nature Protection Potion"], [7254]],
  ["Greater Arcane Protection Potion", ["Greater Arcane Protection Potion"], [17549]],
  ["Greater Fire Protection Potion", ["Greater Fire Protection Potion"], [17543]],
  ["Fire Protection Potion", ["Fire Protection Potion"], [7233]],
  ["Frozen Rune", ["Frozen Rune"], [29432]],
  ["Greater Frost Protection Potion", ["Greater Frost Protection Potion"], [17544]],
  ["Frost Protection Potion", ["Frost Protection Potion"], [7239]],
  ["Frost Ward", ["Frost Ward"], [28609, 8462, 8461, 6143]],
  ["Greater Shadow Protection Potion", ["Greater Shadow Protection Potion"], [17548]],
  ["Shadow Protection Potion", ["Shadow Protection Potion"], [7242]],
  ["Shadow Ward", ["Shadow Ward"], [28610, 11739, 6229]],
  ["Power Word: Shield (excluded from total absorbed!)", ["Power Word: Shield"], [10901, 10900, 10899, 10898, 6066, 6065, 3747]]
];

const rpbEngineering = [
  ["Dense Dynamite", ["Dense Dynamite"], [19784, 23063]],
  ["Goblin Sapper Charge", ["Goblin Sapper Charge"], [13241]],
  ["Stratholme Holy Water", ["Stratholme Holy Water"], [17291]],
  ["Ez-Thro Dynamite II", ["Ez-Thro Dynamite II"], [23000]]
];

const holyNovaHealSpellMap = {
  15237: 23455,
  15430: 23458,
  15431: 23459,
  27799: 27803,
  27800: 27804,
  27801: 27805,
  25331: 25329
};

const rpbClassOrder = ["Druid", "Hunter", "Mage", "Paladin", "Priest", "Rogue", "Shaman", "Warlock", "Warrior"];

function parseRpbConfigCsvRows(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    const next = text[i + 1];
    if (inQuotes) {
      if (char === "\"" && next === "\"") {
        cell += "\"";
        i++;
      } else if (char === "\"") {
        inQuotes = false;
      } else {
        cell += char;
      }
      continue;
    }
    if (char === "\"") {
      inQuotes = true;
    } else if (char === ",") {
      row.push(cell);
      cell = "";
    } else if (char === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else if (char !== "\r") {
      cell += char;
    }
  }
  row.push(cell);
  rows.push(row);
  return rows;
}

function parseRpbConfigCast(configString) {
  const text = clean(configString);
  if (!text || text.indexOf("[") === -1) return null;
  const name = text.split(" [")[0].split(" {")[0];
  const idsText = (text.split("[")[1] || "").split("]")[0];
  const ids = idsText
    .split(",")
    .map(id => Number(String(id).replace("*", "").trim()))
    .filter(id => Number.isFinite(id) && id > 0);
  const castTime = Number.parseFloat((text.split("{")[1] || "").split("}")[0]) || 0;
  return {
    raw: text,
    name,
    ids,
    castTime,
    hasOverheal: text.toLowerCase().includes("overheal"),
    hasUptime: text.toLowerCase().includes("uptime") || text.includes("[99999]") || text.includes("[99998]")
  };
}

function findRpbConfigMarker(rows, marker) {
  for (let rowIndex = 0; rowIndex < rows.length; rowIndex++) {
    const colIndex = (rows[rowIndex] || []).findIndex(value => clean(value).startsWith(marker));
    if (colIndex > -1) return { rowIndex, colIndex };
  }
  return null;
}

function readRpbConfigList(rows, marker) {
  const found = findRpbConfigMarker(rows, marker);
  if (!found) return [];
  const values = [];
  for (let rowIndex = found.rowIndex + 1; rowIndex < rows.length; rowIndex++) {
    const value = clean(rows[rowIndex]?.[found.colIndex]);
    if (!value) break;
    values.push(value);
  }
  return values;
}

async function loadRpbConfigAll() {
  if (rpbConfigAllCache) return rpbConfigAllCache;
  const csv = await readFile(new URL("./rpb-configAll.csv", import.meta.url), "utf8");
  const rows = parseRpbConfigCsvRows(csv);
  const byClass = {};
  rpbClassOrder.forEach(className => {
    byClass[className] = {
      singleTarget: readRpbConfigList(rows, `singleTargetCasts tracked ${className}`).map(parseRpbConfigCast).filter(Boolean),
      aoe: readRpbConfigList(rows, `aoeCasts tracked ${className}`).map(parseRpbConfigCast).filter(Boolean),
      cooldowns: readRpbConfigList(rows, `classCooldowns tracked ${className}`).map(parseRpbConfigCast).filter(Boolean)
    };
  });
  rpbConfigAllCache = {
    rows,
    byClass,
    trinketsAndRacials: readRpbConfigList(rows, "trinketsAndRacials tracked").map(parseRpbConfigCast).filter(Boolean),
    damageTaken: readRpbConfigList(rows, "damageTaken tracked").map(parseRpbConfigCast).filter(Boolean),
    debuffsTracked: readRpbConfigList(rows, "debuffs tracked").map(parseRpbConfigCast).filter(Boolean)
  };
  return rpbConfigAllCache;
}

function findConfiguredCast(rpbConfig, className, spellId, kind) {
  const casts = rpbConfig?.byClass?.[className]?.[kind] || [];
  return casts.find(cast => cast.ids.includes(Number(spellId))) || null;
}

const rpbSpellNamesById = {
  17: "Power Word: Shield",
  72: "Shield Bash",
  99: "Demoralizing Roar",
  100: "Charge",
  116: "Frostbolt",
  118: "Polymorph",
  120: "Cone of Cold",
  122: "Frost Nova",
  133: "Fireball",
  136: "Mend Pet",
  139: "Renew",
  172: "Corruption",
  284: "Heroic Strike",
  325: "Lightning Shield",
  339: "Entangling Roots",
  348: "Immolate",
  355: "Taunt",
  408: "Kidney Shot",
  453: "Mind Soothe",
  498: "Divine Protection",
  527: "Dispel Magic",
  528: "Cure Disease",
  552: "Abolish Disease",
  585: "Smite",
  586: "Fade",
  589: "Shadow Word: Pain",
  596: "Prayer of Healing",
  603: "Curse of Doom",
  605: "Mind Control",
  633: "Lay on Hands",
  642: "Divine Shield",
  686: "Shadow Bolt",
  689: "Drain Life",
  703: "Garrote",
  740: "Tranquility",
  772: "Rend",
  774: "Rejuvenation",
  781: "Disengage",
  853: "Hammer of Justice",
  879: "Exorcism",
  976: "Shadow Protection",
  980: "Curse of Agony",
  996: "Prayer of Healing",
  1004: "Smite",
  1064: "Chain Heal",
  1079: "Rip",
  1094: "Immolate",
  1120: "Drain Soul",
  1160: "Demoralizing Shout",
  1464: "Slam",
  1680: "Whirlwind",
  1715: "Hamstring",
  1752: "Sinister Strike",
  1760: "Backstab",
  1766: "Kick",
  1767: "Kick",
  1768: "Kick",
  1769: "Kick",
  1943: "Rupture",
  1978: "Serpent Sting",
  2006: "Resurrection",
  2050: "Lesser Heal",
  2054: "Heal",
  2055: "Heal",
  2060: "Greater Heal",
  2061: "Flash Heal",
  2098: "Eviscerate",
  2136: "Fire Blast",
  2139: "Counterspell",
  2643: "Multi-Shot",
  2812: "Holy Wrath",
  2944: "Devouring Plague",
  3044: "Arcane Shot",
  3140: "Fireball",
  3408: "Crippling Poison",
  3747: "Power Word: Shield",
  5143: "Arcane Missiles",
  5176: "Wrath",
  5185: "Healing Touch",
  5308: "Execute",
  5394: "Healing Stream Totem",
  5487: "Bear Form",
  5570: "Insect Swarm",
  5676: "Searing Pain",
  5857: "Hellfire Effect",
  6065: "Power Word: Shield",
  6066: "Power Word: Shield",
  6074: "Renew",
  6143: "Frost Ward",
  6229: "Shadow Ward",
  6353: "Soul Fire",
  6358: "Seduction",
  6359: "Fire Resistance",
  6544: "Heroic Leap",
  6552: "Pummel",
  6554: "Pummel",
  1671: "Shield Bash",
  1672: "Shield Bash",
  6572: "Revenge",
  6770: "Sap",
  6789: "Death Coil",
  6807: "Maul",
  6940: "Blessing of Sacrifice",
  7328: "Redemption",
  7373: "Hamstring",
  7384: "Overpower",
  7386: "Sunder Armor",
  8050: "Flame Shock",
  8056: "Frost Shock",
  8042: "Earth Shock",
  8044: "Earth Shock",
  8045: "Earth Shock",
  8046: "Earth Shock",
  8184: "Fire Resistance Totem",
  8190: "Magma Totem",
  8331: "Ez-Thro Dynamite II",
  8457: "Fire Ward",
  8461: "Frost Ward",
  8462: "Frost Ward",
  8676: "Ambush",
  8921: "Moonfire",
  8936: "Regrowth",
  9472: "Flash Heal",
  9473: "Flash Heal",
  9474: "Flash Heal",
  9484: "Shackle Undead",
  9512: "Thistle Tea",
  9592: "Flash Heal",
  9749: "Faerie Fire",
  9888: "Healing Touch",
  9889: "Healing Touch",
  10054: "Mana Agate",
  10057: "Mana Citrine",
  10058: "Mana Ruby",
  10060: "Power Infusion",
  10278: "Blessing of Protection",
  10412: "Earth Shock",
  10413: "Earth Shock",
  10414: "Earth Shock",
  10605: "Chain Lightning",
  10898: "Power Word: Shield",
  10899: "Power Word: Shield",
  10900: "Power Word: Shield",
  10901: "Power Word: Shield",
  10915: "Flash Heal",
  10916: "Flash Heal",
  10917: "Flash Heal",
  10927: "Renew",
  10928: "Renew",
  10929: "Renew",
  10931: "Prayer of Healing",
  10933: "Smite",
  10934: "Smite",
  10937: "Power Word: Fortitude",
  10938: "Power Word: Fortitude",
  10945: "Mind Blast",
  10946: "Mind Blast",
  10947: "Mind Blast",
  10951: "Inner Fire",
  10952: "Inner Fire",
  10953: "Mind Control",
  10955: "Shackle Undead",
  10957: "Shadow Word: Pain",
  10958: "Shadow Word: Pain",
  10963: "Greater Heal",
  10964: "Greater Heal",
  10965: "Greater Heal",
  11349: "Elixir of Poison Resistance",
  11357: "Blade Flurry",
  11551: "Battle Shout",
  11597: "Sunder Armor",
  11659: "Shadow Bolt",
  11660: "Shadow Bolt",
  11661: "Shadow Bolt",
  11739: "Shadow Ward",
  11958: "Ice Block",
  12472: "Icy Veins",
  12654: "Ignite",
  13021: "Blast Wave",
  13033: "Ice Barrier",
  13241: "Goblin Sapper Charge",
  13877: "Blade Flurry",
  15237: "Holy Nova",
  15258: "Shadow Weaving",
  15473: "Shadowform",
  16666: "Demonic Rune",
  17291: "Stratholme Holy Water",
  17528: "Mighty Rage Potion",
  17530: "Greater Mana Potion",
  17531: "Major Mana Potion",
  17534: "Major Healing Potion",
  17540: "Greater Stoneshield Potion",
  17543: "Greater Fire Protection Potion",
  17544: "Greater Frost Protection Potion",
  17546: "Greater Nature Protection Potion",
  17548: "Greater Shadow Protection Potion",
  17549: "Greater Arcane Protection Potion",
  18610: "Heavy Runecloth Bandage",
  19784: "Dense Dynamite",
  20066: "Repentance",
  20271: "Judgement",
  25289: "Battle Shout",
  25314: "Greater Heal",
  25315: "Renew",
  25316: "Prayer of Healing",
  25363: "Smite",
  25364: "Smite",
  25372: "Mind Blast",
  25375: "Mind Blast",
  25384: "Holy Fire",
  25396: "Healing Wave",
  25398: "Prayer of Healing",
  27869: "Dark Rune",
  28609: "Frost Ward",
  28610: "Shadow Ward",
  28764: "Frozen Rune",
  29166: "Innervate"
};

function matchingLabel(name, groups, id = 0) {
  const numericId = Number(id || 0);
  if (numericId) {
    const byId = groups.find(([, , ids]) => Array.isArray(ids) && ids.includes(numericId));
    if (byId) return byId[0];
  }
  const lower = clean(name).toLowerCase();
  if (!lower) return "";
  const found = groups.find(([, terms]) => terms.some(term => lower.includes(term.toLowerCase())));
  return found ? found[0] : "";
}

function labelForAbility(event, groups) {
  return matchingLabel(abilityName(event), groups, abilityId(event));
}

function displayAbilityName(event, preferExtra = false) {
  const name = preferExtra ? extraAbilityName(event) || abilityName(event) : abilityName(event) || extraAbilityName(event);
  if (name) return name;
  const id = preferExtra ? extraAbilityId(event) || abilityId(event) : abilityId(event) || extraAbilityId(event);
  return rpbSpellNamesById[id] || (id ? `Unbekannter Spell (${id})` : "");
}

function inferClassFromSpellName(spellName) {
  const text = clean(spellName).toLowerCase();
  if (!text) return "";
  const rules = [
    ["Priest", ["mind blast", "shadow word", "flash heal", "greater heal", "prayer of healing", "power word", "inner fire", "shackle undead", "psychic scream", "mind control", "mind soothe", "holy fire", "smite", "renew", "fade"]],
    ["Paladin", ["blessing of", "holy shock", "judgement", "exorcism", "hammer of justice", "divine shield", "cleanse", "purify", "seal of", "lay on hands"]],
    ["Druid", ["faerie fire", "wrath", "starfire", "moonfire", "healing touch", "regrowth", "rejuvenation", "innervate", "bear form", "cat form", "dire bear", "hibernate", "abolish poison"]],
    ["Mage", ["fireball", "frostbolt", "arcane missiles", "arcane brilliance", "arcane intellect", "counterspell", "detect magic", "fire blast", "pyroblast", "scorch", "ice block", "mana shield", "polymorph", "remove lesser curse"]],
    ["Warlock", ["shadow bolt", "corruption", "curse of", "drain life", "drain mana", "drain soul", "immolate", "life tap", "searing pain", "soul fire", "banish", "fear"]],
    ["Hunter", ["aimed shot", "arcane shot", "concussive shot", "distracting shot", "serpent sting", "tranquilizing shot", "viper sting", "wing clip", "aspect of", "feign death", "hunter's mark", "mend pet", "raptor strike"]],
    ["Rogue", ["ambush", "backstab", "cheap shot", "distract", "eviscerate", "expose armor", "feint", "garrote", "gouge", "kick", "kidney shot", "rupture", "sinister strike", "slice and dice"]],
    ["Warrior", ["battle shout", "berserker stance", "bloodthirst", "charge", "concussion blow", "defensive stance", "demoralizing shout", "execute", "hamstring", "heroic strike", "intercept", "intimidating shout", "mocking blow", "overpower", "pummel", "revenge", "shield bash", "shield block", "slam", "sunder armor", "taunt", "thunder clap"]]
  ];
  const found = rules.find(([, terms]) => terms.some(term => text.includes(term)));
  return found ? found[0] : "";
}

function rpbCastMeta(spellName, className = "") {
  const text = clean(spellName).toLowerCase();
  if (!text || text.startsWith("unbekannter spell")) return { castTime: 0, kind: "none" };
  const rules = [
    ["aoe", 0, ["cleave", "whirlwind", "multi-shot", "volley", "rain of fire", "hellfire", "blizzard", "arcane explosion", "cone of cold", "holy nova", "prayer of healing", "chain heal", "tranquility", "thunder clap", "sapper", "dynamite"]],
    ["st", 3.5, ["greater heal"]],
    ["st", 3.0, ["healing touch", "starfire", "fireball", "shadow bolt", "aimed shot", "pyroblast", "soul fire"]],
    ["st", 2.5, ["frostbolt", "smite", "holy fire", "heal", "mind blast", "wrath", "lightning bolt", "chain lightning"]],
    ["st", 2.0, ["regrowth", "flash heal", "flash of light", "shadow bolt volley"]],
    ["st", 1.5, ["renew", "rejuvenation", "moonfire", "arcane missiles", "scorch", "fire blast", "holy shock", "immolate", "searing pain", "corruption", "drain life", "drain mana", "drain soul", "shoot", "arcane shot", "serpent sting", "exorcism", "judgement", "cleanse", "purify", "dispel magic", "abolish disease", "cure disease", "power word", "shadow word", "faerie fire", "insect swarm", "hibernate", "banish", "curse of", "shadowburn"]],
    ["st", 1.0, ["heroic strike", "bloodthirst", "execute", "revenge", "sunder armor", "shield bash", "pummel", "kick", "sinister strike", "backstab", "eviscerate", "ambush", "gouge", "kidney shot", "rupture", "garrote", "slice and dice", "hamstring", "taunt", "battle shout", "demoralizing shout", "mortal strike", "overpower", "slam"]]
  ];
  const found = rules.find(([, , terms]) => terms.some(term => text.includes(term)));
  if (!found) return { castTime: 0, kind: "none" };
  let [, castTime, terms] = found;
  const kind = found[0];
  if (className === "Mage" && text.includes("fireball")) castTime = 3.5;
  if (className === "Mage" && text.includes("frostbolt")) castTime = 2.5;
  if (text.includes("arcane missiles")) castTime = 5;
  if (text.includes("arcane explosion")) castTime = 1.5;
  if (text.includes("cleave") || text.includes("whirlwind") || text.includes("thunder clap")) castTime = 1;
  return { castTime, kind };
}

async function buildClaAnalysisRows(analysis) {
  const { token, report, players, fightIds } = await fetchReportBaseForAnalysis(analysis.report_code);
  const combatantEvents = await fetchReportEventsForAnalysis(token, analysis.report_code, "CombatantInfo", fightIds);
  const playersById = actorNameById(players);
  const gearByPlayer = new Map();

  combatantEvents.forEach(event => {
    const player = playersById.get(eventSourceId(event));
    if (!player || gearByPlayer.has(player)) return;
    const gear = normalizeWarcraftLogsGear(event.gear || []);
    if (gear.length) gearByPlayer.set(player, gear);
  });

  const headerPlayers = players.map(player => player.name);
  const title = report.title || analysis.title || "";
  const zone = report.zone?.name || analysis.raid || "";
  const raidDate = report.startTime ? formatDateInBerlin(new Date(Number(report.startTime))) : "";
  const rows = [
    ["", "yes", "", "", "", "title ", title, ...headerPlayers.map(() => "")],
    ["bosses to consider", "all bosses", "", "", "", "zone ", zone, ...headerPlayers.map(() => "")],
    ["", "equip to exclude", "", "", "", "date ", raidDate || "", ...headerPlayers.map(() => "")],
    ["", "id", "name", "", ...headerPlayers.map(() => "Item [Enchant]")]
  ];

  claExcludedGear.forEach(([itemId, itemName], index) => {
    const row = ["", itemId, itemName, ""];
    headerPlayers.forEach(player => {
      const gear = gearByPlayer.get(player) || [];
      const found = gear.find(item => String(item.itemId || item.id) === String(itemId));
      if (!found) {
        row.push(index < headerPlayers.length ? "---------------------------------------------------------------" : "");
        return;
      }
      const enchant = found.permanentEnchantName || found.permanentEnchant || "no enchant";
      row.push(`${found.name || itemName} [${enchant}]`);
    });
    rows.push(row);
  });

  headerPlayers.forEach((player, index) => {
    const gear = gearByPlayer.get(player) || [];
    const missing = gear
      .filter(item => !item.permanentEnchant && !item.permanentEnchantName && !["Hemd", "Schmuck 1", "Schmuck 2", "Ring 1", "Ring 2"].includes(item.slotName))
      .map(item => `${item.name} [no enchant]`);
    if (!missing.length) return;
    const row = ["", "", "", ""];
    headerPlayers.forEach((name, playerIndex) => row.push(playerIndex === index ? missing.join(", ") : ""));
    rows.push(row);
  });

  if (!combatantEvents.length) {
    rows.push([], ["Hinweis", "Keine CombatantInfo-Daten von Warcraft Logs erhalten."]);
  }

  return rows;
}

async function buildRpbAnalysisRows(analysis) {
  const { token, players, fightIds } = await fetchReportBaseForAnalysis(analysis.report_code);
  const playersById = actorNameById(players);
  const headerPlayers = players.map(player => player.name);
  const castEvents = await fetchReportEventsForAnalysis(token, analysis.report_code, "Casts", fightIds);
  const damageDoneEvents = await fetchReportEventsForAnalysis(token, analysis.report_code, "DamageDone", fightIds);
  const damageTakenEvents = await fetchReportEventsForAnalysis(token, analysis.report_code, "DamageTaken", fightIds);
  const interruptEvents = await fetchReportEventsForAnalysis(token, analysis.report_code, "Interrupts", fightIds);
  const consumes = {};
  const trinketsAndRacials = {};
  const absorbs = {};
  const engineeringCounts = {};
  const engineeringDamage = {};
  const interrupts = {};
  const interruptNames = {};

  castEvents.forEach(event => {
    const player = playersById.get(eventSourceId(event));
    const label = labelForAbility(event, rpbConsumables);
    if (player && label) addPlayerAmount(consumes, player, label, 1);
  });

  damageTakenEvents.forEach(event => {
    const player = playersById.get(eventTargetId(event));
    const label = matchingLabel(
      extraAbilityName(event) || abilityName(event),
      rpbAbsorbs,
      extraAbilityId(event) || abilityId(event)
    );
    const amount = Number(event.absorbed || event.absorb || event.amount || 0);
    if (player && label && amount) addPlayerAmount(absorbs, player, label, amount);
  });

  damageDoneEvents.forEach(event => {
    const player = playersById.get(eventSourceId(event));
    const label = labelForAbility(event, rpbEngineering);
    const amount = Number(event.amount || 0);
    if (player && label) {
      addPlayerAmount(engineeringCounts, player, label, 1);
      addPlayerAmount(engineeringDamage, player, "damage done with Engineering etc. total", amount);
    }
  });

  interruptEvents.forEach(event => {
    const player = playersById.get(eventSourceId(event));
    if (!player) return;
    addPlayerAmount(interrupts, player, "# of interrupted spells", 1);
    const interrupted = displayAbilityName(event, true) || "Interrupt";
    if (!interruptNames[player]) interruptNames[player] = new Set();
    interruptNames[player].add(interrupted);
  });

  const rows = [
    ["", ...headerPlayers],
    ["Consumables", ...headerPlayers.map(() => "")]
  ];
  rpbConsumables.forEach(([label]) => rows.push([label, ...headerPlayers.map(player => formatCountValue(consumes[label]?.[player]))]));
  rows.push(["temporary enchant uptime (1+ consecr./blessed?)", ...headerPlayers.map(() => "")]);
  rows.push([], ["Damage absorbed", ...headerPlayers.map(() => "")]);
  rpbAbsorbs.forEach(([label]) => rows.push([label, ...headerPlayers.map(player => formatCountValue(absorbs[label]?.[player]))]));
  rows.push(["total absorbed", ...headerPlayers.map(player => {
    const total = Object.keys(absorbs).reduce((sum, label) => label.startsWith("Power Word") ? sum : sum + Number(absorbs[label]?.[player] || 0), 0);
    return formatCountValue(total);
  })]);
  rows.push([], ["Engineering etc. (avg. hits per use)", ...headerPlayers.map(() => "")]);
  rpbEngineering.forEach(([label]) => rows.push([label, ...headerPlayers.map(player => formatCountValue(engineeringCounts[label]?.[player]))]));
  rows.push(["damage done with Engineering etc. total", ...headerPlayers.map(player => formatCountValue(engineeringDamage["damage done with Engineering etc. total"]?.[player]))]);
  rows.push([], ["Interrupted spells", ...headerPlayers.map(() => "")]);
  rows.push(["# of interrupted spells", ...headerPlayers.map(player => formatCountValue(interrupts["# of interrupted spells"]?.[player]))]);
  rows.push(["names and sources of interrupted spells", ...headerPlayers.map(player => interruptNames[player] ? Array.from(interruptNames[player]).join(", ") : "")]);

  if (!castEvents.length && !damageDoneEvents.length && !damageTakenEvents.length && !interruptEvents.length) {
    rows.push([], ["Hinweis", "Keine Detail-Events von Warcraft Logs erhalten."]);
  }

  return rows;
}

async function buildRpbWebAnalysis(analysis, options = {}) {
  const rpbConfig = await loadRpbConfigAll();
  const base = await fetchReportBaseForAnalysis(analysis.report_code);
  const { token, report, fights, fightIds } = base;
  const classByName = options.classByName instanceof Map ? options.classByName : new Map();
  const roleByName = options.roleByName instanceof Map ? options.roleByName : new Map();
  const players = (base.players || []).map(player => ({
    ...player,
    className: normalizeRpbClassName(classByName.get(clean(player.name).toLowerCase()) || player.className) || "",
    raidRole: normalizeLogAnalysisRaidRole(roleByName.get(clean(player.name).toLowerCase()))
  }));
  const playersById = actorById(players);
  const reportDurationMs = Math.max(0, Number(report.endTime || 0) - Number(report.startTime || 0));
  const fullReportScope = reportDurationMs > 0 ? { startTime: 0, endTime: reportDurationMs } : fightIds;
  const rpbFights = rpbIncludedFightsForAnalysis(fights);
  const rpbFightScope = rpbFights.length ? rpbFights.map(fight => Number(fight.id)) : (fightIds.length ? fightIds : fullReportScope);
  const activityScope = fullReportScope;
  const castEvents = await fetchReportEventsForAnalysis(token, analysis.report_code, "Casts", activityScope);
  const castsTable = await fetchReportTableForAnalysis(token, analysis.report_code, "Casts", activityScope);
  const damageDoneEvents = await fetchReportEventsForAnalysis(token, analysis.report_code, "DamageDone", activityScope);
  const damageTakenEvents = await fetchReportEventsForAnalysis(token, analysis.report_code, "DamageTaken", activityScope);
  const interruptEvents = await fetchReportEventsForAnalysis(token, analysis.report_code, "Interrupts", activityScope);
  const healingEvents = await fetchReportEventsForAnalysis(token, analysis.report_code, "Healing", activityScope);
  const buffEvents = await fetchReportEventsForAnalysis(token, analysis.report_code, "Buffs", activityScope);
  const combatantEvents = await fetchReportEventsForAnalysis(token, analysis.report_code, "CombatantInfo", fightIds.length ? fightIds : fullReportScope);
  const consumes = {};
  const trinketsAndRacials = {};
  const absorbs = {};
  const engineeringCounts = {};
  const engineeringDamage = {};
  const interrupts = {};
  const interruptNames = {};
  const activeSeconds = {};
  const activeEventCounts = {};
  const wclActiveSeconds = {};
  const wclActivePercent = {};
  const healingTotals = {};
  const overhealTotals = {};
  const healingBySpell = {};
  const healingById = {};
  const classCasts = {};
  const claCombatBuffs = {};
  const claWorldBuffs = {};
  const claIgnites = {};
  const damageHitsByPlayerAndAbility = {};
  const classCooldowns = {};
  const gearByPlayer = new Map();
  const stSecondsByPlayer = {};
  const aoeSecondsByPlayer = {};
  const classCastSources = {};
  const healerClasses = new Set(["Druid", "Paladin", "Priest", "Shaman"]);
  const totalFightSeconds = Math.max(1, Math.round((fights || []).reduce((sum, fight) => {
    return sum + Math.max(0, Number(fight.endTime || 0) - Number(fight.startTime || 0));
  }, 0) / 1000));
  const claWorldBuffDefinitions = [
    ["Nef/Ony", [22888, 355363]],
    ["Rend", [16609, 355366, 460940]],
    ["ZG Herz", [24425, 355365]],
    ["Songflower", [15366]],
    ["Mol'dar", [22818]],
    ["Fengus", [22817]],
    ["Slip'kik", [22820]],
    ["DMF", [23736, 23735, 23737, 23738, 23769, 23766, 23768, 23767]],
    ["Zanza/BL", [24417, 24382, 24383, 10667, 10668, 10669, 10692, 10693]]
  ];
  const claCombatBuffDefinitions = [
    ["Greater Fire Protection Potion", [17543]],
    ["Greater Frost Protection Potion", [17544]],
    ["Greater Nature Protection Potion", [17546]],
    ["Greater Shadow Protection Potion", [17548]],
    ["Greater Arcane Protection Potion", [17549]],
    ["Greater Stoneshield Potion", [17540]],
    ["Limited Invulnerability Potion", [3169]],
    ["Free/Living Action Potion", [6615, 24364]],
    ["Demonic/Dark Rune", [16666, 27869]],
    ["Major Mana Potion", [17531]],
    ["Major Healing Potion", [17534]],
    ["Flask of the Titans", [17626]],
    ["Supreme Power", [17628]],
    ["Distilled Wisdom", [17627]],
    ["Chromatic Resistance", [17629]]
  ];

  function playerNameFromEvent(event, source = true) {
    const player = playersById.get(source ? eventSourceId(event) : eventTargetId(event));
    return player ? player.name : "";
  }

  function playerNameFromBuffEvent(event) {
    return playerNameFromEvent(event, false) || playerNameFromEvent(event, true);
  }

  function labelForSpellId(spellId, definitions) {
    const id = Number(spellId || 0);
    if (!id) return "";
    const found = definitions.find(([, ids]) => ids.includes(id));
    return found ? found[0] : "";
  }

  function markActive(event) {
    const player = playerNameFromEvent(event, true);
    if (!player) return;
    if (!activeSeconds[player]) activeSeconds[player] = new Set();
    const timestamp = Number(event.timestamp || event.time || 0);
    if (timestamp) activeSeconds[player].add(Math.floor(timestamp / 1000));
    activeEventCounts[player] = (activeEventCounts[player] || 0) + 1;
  }

  function addHealing(event) {
    const player = playerNameFromEvent(event, true);
    if (!player) return;
    const amount = Number(event.amount || 0);
    const overheal = Number(event.overheal || event.overhealing || event.overhealAmount || 0);
    const id = abilityId(event);
    const spell = displayAbilityName(event) || "Unbekannter Heal";
    healingTotals[player] = (healingTotals[player] || 0) + amount;
    overhealTotals[player] = (overhealTotals[player] || 0) + overheal;
    if (!healingBySpell[spell]) healingBySpell[spell] = {};
    if (!healingBySpell[spell][player]) healingBySpell[spell][player] = { amount: 0, overheal: 0, hits: 0 };
    healingBySpell[spell][player].amount += amount;
    healingBySpell[spell][player].overheal += overheal;
    healingBySpell[spell][player].hits += 1;
    if (id) {
      if (!healingById[id]) healingById[id] = {};
      if (!healingById[id][player]) healingById[id][player] = { amount: 0, overheal: 0, hits: 0 };
      healingById[id][player].amount += amount;
      healingById[id][player].overheal += overheal;
      healingById[id][player].hits += 1;
    }
  }

  function addHealingTableEntry(playerName, entry) {
    if (!playerName || !entry) return;
    const id = abilityIdFromTableEntry(entry);
    const amount = Number(entry.total || entry.amount || 0);
    const overheal = Number(entry.overheal || entry.overhealing || entry.overhealAmount || 0);
    if (!amount && !overheal) return;
    const spell = clean(entry.name) || rpbSpellNamesById[id] || "Unbekannter Heal";
    healingTotals[playerName] = (healingTotals[playerName] || 0) + amount;
    overhealTotals[playerName] = (overhealTotals[playerName] || 0) + overheal;
    if (!healingBySpell[spell]) healingBySpell[spell] = {};
    if (!healingBySpell[spell][playerName]) healingBySpell[spell][playerName] = { amount: 0, overheal: 0, hits: 0 };
    healingBySpell[spell][playerName].amount += amount;
    healingBySpell[spell][playerName].overheal += overheal;
    healingBySpell[spell][playerName].hits += Number(entry.uses || entry.totalUses || entry.hitCount || entry.tickCount || 0);
    if (id) {
      if (!healingById[id]) healingById[id] = {};
      healingById[id][playerName] = {
        amount: (Number(healingById[id]?.[playerName]?.amount || 0) + amount),
        overheal: (Number(healingById[id]?.[playerName]?.overheal || 0) + overheal),
        hits: (Number(healingById[id]?.[playerName]?.hits || 0) + Number(entry.uses || entry.totalUses || entry.hitCount || entry.tickCount || 0))
      };
    }
  }

  function addClassCooldown(event) {
    const player = playersById.get(eventSourceId(event));
    if (!player || !player.className) return;
    const id = abilityId(event);
    const cooldown = findConfiguredCast(rpbConfig, player.className, id, "cooldowns");
    if (!cooldown) return;
    if (!classCooldowns[player.className]) classCooldowns[player.className] = {};
    if (!classCooldowns[player.className][cooldown.name]) classCooldowns[player.className][cooldown.name] = {};
    classCooldowns[player.className][cooldown.name][player.name] = (classCooldowns[player.className][cooldown.name][player.name] || 0) + 1;
  }

  function addDamageHit(event) {
    const player = playersById.get(eventSourceId(event));
    if (!player) return;
    const id = abilityId(event);
    if (!id) return;
    if (!damageHitsByPlayerAndAbility[player.name]) damageHitsByPlayerAndAbility[player.name] = {};
    damageHitsByPlayerAndAbility[player.name][id] = (damageHitsByPlayerAndAbility[player.name][id] || 0) + 1;
  }

  function addConfiguredCastCount(player, cast, kind, count, source = "events") {
    const amount = Number(count || 0);
    if (!player || !player.className || !cast || !cast.name || amount <= 0) return;
    let accepted = false;
    if (!classCasts[player.className]) classCasts[player.className] = {};
    if (!classCasts[player.className][cast.name]) classCasts[player.className][cast.name] = {};
    if (!classCastSources[player.className]) classCastSources[player.className] = {};
    if (!classCastSources[player.className][cast.name]) classCastSources[player.className][cast.name] = {};
    if (source === "table") {
      classCasts[player.className][cast.name][player.name] = amount;
      classCastSources[player.className][cast.name][player.name] = "table";
      accepted = true;
    } else if (classCastSources[player.className][cast.name]?.[player.name] !== "table") {
      classCasts[player.className][cast.name][player.name] = (classCasts[player.className][cast.name][player.name] || 0) + amount;
      classCastSources[player.className][cast.name][player.name] = "events";
      accepted = true;
    }
    if (!accepted) return;
    if (kind === "aoe") {
      aoeSecondsByPlayer[player.name] = (aoeSecondsByPlayer[player.name] || 0) + (cast.castTime * amount);
    } else {
      stSecondsByPlayer[player.name] = (stSecondsByPlayer[player.name] || 0) + (cast.castTime * amount);
    }
  }

  function addClassCast(event) {
    const player = playersById.get(eventSourceId(event));
    if (!player) return;
    if (labelForAbility(event, rpbConsumables) || labelForAbility(event, rpbEngineering)) return;
    const id = abilityId(event);
    const configuredStCast = findConfiguredCast(rpbConfig, player.className, id, "singleTarget");
    const configuredAoeCast = findConfiguredCast(rpbConfig, player.className, id, "aoe");
    const configuredCast = configuredStCast || configuredAoeCast;
    const spell = configuredCast?.name || displayAbilityName(event);
    if (!spell || /^\d+$/.test(spell)) return;
    if (!player.className) player.className = inferClassFromSpellName(spell);
    if (!player.className) return;
    if (configuredCast) {
      addConfiguredCastCount(player, configuredCast, configuredAoeCast ? "aoe" : "singleTarget", 1, "events");
    } else {
      if (!classCasts[player.className]) classCasts[player.className] = {};
      if (!classCasts[player.className][spell]) classCasts[player.className][spell] = {};
      classCasts[player.className][spell][player.name] = (classCasts[player.className][spell][player.name] || 0) + 1;
      const meta = rpbCastMeta(spell, player.className);
      if (meta.castTime > 0 && meta.kind === "aoe") {
        aoeSecondsByPlayer[player.name] = (aoeSecondsByPlayer[player.name] || 0) + meta.castTime;
      } else if (meta.castTime > 0 && meta.kind === "st") {
        stSecondsByPlayer[player.name] = (stSecondsByPlayer[player.name] || 0) + meta.castTime;
      }
    }
  }

  async function loadPlayerCastTables() {
    const limitedPlayers = players.filter(player => player.id && player.className);
    const concurrency = 1;
    let index = 0;
    async function worker() {
      while (index < limitedPlayers.length) {
        const player = limitedPlayers[index++];
        const [table, healingTable] = await Promise.all([
          fetchReportTableForAnalysis(token, analysis.report_code, "Casts", activityScope, player.id),
          fetchReportTableForAnalysis(token, analysis.report_code, "Healing", activityScope, player.id)
        ]);
        const entries = Array.isArray(table.entries) ? table.entries : [];
        entries.forEach(entry => {
          const count = Number(entry.total || entry.uses || entry.amount || entry.count || 0);
          if (!count) return;
          const id = abilityIdFromTableEntry(entry);
          const trinket = (rpbConfig.trinketsAndRacials || []).find(item => item.ids.includes(id));
          if (trinket) addPlayerAmount(trinketsAndRacials, player.name, trinket.name, count);
          const configuredStCast = findConfiguredCast(rpbConfig, player.className, id, "singleTarget");
          const configuredAoeCast = findConfiguredCast(rpbConfig, player.className, id, "aoe");
          const configuredCast = configuredStCast || configuredAoeCast;
          if (!configuredCast) return;
          addConfiguredCastCount(player, configuredCast, configuredAoeCast ? "aoe" : "singleTarget", count, "table");
        });
        (Array.isArray(healingTable.entries) ? healingTable.entries : []).forEach(entry => {
          addHealingTableEntry(player.name, entry);
        });
      }
    }
    await Promise.all(Array.from({ length: Math.min(concurrency, limitedPlayers.length) }, () => worker()));
  }

  if (castsTable && Array.isArray(castsTable.entries)) {
    const tableTotalTime = Number(castsTable.totalTime || 0);
    castsTable.entries.forEach(entry => {
      const name = clean(entry.name);
      if (!name) return;
      const activeMs = Number(entry.activeTime || 0);
      if (activeMs > 0) wclActiveSeconds[name] = Math.round(activeMs / 1000);
      if (tableTotalTime > 0 && activeMs > 0) wclActivePercent[name] = `${Math.round(activeMs * 100 / tableTotalTime)}%`;
      const player = players.find(item => item.name === name);
      if (player && !player.className) player.className = normalizeRpbClassName(entry.type || entry.icon || entry.className);
    });
  }

  await loadPlayerCastTables();

  castEvents.forEach(event => {
    markActive(event);
    addClassCast(event);
    addClassCooldown(event);
  });
  damageDoneEvents.forEach(event => {
    markActive(event);
    addDamageHit(event);
  });
  healingEvents.forEach(event => {
    markActive(event);
  });

  players.forEach(player => {
    if (!player.className) player.className = normalizeRpbClassName(classByName.get(clean(player.name).toLowerCase()));
    if (!player.className) player.className = "Unknown";
    player.raidRole = normalizeLogAnalysisRaidRole(roleByName.get(clean(player.name).toLowerCase()) || player.raidRole);
  });
  players.sort((a, b) => {
    const aIndex = rpbClassOrder.includes(a.className) ? rpbClassOrder.indexOf(a.className) : 999;
    const bIndex = rpbClassOrder.includes(b.className) ? rpbClassOrder.indexOf(b.className) : 999;
    if (aIndex !== bIndex) return aIndex - bIndex;
    return a.name.localeCompare(b.name, "de");
  });

  castEvents.forEach(event => {
    const player = playerNameFromEvent(event, true);
    const label = labelForAbility(event, rpbConsumables);
    if (player && label) addPlayerAmount(consumes, player, label, 1);
  });

  damageTakenEvents.forEach(event => {
    const player = playerNameFromEvent(event, false);
    const label = matchingLabel(
      extraAbilityName(event) || abilityName(event),
      rpbAbsorbs,
      extraAbilityId(event) || abilityId(event)
    );
    const amount = Number(event.absorbed || event.absorb || event.amount || 0);
    if (player && label && amount) addPlayerAmount(absorbs, player, label, amount);
  });

  damageDoneEvents.forEach(event => {
    const player = playerNameFromEvent(event, true);
    const label = labelForAbility(event, rpbEngineering);
    const amount = Number(event.amount || 0);
    if (player && label) {
      addPlayerAmount(engineeringCounts, player, label, 1);
      addPlayerAmount(engineeringDamage, player, "Gesamtschaden durch Engineering etc.", amount);
    }
    if (abilityId(event) === 12654 && player) {
      addPlayerAmount(claIgnites, player, "Ignite Ticks", 1);
      addPlayerAmount(claIgnites, player, "Ignite Schaden", amount);
      const currentMax = Number(claIgnites["Max Ignite Tick"]?.[player] || 0);
      if (amount > currentMax) {
        if (!claIgnites["Max Ignite Tick"]) claIgnites["Max Ignite Tick"] = {};
        claIgnites["Max Ignite Tick"][player] = amount;
      }
    }
  });

  interruptEvents.forEach(event => {
    const player = playerNameFromEvent(event, true);
    if (!player) return;
    addPlayerAmount(interrupts, player, "# of interrupted spells", 1);
    const interrupted = displayAbilityName(event, true) || "Interrupt";
    if (!interruptNames[player]) interruptNames[player] = new Set();
    interruptNames[player].add(interrupted);
  });

  combatantEvents.forEach(event => {
    const player = playerNameFromEvent(event, true);
    if (!player || gearByPlayer.has(player)) return;
    const gear = normalizeWarcraftLogsGear(event.gear || []);
    if (gear.length) gearByPlayer.set(player, gear);
    (Array.isArray(event.auras) ? event.auras : []).forEach(aura => {
      const id = Number(aura.guid || aura.abilityGameID || aura.abilityGameId || aura.id || 0);
      const worldBuff = labelForSpellId(id, claWorldBuffDefinitions);
      const combatBuff = labelForSpellId(id, claCombatBuffDefinitions);
      if (worldBuff) addPlayerAmount(claWorldBuffs, player, worldBuff, 1);
      if (combatBuff) addPlayerAmount(claCombatBuffs, player, combatBuff, 1);
    });
  });

  buffEvents.forEach(event => {
    const player = playerNameFromBuffEvent(event);
    const id = abilityId(event);
    const worldBuff = labelForSpellId(id, claWorldBuffDefinitions);
    const combatBuff = labelForSpellId(id, claCombatBuffDefinitions);
    if (player && worldBuff) addPlayerAmount(claWorldBuffs, player, worldBuff, 1);
    if (player && combatBuff) addPlayerAmount(claCombatBuffs, player, combatBuff, 1);
  });

  const gearItemIds = [];
  gearByPlayer.forEach(items => {
    items.forEach(item => {
      const id = clean(item.itemId || item.id);
      if (id) gearItemIds.push(id);
    });
  });
  const itemMetaById = await getRaidAnalysisItemMetadataByIds(gearItemIds);

  const playerNames = players.map(player => player.name);
  const countRow = (label, table, options = {}) => ({
    label,
    type: options.type || "count",
    tone: options.tone || "",
    values: Object.fromEntries(playerNames.map(player => [player, formatCountValue(table[label]?.[player])]))
  });
  const amountRow = (label, table, options = {}) => ({
    label,
    type: options.type || "amount",
    tone: options.tone || "",
    values: Object.fromEntries(playerNames.map(player => [player, formatCountValue(table[label]?.[player])]))
  });
  const customRow = (label, values, options = {}) => ({
    label,
    type: options.type || "count",
    tone: options.tone || "",
    values: Object.fromEntries(playerNames.map(player => [player, values[player] || ""]))
  });
  const textRow = (label, values, options = {}) => customRow(label, values, { ...options, type: "text" });
  const presenceRow = (label, table, options = {}) => textRow(label, Object.fromEntries(playerNames.map(player => [
    player,
    Number(table[label]?.[player] || 0) > 0 ? "ja" : ""
  ])), options);
  const gearEnchantIgnoredSlots = new Set(["Hemd", "Schmuck 1", "Schmuck 2", "Ring 1", "Ring 2"]);
  const gearItemMeta = item => itemMetaById.get(String(item?.itemId || item?.id || "")) || null;
  const gearItemText = item => {
    if (!item) return "";
    const meta = gearItemMeta(item);
    const enchant = item.permanentEnchantName || item.permanentEnchant || "";
    return `${meta?.name || item.name || item.itemId || "Item"}${enchant ? ` [${enchant}]` : " [kein Enchant]"}`;
  };
  const gearItemCell = item => {
    if (!item) return "";
    const meta = gearItemMeta(item);
    return {
      text: gearItemText(item),
      itemId: clean(item.itemId || item.id),
      quality: meta?.quality || clean(item.quality),
      iconUrl: meta?.iconUrl || clean(item.iconUrl || item.icon),
      slot: meta?.slot || item.slotName || "",
      boss: meta?.boss || "",
      type: meta?.type || "",
      wowhead: meta?.wowhead || "",
      tooltip: meta?.tooltip || meta?.statsText || meta?.equip || "",
      title: [
        meta?.name || item.name || item.itemId || "Item",
        meta?.quality ? `Qualität: ${meta.quality}` : "",
        meta?.slot || item.slotName ? `Slot: ${meta?.slot || item.slotName}` : "",
        meta?.boss ? `Quelle: ${meta.boss}` : "",
        meta?.type ? `Typ: ${meta.type}` : "",
        meta?.tooltip || meta?.statsText || meta?.equip || ""
      ].filter(Boolean).join("\n")
    };
  };
  const gearListText = items => items.map(gearItemText).join(", ");
  const playerGear = player => gearByPlayer.get(player) || [];
  const playerMissingEnchants = playerGearItems => playerGearItems
    .filter(item => !item.permanentEnchant && !item.permanentEnchantName && !gearEnchantIgnoredSlots.has(item.slotName))
    .map(item => gearItemText(item));
  const playerExcludedGear = playerGearItems => playerGearItems
    .filter(item => claExcludedGear.some(([itemId]) => String(item.itemId || item.id) === String(itemId)));
  const claGearSlots = [
    "Kopf", "Hals", "Schultern", "Rücken", "Brust", "Handgelenke", "Hände", "Taille",
    "Beine", "Füße", "Ring 1", "Ring 2", "Schmuck 1", "Schmuck 2", "Waffenhand",
    "Schildhand", "Distanz"
  ];
  const buildClaGearIssueRows = () => {
    const rows = [
      headerRow("Gear-Probleme"),
      textRow("Fehlende Enchants", Object.fromEntries(playerNames.map(player => [
        player,
        playerMissingEnchants(playerGear(player)).join(", ")
      ])), { tone: "interrupt" }),
      countRow("Anzahl fehlende Enchants", {
        "Anzahl fehlende Enchants": Object.fromEntries(playerNames.map(player => [
          player,
          playerMissingEnchants(playerGear(player)).length
        ]))
      }, { tone: "engineering" }),
      textRow("Auffällige/ausgeschlossene Items", Object.fromEntries(playerNames.map(player => [
        player,
        gearListText(playerExcludedGear(playerGear(player)))
      ])), { tone: "trinket" }),
      countRow("Anzahl auffällige Items", {
        "Anzahl auffällige Items": Object.fromEntries(playerNames.map(player => [
          player,
          playerExcludedGear(playerGear(player)).length
        ]))
      }, { tone: "trinket" }),
      headerRow("Auffällige Items im Detail")
    ];
    claExcludedGear.forEach(([itemId, itemName]) => {
      rows.push(textRow(itemName, Object.fromEntries(playerNames.map(player => {
        const found = playerGear(player).find(item => String(item.itemId || item.id) === String(itemId));
        return [player, found ? gearItemCell(found) : ""];
      })), { tone: "muted" }));
    });
    return rows;
  };
  const buildClaGearListingRows = () => [
    headerRow("Gear Listing"),
    ...claGearSlots.map(slot => textRow(slot, Object.fromEntries(playerNames.map(player => {
      const found = playerGear(player).find(item => item.slotName === slot);
      return [player, gearItemCell(found)];
    })), { tone: "classCast" }))
  ];
  const buildClaValidateRows = () => [
    headerRow("Validate"),
    customRow("CombatantInfo vorhanden", Object.fromEntries(playerNames.map(player => [
      player,
      playerGear(player).length ? "ja" : "nein"
    ])), { type: "text", tone: "activity" }),
    countRow("Items erfasst", {
      "Items erfasst": Object.fromEntries(playerNames.map(player => [player, playerGear(player).length]))
    }, { tone: "activity" }),
    countRow("Fehlende Enchants", {
      "Fehlende Enchants": Object.fromEntries(playerNames.map(player => [player, playerMissingEnchants(playerGear(player)).length]))
    }, { tone: "interrupt" }),
    countRow("Auffällige Items", {
      "Auffällige Items": Object.fromEntries(playerNames.map(player => [player, playerExcludedGear(playerGear(player)).length]))
    }, { tone: "trinket" })
  ];
  const buildClaCombatBuffRows = () => [
    headerRow("Combat Buffs"),
    ...claCombatBuffDefinitions.map(([label]) => countRow(label, claCombatBuffs, { tone: generalConsumableTone(label) })),
    headerRow("Consumables aus RPB"),
    ...rpbConsumables.map(([label]) => countRow(label, consumes, { tone: generalConsumableTone(label) })),
    headerRow("Absorbs"),
    ...rpbAbsorbs.map(([label]) => amountRow(label, absorbs, { tone: absorbTone(label) }))
  ];
  const buildClaWorldBuffRows = () => [
    headerRow("World Buffs"),
    ...claWorldBuffDefinitions.map(([label]) => presenceRow(label, claWorldBuffs, { tone: "consumableGreen" }))
  ];
  const buildClaIgniteRows = () => [
    headerRow("Ignites"),
    amountRow("Ignite Schaden", claIgnites, { tone: "engineeringTotal" }),
    countRow("Ignite Ticks", claIgnites, { tone: "engineering" }),
    amountRow("Max Ignite Tick", claIgnites, { tone: "trinket" })
  ];
  const generalConsumableTone = label => {
    if (/Demonic Rune|Dark Rune|Healthstone|Mana Ruby|Mana Gems|Thistle Tea/i.test(label)) return "consumableGreen";
    if (/Poison Resistance|Runecloth Bandage/i.test(label)) return "muted";
    return "consumableBlue";
  };
  const absorbTone = label => {
    if (/Nature/i.test(label)) return "absorbNature";
    if (/Arcane/i.test(label)) return "absorbArcane";
    if (/Fire|Frozen Rune/i.test(label)) return "absorbFire";
    if (/Frost/i.test(label)) return "absorbFrost";
    if (/Shadow|Power Word/i.test(label)) return "absorbShadow";
    return "absorb";
  };
  const engineeringTone = label => label.indexOf("damage done") > -1 ? "engineeringTotal" : "engineering";

  const buildActivityRows = scopeNames => {
    const scoped = Array.isArray(scopeNames) && scopeNames.length ? scopeNames : playerNames;
    const maxTotalActiveSeconds = Math.max(1, ...scoped.map(player => {
      return Math.round((stSecondsByPlayer[player] || 0) + (aoeSecondsByPlayer[player] || 0));
    }));
    return [
    customRow("Sekunden aktiv auf Einzelziel", Object.fromEntries(playerNames.map(player => [
      player,
      formatCountValue(stSecondsByPlayer[player])
    ])), { tone: "activity" }),
    customRow("Aktiv auf Einzelziel %", Object.fromEntries(playerNames.map(player => [
      player,
      stSecondsByPlayer[player] ? `${Math.round((stSecondsByPlayer[player] || 0) * 100 / maxTotalActiveSeconds)}%` : ""
    ])), { tone: "activity" }),
    customRow("Aktiv gesamt %", Object.fromEntries(playerNames.map(player => [
      player,
      (stSecondsByPlayer[player] || aoeSecondsByPlayer[player])
        ? `${Math.round(((stSecondsByPlayer[player] || 0) + (aoeSecondsByPlayer[player] || 0)) * 100 / maxTotalActiveSeconds)}%`
        : ""
    ])), { tone: "activityStrong" }),
    customRow("Aktiv auf AoE %", Object.fromEntries(playerNames.map(player => [
      player,
      aoeSecondsByPlayer[player] ? `${Math.round((aoeSecondsByPlayer[player] || 0) * 100 / maxTotalActiveSeconds)}%` : ""
    ])), { tone: "activity" }),
    customRow("Sekunden aktiv auf AoE", Object.fromEntries(playerNames.map(player => [
      player,
      formatCountValue(aoeSecondsByPlayer[player])
    ])), { tone: "activity" }),
    customRow("WCL-Aktivität gesamt", Object.fromEntries(playerNames.map(player => [
      player,
      wclActivePercent[player] || ""
    ])), { tone: "activity" })
    ];
  };
  const activityRows = buildActivityRows(playerNames);

  const healerNames = players
    .filter(player => healerClasses.has(player.className) || healingTotals[player.name])
    .map(player => player.name);
  const healingRows = [
    customRow("Heilung gesamt", Object.fromEntries(playerNames.map(player => [player, formatCountValue(healingTotals[player])])), { tone: "healing" }),
    customRow("Overheal gesamt", Object.fromEntries(playerNames.map(player => [player, formatCountValue(overhealTotals[player])])), { tone: "healing" }),
    customRow("Overheal %", Object.fromEntries(playerNames.map(player => {
      const healing = Number(healingTotals[player] || 0);
      const overheal = Number(overhealTotals[player] || 0);
      return [player, healing + overheal > 0 ? `${Math.round(overheal * 100 / (healing + overheal))}%` : ""];
    })), { tone: "healing" })
  ];
  Object.keys(healingBySpell)
    .sort((a, b) => a.localeCompare(b, "de"))
    .forEach(spell => {
      healingRows.push(customRow(`${spell} (Overheal %)`, Object.fromEntries(playerNames.map(player => {
        const data = healingBySpell[spell][player];
        if (!data || (!data.amount && !data.overheal)) return [player, ""];
        const pct = data.amount + data.overheal > 0 ? Math.round(data.overheal * 100 / (data.amount + data.overheal)) : 0;
        return [player, `${Math.round(data.amount)} (${pct}%)`];
      })), { type: "text", tone: "healing" }));
    });

  const headerRow = (label, options = {}) => ({
    label,
    type: "header",
    tone: options.tone || "sectionHeader",
    className: options.className || "",
    values: {}
  });

  function configuredCastRow(className, cast, kind) {
    const isHealingRow = cast.hasOverheal || healerClasses.has(className);
    return customRow(cast.name, Object.fromEntries(playerNames.map(player => {
      const classPlayers = players.filter(item => item.className === className).map(item => item.name);
      if (!classPlayers.includes(player)) return [player, ""];
      const castCount = Number(classCasts[className]?.[cast.name]?.[player] || 0);
      if (cast.hasOverheal) {
        const data = cast.ids.reduce((sum, id) => {
          const healId = holyNovaHealSpellMap[id] || id;
          const row = healingById[healId]?.[player];
          if (!row) return sum;
          sum.amount += Number(row.amount || 0);
          sum.overheal += Number(row.overheal || 0);
          return sum;
        }, { amount: 0, overheal: 0 });
        if (!castCount) return [player, "0"];
        const pct = data.amount + data.overheal > 0 ? Math.round(data.overheal * 100 / (data.amount + data.overheal)) : 0;
        return [player, `${formatCountValue(castCount)} (${pct}%)`];
      }
      if (kind === "aoe" && castCount > 0) {
        const ids = new Set(cast.ids || []);
        if (/Blade Flurry/i.test(cast.name)) ids.add(22482);
        const hits = Array.from(ids).reduce((sum, id) => sum + Number(damageHitsByPlayerAndAbility[player]?.[id] || 0), 0);
        if (hits > 0) return [player, `${formatCountValue(castCount)} (${(hits / castCount).toFixed(2)})`];
      }
      return [player, formatCountValue(castCount)];
    })), { type: cast.hasOverheal ? "text" : "count", tone: isHealingRow ? "healing" : kind === "aoe" ? "aoeCast" : "classCast" });
  }

  function configuredCooldownRows(className) {
    const cooldowns = rpbConfig.byClass?.[className]?.cooldowns || [];
    const rows = [];
    cooldowns.forEach(cooldown => {
      rows.push(customRow(`${cooldown.name} auf Trash`, Object.fromEntries(playerNames.map(player => [player, "0"])), { tone: "cooldown" }));
      rows.push(customRow(`${cooldown.name} auf Bossen`, Object.fromEntries(playerNames.map(player => [player, "0"])), { tone: "cooldown" }));
      rows.push(customRow(`${cooldown.name} gesamt`, Object.fromEntries(playerNames.map(player => [
        player,
        formatCountValue(classCooldowns[className]?.[cooldown.name]?.[player])
      ])), { tone: "total" }));
    });
    return rows;
  }

  const classSections = rpbClassOrder
    .filter(className => players.some(player => player.className === className))
    .map(className => {
      const classPlayers = players.filter(player => player.className === className).map(player => player.name);
      const config = rpbConfig.byClass?.[className] || { singleTarget: [], aoe: [] };
      const castRows = [
        ...config.singleTarget.map(cast => configuredCastRow(className, cast, "singleTarget")),
        ...config.aoe.map(cast => configuredCastRow(className, cast, "aoe"))
      ];

      const cooldownRows = configuredCooldownRows(className);
      const rows = castRows;
      return {
        id: `class-${className.toLowerCase()}`,
        label: className,
        className,
        description: `${className}: klassenspezifische Casts.`,
        rows: rows.length ? rows : [customRow("Keine Klassencasts erkannt", {}, { tone: "classCast" })],
        cooldownRows,
        playerFilter: classPlayers
      };
    });
  const classSectionByName = new Map(classSections.map(section => [section.className, section]));
  const namesForClasses = classNames => players
    .filter(player => classNames.includes(player.className))
    .map(player => player.name);
  const namesForRolesOrClasses = (roleNames, classNames) => players
    .filter(player => {
      if (player.raidRole === "ignore") return false;
      if (player.raidRole) return roleNames.includes(player.raidRole);
      return classNames.includes(player.className);
    })
    .map(player => player.name);
  const namesForRolesOnly = roleNames => players
    .filter(player => player.raidRole !== "ignore" && player.raidRole && roleNames.includes(player.raidRole))
    .map(player => player.name);
  const roleAwareNames = (roleNames, fallbackClassNames) => {
    const explicit = namesForRolesOnly(roleNames);
    return explicit.length ? explicit : namesForRolesOrClasses(roleNames, fallbackClassNames);
  };
  const rowsForClasses = (classNames, scopeNamesOverride = null) => {
    const rows = [];
    const sections = classNames.map(className => classSectionByName.get(className)).filter(Boolean);
    classNames.forEach(className => {
      const section = classSectionByName.get(className);
      if (!section) return;
      rows.push(headerRow(className, { className }));
      rows.push(...section.rows);
    });
    const scopeNames = Array.isArray(scopeNamesOverride) ? scopeNamesOverride : namesForClasses(classNames);
    if (scopeNames.length) rows.push(...buildActivityRows(scopeNames));
    sections.forEach(section => {
      if (!section.cooldownRows || !section.cooldownRows.length) return;
      rows.push(headerRow("Klassenspezifische Cooldowns", { className: section.className }));
      rows.push(...section.cooldownRows);
    });
    return rows.length ? rows : [customRow("Keine Klassencasts erkannt", {}, { tone: "classCast" })];
  };

  const casterPlayerNames = namesForRolesOrClasses(["caster", "owl", "shadow", "support"], ["Druid", "Mage", "Warlock", "Priest", "Shaman"]);
  const healerPlayerNames = roleAwareNames(["healer"], ["Druid", "Paladin", "Priest", "Shaman"]);
  const physicalPlayerNames = namesForRolesOrClasses(["melee", "cat", "hunter"], ["Druid", "Hunter", "Rogue", "Warrior"]);
  const tankPlayerNames = namesForRolesOrClasses(["main_tank", "off_tank", "tank"], ["Druid", "Paladin", "Warrior"]);

  const totalAbsorbed = {
    label: "Gesamt absorbiert",
    type: "amount",
    tone: "total",
    values: Object.fromEntries(playerNames.map(player => {
      const total = Object.keys(absorbs).reduce((sum, label) => {
        return label.startsWith("Power Word") ? sum : sum + Number(absorbs[label]?.[player] || 0);
      }, 0);
      return [player, formatCountValue(total)];
    }))
  };

  const interruptDetails = {
    label: "Namen und Quellen der unterbrochenen Zauber",
    type: "text",
    values: Object.fromEntries(playerNames.map(player => [
      player,
      interruptNames[player] ? Array.from(interruptNames[player]).join(", ") : ""
    ]))
  };

  const generalRows = [
    headerRow("Stats and Miscellaneous"),
    ...activityRows,
    headerRow("Consumables"),
    ...rpbConsumables.map(([label]) => countRow(label, consumes, { tone: generalConsumableTone(label) })),
    headerRow("Trinkets und Racials"),
    ...(rpbConfig.trinketsAndRacials || []).map(item => countRow(item.name, trinketsAndRacials, { tone: "trinket" })),
    headerRow("Absorbierter Schaden"),
    ...rpbAbsorbs.map(([label]) => amountRow(label, absorbs, { tone: absorbTone(label) })),
    totalAbsorbed,
    headerRow("Engineering etc. (ø = Treffer pro Nutzung)"),
    ...rpbEngineering.map(([label]) => countRow(label, engineeringCounts, { tone: "engineering" })),
    amountRow("Gesamtschaden durch Engineering etc.", engineeringDamage, { tone: "engineeringTotal" }),
    headerRow("Unterbrochene Zauber"),
    countRow("# unterbrochene Zauber", interrupts, { tone: "interrupt" }),
    interruptDetails
  ];

  const claInfoRows = label => [
    headerRow(label),
    customRow("Status", Object.fromEntries(playerNames.map(player => [
      player,
      "Noch nicht aus der CLA-Logik befüllt"
    ])), { type: "text", tone: "muted" })
  ];

  const sections = [
    {
      id: "general",
      label: "Allgemein",
      description: "Sheet-nahe Gesamtübersicht mit Aktivität, Consumables, Absorbs, Engineering und Interrupts.",
      rows: generalRows,
      hideEmptyRows: true,
      compact: true,
      ignoreClassFilter: true
    },
    {
      id: "caster",
      label: "Zauberer",
      description: "Caster-Übersicht: Aktivität und allgemeine Kennzahlen.",
      rows: buildActivityRows(casterPlayerNames),
      playerFilter: casterPlayerNames
    },
    {
      id: "caster-casts",
      label: "Zauberer - Zauber",
      description: "Klassenblöcke für Caster-Casts wie im Sheet.",
      rows: rowsForClasses(["Druid", "Mage", "Warlock", "Priest", "Shaman"], casterPlayerNames),
      playerFilter: casterPlayerNames,
      hideEmptyRows: true
    },
    {
      id: "healer",
      label: "Heiler",
      description: "Heiler-Übersicht mit Healing, Overheal und Aktivität.",
      rows: buildActivityRows(healerPlayerNames).concat(healingRows.slice(0, 3)),
      playerFilter: healerPlayerNames
    },
    {
      id: "healer-casts",
      label: "Heiler - Zauber",
      description: "Heiler-Casts und Overheal pro Spell.",
      rows: rowsForClasses(["Druid", "Paladin", "Priest", "Shaman"], healerPlayerNames),
      playerFilter: healerPlayerNames,
      hideEmptyRows: true
    },
    {
      id: "physical",
      label: "Nahkampf",
      description: "Physical-Übersicht mit Aktivität und allgemeinen Kennzahlen.",
      rows: buildActivityRows(physicalPlayerNames),
      playerFilter: physicalPlayerNames
    },
    {
      id: "physical-casts",
      label: "Nahkampf - Zauber",
      description: "Klassenblöcke für Physical-Casts wie im Sheet.",
      rows: rowsForClasses(["Druid", "Hunter", "Rogue", "Warrior"], physicalPlayerNames),
      playerFilter: physicalPlayerNames,
      hideEmptyRows: true
    },
    {
      id: "tank",
      label: "Tank",
      description: "Tank-nahe Übersicht mit Aktivität und vermeidbarem Schaden.",
      rows: buildActivityRows(tankPlayerNames).concat(rpbAbsorbs.map(([label]) => amountRow(label, absorbs, { tone: "absorb" })).concat(totalAbsorbed)),
      playerFilter: tankPlayerNames
    },
    {
      id: "tank-casts",
      label: "Tank - Zauber",
      description: "Tank-Casts nach Klassenblöcken.",
      rows: rowsForClasses(["Druid", "Paladin", "Warrior"], tankPlayerNames),
      playerFilter: tankPlayerNames,
      hideEmptyRows: true
    },
    {
      id: "cla-gear-issues",
      label: "gear issues",
      description: "CLA: Gear-Probleme und fehlende/auffällige Ausrüstung.",
      rows: buildClaGearIssueRows(),
      hideEmptyRows: true,
      compact: true
    },
    {
      id: "cla-gear-listing",
      label: "gear listing",
      description: "CLA: Ausrüstungsliste pro Spieler.",
      rows: buildClaGearListingRows(),
      hideEmptyRows: true,
      compact: true
    },
    {
      id: "cla-combat-buffs",
      label: "combat buffs",
      description: "CLA: Combat-Buffs, Verbrauchsgüter und Buff-Nutzung.",
      rows: buildClaCombatBuffRows(),
      hideEmptyRows: true,
      compact: true
    },
    {
      id: "cla-ignites",
      label: "ignites",
      description: "CLA: Ignite-Auswertung.",
      rows: buildClaIgniteRows(),
      hideEmptyRows: true,
      compact: true
    },
    {
      id: "cla-world-buffs",
      label: "world buffs",
      description: "CLA: Worldbuff-Übersicht.",
      rows: buildClaWorldBuffRows(),
      hideEmptyRows: true,
      compact: true
    },
    {
      id: "cla-validate",
      label: "validate",
      description: "CLA: Log-Validierung.",
      rows: buildClaValidateRows(),
      compact: true
    }
  ];

  return {
    type: "rpb",
    generatedAt: new Date().toISOString(),
    analysis: normalizeLogAnalysis(analysis),
    report: {
      title: report.title || analysis.title || "",
      raid: report.zone?.name || analysis.raid || "",
      raidDate: report.startTime ? formatDateInBerlin(new Date(Number(report.startTime))) : (analysis.raid_date ? new Date(analysis.raid_date).toISOString().slice(0, 10) : ""),
      reportCode: analysis.report_code || "",
      reportUrl: analysis.report_url || ""
    },
    players: players.map(player => ({
      id: player.id,
      name: player.name,
      server: player.server || "",
      className: player.className || "",
      raidRole: player.raidRole || ""
    })),
    roleOptions: logAnalysisRaidRoleOptions,
    sections,
    warnings: (!castEvents.length && !damageDoneEvents.length && !damageTakenEvents.length && !interruptEvents.length && !healingEvents.length)
      ? ["Keine Detail-Events von Warcraft Logs erhalten."]
      : (!combatantEvents.length ? ["Keine CombatantInfo-Daten von Warcraft Logs erhalten. CLA-Gear kann unvollständig sein."] : [])
  };
}

function raidImporterTableEntries(table) {
  return Array.isArray(table?.entries) ? table.entries : [];
}

function raidImporterTableAuras(table) {
  return Array.isArray(table?.auras) ? table.auras : [];
}

function raidImporterEntryTotal(table, ids, fields = ["total", "uses", "amount", "count"]) {
  const wanted = new Set((ids || []).map(Number).filter(Boolean));
  return raidImporterTableEntries(table).reduce((sum, entry) => {
    if (wanted.size && !wanted.has(abilityIdFromTableEntry(entry))) return sum;
    const value = fields.map(field => Number(entry?.[field] || 0)).find(number => number > 0) || 0;
    return sum + value;
  }, 0);
}

function raidImporterHealingSummary(table, ids = null) {
  const wanted = ids ? new Set(ids.map(Number).filter(Boolean)) : null;
  return raidImporterTableEntries(table).reduce((summary, entry) => {
    if (wanted && !wanted.has(abilityIdFromTableEntry(entry))) return summary;
    const amount = Number(entry.total || entry.amount || 0);
    const overheal = Number(entry.overheal || entry.overhealing || entry.overhealAmount || 0);
    const uses = Number(entry.uses || entry.totalUses || entry.hitCount || entry.tickCount || entry.total || 0);
    const crits = Number(entry.critHitCount || 0) + Number(entry.critTickCount || 0);
    summary.amount += amount;
    summary.overheal += overheal;
    summary.uses += uses;
    summary.crits += crits;
    return summary;
  }, { amount: 0, overheal: 0, uses: 0, crits: 0 });
}

function raidImporterOverhealText(summary) {
  const total = Number(summary.amount || 0) + Number(summary.overheal || 0);
  const pct = total > 0 ? Math.round(Number(summary.overheal || 0) * 100 / total) : 0;
  return summary.uses || total ? `${Math.round(summary.uses || 0)} (${pct}% OH)` : "0";
}

function raidImporterCastOverhealText(castCount, summary) {
  const count = Number(castCount || 0);
  const total = Number(summary.amount || 0) + Number(summary.overheal || 0);
  const pct = total > 0 ? Math.round(Number(summary.overheal || 0) * 100 / total) : 0;
  return count ? `${Math.round(count)} (${pct}% OH)` : "0";
}

function raidImporterAuraUptimePercent(table, ids, totalTime) {
  const wanted = new Set((ids || []).map(Number).filter(Boolean));
  const uptime = raidImporterTableAuras(table).reduce((sum, aura) => {
    if (!wanted.has(Number(aura.guid || aura.id || 0))) return sum;
    return sum + Number(aura.totalUptime || 0);
  }, 0);
  return totalTime > 0 ? Math.round(uptime * 1000 / totalTime) / 10 : 0;
}

function raidImporterAuraNames(table, definitions) {
  const ids = new Set(raidImporterTableAuras(table).map(aura => Number(aura.guid || aura.id || 0)));
  return Object.entries(definitions)
    .filter(([, spellIds]) => spellIds.some(id => ids.has(Number(id))))
    .map(([label]) => label);
}

function raidImporterDefinitionObject(definitions) {
  return Object.fromEntries((definitions || []).map(([label, , ids]) => [label, ids || []]));
}

function raidImporterTrackedCounts(table, definitions) {
  return Object.fromEntries((definitions || []).map(([label, , ids]) => [
    label,
    raidImporterEntryTotal(table, ids || [])
  ]));
}

function raidImporterNonZeroNames(counts) {
  return Object.entries(counts || {})
    .filter(([, value]) => Number(value || 0) > 0)
    .map(([label]) => label);
}

function raidProcessorEntryCount(entry, isAoE = false) {
  let total = Number(entry?.total || entry?.uses || entry?.amount || entry?.count || 0);
  if (isAoE && total === 0 && Array.isArray(entry?.subentries) && Number(entry.subentries[0]?.total || 0) > 0) {
    total = Number(entry.subentries[0].total || 0);
  }
  return total;
}

function raidProcessorTableCount(table, ids, isAoE = false) {
  const wanted = new Set((ids || []).map(Number).filter(Boolean));
  return raidImporterTableEntries(table).reduce((sum, entry) => {
    if (!wanted.has(abilityIdFromTableEntry(entry))) return sum;
    return sum + raidProcessorEntryCount(entry, isAoE);
  }, 0);
}

function raidProcessorOverhealPercent(cast, castsTable, healingTable) {
  if (!cast?.hasOverheal) return 0;
  const ids = new Set((cast.ids || []).map(Number).filter(Boolean));
  const healingById = new Map();
  raidImporterTableEntries(healingTable).forEach(entry => {
    const id = abilityIdFromTableEntry(entry);
    healingById.set(id, {
      amount: Number(entry.total || entry.amount || 0),
      overheal: Number(entry.overheal || entry.overhealing || entry.overhealAmount || 0)
    });
  });
  let weighted = 0;
  let totalCasts = 0;
  let omittedCasts = 0;
  raidImporterTableEntries(castsTable).forEach(entry => {
    const castId = abilityIdFromTableEntry(entry);
    if (!ids.has(castId)) return;
    const count = raidProcessorEntryCount(entry, true);
    if (!count) return;
    const healId = holyNovaHealSpellMap[castId] || castId;
    const healing = healingById.get(healId);
    totalCasts += count;
    if (healing && healing.overheal > 0 && healing.amount + healing.overheal > 0) {
      weighted += (healing.overheal * 100 / (healing.amount + healing.overheal)) * count;
    } else {
      omittedCasts += count;
    }
  });
  const denom = totalCasts - omittedCasts;
  return denom > 0 ? Math.round(weighted / denom) : 0;
}

function raidProcessorAverageHits(cast, castsTable, hitTable, isAoE = false) {
  if (!isAoE) return { averageHits: 0, rawHits: 0, rawCasts: 0 };
  const ids = new Set((cast.ids || []).map(Number).filter(Boolean));
  let rawHits = 0;
  let rawCasts = 0;
  raidImporterTableEntries(castsTable).forEach(castEntry => {
    const castId = abilityIdFromTableEntry(castEntry);
    if (!ids.has(castId)) return;
    const castCount = raidProcessorEntryCount(castEntry, true);
    if (!castCount) return;
    raidImporterTableEntries(hitTable).forEach(hitEntry => {
      const hitId = abilityIdFromTableEntry(hitEntry);
      if (hitId !== castId && !(castId === 13877 && hitId === 22482)) return;
      rawHits += Number(hitEntry.hitCount || 0) + Number(hitEntry.missCount || 0);
      rawCasts += castCount;
    });
  });
  return {
    averageHits: rawCasts > 0 ? Math.round((rawHits / rawCasts) * 100) / 100 : 0,
    rawHits,
    rawCasts
  };
}

function raidProcessorCastResult(cast, tables, isAoE = false) {
  const hitTable = cast?.hasOverheal ? tables.healing : tables.damageDone;
  const hitStats = raidProcessorAverageHits(cast, tables.casts, hitTable, isAoE);
  const amount = raidProcessorTableCount(tables.casts, cast.ids, isAoE);
  return {
    name: cast.name,
    ids: cast.ids,
    hasUptime: Boolean(cast.hasUptime),
    hasOverheal: Boolean(cast.hasOverheal),
    uptimePercent: 0,
    overhealPercent: raidProcessorOverhealPercent(cast, tables.casts, tables.healing),
    amount,
    adjustedAmount: amount,
    uptime: 0,
    castTime: cast.castTime || 0,
    averageHits: hitStats.averageHits,
    rawHits: hitStats.rawHits,
    rawCasts: hitStats.rawCasts,
    lowerRankPercent: 0
  };
}

function raidProcessorConsumableResults(castsTable) {
  return rpbConsumables.map(([name, , ids]) => ({
    name,
    amount: raidProcessorTableCount(castsTable, ids)
  }));
}

function raidProcessorEngineeringResults(castsTable, damageDoneTable) {
  return rpbEngineering.map(([name, , ids]) => {
    const amount = raidProcessorTableCount(castsTable, ids);
    const hitCount = raidImporterTableEntries(damageDoneTable).reduce((sum, entry) => {
      return ids.includes(abilityIdFromTableEntry(entry))
        ? sum + Number(entry.hitCount || 0) + Number(entry.missCount || 0)
        : sum;
    }, 0);
    return { name, amount, hitCount };
  });
}

function raidProcessorDamageTakenResult(damageTakenTable, trackedAbilities) {
  const perAbility = (trackedAbilities || []).map(tracked => raidImporterEntryTotal(damageTakenTable, tracked.ids));
  return {
    perAbility,
    total: perAbility.reduce((sum, value) => sum + Number(value || 0), 0)
  };
}

function raidProcessorDebuffsAppliedResult(debuffsTable, trackedDebuffs) {
  return (trackedDebuffs || []).map(tracked => {
    const amount = raidImporterTableAuras(debuffsTable)
      .filter(aura => tracked.ids.includes(Number(aura.guid || aura.id || 0)))
      .reduce((sum, aura) => sum + Number(aura.totalUses || 0), 0);
    return amount > 0 ? amount : "";
  });
}

function raidProcessorAbsorbResults(buffsTable) {
  const perAbsorb = rpbAbsorbs.map(([, , ids]) => {
    const present = raidImporterAuraNames(buffsTable, raidImporterDefinitionObject([[rpbAbsorbs[0]?.[0] || "", [], ids]])).length > 0;
    return present ? 1 : 0;
  });
  return {
    perAbsorb,
    total: perAbsorb.reduce((sum, value, index) => {
      const label = rpbAbsorbs[index]?.[0] || "";
      return label.startsWith("Power Word") ? sum : sum + Number(value || 0);
    }, 0)
  };
}

function buildRaidPlayerResult({ player, rpbConfig, tables, deaths = [] }) {
  const classConfig = rpbConfig.byClass?.[player.className] || { singleTarget: [], aoe: [], cooldowns: [] };
  const singleTargetCasts = classConfig.singleTarget.map(cast => raidProcessorCastResult(cast, tables, false));
  const aoeCasts = classConfig.aoe.map(cast => raidProcessorCastResult(cast, tables, true));
  const consumables = raidProcessorConsumableResults(tables.casts);
  const engineering = raidProcessorEngineeringResults(tables.casts, tables.damageDone);
  const engineeringDamageTotal = engineering.reduce((sum, item) => {
    const ids = (rpbEngineering.find(([name]) => name === item.name)?.[2]) || [];
    return sum + raidImporterTableEntries(tables.damageDone).reduce((entrySum, entry) => {
      return ids.includes(abilityIdFromTableEntry(entry)) ? entrySum + Number(entry.total || 0) : entrySum;
    }, 0);
  }, 0);
  return {
    playerId: player.id,
    playerName: player.name,
    playerClass: player.className,
    role: player.raidRole || "",
    singleTargetCasts,
    aoeCasts,
    cooldowns: {},
    damageTaken: {
      ...raidProcessorDamageTakenResult(tables.damageTaken, rpbConfig.damageTaken || []),
      deaths: String(deaths.length || "")
    },
    debuffsApplied: raidProcessorDebuffsAppliedResult(tables.debuffs, rpbConfig.debuffsTracked || []),
    trinkets: (rpbConfig.trinketsAndRacials || []).map(item => ({
      name: item.name,
      amount: raidProcessorTableCount(tables.casts, item.ids),
      uptime: 0
    })),
    engineering,
    engineeringDamageTotal,
    consumables,
    absorbs: raidProcessorAbsorbResults(tables.buffs),
    interruptsTotal: 0,
    interruptsDetails: "",
    source: "wcl-tables-player-result-v1"
  };
}

function parseNumberList(value) {
  return String(value || "")
    .split(/[,\s]+/)
    .map(item => Number(String(item).replace("*", "").trim()))
    .filter(number => Number.isFinite(number) && number > 0);
}

async function debugRaidLogAnalysisScopes({ guildId, query: params }) {
  const reportCode = extractWarcraftLogsReportCode(params.reportCode || params.report || params.reportUrl || params.url);
  if (!reportCode) {
    const error = new Error("Warcraft-Logs-Link oder Report-Code fehlt.");
    error.statusCode = 400;
    throw error;
  }
  const base = await fetchReportBaseForAnalysis(reportCode);
  const { token, report, players: rawPlayers, fights, fightIds } = base;
  const playerName = clean(params.playerName || params.player || "");
  const playerId = Number(params.playerId || 0);
  const player = rawPlayers.find(item => playerId > 0 ? Number(item.id) === playerId : clean(item.name).toLowerCase() === playerName.toLowerCase());
  if (!player) {
    const error = new Error("Spieler wurde im Warcraft-Logs-Report nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }
  const ids = parseNumberList(params.ids || params.spellIds);
  const rpbFights = rpbIncludedFightsForAnalysis(fights);
  const rpbFightScope = rpbFights.length ? rpbFights.map(fight => Number(fight.id)) : fightIds;
  const reportDurationMs = Math.max(0, Number(report.endTime || 0) - Number(report.startTime || 0));
  const fullTimeScope = reportDurationMs > 0 ? { startTime: 0, endTime: reportDurationMs } : null;
  async function tableSummary(label, dataType, scope, options) {
    const table = await fetchReportTableForAnalysis(token, reportCode, dataType, scope, { ...options, strict: true });
    return {
      label,
      dataType,
      totalForIds: ids.length ? raidImporterEntryTotal(table, ids) : null,
      totalEntries: raidImporterTableEntries(table).reduce((sum, entry) => sum + Number(entry.total || entry.uses || entry.amount || entry.count || 0), 0),
      matchedEntries: ids.length ? raidImporterTableEntries(table)
        .filter(entry => ids.includes(abilityIdFromTableEntry(entry)))
        .map(entry => ({
          id: abilityIdFromTableEntry(entry),
          name: clean(entry.name),
          total: Number(entry.total || 0),
          uses: Number(entry.uses || 0),
          amount: Number(entry.amount || 0),
          hitCount: Number(entry.hitCount || 0),
          overheal: Number(entry.overheal || entry.overhealing || entry.overhealAmount || 0)
        })) : []
    };
  }
  return {
    success: true,
    report: {
      code: reportCode,
      title: report.title || "",
      durationMs: reportDurationMs,
      fights: fights.length,
      rpbFights: rpbFights.length
    },
    player: {
      id: player.id,
      name: player.name,
      className: player.className || player.subType || player.type || ""
    },
    ids,
    scopes: [
      await tableSummary("fightIDs", "Casts", rpbFightScope, { sourceId: player.id }),
      await tableSummary("full report time", "Casts", fullTimeScope, { sourceId: player.id }),
      await tableSummary("unfiltered", "Casts", null, { sourceId: player.id }),
      await tableSummary("healing full report time", "Healing", fullTimeScope, { sourceId: player.id }),
      await tableSummary("healing unfiltered", "Healing", null, { sourceId: player.id })
    ]
  };
}

function raidImporterGearSlotName(slot) {
  const names = {
    0: "Head",
    1: "Neck",
    2: "Shoulders",
    3: "Shirt",
    4: "Chest",
    5: "Waist",
    6: "Legs",
    7: "Feet",
    8: "Bracers",
    9: "Hands",
    10: "Ring1",
    11: "Ring2",
    12: "Trinket1",
    13: "Trinket2",
    14: "Cloak",
    15: "Weapon",
    16: "Off-Hand",
    17: "Wand/Idol/Relic etc."
  };
  return names[Number(slot)] || clean(slot);
}

function raidImporterEnchantIssue(item, playerClass = "") {
  const slot = Number(item?.slot);
  const itemName = clean(item?.name);
  const enchantName = clean(item?.permanentEnchantName || item?.permanentEnchant);
  const lower = `${itemName} ${enchantName}`.toLowerCase();
  if (lower.includes("undead") || lower.includes("scourge")) {
    return "vs. undead item/enchant used on non-undead";
  }
  const enchantableSlots = new Set([0, 2, 4, 7, 8, 9, 14, 15]);
  if (enchantableSlots.has(slot) && !enchantName) return "no enchant on this item";
  if (slot === 9 && Number(item?.permanentEnchant) === 2617 && playerClass === "Priest") {
    return "has an enchant that is considered suboptimal";
  }
  return "";
}

function raidImporterGearFromCombatantInfo(combatantInfo, playerClass = "") {
  return (Array.isArray(combatantInfo?.gear) ? combatantInfo.gear : [])
    .filter(item => Number(item?.id || item?.itemID || item?.itemId || 0) > 0)
    .map(item => ({
      slot: raidImporterGearSlotName(item.slot),
      itemId: Number(item.id || item.itemID || item.itemId || 0),
      name: clean(item.name),
      quality: item.quality || "",
      permanentEnchant: item.permanentEnchant || "",
      permanentEnchantName: clean(item.permanentEnchantName),
      temporaryEnchant: item.temporaryEnchant || "",
      temporaryEnchantName: clean(item.temporaryEnchantName),
      issue: raidImporterEnchantIssue(item, playerClass)
    }));
}

async function importRaidLogAnalysis({ guildId, query: params }) {
  const reportCode = extractWarcraftLogsReportCode(params.reportCode || params.report || params.reportUrl || params.url);
  if (!reportCode) {
    const error = new Error("Warcraft-Logs-Link oder Report-Code fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const rpbConfig = await loadRpbConfigAll();
  const classByName = await getGuildClassMap(guildId);
  const base = await fetchReportBaseForAnalysis(reportCode);
  const { token, report, players: rawPlayers, fights, fightIds } = base;
  let players = rawPlayers.map(player => ({
    ...player,
    className: normalizeRpbClassName(classByName.get(clean(player.name).toLowerCase()) || player.className) || "Unknown"
  })).sort((a, b) => a.name.localeCompare(b.name, "de"));
  const rpbFights = rpbIncludedFightsForAnalysis(fights);
  const rpbFightScope = rpbFights.length ? rpbFights.map(fight => Number(fight.id)) : fightIds;
  const bossFights = rpbFights.filter(fight => Number(fight.encounterID || 0) > 0);
  const bossFightIds = new Set(bossFights.map(fight => Number(fight.id)));
  const lastBossFight = bossFights[bossFights.length - 1] || rpbFights[rpbFights.length - 1] || fights[fights.length - 1];
  const gearScope = lastBossFight
    ? { startTime: Number(lastBossFight.startTime || 0), endTime: Number(lastBossFight.endTime || 0) }
    : rpbFightScope;
  const rpbStartTime = rpbFights.length ? Math.min(...rpbFights.map(fight => Number(fight.startTime || 0))) : 0;
  const rpbEndTime = rpbFights.length ? Math.max(...rpbFights.map(fight => Number(fight.endTime || 0))) : Math.max(0, Number(report.endTime || 0) - Number(report.startTime || 0));
  const rpbTimeScope = rpbEndTime > rpbStartTime ? { startTime: rpbStartTime, endTime: rpbEndTime } : rpbFightScope;
  const reportDurationMs = Math.max(0, Number(report.endTime || 0) - Number(report.startTime || 0));
  const fullReportScope = reportDurationMs > 0 ? { startTime: 0, endTime: reportDurationMs } : (fightIds.length ? fightIds : rpbTimeScope);
  const activityScope = fullReportScope;
  const reportInfo = {
    code: reportCode,
    url: normalizeWarcraftLogsReportUrl(params.reportUrl || params.url || "", reportCode),
    title: report.title || "",
    raid: report.zone?.name || "",
    raidDate: report.startTime ? formatDateInBerlin(new Date(Number(report.startTime))) : "",
    includedFights: rpbFights.length,
    bossFights: bossFights.length,
    gearSnapshotFight: lastBossFight ? lastBossFight.name : "",
    scopeRule: "activity values use full report WCL table time range; gear from last included boss"
  };
  if (String(params.listOnly || params.playersOnly || "") === "1") {
    return {
      success: true,
      importer: "wcl-raid-player-analysis-v1",
      listOnly: true,
      report: reportInfo,
      players: players.map(player => ({
        id: player.id,
        name: player.name,
        server: player.server || "",
        className: player.className
      }))
    };
  }
  const wantedPlayerId = Number(params.playerId || 0);
  const wantedPlayerName = clean(params.playerName || params.player || "").toLowerCase();
  if (wantedPlayerId > 0 || wantedPlayerName) {
    players = players.filter(player => {
      if (wantedPlayerId > 0) return Number(player.id) === wantedPlayerId;
      return clean(player.name).toLowerCase() === wantedPlayerName;
    });
    if (!players.length) {
      const error = new Error("Spieler wurde im Warcraft-Logs-Report nicht gefunden.");
      error.statusCode = 404;
      throw error;
    }
  }
  const allDeaths = await fetchReportEventsForAnalysis(token, reportCode, "Deaths", activityScope);
  const worldBuffDefinitions = {
    "Nef/Ony": [22888, 355363],
    Rend: [16609, 355366, 460940],
    "ZG heart": [24425, 355365],
    Songflower: [15366],
    "Mol'dar": [22818],
    Fengus: [22817],
    "Slip'kik": [22820],
    DMF: [23736, 23735, 23737, 23738, 23769, 23766, 23768, 23767],
    "Zanza/BL": [24417, 24382, 24383, 10667, 10668, 10669, 10692, 10693]
  };
  const consumableDefinitions = raidImporterDefinitionObject(rpbConsumables);
  const absorbDefinitions = raidImporterDefinitionObject(rpbAbsorbs);
  const engineeringDefinitions = raidImporterDefinitionObject(rpbEngineering);
  const avoidableDamageDefinitions = {
    "Cleave": [797, 3433, 3434, 3435, 5532, 11427, 15284, 15496, 15579, 15584, 15613, 15622, 15623, 15663, 16044, 17685, 19632, 19642, 20571, 20605, 20666, 20677, 20684, 20691, 22540, 26350, 27794, 19983, 845, 7369, 11608, 11609, 20569],
    "Bomb": [8858, 9143, 22334]
  };

  const importedPlayers = [];
  const concurrency = 1;
  let index = 0;
  async function worker() {
    while (index < players.length) {
      const player = players[index++];
      const [castsTable, healingTable, damageDoneTable, damageTakenTable, buffsTable, debuffsTable, summaryTable] = await Promise.all([
        fetchReportTableForAnalysis(token, reportCode, "Casts", activityScope, { sourceId: player.id, strict: true }),
        fetchReportTableForAnalysis(token, reportCode, "Healing", activityScope, { sourceId: player.id, strict: true }),
        fetchReportTableForAnalysis(token, reportCode, "DamageDone", activityScope, { sourceId: player.id, strict: true }),
        fetchReportTableForAnalysis(token, reportCode, "DamageTaken", activityScope, { targetId: player.id, strict: true }),
        fetchReportTableForAnalysis(token, reportCode, "Buffs", activityScope, { targetId: player.id, strict: true }),
        fetchReportTableForAnalysis(token, reportCode, "Debuffs", activityScope, { targetId: player.id, strict: true }),
        fetchReportTableForAnalysis(token, reportCode, "Summary", gearScope, { sourceId: player.id, strict: true })
      ]);

      const classConfig = rpbConfig.byClass?.[player.className] || { singleTarget: [], aoe: [], cooldowns: [] };
      const casts = {};
      [...classConfig.singleTarget, ...classConfig.aoe].forEach(cast => {
        casts[cast.name] = raidImporterEntryTotal(castsTable, cast.ids);
      });
      const cooldowns = {};
      classConfig.cooldowns.forEach(cooldown => {
        cooldowns[cooldown.name] = raidImporterEntryTotal(castsTable, cooldown.ids);
      });
      const trinketsAndRacials = {};
      (rpbConfig.trinketsAndRacials || []).forEach(item => {
        const total = raidImporterEntryTotal(castsTable, item.ids);
        if (total) trinketsAndRacials[item.name] = total;
      });

      const healing = {
        total: raidImporterHealingSummary(healingTable),
        bySpell: {},
        byConfiguredCast: {}
      };
      raidImporterTableEntries(healingTable).forEach(entry => {
        const label = clean(entry.name) || String(abilityIdFromTableEntry(entry));
        healing.bySpell[label] = raidImporterHealingSummary({ entries: [entry] });
      });
      [...classConfig.singleTarget, ...classConfig.aoe].filter(cast => cast.hasOverheal).forEach(cast => {
        healing.byConfiguredCast[cast.name] = raidImporterCastOverhealText(
          raidImporterEntryTotal(castsTable, cast.ids),
          raidImporterHealingSummary(healingTable, cast.ids)
        );
      });

      const criticalOutgoing = raidImporterTableEntries(damageDoneTable).reduce((sum, entry) => sum + Number(entry.critHitCount || 0) + Number(entry.critTickCount || 0), 0);
      const resistOutgoing = raidImporterTableEntries(damageDoneTable).reduce((sum, entry) => {
        const resistedHits = (entry.hitdetails || []).reduce((hitSum, detail) => /resisted/i.test(clean(detail.type)) ? hitSum + Number(detail.count || 0) : hitSum, 0);
        const resists = (entry.missdetails || []).reduce((missSum, detail) => /resist/i.test(clean(detail.type)) ? missSum + Number(detail.count || 0) : missSum, 0);
        return sum + resistedHits + resists;
      }, 0);
      const damageTakenAbilities = {};
      raidImporterTableEntries(damageTakenTable).forEach(entry => {
        (entry.abilities || []).forEach(ability => {
          const label = clean(ability.name) || String(ability.guid || "");
          damageTakenAbilities[label] = (damageTakenAbilities[label] || 0) + Number(ability.total || 0);
        });
      });
      const avoidableDamage = {};
      Object.entries(avoidableDamageDefinitions).forEach(([label, ids]) => {
        const wanted = new Set(ids.map(Number));
        avoidableDamage[label] = raidImporterTableEntries(damageTakenTable).reduce((sum, entry) => {
          return sum + (entry.abilities || []).reduce((abilitySum, ability) => {
            return wanted.has(Number(ability.guid || 0)) ? abilitySum + Number(ability.total || 0) : abilitySum;
          }, 0);
        }, 0);
      });
      (rpbConfig.damageTaken || []).forEach(tracked => {
        avoidableDamage[tracked.name] = raidImporterEntryTotal(damageTakenTable, tracked.ids);
      });
      const totalDamageTaken = raidImporterTableEntries(damageTakenTable).reduce((sum, entry) => sum + Number(entry.total || 0), 0);
      const combatantInfo = summaryTable?.combatantInfo || {};
      const gear = raidImporterGearFromCombatantInfo(combatantInfo, player.className);
      const consumableCounts = raidImporterTrackedCounts(castsTable, rpbConsumables);
      const absorbBuffs = raidImporterAuraNames(buffsTable, absorbDefinitions);
      const absorbCounts = Object.fromEntries(rpbAbsorbs.map(([label, , ids]) => [
        label,
        absorbBuffs.includes(label) ? 1 : raidImporterEntryTotal(buffsTable, ids || [])
      ]));
      const engineeringCounts = raidImporterTrackedCounts(castsTable, rpbEngineering);
      const consumables = Array.from(new Set([
        ...raidImporterAuraNames(buffsTable, consumableDefinitions),
        ...raidImporterNonZeroNames(consumableCounts)
      ]));
      const worldBuffs = raidImporterAuraNames(buffsTable, worldBuffDefinitions);
      const playerDeaths = allDeaths.filter(event => eventSourceId(event) === Number(player.id) || eventTargetId(event) === Number(player.id));
      const worldBuffsLostDueToDying = playerDeaths.some(event => bossFightIds.has(Number(event.fight || event.fightID || event.fightId))) && worldBuffs.length > 0;
      const playerResult = buildRaidPlayerResult({
        player,
        rpbConfig,
        tables: {
          casts: castsTable,
          healing: healingTable,
          damageDone: damageDoneTable,
          damageTaken: damageTakenTable,
          buffs: buffsTable,
          debuffs: debuffsTable
        },
        deaths: playerDeaths
      });

      importedPlayers.push({
        id: player.id,
        name: player.name,
        server: player.server || "",
        className: player.className,
        stats: {
          battleShoutUptimePercent: raidImporterAuraUptimePercent(buffsTable, [6673, 5242, 6192, 11549, 11550, 11551, 25289], Number(buffsTable.totalTime || 0)),
          criticalHealsDone: healing.total.crits,
          criticalOutgoing,
          resistOutgoing,
          deathsTotal: playerDeaths.length,
          worldBuffsLostDueToDying
        },
        casts,
        cooldowns,
        trinketsAndRacials,
        healing,
        damageTaken: {
          total: totalDamageTaken,
          abilities: damageTakenAbilities,
          avoidable: avoidableDamage
        },
        buffs: {
          consumables,
          worldBuffs,
          rawAuras: raidImporterTableAuras(buffsTable).map(aura => ({
            id: Number(aura.guid || 0),
            name: clean(aura.name),
            totalUses: Number(aura.totalUses || 0),
            totalUptime: Number(aura.totalUptime || 0)
          }))
        },
        debuffs: raidImporterTableAuras(debuffsTable).map(aura => ({
          id: Number(aura.guid || 0),
          name: clean(aura.name),
          totalUses: Number(aura.totalUses || 0),
          totalUptime: Number(aura.totalUptime || 0)
        })),
        trackedDebuffs: Object.fromEntries((rpbConfig.debuffsTracked || []).map(tracked => [
          tracked.name,
          raidImporterTableAuras(debuffsTable)
            .filter(aura => tracked.ids.includes(Number(aura.guid || aura.id || 0)))
            .reduce((sum, aura) => sum + Number(aura.totalUses || 0), 0)
        ])),
        general: {
          consumables: consumableCounts,
          absorbs: absorbCounts,
          engineering: engineeringCounts
        },
        gear,
        enchantIssues: gear.filter(item => item.issue),
        playerResult
      });
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, players.length) }, () => worker()));
  importedPlayers.sort((a, b) => a.name.localeCompare(b.name, "de"));

  return {
    success: true,
    importer: "wcl-raid-player-analysis-v1",
    generatedAt: new Date().toISOString(),
    sources: {
      casts: "WarcraftLogs table(Casts) per player",
      healing: "WarcraftLogs table(Healing) per player",
      damageDone: "WarcraftLogs table(DamageDone) per player",
      damageTaken: "WarcraftLogs table(DamageTaken) per player",
      buffs: "WarcraftLogs table(Buffs) per player",
      debuffs: "WarcraftLogs table(Debuffs) per player",
      gear: "WarcraftLogs table(Summary) gear snapshot",
      deaths: "WarcraftLogs events(Deaths)",
      playerResult: "processor-shaped object based on CastsProcessor/DamageProcessor/OutputBuilder"
    },
    report: reportInfo,
    players: importedPlayers
  };
}

async function buildLogAnalysisRows(analysis, type) {
  try {
    return type === "cla" ? await buildClaAnalysisRows(analysis) : await buildRpbAnalysisRows(analysis);
  } catch (error) {
    console.warn("Loganalyse konnte nicht vollständig erzeugt werden:", error.message || error);
    return buildLogAnalysisFallbackRows(analysis, type, error);
  }
}

function buildLogAnalysisFallbackRows(analysis, type, error = null) {
  const summary = analysis.summary || {};
  const kind = type === "cla" ? "CLA" : "RPB";
  const generatedAt = new Date().toISOString();
  const raid = analysis.raid || summary.raid || "Nicht erkannt";
  const raidDate = analysis.raid_date ? new Date(analysis.raid_date).toISOString().slice(0, 10) : (summary.raidDate || "");
  const title = analysis.title || "";
  return [
    [`${kind} Loganalyse`],
    [],
    ["Feld", "Wert"],
    ["Typ", kind],
    ["Raid", raid],
    ["Datum", raidDate || "-"],
    ["Warcraft-Logs-Code", analysis.report_code || ""],
    ["Warcraft-Logs-Link", analysis.report_url || ""],
    ["Titel", title],
    ["Erstellt am", generatedAt],
    [],
    ["Auswertung", "Hinweis"],
    [
      type === "cla" ? "CLA" : "RPB",
      "Die Datei wurde aus dem gespeicherten Warcraft-Logs-Report in LichtLoot erzeugt. Detailwerte koennen hier erweitert werden, sobald die gewuenschten Bewertungsregeln feststehen."
    ],
    ...(error ? [["Hinweis", error.message || String(error)]] : [])
  ];
}

async function buildLogAnalysisCsv(analysis, type) {
  return buildCsv(await buildLogAnalysisRows(analysis, type));
}

async function getPublicLogAnalysisWeb({ guildId, query: params }) {
  await ensureLogAnalysisSheetExportsTable();
  const id = clean(params.id || params.analysisId);
  const type = clean(params.type || params.analysisType || "combined").toLowerCase();
  if (!isUuid(id)) {
    const error = new Error("Loganalyse-ID fehlt.");
    error.statusCode = 400;
    throw error;
  }
  if (!["rpb", "cla", "combined"].includes(type)) {
    const error = new Error("Unbekannter Analyse-Typ.");
    error.statusCode = 400;
    throw error;
  }
  const result = await query(
    `select *
     from log_analyses
     where guild_id = $1 and id = $2
     limit 1`,
    [guildId, id]
  );
  if (!result.rows.length) {
    const error = new Error("Loganalyse wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }
  if (type === "combined") {
    const rpb = await buildStoredSheetWebAnalysis(result.rows[0], "rpb");
    const cla = await buildStoredSheetWebAnalysis(result.rows[0], "cla");
    if (rpb || cla) {
      return {
        success: true,
        webAnalysis: {
          type: "combined",
          source: "sheet-export",
          analysis: normalizeLogAnalysis(result.rows[0]),
          report: (rpb || cla)?.report || {},
          rpb,
          cla
        }
      };
    }
    const combatLogAnalysis = await buildStoredCombatLogWebAnalysis(result.rows[0], "rpb", guildId);
    if (combatLogAnalysis) {
      return {
        success: true,
        webAnalysis: {
          type: "combined",
          source: "combat-log",
          analysis: normalizeLogAnalysis(result.rows[0]),
          report: combatLogAnalysis.report || {},
          rpb: combatLogAnalysis,
          cla: null
        }
      };
    }
  } else {
    const sheetAnalysis = await buildStoredSheetWebAnalysis(result.rows[0], type);
    if (sheetAnalysis) {
      return {
        success: true,
        webAnalysis: sheetAnalysis
      };
    }
    const combatLogAnalysis = await buildStoredCombatLogWebAnalysis(result.rows[0], type, guildId);
    if (combatLogAnalysis) {
      return {
        success: true,
        webAnalysis: combatLogAnalysis
      };
    }
  }
  {
    const error = new Error("Für diese Auswertung wurden noch keine Detaildaten gespeichert.");
    error.statusCode = 404;
    throw error;
  }
}

async function getPublicLogAnalysisWebLegacy({ guildId, query: params }) {
  await ensureLogAnalysisSheetExportsTable();
  await ensureCombatLogImportsTable();
  const id = clean(params.id || params.analysisId);
  const type = clean(params.type || params.analysisType || "rpb").toLowerCase();
  if (!isUuid(id)) {
    const error = new Error("Loganalyse-ID fehlt.");
    error.statusCode = 400;
    throw error;
  }
  if (!["rpb", "cla"].includes(type)) {
    const error = new Error("Unbekannter Analyse-Typ.");
    error.statusCode = 400;
    throw error;
  }
  const result = await query(
    `select *
     from log_analyses
     where guild_id = $1 and id = $2
     limit 1`,
    [guildId, id]
  );
  if (!result.rows.length) {
    const error = new Error("Loganalyse wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }
  const sheetAnalysis = await buildStoredSheetWebAnalysis(result.rows[0], type);
  if (sheetAnalysis) {
    return {
      success: true,
      webAnalysis: sheetAnalysis
    };
  }
  const combatLogAnalysis = await buildStoredCombatLogWebAnalysis(result.rows[0], type, guildId);
  if (combatLogAnalysis) {
    return {
      success: true,
      webAnalysis: combatLogAnalysis
    };
  }
  if (type !== "rpb") {
    const error = new Error("Für diese Auswertung wurden noch keine Sheet-Daten exportiert.");
    error.statusCode = 404;
    throw error;
  }
  const classByName = await getGuildClassMap(guildId);
  const roleByName = new Map(Object.entries(result.rows[0].summary?.raidRoles || {}).map(([name, role]) => [
    clean(name).toLowerCase(),
    normalizeLogAnalysisRaidRole(role)
  ]));
  return {
    success: true,
    webAnalysis: await buildRpbWebAnalysis(result.rows[0], { classByName, roleByName })
  };
}

async function ensureCombatLogImportsTable() {
  await ensureLogAnalysesTable();
  await query(
    `create table if not exists log_analysis_combat_imports (
       id uuid primary key default gen_random_uuid(),
       analysis_id uuid not null references log_analyses(id) on delete cascade,
       file_name text,
       payload jsonb not null default '{}'::jsonb,
       created_at timestamptz not null default now(),
       updated_at timestamptz not null default now(),
       unique (analysis_id)
     )`
  );
  await query(
    `create index if not exists log_analysis_combat_imports_analysis_idx
     on log_analysis_combat_imports (analysis_id)`
  );
}

function combatLogDateToIso(value) {
  const match = clean(value).match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  if (!match) return "";
  return `${match[3]}-${String(match[1]).padStart(2, "0")}-${String(match[2]).padStart(2, "0")}`;
}

function normalizeCombatLogRaidName(value) {
  const text = clean(value);
  const lower = text.toLowerCase();
  if (lower.includes("geschmolzener kern") || lower.includes("molten core")) return "MC";
  if (lower.includes("pechschwingenhort") || lower.includes("blackwing")) return "BWL";
  if (lower.includes("naxx")) return "Naxx";
  if (lower.includes("ahn'qiraj") || lower.includes("aq40")) return "AQ40";
  if (lower.includes("zul'gurub") || lower.includes("zg")) return "ZG";
  return text || "CombatLog";
}

async function parseCombatLogTextSafe(text, options = {}) {
  try {
    const parser = await import("./combat-log-parser.js");
    return parser.parseCombatLogText(text, options);
  } catch (error) {
    const wrapped = new Error("CombatLog-Parser konnte nicht geladen werden. Bitte Deployment-Dateien prüfen.");
    wrapped.statusCode = 500;
    wrapped.cause = error;
    throw wrapped;
  }
}

async function importCombatLogAnalysis({ guildId, query: params, text }) {
  requireMasterCode(params.masterCode);
  await ensureCombatLogImportsTable();
  const logText = String(text || params.logText || "");
  if (!logText.trim()) {
    const error = new Error("CombatLog-Datei fehlt.");
    error.statusCode = 400;
    throw error;
  }
  const fileName = clean(params.fileName || params.filename || "WoWCombatLog.txt");
  const parsed = await parseCombatLogTextSafe(logText, { fileName });
  const classByName = await getGuildClassMap(guildId);
  const roleByName = new Map();
  const summaryRoles = {};

  Object.values(parsed.players || {}).forEach(player => {
    const key = clean(player.name).toLowerCase();
    const className = normalizeRpbClassName(classByName.get(key)) || normalizeRpbClassName(player.className) || "Unknown";
    player.className = className;
  });
  parsed.playerList = Object.values(parsed.players || {})
    .sort((a, b) => a.name.localeCompare(b.name, "de"))
    .map(player => ({
      name: player.name,
      guid: player.guid || "",
      className: player.className || "Unknown",
      raidRole: roleByName.get(clean(player.name).toLowerCase()) || "",
      activeSeconds: player.activeSeconds || 0,
      castTotal: player.castTotal || 0,
      healingDone: player.healingDone || 0,
      overheal: player.overheal || 0,
      overhealPercent: player.overhealPercent || 0,
      healEvents: player.healEvents || 0
    }));

  const raid = normalizeCombatLogRaidName(parsed.zone || parsed.raid);
  const raidDate = combatLogDateToIso(parsed.startedAt);
  const reportCode = `combatlog-${Date.now()}-${randomUUID().slice(0, 8)}`;
  const reportUrl = `combat-log://${encodeURIComponent(fileName)}`;
  const title = clean(params.title) || `${raid} CombatLog`;
  const summary = {
    source: "combat-log",
    raid,
    raidDate,
    fileName,
    encounters: parsed.encounters.length,
    players: parsed.playerList.length,
    casts: parsed.totals.casts,
    heals: parsed.totals.heals,
    buffs: parsed.totals.buffs,
    raidRoles: summaryRoles
  };
  const saved = await query(
    `insert into log_analyses (
       guild_id, report_code, report_url, title, raid, raid_date, status, summary, updated_at, analyzed_at
     )
     values ($1,$2,$3,$4,$5,nullif($6,'')::date,'combatlog_imported',$7::jsonb,now(),now())
     returning *`,
    [guildId, reportCode, reportUrl, title, raid, raidDate, JSON.stringify(summary)]
  );
  await query(
    `insert into log_analysis_combat_imports (analysis_id, file_name, payload, updated_at)
     values ($1,$2,$3::jsonb,now())
     on conflict (analysis_id) do update
       set file_name = excluded.file_name,
           payload = excluded.payload,
           updated_at = now()`,
    [saved.rows[0].id, fileName, JSON.stringify(parsed)]
  );
  return {
    success: true,
    analysis: normalizeLogAnalysis(saved.rows[0]),
    summary,
    webUrl: `web-auswertung.html?id=${encodeURIComponent(saved.rows[0].id)}`
  };
}

async function buildStoredCombatLogWebAnalysis(analysis, type, guildId) {
  if (type !== "rpb") return null;
  const result = await query(
    `select payload
     from log_analysis_combat_imports
     where analysis_id = $1
     limit 1`,
    [analysis.id]
  );
  if (!result.rows.length) return null;
  return buildCombatLogWebAnalysis(analysis, result.rows[0].payload || {}, guildId);
}

async function buildCombatLogWebAnalysis(analysis, payload, guildId) {
  const classByName = await getGuildClassMap(guildId);
  const roleByName = new Map(Object.entries(analysis.summary?.raidRoles || {}).map(([name, role]) => [
    clean(name).toLowerCase(),
    normalizeLogAnalysisRaidRole(role)
  ]));
  const players = Object.values(payload.players || {}).map(player => {
    const key = clean(player.name).toLowerCase();
    return {
      id: player.guid || player.name,
      name: player.name,
      server: "",
      className: normalizeRpbClassName(classByName.get(key)) || normalizeRpbClassName(player.className) || "Unknown",
      raidRole: normalizeLogAnalysisRaidRole(roleByName.get(key) || player.raidRole)
    };
  }).sort((a, b) => {
    const aIndex = rpbClassOrder.includes(a.className) ? rpbClassOrder.indexOf(a.className) : 999;
    const bIndex = rpbClassOrder.includes(b.className) ? rpbClassOrder.indexOf(b.className) : 999;
    if (aIndex !== bIndex) return aIndex - bIndex;
    return a.name.localeCompare(b.name, "de");
  });
  const playerNames = players.map(player => player.name);
  const rawByName = new Map(Object.values(payload.players || {}).map(player => [player.name, player]));
  const valuesFor = fn => Object.fromEntries(playerNames.map(name => [name, fn(rawByName.get(name) || {})]));
  const row = (label, values, options = {}) => ({ label, type: options.type || "count", tone: options.tone || "", values });
  const headerRow = (label, options = {}) => ({ label, type: "header", tone: "sectionHeader", className: options.className || "", values: {} });
  const rowsToMatrix = rows => [
    ["Wert", ...playerNames],
    ...(Array.isArray(rows) ? rows : []).map(entry => [
      entry?.label || "",
      ...playerNames.map(name => entry?.values?.[name] ?? "")
    ])
  ];
  const withMatrix = section => ({
    ...section,
    matrix: section.matrix || { values: rowsToMatrix(section.rows || []) }
  });
  const activityRows = [
    row("Sekunden aktiv", valuesFor(player => player.activeSeconds || ""), { tone: "activity" }),
    row("Casts gesamt", valuesFor(player => player.castTotal || ""), { tone: "activity" }),
    row("Heilung", valuesFor(player => player.healingDone || ""), { tone: "heal" }),
    row("Overheal", valuesFor(player => player.overheal || ""), { tone: "heal" }),
    row("Overheal %", valuesFor(player => player.overhealPercent ? `${player.overhealPercent}%` : ""), { tone: "heal" })
  ];
  const classRows = classNames => {
    const rows = [];
    classNames.forEach(className => {
      const classPlayers = players.filter(player => player.className === className).map(player => player.name);
      if (!classPlayers.length) return;
      const spellNames = new Set();
      classPlayers.forEach(name => {
        Object.keys(rawByName.get(name)?.casts || {}).forEach(spell => spellNames.add(spell));
      });
      rows.push(headerRow(className, { className }));
      [...spellNames].sort((a, b) => a.localeCompare(b, "de")).forEach(spell => {
        rows.push(row(spell, Object.fromEntries(playerNames.map(name => [
          name,
          classPlayers.includes(name) ? (rawByName.get(name)?.casts?.[spell] || "") : ""
        ])), { tone: "classCast" }));
      });
    });
    return rows;
  };
  const healerRows = () => {
    const healerNames = players
      .filter(player => player.raidRole === "healer" || (!player.raidRole && ["Druid", "Paladin", "Priest", "Shaman"].includes(player.className)))
      .map(player => player.name);
    const spells = new Set();
    healerNames.forEach(name => Object.keys(rawByName.get(name)?.healing || {}).forEach(spell => spells.add(spell)));
    const rows = [
      headerRow("Heiler"),
      ...activityRows.filter(item => ["Sekunden aktiv", "Heilung", "Overheal", "Overheal %"].includes(item.label))
    ];
    [...spells].sort((a, b) => a.localeCompare(b, "de")).forEach(spell => {
      rows.push(row(`${spell} (overheal%)`, Object.fromEntries(playerNames.map(name => {
        if (!healerNames.includes(name)) return [name, ""];
        const data = rawByName.get(name)?.healing?.[spell];
        if (!data) return [name, ""];
        const total = Number(data.amount || 0) + Number(data.overheal || 0);
        const percent = total > 0 ? Math.round(Number(data.overheal || 0) * 100 / total) : 0;
        return [name, `${data.casts || 0} (${percent}%)`];
      })), { tone: "heal" }));
    });
    return rows;
  };
  const buffTotals = new Map();
  playerNames.forEach(name => {
    Object.entries(rawByName.get(name)?.buffs || {}).forEach(([spell, count]) => {
      buffTotals.set(spell, Number(buffTotals.get(spell) || 0) + Number(count || 0));
    });
  });
  const buffRows = [...buffTotals.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "de"))
    .slice(0, 120)
    .map(([spell]) => row(spell, Object.fromEntries(playerNames.map(name => [
      name,
      rawByName.get(name)?.buffs?.[spell] || ""
    ])), { tone: "buff" }));
  const encounterRows = Array.isArray(payload.encounters) ? payload.encounters.map(encounter => [
    encounter.name || encounter.boss || "Boss",
    encounter.startedAt || encounter.start || "",
    encounter.endedAt || encounter.end || "",
    encounter.success === true ? "Ja" : (encounter.success === false ? "Nein" : "")
  ]) : [];
  const sections = [
    { id: "general", label: "Allgemein", rows: [headerRow("CombatLog"), ...activityRows], compact: true, ignoreClassFilter: true },
    { id: "bosses", label: "Bosskämpfe", matrix: { values: [["Boss", "Start", "Ende", "Erfolg"], ...encounterRows] }, compact: true, ignoreClassFilter: true },
    { id: "buffs", label: "Buffs", rows: [headerRow("Buffs"), ...buffRows], hideEmptyRows: true },
    { id: "caster-casts", label: "Zauberer - Zauber", rows: classRows(["Druid", "Mage", "Warlock", "Priest", "Shaman"]), hideEmptyRows: true },
    { id: "healer", label: "Heiler", rows: healerRows(), hideEmptyRows: true },
    { id: "healer-casts", label: "Heiler - Zauber", rows: healerRows(), hideEmptyRows: true },
    { id: "physical-casts", label: "Nahkampf - Zauber", rows: classRows(["Druid", "Hunter", "Rogue", "Warrior"]), hideEmptyRows: true },
    { id: "tank-casts", label: "Tank - Zauber", rows: classRows(["Druid", "Paladin", "Warrior"]), hideEmptyRows: true }
  ].map(withMatrix);
  return {
    type: "rpb",
    source: "combat-log",
    generatedAt: new Date().toISOString(),
    analysis: normalizeLogAnalysis(analysis),
    report: {
      title: analysis.title || payload.file || "CombatLog",
      raid: payload.zone || analysis.raid || "",
      raidDate: analysis.raid_date ? new Date(analysis.raid_date).toISOString().slice(0, 10) : combatLogDateToIso(payload.startedAt),
      reportCode: analysis.report_code || "",
      reportUrl: analysis.report_url || ""
    },
    players,
    roleOptions: logAnalysisRaidRoleOptions,
    sections,
    warnings: payload.totals?.combatantInfo ? [] : ["Keine CombatantInfo-Daten im CombatLog gefunden."]
  };
}

async function ensureLogAnalysisSheetExportsTable() {
  await ensureLogAnalysesTable();
  await query(
    `create table if not exists log_analysis_sheet_exports (
       id uuid primary key default gen_random_uuid(),
       analysis_id uuid not null references log_analyses(id) on delete cascade,
       analysis_type text not null check (analysis_type in ('rpb', 'cla')),
       sheet_name text not null,
       sheet_order integer not null default 0,
       payload jsonb not null default '{}'::jsonb,
       created_at timestamptz not null default now(),
       updated_at timestamptz not null default now(),
       unique (analysis_id, analysis_type, sheet_name)
     )`
  );
  await query(
    `create index if not exists log_analysis_sheet_exports_analysis_idx
     on log_analysis_sheet_exports (analysis_id, analysis_type, sheet_order)`
  );
  await query(
    `create table if not exists log_analysis_player_metrics (
       id uuid primary key default gen_random_uuid(),
       analysis_id uuid not null references log_analyses(id) on delete cascade,
       analysis_type text not null check (analysis_type in ('rpb', 'cla')),
       player_name text not null,
       class_name text,
       raid_role text,
       sheet_name text not null,
       category text,
       metric_key text not null,
       metric_label text not null,
       value_text text,
       value_number numeric,
       row_index integer,
       column_index integer,
       item_id text,
       item_name text,
       style jsonb not null default '{}'::jsonb,
       extra jsonb not null default '{}'::jsonb,
       created_at timestamptz not null default now(),
       updated_at timestamptz not null default now(),
       unique (analysis_id, analysis_type, player_name, sheet_name, metric_key, row_index, column_index)
     )`
  );
  await query(
    `create index if not exists log_analysis_player_metrics_lookup_idx
     on log_analysis_player_metrics (analysis_id, analysis_type, player_name, sheet_name)`
  );
  await query(
    `create index if not exists log_analysis_player_metrics_metric_idx
     on log_analysis_player_metrics (analysis_id, analysis_type, metric_key)`
  );
}

function normalizeSheetExportPayload(rawSheet, index = 0) {
  const sheet = rawSheet && typeof rawSheet === "object" ? rawSheet : {};
  const values = Array.isArray(sheet.values) ? sheet.values : (Array.isArray(sheet.data) ? sheet.data : []);
  const backgrounds = Array.isArray(sheet.backgrounds) ? sheet.backgrounds : [];
  const fontColors = Array.isArray(sheet.fontColors) ? sheet.fontColors : [];
  const notes = Array.isArray(sheet.notes) ? sheet.notes : [];
  return {
    name: clean(sheet.name || sheet.sheetName || `Sheet ${index + 1}`),
    order: Number.isFinite(Number(sheet.order)) ? Number(sheet.order) : index,
    payload: {
      values,
      backgrounds,
      fontColors,
      notes,
      mergedRanges: Array.isArray(sheet.mergedRanges) ? sheet.mergedRanges : [],
      frozenRows: Number(sheet.frozenRows || 0),
      frozenColumns: Number(sheet.frozenColumns || 0),
      source: clean(sheet.source || "google-sheet")
    }
  };
}

function normalizeMetricKey(value) {
  return slugPart(value || "wert") || "wert";
}

function numberFromMetricValue(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const text = clean(value);
  if (!text) return null;
  const match = text.replace(/\./g, "").replace(",", ".").match(/-?\d+(\.\d+)?/);
  return match ? Number(match[0]) : null;
}

function normalizePlayerMetricExport(rawEntry, index = 0) {
  const entry = rawEntry && typeof rawEntry === "object" ? rawEntry : {};
  const playerName = clean(entry.playerName || entry.player || entry.name || entry.charakter || entry.character);
  const sheetName = clean(entry.sheetName || entry.sheet || entry.tab || "All");
  const label = clean(entry.metricLabel || entry.label || entry.metric || entry.rowLabel || entry.nameOfMetric || entry.key);
  const value = entry.valueText ?? entry.displayValue ?? entry.value ?? "";
  const style = entry.style && typeof entry.style === "object" ? entry.style : {};
  const extra = entry.extra && typeof entry.extra === "object" ? entry.extra : {};
  return {
    playerName,
    className: normalizeRpbClassName(entry.className || entry.class || entry.klasse) || clean(entry.className || entry.class || entry.klasse),
    raidRole: normalizeLogAnalysisRaidRole(entry.raidRole || entry.role || ""),
    sheetName,
    category: clean(entry.category || entry.section || entry.group || ""),
    metricKey: normalizeMetricKey(entry.metricKey || entry.key || label || `metric-${index}`),
    metricLabel: label || normalizeMetricKey(entry.metricKey || `metric-${index}`),
    valueText: clean(value),
    valueNumber: entry.valueNumber != null ? Number(entry.valueNumber) : numberFromMetricValue(value),
    rowIndex: Number.isFinite(Number(entry.rowIndex ?? entry.row)) ? Number(entry.rowIndex ?? entry.row) : index,
    columnIndex: Number.isFinite(Number(entry.columnIndex ?? entry.column)) ? Number(entry.columnIndex ?? entry.column) : 0,
    itemId: clean(entry.itemId || entry.item_id),
    itemName: clean(entry.itemName || entry.item || ""),
    style,
    extra
  };
}

const logAnalysisRpbImportSheets = [
  "General",
  "Caster",
  "Caster - casts",
  "Healer",
  "Healer - casts",
  "Physical",
  "Physical - casts",
  "Tank",
  "Tank - casts"
];

const logAnalysisClaImportSheets = [
  "combat buffs",
  "gear issues",
  "world buffs",
  "gear listing",
  "ignites",
  "frost resistance",
  "pulls"
];

function parseGoogleSpreadsheetId(value) {
  const match = clean(value).match(/\/spreadsheets\/d\/([A-Za-z0-9_-]+)/);
  return match ? match[1] : "";
}

async function fetchGoogleSheetCsv(spreadsheetId, sheetName) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const url = `https://docs.google.com/spreadsheets/d/${encodeURIComponent(spreadsheetId)}/gviz/tq?tqx=out:csv&sheet=${encodeURIComponent(sheetName)}`;
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) return null;
    const text = await response.text();
    if (/<!doctype html|<html/i.test(text)) return null;
    const values = parseCsvRows(text);
    const hasCells = values.some(row => row.some(cell => clean(cell)));
    return hasCells ? values : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

function sheetValuesFingerprint(values) {
  return JSON.stringify((values || []).map(row => (row || []).map(cell => clean(cell))).filter(row => row.some(Boolean)));
}

function metricKeyFromLabel(value) {
  return normalizeMetricKey(value);
}

function rowHasOnlyOneFilledCell(row) {
  return (row || []).filter(cell => clean(cell)).length === 1;
}

function nearestSheetCategory(values, rowIndex) {
  for (let r = rowIndex; r >= 0; r--) {
    const first = clean(values[r]?.[0]);
    if (first && rowHasOnlyOneFilledCell(values[r])) return first;
  }
  return "";
}

function firstRowLabel(row) {
  for (let c = 0; c < Math.min((row || []).length, 4); c++) {
    const value = clean(row[c]);
    if (value) return value;
  }
  return "";
}

function detectPlayerHeaderRow(values, knownPlayers) {
  let bestRow = -1;
  let bestScore = 0;
  const maxRows = Math.min(values.length, 15);
  for (let r = 0; r < maxRows; r++) {
    let score = 0;
    for (let c = 1; c < (values[r] || []).length; c++) {
      if (knownPlayers.has(clean(values[r][c]).toLowerCase())) score++;
    }
    if (score > bestScore) {
      bestScore = score;
      bestRow = r;
    }
  }
  return bestScore >= 2 ? bestRow : -1;
}

function detectMetricHeaderRow(values) {
  let bestRow = -1;
  let bestScore = 0;
  const maxRows = Math.min(values.length, 15);
  for (let r = 0; r < maxRows; r++) {
    let score = 0;
    for (let c = 1; c < (values[r] || []).length; c++) {
      if (clean(values[r][c])) score++;
    }
    if (score > bestScore) {
      bestScore = score;
      bestRow = r;
    }
  }
  return bestScore >= 2 ? bestRow : -1;
}

function extractSheetImportMetrics({ values, sheetName, type, classByPlayer }) {
  const metrics = [];
  const knownPlayers = new Set(classByPlayer.keys());
  const headerRow = detectPlayerHeaderRow(values, knownPlayers);
  if (headerRow >= 0) {
    const playerColumns = [];
    for (let c = 1; c < (values[headerRow] || []).length; c++) {
      const name = clean(values[headerRow][c]);
      if (knownPlayers.has(name.toLowerCase())) playerColumns.push({ name, column: c });
    }
    for (let r = headerRow + 1; r < values.length; r++) {
      const label = firstRowLabel(values[r]);
      if (!label || rowHasOnlyOneFilledCell(values[r])) continue;
      playerColumns.forEach(player => {
        const value = clean(values[r]?.[player.column]);
        if (!value) return;
        metrics.push({
          playerName: player.name,
          className: classByPlayer.get(player.name.toLowerCase()) || "",
          sheetName,
          category: nearestSheetCategory(values, r),
          metricKey: metricKeyFromLabel(label),
          metricLabel: label,
          valueText: value,
          rowIndex: r,
          columnIndex: player.column,
          style: {},
          extra: { importSource: "google-csv", analysisType: type }
        });
      });
    }
    return metrics;
  }

  const metricHeaderRow = detectMetricHeaderRow(values);
  if (metricHeaderRow < 0) return metrics;
  const headers = values[metricHeaderRow] || [];
  for (let r = metricHeaderRow + 1; r < values.length; r++) {
    const playerName = clean(values[r]?.[0]);
    if (!knownPlayers.has(playerName.toLowerCase())) continue;
    for (let c = 1; c < (values[r] || []).length; c++) {
      const label = clean(headers[c]);
      const value = clean(values[r][c]);
      if (!label || !value) continue;
      metrics.push({
        playerName,
        className: classByPlayer.get(playerName.toLowerCase()) || "",
        sheetName,
        category: sheetName,
        metricKey: metricKeyFromLabel(label),
        metricLabel: label,
        valueText: value,
        rowIndex: r,
        columnIndex: c,
        style: {},
        extra: { importSource: "google-csv", analysisType: type }
      });
    }
  }
  return metrics;
}

async function importLogAnalysisSheetExportFromUrl({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  await ensureLogAnalysisSheetExportsTable();
  const id = clean(params.id || params.analysisId);
  const type = clean(params.type || params.analysisType || "").toLowerCase();
  if (!isUuid(id) || !["cla", "rpb"].includes(type)) {
    const error = new Error("Loganalyse oder Typ fehlt.");
    error.statusCode = 400;
    throw error;
  }
  const result = await query(
    `select * from log_analyses where guild_id = $1 and id = $2 limit 1`,
    [guildId, id]
  );
  const analysis = result.rows[0];
  if (!analysis) {
    const error = new Error("Loganalyse wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }
  const summary = analysis.summary || {};
  const sheetUrl = clean(params.sheetUrl || summary[`${type}DownloadUrl`]);
  const spreadsheetId = parseGoogleSpreadsheetId(sheetUrl);
  if (!spreadsheetId) {
    const error = new Error(`${type.toUpperCase()}-Sheet-Link fehlt.`);
    error.statusCode = 400;
    throw error;
  }

  const classByPlayer = await getGuildClassMap(guildId);
  const candidates = type === "cla" ? logAnalysisClaImportSheets : logAnalysisRpbImportSheets;
  const sheets = [];
  const playerMetrics = [];
  const seenSheetPayloads = new Set();
  for (const sheetName of candidates) {
    const values = await fetchGoogleSheetCsv(spreadsheetId, sheetName);
    if (!values) continue;
    const fingerprint = sheetValuesFingerprint(values);
    if (seenSheetPayloads.has(fingerprint)) continue;
    seenSheetPayloads.add(fingerprint);
    sheets.push({
      name: sheetName,
      order: sheets.length,
      values,
      backgrounds: [],
      fontColors: [],
      notes: [],
      source: "google-csv"
    });
    playerMetrics.push(...extractSheetImportMetrics({ values, sheetName, type, classByPlayer }));
  }

  if (!sheets.length) {
    const error = new Error("Google-Sheet konnte nicht gelesen werden. Bitte pruefen, ob der Link freigegeben ist.");
    error.statusCode = 400;
    throw error;
  }

  return saveLogAnalysisSheetExport({
    guildId,
    query: {
      ...params,
      id,
      type,
      sheetUrl,
      sheets,
      playerMetrics
    }
  });
}

async function findLogAnalysisForSheetExport(guildId, params) {
  const id = clean(params.id || params.analysisId);
  if (isUuid(id)) {
    const result = await query(
      `select * from log_analyses where guild_id = $1 and id = $2 limit 1`,
      [guildId, id]
    );
    if (result.rows.length) return result.rows[0];
  }
  const reportUrl = clean(params.reportUrl || params.url || params.logUrl);
  const reportCode = clean(params.reportCode || extractWarcraftLogsReportCode(reportUrl));
  if (!reportCode) return null;
  const saved = await saveLogAnalysis({
    guildId,
    query: {
      ...params,
      reportCode,
      reportUrl,
      status: clean(params.status || "sheet_exported")
    }
  });
  const result = await query(
    `select * from log_analyses where guild_id = $1 and id = $2 limit 1`,
    [guildId, saved.analysis.id]
  );
  return result.rows[0] || null;
}

async function saveLogAnalysisSheetExport({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensureLogAnalysisSheetExportsTable();
  const type = clean(params.type || params.analysisType || "rpb").toLowerCase();
  if (!["rpb", "cla"].includes(type)) {
    const error = new Error("Unbekannter Analyse-Typ.");
    error.statusCode = 400;
    throw error;
  }
  const analysis = await findLogAnalysisForSheetExport(guildId, params);
  if (!analysis) {
    const error = new Error("Loganalyse wurde nicht gefunden oder Report-Code fehlt.");
    error.statusCode = 404;
    throw error;
  }
  const rawSheets = typeof params.sheets === "string"
    ? JSON.parse(params.sheets || "[]")
    : (params.sheets || []);
  const sheets = (Array.isArray(rawSheets) ? rawSheets : [rawSheets])
    .map(normalizeSheetExportPayload)
    .filter(sheet => sheet.name && Array.isArray(sheet.payload.values));
  const rawPlayerMetrics = typeof params.playerMetrics === "string"
    ? JSON.parse(params.playerMetrics || "[]")
    : (params.playerMetrics || params.entries || []);
  const playerMetrics = (Array.isArray(rawPlayerMetrics) ? rawPlayerMetrics : [rawPlayerMetrics])
    .map(normalizePlayerMetricExport)
    .filter(entry => entry.playerName && entry.sheetName && entry.metricKey);
  if (!sheets.length) {
    const error = new Error("Keine Sheet-Daten im Export gefunden.");
    error.statusCode = 400;
    throw error;
  }
  await query("delete from log_analysis_sheet_exports where analysis_id = $1 and analysis_type = $2", [analysis.id, type]);
  await query("delete from log_analysis_player_metrics where analysis_id = $1 and analysis_type = $2", [analysis.id, type]);
  for (const sheet of sheets) {
    await query(
      `insert into log_analysis_sheet_exports (analysis_id, analysis_type, sheet_name, sheet_order, payload)
       values ($1,$2,$3,$4,$5::jsonb)
       on conflict (analysis_id, analysis_type, sheet_name) do update
         set sheet_order = excluded.sheet_order,
             payload = excluded.payload,
             updated_at = now()`,
      [analysis.id, type, sheet.name, sheet.order, JSON.stringify(sheet.payload)]
    );
  }
  for (const entry of playerMetrics) {
    await query(
      `insert into log_analysis_player_metrics (
         analysis_id, analysis_type, player_name, class_name, raid_role,
         sheet_name, category, metric_key, metric_label, value_text, value_number,
         row_index, column_index, item_id, item_name, style, extra
       )
       values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16::jsonb,$17::jsonb)
       on conflict (analysis_id, analysis_type, player_name, sheet_name, metric_key, row_index, column_index)
       do update set
         class_name = excluded.class_name,
         raid_role = excluded.raid_role,
         category = excluded.category,
         metric_label = excluded.metric_label,
         value_text = excluded.value_text,
         value_number = excluded.value_number,
         item_id = excluded.item_id,
         item_name = excluded.item_name,
         style = excluded.style,
         extra = excluded.extra,
         updated_at = now()`,
      [
        analysis.id,
        type,
        entry.playerName,
        entry.className,
        entry.raidRole,
        entry.sheetName,
        entry.category,
        entry.metricKey,
        entry.metricLabel,
        entry.valueText,
        entry.valueNumber,
        entry.rowIndex,
        entry.columnIndex,
        entry.itemId,
        entry.itemName,
        JSON.stringify(entry.style || {}),
        JSON.stringify(entry.extra || {})
      ]
    );
  }
  const summaryPatch = {
    [`${type}SheetExportedAt`]: new Date().toISOString(),
    [`${type}SheetCount`]: sheets.length,
    [`${type}SheetNames`]: sheets.map(sheet => sheet.name),
    [`${type}PlayerMetricCount`]: playerMetrics.length
  };
  const result = await query(
    `update log_analyses
     set status = $3,
         summary = coalesce(summary, '{}'::jsonb) || $4::jsonb,
         updated_at = now()
     where guild_id = $1 and id = $2
     returning *`,
    [guildId, analysis.id, `${type}_sheet_exported`, JSON.stringify(summaryPatch)]
  );
  return {
    success: true,
    analysis: normalizeLogAnalysis(result.rows[0] || analysis),
    type,
    sheets: sheets.map(sheet => sheet.name),
    sheetCount: sheets.length,
    playerMetricCount: playerMetrics.length
  };
}

function buildStoredSheetWebAnalysisFromRows(analysis, type, rows, metricRows = []) {
  if (!rows.length) return null;
  const playerMap = new Map();
  metricRows.forEach(row => {
    const name = clean(row.player_name);
    if (!name || playerMap.has(name)) return;
    playerMap.set(name, {
      name,
      className: normalizeRpbClassName(row.class_name) || row.class_name || "",
      raidRole: normalizeLogAnalysisRaidRole(row.raid_role || "")
    });
  });
  const sections = rows.map((row, index) => ({
    id: `sheet-${slugPart(row.sheet_name || `tab-${index + 1}`) || index}`,
    label: row.sheet_name || `Tab ${index + 1}`,
    description: "Aus dem Google Sheet nach Railway exportiert.",
    source: "sheet-export",
    matrix: row.payload || { values: [] },
    compact: true,
    ignoreClassFilter: true
  }));
  const summary = analysis.summary || {};
  return {
    type,
    source: "sheet-export",
    generatedAt: summary[`${type}SheetExportedAt`] || analysis.updated_at || new Date().toISOString(),
    analysis: normalizeLogAnalysis(analysis),
    report: {
      title: analysis.title || summary.title || `${type.toUpperCase()} Auswertung`,
      raid: analysis.raid || summary.raid || "",
      raidDate: analysis.raid_date ? new Date(analysis.raid_date).toISOString().slice(0, 10) : (summary.raidDate || ""),
      reportCode: analysis.report_code || "",
      reportUrl: analysis.report_url || ""
    },
    players: Array.from(playerMap.values()),
    playerMetrics: metricRows.map(row => ({
      playerName: row.player_name || "",
      className: row.class_name || "",
      raidRole: row.raid_role || "",
      sheetName: row.sheet_name || "",
      category: row.category || "",
      metricKey: row.metric_key || "",
      metricLabel: row.metric_label || "",
      valueText: row.value_text || "",
      valueNumber: row.value_number == null ? null : Number(row.value_number),
      rowIndex: row.row_index,
      columnIndex: row.column_index,
      itemId: row.item_id || "",
      itemName: row.item_name || "",
      style: row.style || {},
      extra: row.extra || {}
    })),
    roleOptions: logAnalysisRaidRoleOptions,
    sections,
    warnings: []
  };
}

async function buildStoredSheetWebAnalysis(analysis, type) {
  await ensureLogAnalysisSheetExportsTable();
  const result = await query(
    `select sheet_name, sheet_order, payload
     from log_analysis_sheet_exports
     where analysis_id = $1 and analysis_type = $2
     order by sheet_order asc, sheet_name asc`,
    [analysis.id, type]
  );
  const metrics = await query(
    `select player_name, class_name, raid_role, sheet_name, category,
            metric_key, metric_label, value_text, value_number,
            row_index, column_index, item_id, item_name, style, extra
     from log_analysis_player_metrics
     where analysis_id = $1 and analysis_type = $2
     order by player_name asc, sheet_name asc, row_index asc, column_index asc`,
    [analysis.id, type]
  );
  return buildStoredSheetWebAnalysisFromRows(analysis, type, result.rows, metrics.rows);
}

async function setPublicLogAnalysisRaidRoles({ guildId, query: params }) {
  await ensureLogAnalysesTable();
  const id = clean(params.id || params.analysisId);
  if (!isUuid(id)) {
    const error = new Error("Loganalyse-ID fehlt.");
    error.statusCode = 400;
    throw error;
  }
  const rawRoles = typeof params.roles === "string" ? JSON.parse(params.roles || "{}") : (params.roles || {});
  const raidRoles = {};
  Object.entries(rawRoles || {}).forEach(([name, role]) => {
    const player = clean(name);
    const normalized = normalizeLogAnalysisRaidRole(role);
    if (player && normalized) raidRoles[player] = normalized;
  });
  const result = await query(
    `update log_analyses
     set summary = coalesce(summary, '{}'::jsonb) || jsonb_build_object('raidRoles', $3::jsonb),
         updated_at = now()
     where guild_id = $1 and id = $2
     returning *`,
    [guildId, id, JSON.stringify(raidRoles)]
  );
  if (!result.rows.length) {
    const error = new Error("Loganalyse wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }
  return {
    success: true,
    raidRoles,
    analysis: normalizeLogAnalysis(result.rows[0])
  };
}

async function downloadLogAnalysis({ guildId, query: params, res }) {
  await ensureLogAnalysesTable();

  const id = clean(params.id || params.analysisId);
  const type = clean(params.type || params.analysisType).toLowerCase();
  const token = clean(params.token);
  if (!isUuid(id) || !["cla", "rpb"].includes(type) || !token) {
    const error = new Error("Download-Link ist unvollständig.");
    error.statusCode = 400;
    throw error;
  }

  const result = await query(
    `select *
     from log_analyses
     where guild_id = $1 and id = $2
     limit 1`,
    [guildId, id]
  );
  if (!result.rows.length) {
    const error = new Error("Loganalyse wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const analysis = result.rows[0];
  const summary = analysis.summary || {};
  const expectedToken = type === "cla" ? summary.claDownloadToken : summary.rpbDownloadToken;
  if (!expectedToken || token !== expectedToken) {
    const error = new Error("Download-Link ist nicht mehr gültig.");
    error.statusCode = 403;
    throw error;
  }

  const raid = analysis.raid || summary.raid || "log";
  const raidDate = analysis.raid_date ? new Date(analysis.raid_date).toISOString().slice(0, 10) : (summary.raidDate || "");
  const filename = `${type.toUpperCase()}-${slugPart(raid)}${raidDate ? `-${raidDate}` : ""}.csv`;
  res.setHeader("Content-Type", "text/csv; charset=utf-8");
  res.setHeader("Content-Disposition", `attachment; filename="${filename}"`);
  return res.send(await buildLogAnalysisCsv(analysis, type));
}

async function ensureLogAnalysesTable() {
  await query(
    `create table if not exists log_analyses (
       id uuid primary key default gen_random_uuid(),
       guild_id uuid not null references guilds(id) on delete cascade,
       report_code text not null,
       report_url text not null,
       title text,
       raid text,
       raid_date date,
       status text not null default 'pending',
       summary jsonb not null default '{}'::jsonb,
       discord_channel_id text,
       discord_message_id text,
       discord_author text,
       posted_at timestamptz,
       analyzed_at timestamptz,
       created_at timestamptz not null default now(),
       updated_at timestamptz not null default now(),
       unique (guild_id, report_code)
     )`
  );
  await query(
    `create index if not exists log_analyses_guild_created_idx
     on log_analyses (guild_id, created_at desc)`
  );
}

async function getLogAnalyses({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  await ensureLogAnalysesTable();

  const limit = Math.min(Math.max(Number(params.limit || 50), 1), 200);
  const result = await query(
    `select *
     from log_analyses
     where guild_id = $1
     order by coalesce(raid_date, posted_at::date, created_at::date) desc, posted_at desc nulls last, created_at desc
     limit $2`,
    [guildId, limit]
  );

  return {
    success: true,
    analyses: result.rows.map(normalizeLogAnalysis)
  };
}

async function getPublicLogAnalyses({ guildId, query: params }) {
  await ensureLogAnalysesTable();
  await ensureLogAnalysisSheetExportsTable();

  const limit = Math.min(Math.max(Number(params.limit || 12), 1), 40);
  const sheetOnly = ["1", "true", "ja", "yes"].includes(clean(params.sheetOnly || params.webReady).toLowerCase());
  const result = await query(
    `select la.*,
            coalesce((
              select count(*)::int
              from log_analysis_sheet_exports se
              where se.analysis_id = la.id and se.analysis_type = 'rpb'
            ), 0) as rpb_sheet_count,
            coalesce((
              select count(*)::int
              from log_analysis_sheet_exports se
              where se.analysis_id = la.id and se.analysis_type = 'cla'
            ), 0) as cla_sheet_count
     from log_analyses la
     where la.guild_id = $1
       and (
         $3::boolean = false
         or exists (
           select 1
           from log_analysis_sheet_exports se
           where se.analysis_id = la.id
         )
       )
     order by coalesce(raid_date, posted_at::date, created_at::date) desc, posted_at desc nulls last, created_at desc
     limit $2`,
    [guildId, limit, sheetOnly]
  );

  return {
    success: true,
    analyses: result.rows.map(normalizeLogAnalysis)
  };
}

async function saveLogAnalysis({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensureLogAnalysesTable();

  const reportUrl = clean(params.reportUrl || params.url || params.logUrl);
  const reportCode = clean(params.reportCode || extractWarcraftLogsReportCode(reportUrl));
  if (!reportCode) {
    const error = new Error("Warcraft-Logs-Report wurde nicht erkannt.");
    error.statusCode = 400;
    throw error;
  }

  const summary = typeof params.summary === "string"
    ? JSON.parse(params.summary || "{}")
    : (params.summary || {});
  const normalizedUrl = normalizeWarcraftLogsReportUrl(reportUrl, reportCode);
  const reportMeta = await fetchWarcraftLogsReportMetaSafe(reportCode);
  const logTitle = clean(params.title) || reportMeta.title || "";
  const logRaid = normalizeLogRaidType(params.raid || summary.raid || reportMeta.raid || "");
  const logDate = clean(params.raidDate || summary.raidDate || reportMeta.raidDate || "");

  const result = await query(
    `insert into log_analyses (
       guild_id, report_code, report_url, title, raid, raid_date, status, summary,
       discord_channel_id, discord_message_id, discord_author, posted_at, updated_at
     )
     values ($1,$2,$3,$4,$5,nullif($6,'')::date,$7,$8::jsonb,$9,$10,$11,nullif($12,'')::timestamptz,now())
     on conflict (guild_id, report_code) do update
       set report_url = excluded.report_url,
           title = coalesce(nullif(excluded.title, ''), log_analyses.title),
           raid = coalesce(nullif(excluded.raid, ''), log_analyses.raid),
           raid_date = coalesce(excluded.raid_date, log_analyses.raid_date),
           status = case
             when excluded.status in ('pending', '')
                  and (
                    nullif(log_analyses.summary->>'claDownloadUrl', '') is not null
                    or nullif(log_analyses.summary->>'rpbDownloadUrl', '') is not null
                    or log_analyses.status in ('cla_done', 'rpb_done')
                  )
               then log_analyses.status
             else coalesce(nullif(excluded.status, ''), log_analyses.status)
           end,
           summary = coalesce(log_analyses.summary, '{}'::jsonb) || coalesce(excluded.summary, '{}'::jsonb),
           discord_channel_id = coalesce(nullif(excluded.discord_channel_id, ''), log_analyses.discord_channel_id),
           discord_message_id = coalesce(nullif(excluded.discord_message_id, ''), log_analyses.discord_message_id),
           discord_author = coalesce(nullif(excluded.discord_author, ''), log_analyses.discord_author),
           posted_at = coalesce(excluded.posted_at, log_analyses.posted_at),
           updated_at = now()
     returning *`,
    [
      guildId,
      reportCode,
      normalizedUrl,
      logTitle,
      logRaid,
      logDate,
      clean(params.status || "pending"),
      JSON.stringify(summary || {}),
      clean(params.discordChannelId),
      clean(params.discordMessageId),
      clean(params.discordAuthor),
      clean(params.postedAt)
    ]
  );

  return {
    success: true,
    analysis: normalizeLogAnalysis(result.rows[0])
  };
}

async function runLogAnalysis({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  await ensureLogAnalysesTable();

  const id = clean(params.id || params.analysisId);
  const type = clean(params.type || params.analysisType).toLowerCase();
  if (!isUuid(id)) {
    const error = new Error("Loganalyse-ID fehlt.");
    error.statusCode = 400;
    throw error;
  }
  if (!["cla", "rpb"].includes(type)) {
    const error = new Error("Unbekannter Analyse-Typ.");
    error.statusCode = 400;
    throw error;
  }

  const existing = await query(
    `select *
     from log_analyses
     where guild_id = $1 and id = $2
     limit 1`,
    [guildId, id]
  );
  if (!existing.rows.length) {
    const error = new Error("Loganalyse wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const current = existing.rows[0];
  const reportMeta = (!current.raid || !current.raid_date)
    ? await fetchWarcraftLogsReportMetaSafe(current.report_code)
    : {};
  const downloadTokenKey = type === "cla" ? "claDownloadToken" : "rpbDownloadToken";
  const downloadUrlKey = type === "cla" ? "claDownloadUrl" : "rpbDownloadUrl";
  const downloadToken = current.summary?.[downloadTokenKey] || randomUUID();
  const generatorRunId = randomUUID();
  let generatorResult = null;
  let generatorError = "";
  try {
    generatorResult = await startExternalLogAnalysisGenerator({ analysis: current, type, guildId, generatorRunId });
  } catch (error) {
    generatorError = error.message || String(error);
    console.warn(`${type.toUpperCase()} Generator konnte nicht gestartet werden:`, error.message || error);
  }

  const generatedSheetUrl = generatorResult?.sheetUrl || generatorResult?.spreadsheetUrl || generatorResult?.url || "";
  const hasExternalGenerator = Boolean(generatorResult);
  const generatorStatus = generatedSheetUrl ? "done" : hasExternalGenerator ? "queued" : "failed";
  const summaryPatch = {
    lastRequestedAnalysis: type.toUpperCase(),
    analysisRequestedAt: new Date().toISOString(),
    [downloadTokenKey]: downloadToken,
    [`${type}GeneratorJobId`]: generatorResult?.jobId || "",
    [`${type}GeneratorRunId`]: generatorRunId,
    [`${type}GeneratorStartedAt`]: new Date().toISOString(),
    [`${type}GeneratorStatus`]: generatorResult?.status || generatorStatus,
    [`${type}GeneratorError`]: generatorError
  };
  if (generatedSheetUrl) summaryPatch[downloadUrlKey] = generatedSheetUrl;
  const nextStatus = generatedSheetUrl ? `${type}_done` : hasExternalGenerator ? `${type}_queued` : `${type}_failed`;
  const result = await query(
    `update log_analyses
     set status = $3,
         summary = coalesce(summary, '{}'::jsonb) || $4::jsonb,
         title = coalesce(nullif($5, ''), title),
         raid = coalesce(nullif($6, ''), raid),
         raid_date = coalesce(nullif($7, '')::date, raid_date),
         updated_at = now()
     where guild_id = $1 and id = $2
     returning *`,
    [
      guildId,
      id,
      nextStatus,
      JSON.stringify(summaryPatch),
      reportMeta.title || "",
      normalizeLogRaidType(reportMeta.raid || ""),
      reportMeta.raidDate || ""
    ]
  );

  return {
    success: true,
    analysisType: type.toUpperCase(),
    analysis: normalizeLogAnalysis(result.rows[0])
  };
}

function getLogAnalysisGeneratorConfig(type) {
  const prefix = type === "cla" ? "CLA" : "RPB";
  const url = process.env[`${prefix}_GENERATOR_URL`] || "";
  const token = process.env[`${prefix}_GENERATOR_TOKEN`] || "";
  return { url: clean(url), token: clean(token) };
}

function buildLogAnalysisCallbackUrl(baseUrl) {
  const value = clean(baseUrl).replace(/\/$/, "");
  if (!value) return "";
  if (value.endsWith("/api/apps-script")) return value;
  return `${value}/api/apps-script`;
}

async function startExternalLogAnalysisGenerator({ analysis, type, guildId, generatorRunId }) {
  const config = getLogAnalysisGeneratorConfig(type);
  if (!config.url) {
    const prefix = type === "cla" ? "CLA" : "RPB";
    throw new Error(`${prefix}_GENERATOR_URL fehlt in Railway. Bitte den Apps-Script-Web-App-Link des ${prefix}-Generators als Railway-Variable eintragen.`);
  }

  const callbackBaseUrl = process.env.LICHTLOOT_API_URL || process.env.PUBLIC_API_URL || "";
  const legacyApiKey = clean(
    process.env.WCL_V1_API_KEY ||
    process.env.WCL_API_KEY ||
    process.env.WARCRAFTLOGS_API_KEY ||
    process.env.RPB_CLIENT_KEY ||
    ""
  );
  const payload = {
    action: `create${type.toUpperCase()}`,
    type,
    analysisId: analysis.id,
    guildId,
    reportCode: analysis.report_code || "",
    reportUrl: analysis.report_url || "",
    raid: analysis.raid || "",
    raidDate: analysis.raid_date ? new Date(analysis.raid_date).toISOString().slice(0, 10) : "",
    title: analysis.title || "",
    apiKey: legacyApiKey,
    token: config.token,
    callbackToken: logAnalysisCallbackToken,
    jobToken: generatorRunId || "",
    generatorRunId: generatorRunId || "",
    callbackUrl: buildLogAnalysisCallbackUrl(callbackBaseUrl)
  };

  const response = await fetch(config.url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  if (!response.ok || data.success === false) {
    throw new Error(data.error || data.message || `Generator antwortete mit HTTP ${response.status}`);
  }
  return data;
}

async function completeExternalLogAnalysis({ guildId, query: params }) {
  await ensureLogAnalysesTable();
  const token = clean(params.callbackToken || params.token);
  if (!logAnalysisCallbackToken || token !== logAnalysisCallbackToken) {
    const error = new Error("Generator-Rückmeldung ist nicht autorisiert.");
    error.statusCode = 403;
    throw error;
  }

  const id = clean(params.id || params.analysisId);
  const type = clean(params.type || params.analysisType).toLowerCase();
  if (!isUuid(id) || !["cla", "rpb"].includes(type)) {
    const error = new Error("Generator-Rückmeldung ist unvollständig.");
    error.statusCode = 400;
    throw error;
  }

  const sheetUrl = clean(params.sheetUrl || params.spreadsheetUrl || params.url || params.downloadUrl);
  const callbackStatus = clean(params.status).toLowerCase();
  const inProgress = ["queued", "running", "started", "working"].includes(callbackStatus);
  const failed = callbackStatus === "failed" || clean(params.error);
  const callbackRunId = clean(params.jobToken || params.generatorRunId || params.runId);
  const downloadUrlKey = type === "cla" ? "claDownloadUrl" : "rpbDownloadUrl";
  if (callbackRunId) {
    const existing = await query(
      `select summary
       from log_analyses
       where guild_id = $1 and id = $2
       limit 1`,
      [guildId, id]
    );
    if (!existing.rows.length) {
      const error = new Error("Loganalyse wurde nicht gefunden.");
      error.statusCode = 404;
      throw error;
    }
    const activeRunId = clean(existing.rows[0].summary?.[`${type}GeneratorRunId`]);
    if (activeRunId && activeRunId !== callbackRunId) {
      return {
        success: true,
        ignored: true,
        reason: "stale_generator_callback",
        analysisType: type.toUpperCase()
      };
    }
    if (!activeRunId) {
      return {
        success: true,
        ignored: true,
        reason: "cancelled_generator_callback",
        analysisType: type.toUpperCase()
      };
    }
  }
  const summaryPatch = {
    [`${type}GeneratorStatus`]: failed ? "failed" : inProgress ? "queued" : "done",
    [`${type}GeneratorError`]: clean(params.error || ""),
    [`${type}GeneratorWarnings`]: clean(params.warnings || params.warning || ""),
    [`${type}GeneratorMessage`]: clean(params.message || params.statusText || params.detail || "")
  };
  if (!inProgress) summaryPatch[`${type}GeneratorFinishedAt`] = new Date().toISOString();
  if (sheetUrl) summaryPatch[downloadUrlKey] = sheetUrl;

  const result = await query(
    `update log_analyses
     set status = $3,
         summary = coalesce(summary, '{}'::jsonb) || $4::jsonb,
         updated_at = now()
     where guild_id = $1 and id = $2
     returning *`,
    [
      guildId,
      id,
      failed ? `${type}_failed` : inProgress ? `${type}_queued` : `${type}_done`,
      JSON.stringify(summaryPatch)
    ]
  );
  if (!result.rows.length) {
    const error = new Error("Loganalyse wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  return {
    success: true,
    analysisType: type.toUpperCase(),
    analysis: normalizeLogAnalysis(result.rows[0])
  };
}

async function setLogAnalysisSheetUrl({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  await ensureLogAnalysesTable();

  const id = clean(params.id || params.analysisId);
  const type = clean(params.type || params.analysisType).toLowerCase();
  const sheetUrl = clean(params.sheetUrl || params.spreadsheetUrl || params.url || params.downloadUrl);
  if (!isUuid(id) || !["cla", "rpb"].includes(type)) {
    const error = new Error("Loganalyse-ID oder Typ fehlt.");
    error.statusCode = 400;
    throw error;
  }
  if (!/^https:\/\/docs\.google\.com\/spreadsheets\/d\//i.test(sheetUrl)) {
    const error = new Error("Bitte einen Google-Sheets-Link einfügen.");
    error.statusCode = 400;
    throw error;
  }

  const downloadUrlKey = type === "cla" ? "claDownloadUrl" : "rpbDownloadUrl";
  const summaryPatch = {
    [downloadUrlKey]: sheetUrl,
    [`${type}GeneratorStatus`]: "done",
    [`${type}GeneratorFinishedAt`]: new Date().toISOString(),
    [`${type}GeneratorManualLink`]: true
  };
  const result = await query(
    `update log_analyses
     set status = $3,
         summary = coalesce(summary, '{}'::jsonb) || $4::jsonb,
         updated_at = now()
     where guild_id = $1 and id = $2
     returning *`,
    [guildId, id, `${type}_done`, JSON.stringify(summaryPatch)]
  );
  if (!result.rows.length) {
    const error = new Error("Loganalyse wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  return {
    success: true,
    analysisType: type.toUpperCase(),
    analysis: normalizeLogAnalysis(result.rows[0])
  };
}

async function cleanupIncompleteClaAnalyses({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  await ensureLogAnalysesTable();

  const result = await query(
    `update log_analyses
     set status = case
           when nullif(summary->>'rpbDownloadUrl', '') is not null then 'rpb_done'
           when lower(coalesce(summary->>'rpbGeneratorStatus', '')) = 'queued' then 'rpb_queued'
           when lower(coalesce(summary->>'rpbGeneratorStatus', '')) = 'failed' then 'rpb_failed'
           else 'pending'
         end,
         summary = coalesce(summary, '{}'::jsonb)
           - 'claDownloadUrl'
           - 'claDownloadToken'
           - 'claGeneratorJobId'
           - 'claGeneratorRunId'
           - 'claGeneratorStartedAt'
           - 'claGeneratorStatus'
           - 'claGeneratorError'
           - 'claGeneratorWarnings'
           - 'claGeneratorFinishedAt'
           - 'claGeneratorManualLink',
         updated_at = now()
     where guild_id = $1
       and (
         status in ('cla_queued', 'cla_failed')
         or lower(coalesce(summary->>'claGeneratorStatus', '')) in ('queued', 'failed', 'error', 'started', 'running')
         or nullif(summary->>'claGeneratorError', '') is not null
         or (
           nullif(summary->>'claDownloadUrl', '') is not null
           and summary->>'claDownloadUrl' !~* '^https://docs\\.google\\.com/spreadsheets/d/'
         )
       )
     returning id`,
    [guildId]
  );

  return {
    success: true,
    deletedCla: result.rowCount
  };
}

async function cleanupIncompleteRpbAnalyses({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  await ensureLogAnalysesTable();

  const result = await query(
    `update log_analyses
     set status = case
           when nullif(summary->>'claDownloadUrl', '') is not null then 'cla_done'
           when lower(coalesce(summary->>'claGeneratorStatus', '')) = 'queued' then 'cla_queued'
           when lower(coalesce(summary->>'claGeneratorStatus', '')) = 'failed' then 'cla_failed'
           else 'pending'
         end,
         summary = coalesce(summary, '{}'::jsonb)
           - 'rpbDownloadUrl'
           - 'rpbDownloadToken'
           - 'rpbGeneratorJobId'
           - 'rpbGeneratorRunId'
           - 'rpbGeneratorStartedAt'
           - 'rpbGeneratorStatus'
           - 'rpbGeneratorError'
           - 'rpbGeneratorWarnings'
           - 'rpbGeneratorFinishedAt'
           - 'rpbGeneratorManualLink',
         updated_at = now()
     where guild_id = $1
       and (
         status in ('rpb_queued', 'rpb_failed')
         or lower(coalesce(summary->>'rpbGeneratorStatus', '')) in ('queued', 'failed', 'error', 'started', 'running')
         or nullif(summary->>'rpbGeneratorError', '') is not null
         or (
           nullif(summary->>'rpbDownloadUrl', '') is not null
           and summary->>'rpbDownloadUrl' !~* '^https://docs\\.google\\.com/spreadsheets/d/'
         )
       )
     returning id`,
    [guildId]
  );

  return {
    success: true,
    deletedRpb: result.rowCount
  };
}

async function resetLogAnalyses({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  await ensureLogAnalysisSheetExportsTable();
  await ensureCombatLogImportsTable();

  const result = await query(
    `delete from log_analyses
     where guild_id = $1
     returning id`,
    [guildId]
  );

  return {
    success: true,
    deletedAnalyses: result.rowCount
  };
}

async function clearLogAnalysisType({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  await ensureLogAnalysesTable();

  const id = clean(params.id || params.analysisId);
  const type = clean(params.type || params.analysisType).toLowerCase();
  if (!isUuid(id) || !["cla", "rpb"].includes(type)) {
    const error = new Error("Loganalyse-ID oder Typ fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const otherType = type === "cla" ? "rpb" : "cla";
  const result = await query(
    `update log_analyses
     set status = case
           when nullif(summary->>$3, '') is not null then $4
           when lower(coalesce(summary->>$5, '')) = 'queued' then $6
           when lower(coalesce(summary->>$5, '')) = 'failed' then $7
           else 'pending'
         end,
         summary = coalesce(summary, '{}'::jsonb)
           - $8
           - $9
           - $10
           - $11
           - $12
           - $13
           - $14
           - $15
           - $16
           - $17,
         updated_at = now()
     where guild_id = $1 and id = $2
     returning *`,
    [
      guildId,
      id,
      `${otherType}DownloadUrl`,
      `${otherType}_done`,
      `${otherType}GeneratorStatus`,
      `${otherType}_queued`,
      `${otherType}_failed`,
      `${type}DownloadUrl`,
      `${type}DownloadToken`,
      `${type}GeneratorJobId`,
      `${type}GeneratorStatus`,
      `${type}GeneratorError`,
      `${type}GeneratorWarnings`,
      `${type}GeneratorFinishedAt`,
      `${type}GeneratorManualLink`,
      `${type}GeneratorRunId`,
      `${type}GeneratorStartedAt`
    ]
  );
  if (!result.rows.length) {
    const error = new Error("Loganalyse wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  return {
    success: true,
    analysisType: type.toUpperCase(),
    analysis: normalizeLogAnalysis(result.rows[0])
  };
}

function normalizeIssueReportRow(row, index = 0) {
  return {
    id: row.id,
    rowNumber: row.id,
    number: index + 1,
    time: row.created_at ? row.created_at.toISOString() : "",
    type: row.type || "",
    source: row.source || "",
    category: row.category || "",
    raid: row.raid || "",
    item: row.item || "",
    slot: row.slot || "",
    points: row.points || "",
    player: row.player || "",
    server: row.server || "",
    note: row.note || "",
    page: row.page || "",
    originalDate: row.original_date || ""
  };
}

async function reportIssue({ guildId, query: params }) {
  let reportPlayer = clean(params.player || params.char || params.spieler);
  let reportServer = clean(params.server);
  if (!reportPlayer) {
    const pin = params.playerPin || params.characterPin || params.pin;
    if (pin) {
      const characters = await getCharactersByPin(guildId, pin);
      const character = characters[0] || null;
      if (character) {
        reportPlayer = clean(character.name);
        reportServer = clean(character.server);
      }
    }
  }

  const result = await query(
    `insert into issue_reports (
       guild_id, type, source, category, raid, item, slot, points,
       player, server, note, page, original_date
     )
     values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
     returning *`,
    [
      guildId,
      clean(params.type),
      clean(params.source),
      clean(params.category),
      clean(params.raid),
      clean(params.item),
      clean(params.slot),
      clean(params.points),
      reportPlayer,
      reportServer,
      clean(params.note),
      clean(params.page),
      clean(params.createdAt || params.originalDate)
    ]
  );
  return { success: true, report: normalizeIssueReportRow(result.rows[0]) };
}

async function getIssueReports({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  const result = await query(
    `select *
     from issue_reports
     where guild_id = $1 and resolved_at is null
     order by created_at desc`,
    [guildId]
  );
  return { success: true, reports: result.rows.map(normalizeIssueReportRow) };
}

async function resolveIssueReport({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  const id = clean(params.id || params.rowNumber);
  const result = await query(
    `update issue_reports
     set resolved_at = now()
     where guild_id = $1 and id = $2
     returning *`,
    [guildId, id]
  );

  let notified = false;
  let notificationError = "";
  const report = result.rows[0] || null;

  if (report && report.player) {
    try {
      const player = await findPlayerByRecipient(guildId, report.player, report.server);
      if (player) {
        const playerName = clean(player.main_name || player.character_name || report.player) || "Spieler";
        const bodyParts = [
          `Lieber ${playerName},`,
          "",
          "vielen Dank für deine Mithilfe, das Item wurde geändert.",
          "",
          "LG"
        ];

        await query(
          `insert into player_messages (
             guild_id, player_pin, title, body, raid_name, sender
           )
           values ($1,$2,$3,$4,$5,$6)`,
          [
            guildId,
            player.player_pin,
            "Item wurde geändert",
            bodyParts.join("\n"),
            report.raid || "",
            "Gildenleitung"
          ]
        );
        notified = true;
      } else {
        notificationError = "Spieler/Charakter wurde nicht gefunden.";
      }
    } catch (error) {
      notificationError = error.message || "Spieler konnte nicht benachrichtigt werden.";
    }
  } else if (report) {
    notificationError = "Kein Spieler in der Meldung.";
  }

  return { success: true, resolved: result.rowCount, notified, notificationError };
}

function normalizePlayerMessageRow(row) {
  const raidDate = row.raid_date ? row.raid_date.toISOString().slice(0, 10) : "";
  return {
    id: row.id,
    playerPin: row.player_pin || "",
    recipientNames: row.recipient_names || "",
    title: row.title || "",
    body: row.body || "",
    raidId: row.raid_id || "",
    raidName: row.raid_name || "",
    raidDate,
    raidTime: row.raid_time || "",
    leadPin: row.lead_pin || "",
    sender: row.sender_display || row.sender || "",
    createdAt: row.created_at,
    readAt: row.read_at,
    read: Boolean(row.read_at)
  };
}

async function sendPlayerMessage({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  const recipient = clean(params.recipient || params.character || params.char || params.player || params.playerPin || params.pin);
  if (!recipient) {
    const error = new Error("Bitte Empfänger angeben.");
    error.statusCode = 400;
    throw error;
  }

  const player = await findPlayerByRecipient(guildId, recipient, params.server);
  if (!player) {
    const error = new Error("Dieser Spieler/Charakter wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const result = await query(
    `insert into player_messages (
       guild_id, player_pin, title, body, raid_id, raid_name,
       raid_date, raid_time, lead_pin, sender
     )
     values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
     returning *`,
    [
      guildId,
      player.player_pin,
      clean(params.title) || "Raidlead-PIN",
      clean(params.body) || "Du wurdest als Raidlead eingetragen.",
      clean(params.raidId),
      clean(params.raidName),
      parseDateValue(params.raidDate || params.date || null),
      clean(params.raidTime || params.time),
      clean(params.leadPin),
      clean(params.sender) || "Gildenleitung"
    ]
  );
  return { success: true, message: normalizePlayerMessageRow(result.rows[0]) };
}

async function sendPlayerMessageFromPlayer({ guildId, query: params }) {
  const senderPin = normalizePin(params.fromPlayerPin || params.senderPin || params.fromPin);
  const recipient = clean(params.recipient || params.character || params.char || params.player || params.toPlayerPin || params.playerPin || params.pin);
  const body = clean(params.body || params.message);
  if (!senderPin || !recipient || !body) {
    const error = new Error("Bitte Absender, Empfänger und Nachricht angeben.");
    error.statusCode = 400;
    throw error;
  }

  const sender = await findPlayerByPin(guildId, senderPin);
  if (!sender) {
    const error = new Error("Dein SpielerLogin wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }
  const senderName =
    await getVerifiedSenderCharacterName(guildId, senderPin, params.senderCharacter || params.senderChar, params.senderServer) ||
    await getPlayerDisplayNameByPin(guildId, senderPin) ||
    "Spieler";

  const recipientPlayer = await findPlayerByRecipient(guildId, recipient, params.server);
  if (!recipientPlayer) {
    const error = new Error("Empfänger wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const result = await query(
    `insert into player_messages (
       guild_id, player_pin, title, body, raid_id, raid_name,
       raid_date, raid_time, lead_pin, sender
     )
     values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
     returning *`,
    [
      guildId,
      recipientPlayer.player_pin,
      clean(params.title) || "Nachricht",
      body,
      clean(params.raidId),
      clean(params.raidName),
      parseDateValue(params.raidDate || params.date || null),
      clean(params.raidTime || params.time),
      clean(params.leadPin),
      senderName
    ]
  );
  return { success: true, message: normalizePlayerMessageRow(result.rows[0]) };
}

async function getPlayerMessages({ guildId, query: params }) {
  const playerPin = normalizePin(params.playerPin || params.pin);
  if (!playerPin) {
    const error = new Error("Bitte SpielerLogin eingeben.");
    error.statusCode = 400;
    throw error;
  }

  const result = await query(
    `select pm.*,
            coalesce((
              select string_agg(c.name, ', ' order by c.name)
              from players p
              join characters c on c.player_id = p.id
              where p.guild_id = pm.guild_id and p.player_pin = pm.player_pin
            ), '') as recipient_names,
            coalesce((
              select coalesce((
                select c.name
                from characters c
                where c.player_id = p.id
                order by c.is_main desc, c.created_at asc
                limit 1
              ), p.player_pin)
              from players p
              where p.guild_id = pm.guild_id
                and p.player_pin = substring(pm.sender from '^Spieler (.+)$')
              limit 1
            ), pm.sender) as sender_display
     from player_messages pm
     where pm.guild_id = $1 and pm.player_pin = $2
     order by created_at desc
     limit 50`,
    [guildId, playerPin]
  );
  return { success: true, messages: result.rows.map(normalizePlayerMessageRow) };
}

async function getPlayerSentMessages({ guildId, query: params }) {
  const playerPin = normalizePin(params.playerPin || params.pin);
  if (!playerPin) {
    const error = new Error("Bitte SpielerLogin eingeben.");
    error.statusCode = 400;
    throw error;
  }

  const result = await query(
    `select pm.*,
            coalesce((
              select string_agg(c.name, ', ' order by c.name)
              from players p
              join characters c on c.player_id = p.id
              where p.guild_id = pm.guild_id and p.player_pin = pm.player_pin
            ), '') as recipient_names
     from player_messages pm
     where pm.guild_id = $1
       and (
         pm.sender = $2
         or pm.sender = any(
           select c.name
           from players p
           join characters c on c.player_id = p.id
           where p.guild_id = pm.guild_id and p.player_pin = $3
         )
       )
     order by pm.created_at desc
     limit 50`,
    [guildId, `Spieler ${playerPin}`, playerPin]
  );
  return { success: true, messages: result.rows.map(normalizePlayerMessageRow) };
}

async function getGuildSentMessages({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  const result = await query(
    `select pm.*,
            coalesce((
              select string_agg(c.name, ', ' order by c.name)
              from players p
              join characters c on c.player_id = p.id
              where p.guild_id = pm.guild_id and p.player_pin = pm.player_pin
            ), '') as recipient_names
     from player_messages pm
     where pm.guild_id = $1
       and pm.sender = 'Gildenleitung'
       and coalesce(pm.lead_pin, '') <> ''
     order by pm.created_at desc
     limit 100`,
    [guildId]
  );
  return { success: true, messages: result.rows.map(normalizePlayerMessageRow) };
}

async function markPlayerMessageRead({ guildId, query: params }) {
  const playerPin = normalizePin(params.playerPin || params.pin);
  const id = clean(params.id || params.messageId);
  const result = await query(
    `update player_messages
     set read_at = coalesce(read_at, now())
     where guild_id = $1 and player_pin = $2 and id = $3
     returning *`,
    [guildId, playerPin, id]
  );
  return { success: true, message: result.rows[0] ? normalizePlayerMessageRow(result.rows[0]) : null };
}

async function deletePlayerMessage({ guildId, query: params }) {
  const playerPin = normalizePin(params.playerPin || params.pin);
  const id = clean(params.id || params.messageId);
  const folder = clean(params.folder || params.box);
  if (!playerPin || !id) {
    const error = new Error("Bitte SpielerLogin und Nachricht angeben.");
    error.statusCode = 400;
    throw error;
  }

  const result = await query(
    `delete from player_messages
     where guild_id = $1
       and id = $2
       and (
         player_pin = $3
         or (
           $4 = 'sent'
           and (
             sender = $5
             or sender = any(
               select c.name
               from players p
               join characters c on c.player_id = p.id
               where p.guild_id = player_messages.guild_id and p.player_pin = $3
             )
           )
         )
       )
     returning id`,
    [guildId, id, playerPin, folder, `Spieler ${playerPin}`]
  );
  return { success: true, deleted: result.rowCount };
}

async function deleteGuildPlayerMessage({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  const id = clean(params.id || params.messageId);
  if (!id) {
    const error = new Error("Bitte Nachricht angeben.");
    error.statusCode = 400;
    throw error;
  }

  const result = await query(
    `delete from player_messages
     where guild_id = $1
       and id = $2
       and sender = 'Gildenleitung'
     returning id`,
    [guildId, id]
  );
  return { success: true, deleted: result.rowCount };
}

async function deleteRaid({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  const raidId = clean(params.raidId || params.RaidID || params.raidID);
  const id = clean(params.id || params.dbId || params.databaseId);
  const prioPin = clean(params.playerPin || params.prioPin || params.raidPin);
  const leadPin = clean(params.leadPin || params.raidleadPin);
  const values = [guildId];
  const clauses = [];

  if (id) {
    values.push(id);
    clauses.push(`id::text = $${values.length}`);
  }

  if (raidId) {
    values.push(raidId);
    clauses.push(`external_raid_id = $${values.length}`);
    if (isUuid(raidId)) {
      clauses.push(`id::text = $${values.length}`);
    }
  }

  if (prioPin) {
    values.push(prioPin);
    clauses.push(`raid_pin = $${values.length}`);
  }

  if (leadPin) {
    values.push(leadPin);
    clauses.push(`lead_pin = $${values.length}`);
  }

  if (!clauses.length) {
    const error = new Error("Bitte Raid angeben.");
    error.statusCode = 400;
    throw error;
  }

  const result = await query(
    `delete from raids
     where guild_id = $1
       and (${clauses.join(" or ")})
     returning id, external_raid_id, name`,
    values
  );
  return { success: true, deleted: result.rowCount, raid: result.rows[0] || null };
}

async function createRaid({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  return createRaidRecord({ guildId, query: params });
}

async function createRaidForBot({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  const raidType = normalizeRaidType(params.raid || params.raidName);
  if (!raidType) {
    const error = new Error("Raidtyp fehlt.");
    error.statusCode = 400;
    throw error;
  }
  const prioPin = clean(params.playerPin || params.prioPin || params.raidPin) || randomRaidCode(3);
  return createRaidRecord({
    guildId,
    query: {
      ...params,
      raid: raidType,
      playerPin: prioPin,
      prioPin,
      leadPin: clean(params.leadPin || params.raidleadPin) || randomRaidCode(4),
      status: params.status || "geschlossen",
      p0PlusFreigabe: params.p0PlusFreigabe || "geöffnet",
      raidHelperEnabled: clean(params.raidHelperEnabled || params.raidhelperEnabled || "false"),
      createdBy: clean(params.createdBy || params.erstelltVon) || "Gildenleitung",
      guildName: clean(params.guildName || params.gilde || params.displayGuild || params.guild)
    }
  });
}

async function createRandomRaid({ guildId, query: params }) {
  const raidType = normalizeRaidType(params.raid || params.raidName);
  const allowedRaids = new Set(["mc", "bwl", "aq40", "naxx", "zg", "zg-mittwoch", "zg-prime", "zg-late", "aq20", "ony"]);
  if (!allowedRaids.has(raidType)) {
    const error = new Error("Dieser Raidtyp kann nicht erstellt werden.");
    error.statusCode = 400;
    throw error;
  }

  const prioPin = clean(params.playerPin || params.prioPin || params.raidPin);
  const leadPin = clean(params.leadPin || params.raidleadPin);
  if (!prioPin || !leadPin) {
    const error = new Error("PrioPIN oder LeadPIN fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const creator = clean(params.createdBy || params.created_by || params.erstelltVon || params.ersteller);
  const creatorLogin = clean(params.creatorPlayerLogin || params.spielerLogin || params.loginPin);
  if (!creator && !creatorLogin) {
    const error = new Error("Spielerlogin fehlt. Bitte erst mit deinem Spielerlogin einloggen.");
    error.statusCode = 400;
    throw error;
  }
  const creatorPlayer = creatorLogin ? await findPlayerByPin(guildId, creatorLogin) : null;
  if (!creatorPlayer || !canPlayerRoleCreateRaid(creatorPlayer.role)) {
    const error = new Error("Zum Erstellen von Raids wende dich an die Gildenleitung.");
    error.statusCode = 403;
    throw error;
  }

  return createRaidRecord({
    guildId,
    query: {
      ...params,
      raid: raidType,
      status: "geschlossen",
      p0PlusFreigabe: "geöffnet"
    }
  });
}

async function createRaidRecord({ guildId, query: params }) {
  const raidType = normalizeRaidType(params.raid || params.raidName);
  await requireNachtlootSpecialRaidGuild(guildId, raidType);
  const raidDate = parseDateValue(params.raidDate || params.datum || params.date);
  const raidName = clean(params.raidName) || displayRaidName(raidType);
  const externalRaidId = clean(params.raidId || params.RaidID || params.raidID) || `${raidType}-${Date.now()}`;
  const raidTime = clean(params.raidTime || params.uhrzeit) || null;
  const prioPin = clean(params.playerPin || params.prioPin || params.raidPin);
  const leadPin = clean(params.leadPin || params.raidleadPin);
  const status = normalizeStatus(params.status || "geschlossen");
  const p0plusFreigabe = normalizeStatus(params.p0PlusFreigabe || params.p0PlusOverride || "geöffnet");
  const creatorLogin = clean(params.creatorPlayerLogin || params.spielerLogin || params.loginPin);
  const createdBy =
    clean(params.createdBy || params.created_by || params.erstelltVon || params.ersteller) ||
    (creatorLogin ? `SpielerLogin ${creatorLogin}` : "");

  if (raidType && raidDate && raidTime) {
    const existing = await query(
      `select *
       from raids
       where guild_id = $1
         and lower(raid_type) = any($2)
         and raid_date = $3
         and coalesce(raid_time, '') = $4
         and coalesce(status, '') <> 'archiviert'
       order by
         case when external_raid_id = $5 then 0 else 1 end,
         case when raidhelper_enabled = true then 0 else 1 end,
         created_at asc
       limit 1`,
      [guildId, raidTypeSearchValues(raidType), raidDate, raidTime, externalRaidId]
    );
    if (existing.rows[0] && existing.rows[0].external_raid_id !== externalRaidId) {
      return { success: true, reused: true, ...normalizeRaidRow(existing.rows[0]) };
    }
  }

  const result = await query(
    `insert into raids (
       guild_id, name, raid_type, raid_date, external_raid_id, raid_pin,
       lead_pin, raid_time, guild_name, player_link, status, p0plus_freigabe, created_by,
       raidhelper_enabled, signup_deadline, max_players, tank_slots, heal_slots, dd_slots,
       discord_channel_id, discord_message_id, description, raid_image_url, loot_master, loot_master_targets, status_notify_targets, announcement_notify_targets
     )
     values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
             $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26, $27)
     on conflict (guild_id, external_raid_id)
       where external_raid_id is not null and external_raid_id <> ''
     do update
       set name = coalesce(
             nullif(
               excluded.name,
               case excluded.raid_type
                 when 'mc' then 'Molten Core'
                 when 'bwl' then 'Blackwing Lair'
                 when 'aq40' then 'Ahn''Qiraj 40'
                 when 'naxx' then 'Naxxramas'
                 when 'zg' then 'Zul''Gurub'
                 when 'aq20' then 'AQ 20'
                 when 'ony' then 'Onyxia'
                 else ''
               end
             ),
             raids.name,
             excluded.name
           ),
           external_raid_id = coalesce(excluded.external_raid_id, raids.external_raid_id),
           raid_date = coalesce(excluded.raid_date, raids.raid_date),
           raid_pin = coalesce(excluded.raid_pin, raids.raid_pin),
           lead_pin = coalesce(excluded.lead_pin, raids.lead_pin),
           raid_time = coalesce(excluded.raid_time, raids.raid_time),
           guild_name = coalesce(excluded.guild_name, raids.guild_name),
           player_link = coalesce(excluded.player_link, raids.player_link),
           status = excluded.status,
           p0plus_freigabe = excluded.p0plus_freigabe,
           created_by = coalesce(nullif(excluded.created_by, ''), raids.created_by),
           raidhelper_enabled = excluded.raidhelper_enabled,
           signup_deadline = coalesce(excluded.signup_deadline, raids.signup_deadline),
           max_players = coalesce(excluded.max_players, raids.max_players),
           tank_slots = coalesce(excluded.tank_slots, raids.tank_slots),
           heal_slots = coalesce(excluded.heal_slots, raids.heal_slots),
           dd_slots = coalesce(excluded.dd_slots, raids.dd_slots),
           discord_channel_id = coalesce(excluded.discord_channel_id, raids.discord_channel_id),
           discord_message_id = coalesce(excluded.discord_message_id, raids.discord_message_id),
           description = coalesce(excluded.description, raids.description),
           raid_image_url = coalesce(excluded.raid_image_url, raids.raid_image_url),
           loot_master = coalesce(nullif(excluded.loot_master, ''), raids.loot_master),
           loot_master_targets = case when excluded.loot_master_targets = '[]'::jsonb then raids.loot_master_targets else excluded.loot_master_targets end,
           status_notify_targets = case when excluded.status_notify_targets = '[]'::jsonb then raids.status_notify_targets else excluded.status_notify_targets end,
           announcement_notify_targets = case when excluded.announcement_notify_targets = '[]'::jsonb then raids.announcement_notify_targets else excluded.announcement_notify_targets end,
           updated_at = now()
     returning *`,
    [
      guildId,
      raidName,
      raidType,
      raidDate,
      externalRaidId,
      prioPin || null,
      leadPin || null,
      raidTime,
      clean(params.guildName || params.displayGuild || params.gilde || params.guild) || null,
      clean(params.playerLink) || null,
      status,
      p0plusFreigabe,
      createdBy || null,
      clean(params.raidHelperEnabled || params.raidhelperEnabled).toLowerCase() === "false" ? false : true,
      clean(params.signupDeadline || params.anmeldeschluss) || null,
      parseOptionalInteger(params.maxPlayers || params.maxSpieler),
      parseOptionalInteger(params.tankSlots || params.tanks),
      parseOptionalInteger(params.healSlots || params.heals || params.heiler),
      parseOptionalInteger(params.ddSlots || params.dds),
      clean(params.discordChannelId) || null,
      clean(params.discordMessageId || params.raidHelperMessageId) || null,
      clean(params.description || params.beschreibung) || null,
      clean(params.raidImageUrl || params.imageUrl || params.bildUrl) || null,
      clean(params.lootMaster || params.pluendermeister) || null,
      (() => {try{const value=typeof params.lootMasterTargets==="string"?JSON.parse(params.lootMasterTargets):params.lootMasterTargets;return JSON.stringify(Array.isArray(value)?value:[]);}catch{return "[]";}})(),
      (() => {
        try {
          const value = typeof params.statusNotifyTargets === "string" ? JSON.parse(params.statusNotifyTargets) : params.statusNotifyTargets;
          return JSON.stringify(Array.isArray(value) ? value : []);
        } catch {
          return "[]";
        }
      })(),
      (() => {
        try {
          const value = typeof params.announcementNotifyTargets === "string" ? JSON.parse(params.announcementNotifyTargets) : params.announcementNotifyTargets;
          return JSON.stringify(Array.isArray(value) ? value : []);
        } catch {
          return "[]";
        }
      })()
    ]
  );

  const raid = result.rows[0];
  await syncPoPostDateTimeForRaid(guildId, raid).catch(error => {
    console.warn("PO-Anmelder konnten nach Raid-Änderung nicht aktualisiert werden:", error.message || error);
  });
  if(clean(raid.lead_pin)){
    const savedTargets=Array.isArray(raid.loot_master_targets)?raid.loot_master_targets:[];
    const lootMasterNotificationKey=`loot_master:${clean(raid.raid_type).toLowerCase()}`;
    const configuredTargets=await notificationTargetsForPermissions(guildId,lootMasterNotificationKey).catch(()=>[]);
    const targetKeys=new Set();
    const targets=[...savedTargets,...configuredTargets].filter(target=>{const key=`${clean(target?.type)||"name"}:${clean(target?.value||target?.name)}`;if(targetKeys.has(key))return false;targetKeys.add(key);return clean(target?.value||target?.name);});
    if(targets.length){
      const lootMasterPin=await effectiveLootMasterPin(guildId);
      const messageTemplate=(await notificationMessageTemplate(guildId,lootMasterNotificationKey).catch(()=>""))||(await notificationMessageTemplate(guildId,"loot_master").catch(()=>""));
      await enqueueBotUpdate({guildId,type:"loot_master_leadpin_notice",payload:{targets,raidId:raidPublicId(raid),raidName:raid.name||displayRaidName(raid.raid_type),raidDate:raid.raid_date||"",raidTime:raid.raid_time||"",leadPin:raid.lead_pin,lootMasterPin,messageTemplate}}).catch(error=>console.warn("LeadPIN-DM konnte nicht eingereiht werden:",error.message||error));
    }
  }
  return { success: true, ...normalizeRaidRow(raid) };
}

async function setRaidLootMasterTargets({guildId,query:params}){
  requireMasterCode(params.masterCode);
  const raid=await findRaid(guildId,params);
  if(!raid){const error=new Error("Raid wurde nicht gefunden.");error.statusCode=404;throw error;}
  let targets=[];
  try{const parsed=typeof params.targets==="string"?JSON.parse(params.targets):params.targets;targets=Array.isArray(parsed)?parsed:[];}catch{}
  targets=targets.map(target=>({type:clean(target?.type).toLowerCase()==="role"?"role":"name",value:clean(target?.value||target?.name),label:clean(target?.label||target?.value||target?.name)})).filter(target=>target.value);
  const result=await query(`update raids set loot_master_targets=$1::jsonb,updated_at=now() where id=$2 returning *`,[JSON.stringify(targets),raid.id]);
  const saved=result.rows[0];
  let queued=false;
  if(targets.length&&clean(saved.lead_pin)){
    const lootMasterPin=await effectiveLootMasterPin(guildId);
    const lootMasterNotificationKey=`loot_master:${clean(saved.raid_type).toLowerCase()}`;
    const messageTemplate=(await notificationMessageTemplate(guildId,lootMasterNotificationKey).catch(()=>""))||(await notificationMessageTemplate(guildId,"loot_master").catch(()=>""));
    const notice=await enqueueBotUpdate({guildId,type:"loot_master_leadpin_notice",payload:{targets,raidId:raidPublicId(saved),raidName:saved.name||displayRaidName(saved.raid_type),raidDate:saved.raid_date||"",raidTime:saved.raid_time||"",leadPin:saved.lead_pin,lootMasterPin,messageTemplate}});
    queued=Boolean(notice?.success);
  }
  return {success:true,targets,queued,...normalizeRaidRow(saved)};
}

async function syncPoPostDateTimeForRaid(guildId, raid) {
  if (!raid || !clean(raid.raid_pin)) return { updated: 0, queued: 0 };
  await ensurePoPostEntriesSchema();
  const result = await query(
    `update po_post_entries
     set raid = upper($2),
         raid_date = $3,
         raid_time = $4,
         updated_at = now()
     where guild_id = $1
       and archived_at is null
       and raid_pin = $5
     returning post_key, source_channel_id, target_channel_id, discord_message_id, raid, title`,
    [guildId, normalizeRaidType(raid.raid_type), raid.raid_date, raid.raid_time || "", raid.raid_pin]
  );
  const payloads = new Map();
  for (const row of result.rows || []) {
    const key = [row.post_key, row.source_channel_id, row.target_channel_id, row.discord_message_id || ""].join("|");
    payloads.set(key, {
      postKey: row.post_key || "",
      sourceChannelId: row.source_channel_id || "",
      targetChannelId: row.target_channel_id || row.source_channel_id || "",
      messageId: row.discord_message_id || "",
      discordMessageId: row.discord_message_id || "",
      raid: row.raid || normalizeRaidType(raid.raid_type).toUpperCase(),
      title: row.title || "PO Liste",
      source: "raid_datetime_changed"
    });
  }
  for (const payload of payloads.values()) {
    await enqueueBotUpdate({ guildId, type: "po_post", payload })
      .catch(error => console.warn("PO-Anmelder-Refresh konnte nach Raid-Änderung nicht queued werden:", error.message || error));
  }
  return { updated: result.rowCount || 0, queued: payloads.size };
}

function normalizeRaidSignupRow(row) {
  return {
    id: row.id,
    characterId: row.character_id || "",
    player: row.player_name || row.name || "",
    char: row.player_name || row.name || "",
    server: row.server || "",
    className: row.class_name || "",
    role: normalizeSignupRole(row.role),
    status: normalizeSignupStatus(row.status),
    note: row.note || "",
    source: row.source || "lichtloot",
    discordName: row.discord_name || "",
    discordUserId: row.discord_user_id || "",
    hasPrio: row.has_prio === true || row.has_prio === "true",
    createdAt: row.created_at,
    updatedAt: row.updated_at
  };
}

function buildSignupCounts(signups, externalSignups = []) {
  const counts = {
    signed: 0,
    bench: 0,
    tentative: 0,
    absent: 0,
    total: 0,
    tank: 0,
    heal: 0,
    dd: 0,
    flex: 0,
    external: externalSignups.length
  };
  [...signups, ...externalSignups].forEach(signup => {
    const status = normalizeSignupStatus(signup.status);
    const role = normalizeSignupRole(signup.role);
    counts[status] = Number(counts[status] || 0) + 1;
    if (status !== "absent") counts.total += 1;
    counts[role] = Number(counts[role] || 0) + 1;
  });
  return counts;
}

async function findRaid(guildId, params) {
  const raidId = clean(params.raidId || params.RaidID || params.raidID);
  const leadPin = clean(params.leadPin || params.raidleadPin);
  const prioPin = clean(params.playerPin || params.prioPin || params.raidPin);
  const raidType = normalizeRaidType(params.raid || params.raidName);
  const raidDate = clean(params.raidDate || params.date || params.datum);
  const raidTime = clean(params.raidTime || params.time || params.uhrzeit);
  const values = [guildId];
  const identityClauses = [];

  if (raidId) {
    values.push(raidId);
    if (isUuid(raidId)) {
      identityClauses.push(`id = $${values.length}`);
    } else {
      identityClauses.push(`external_raid_id = $${values.length}`);
    }
  } else if (raidType && raidDate) {
    values.push(raidTypeSearchValues(raidType));
    identityClauses.push(`lower(raid_type) = any($${values.length})`);
    values.push(raidDate);
    identityClauses.push(`raid_date = $${values.length}::date`);
    if (raidTime) {
      values.push(raidTime);
      identityClauses.push(`coalesce(raid_time, '') = $${values.length}`);
    }
  } else if (leadPin) {
    values.push(leadPin);
    identityClauses.push(`lead_pin = $${values.length}`);
  } else if (prioPin) {
    values.push(prioPin);
    identityClauses.push(`raid_pin = $${values.length}`);
  }

  if (!identityClauses.length && raidType) {
    values.push(raidTypeSearchValues(raidType));
    identityClauses.push(`lower(raid_type) = any($${values.length})`);
  }

  const clauses = ["guild_id = $1"];
  if (identityClauses.length) clauses.push(`(${identityClauses.join(" or ")})`);
  if (raidType && (leadPin || prioPin) && !raidId) {
    values.push(raidTypeSearchValues(raidType));
    clauses.push(`lower(raid_type) = any($${values.length})`);
  }

  let result = await query(
    `select *
     from raids
     where ${clauses.join(" and ")}
     order by raid_date desc, created_at desc
     limit 1`,
    values
  );

  if (!result.rows.length && prioPin) {
    result = await query(
      `select *
       from raids
       where guild_id = $1
         and raid_pin = $2
       order by raid_date desc, created_at desc
       limit 1`,
      [guildId, prioPin]
    );
  }

  return result.rows[0] || null;
}

async function findRaidForDiscordImport(guildId, params) {
  const explicitRaid = await findRaid(guildId, params);
  if (explicitRaid) return explicitRaid;

  const raidType = normalizeRaidType(params.raid || params.raidName);
  const raidDate = clean(params.raidDate || params.datum || params.date);
  const raidTime = clean(params.raidTime || params.uhrzeit || params.time);
  const discordMessageId = clean(params.discordMessageId || params.raidHelperMessageId);
  const discordChannelId = clean(params.discordChannelId);

  if (discordMessageId) {
    const values = [guildId, discordMessageId];
    let channelClause = "";
    if (discordChannelId) {
      values.push(discordChannelId);
      channelClause = `and coalesce(discord_channel_id, '') = $${values.length}`;
    }
    const byDiscord = await query(
      `select *
       from raids
       where guild_id = $1
         and discord_message_id = $2
         ${channelClause}
       order by
         case when coalesce(created_by, '') = 'Discord-Import' then 1 else 0 end,
         case when nullif(coalesce(description, ''), '') is not null then 0 else 1 end,
         created_at desc
       limit 1`,
      values
    );
    if (byDiscord.rows[0]) return byDiscord.rows[0];
  }

  if (raidType && raidDate) {
    const result = await query(
      `select *
       from raids
       where guild_id = $1
         and lower(raid_type) = any($2)
         and raid_date = $3
         and ($4 = '' or coalesce(raid_time, '') = $4)
       order by
         case when coalesce(created_by, '') = 'Discord-Import' then 1 else 0 end,
         case when nullif(coalesce(raid_pin, ''), '') is not null then 0 else 1 end,
         case when nullif(coalesce(description, ''), '') is not null then 0 else 1 end,
         created_at desc
       limit 1`,
      [guildId, raidTypeSearchValues(raidType), parseDateValue(raidDate), raidTime]
    );
    if (result.rows[0]) return result.rows[0];
  }

  if (!raidType || !raidDate) return null;
  const created = await createRaidRecord({
    guildId,
    query: {
      raid: raidType,
      raidName: clean(params.raidName) || displayRaidName(raidType),
      raidDate,
      raidTime,
      raidId: `discord-${raidType}-${raidDate}-${raidTime || "time"}`,
      status: "geschlossen",
      p0PlusFreigabe: "geöffnet",
      createdBy: "Discord-Import",
      discordChannelId,
      discordMessageId,
      raidHelperEnabled: "true"
    }
  });
  return findRaid(guildId, { raidId: created.raidId });
}

async function getRaidHelper({ guildId, query: params }) {
  const lookupValue = clean(
    params.raidId
    || params.id
    || params.playerPin
    || params.raidPin
    || [params.raid, params.raidDate, params.raidTime].filter(Boolean).join("|")
  );
  const missingCacheKey = `${guildId}:${lookupValue}`;
  const missingUntil = missingRaidHelperCache.get(missingCacheKey) || 0;
  if (lookupValue && missingUntil > Date.now()) {
    return {
      success: false,
      missing: true,
      stale: true,
      error: "Raid wurde nicht gefunden."
    };
  }
  if (missingUntil) missingRaidHelperCache.delete(missingCacheKey);

  const raid = await findRaid(guildId, params);
  if (!raid) {
    if (lookupValue) {
      missingRaidHelperCache.set(
        missingCacheKey,
        Date.now() + MISSING_RAID_HELPER_CACHE_TTL_MS
      );
    }
    return {
      success: false,
      missing: true,
      stale: true,
      error: "Raid wurde nicht gefunden."
    };
  }
  if (lookupValue) missingRaidHelperCache.delete(missingCacheKey);

  const signupResult = await query(
    `select
       rs.id, rs.character_id, rs.status, rs.note, rs.role, rs.source,
       rs.discord_user_id, rs.discord_name, rs.created_at, rs.updated_at,
       c.name as player_name, c.server, c.class_name,
       exists(
         select 1
         from prios pr
         where pr.raid_id = rs.raid_id
           and pr.character_id = rs.character_id
       ) as has_prio
     from raid_signups rs
     join characters c on c.id = rs.character_id
     where rs.raid_id = $1
     order by
       case rs.status when 'signed' then 0 when 'tentative' then 1 when 'bench' then 2 else 3 end,
       case rs.role when 'tank' then 0 when 'heal' then 1 when 'dd' then 2 else 3 end,
       c.name asc`,
    [raid.id]
  );

  const externalResult = await query(
    `select res.id, res.player_name, res.class_name, res.role, res.status, res.note, res.source,
            res.discord_user_id, res.discord_name, res.created_at, res.updated_at,
            exists(
              select 1
              from prios pr
              join characters c on c.id = pr.character_id
              join players p on p.id = c.player_id
              where pr.raid_id = $2
                and p.guild_id = $1
                and lower(c.name) = lower(res.player_name)
            ) as has_prio
     from raid_external_signups res
     where res.guild_id = $1
       and (res.raid_id = $2 or (res.raid_id is null and lower(res.raid_type) = any($3) and res.raid_date = $4))
     order by res.player_name asc`,
    [guildId, raid.id, raidTypeSearchValues(raid.raid_type), raid.raid_date]
  );

  const signups = signupResult.rows.map(normalizeRaidSignupRow);
  const externalSignups = externalResult.rows.map(row => normalizeRaidSignupRow({ ...row, source: row.source || "discord" }));
  await ensurePoPostEntriesSchema();
  const poPins = [raid.raid_pin, raid.external_raid_id, raid.id].map(clean).filter(Boolean);
  const poApprovalResult = poPins.length ? await query(
    `select player_name, approval_status
     from po_post_entries
     where guild_id = $1
       and archived_at is null
       and raid_pin = any($2)
       and coalesce(player_name, '') <> ''`,
    [guildId, poPins]
  ) : { rows: [] };
  const poApprovalByPlayer = new Map();
  for (const row of poApprovalResult.rows) {
    const playerKey = clean(row.player_name).toLowerCase();
    const status = clean(row.approval_status).toLowerCase();
    const current = poApprovalByPlayer.get(playerKey) || "";
    if (["approved", "freigegeben"].includes(status)) poApprovalByPlayer.set(playerKey, "approved");
    else if (!current && ["pending", "offen", "wartet"].includes(status)) poApprovalByPlayer.set(playerKey, "pending");
  }
  for (const row of [...signups, ...externalSignups]) {
    row.poApprovalStatus = poApprovalByPlayer.get(clean(row.player || row.char).toLowerCase()) || "";
  }
  const prioCountResult = await query("select count(*)::int as count from prios where raid_id = $1", [raid.id]);
  const prioCount = Number(prioCountResult.rows[0]?.count || 0);
  const signupCount = signups.length + externalSignups.length;
  const warnings = [];
  if (signupCount > 0 && prioCount === 0) {
    warnings.push("Attendance vorhanden, aber keine Prioliste gespeichert.");
  }
  return {
    success: true,
    raid: {
      ...normalizeRaidRow(raid),
      signupCount,
      prioCount,
      warnings
    },
    signups,
    externalSignups,
    counts: buildSignupCounts(signups, externalSignups),
    prioCount,
    warnings
  };
}

async function saveRaidSignup({ guildId, query: params }) {
  const raid = await findRaid(guildId, params);
  if (!raid) {
    const error = new Error("Raid wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const playerPin = normalizePin(params.playerPin || params.pin || params.spielerLogin);
  const charName = clean(params.char || params.character || params.player);
  if (!playerPin || !charName) {
    const error = new Error("SpielerLogin und Charakter fehlen.");
    error.statusCode = 400;
    throw error;
  }

  const character = await findCharacterForPin(guildId, playerPin, charName, params.server);
  if (!character) {
    const error = new Error("Dieser Charakter gehört nicht zu deinem SpielerLogin.");
    error.statusCode = 403;
    throw error;
  }
  if (normalizePlayerApprovalStatus(character.approval_status) !== "approved") {
    const error = new Error("Dieser SpielerLogin wartet noch auf Freigabe durch die Gildenleitung.");
    error.statusCode = 403;
    throw error;
  }

  const status = normalizeSignupStatus(params.signupStatus || params.signup || params.status);
  const role = normalizeSignupRole(params.signupRole || params.role);
  const note = clean(params.note || params.comment);
  const source = clean(params.source || "lichtloot");
  const discordUserId = clean(params.discordUserId);
  const discordName = clean(params.discordName);

  // Pro Raid darf ein SpielerLogin nur genau einen Charakter anmelden.
  // Ein Wechsel des Charakters ersetzt deshalb die bisherige Anmeldung.
  await query(
    `delete from raid_signups rs
     using characters c
     where rs.character_id = c.id
       and rs.raid_id = $1
       and c.player_id = $2
       and rs.character_id <> $3`,
    [raid.id, character.player_id, character.id]
  );

  // Ältere Discord-Importe desselben Spielers dürfen nicht parallel zur
  // verifizierten SpielerLogin-Anmeldung im Embed stehen bleiben.
  await query(
    `delete from raid_external_signups
     where guild_id = $1
       and raid_id = $2
       and (
         lower(player_name) = lower($3)
         or ($4 <> '' and player_pin = $4)
         or ($5 <> '' and discord_user_id = $5)
       )`,
    [guildId, raid.id, charName, playerPin, discordUserId]
  );

  const result = await query(
    `insert into raid_signups (
       raid_id, character_id, status, note, role, source, discord_user_id, discord_name
     )
     values ($1,$2,$3,$4,$5,$6,$7,$8)
     on conflict (raid_id, character_id)
     do update
       set status = excluded.status,
           note = excluded.note,
           role = excluded.role,
           source = excluded.source,
           discord_user_id = coalesce(nullif(excluded.discord_user_id, ''), raid_signups.discord_user_id),
           discord_name = coalesce(nullif(excluded.discord_name, ''), raid_signups.discord_name),
           updated_at = now()
     returning *`,
    [
      raid.id,
      character.id,
      status,
      note,
      role,
      source,
      discordUserId,
      discordName
    ]
  );

  let snapshot = null;
  try {
    snapshot = await getRaidHelper({ guildId, query: { raidId: raid.external_raid_id || raid.id, playerPin: raid.raid_pin || "" } });
  } catch {
    snapshot = null;
  }

  let refreshQueued = false;
  if (raid.discord_channel_id && raid.discord_message_id) {
    const refresh = await enqueueBotUpdate({
      guildId,
      type: "raid_announcement_refresh",
      payload: {
        raidId: raid.external_raid_id || raid.id,
        playerPin: raid.raid_pin || "",
        prioPin: raid.raid_pin || "",
        raid: raid.raid_type || "",
        raidDate: raid.raid_date ? raid.raid_date.toISOString().slice(0, 10) : "",
        raidTime: raid.raid_time || "",
        channelId: raid.discord_channel_id,
        discordChannelId: raid.discord_channel_id,
        messageId: raid.discord_message_id,
        discordMessageId: raid.discord_message_id,
        raidSnapshot: snapshot?.raid || normalizeRaidRow(raid),
        signups: snapshot?.signups || [],
        externalSignups: snapshot?.externalSignups || [],
        source: "raid_signup_saved"
      }
    }).catch(() => null);
    refreshQueued = Boolean(refresh?.success);
  }

  return {
    success: true,
    raid: snapshot?.raid || normalizeRaidRow(raid),
    signup: normalizeRaidSignupRow({
      ...result.rows[0],
      player_name: character.name,
      server: character.server,
      class_name: character.class_name
    }),
    helper: snapshot || null,
    signups: snapshot?.signups || [],
    externalSignups: snapshot?.externalSignups || [],
    refreshQueued
  };
}

async function deleteRaidSignup({ guildId, query: params }) {
  const raid = await findRaid(guildId, params);
  if (!raid) return { success: true, deleted: 0 };

  const playerPin = normalizePin(params.playerPin || params.pin || params.spielerLogin);
  const charName = clean(params.char || params.character || params.player);
  if (!playerPin || !charName) {
    const error = new Error("SpielerLogin und Charakter fehlen.");
    error.statusCode = 400;
    throw error;
  }

  const character = await findCharacterForPin(guildId, playerPin, charName, params.server);
  if (!character) {
    const error = new Error("Dieser Charakter gehört nicht zu deinem SpielerLogin.");
    error.statusCode = 403;
    throw error;
  }

  const result = await query(
    `delete from raid_signups
     where raid_id = $1 and character_id = $2`,
    [raid.id, character.id]
  );
  return { success: true, deleted: result.rowCount };
}

async function adminUpdateRaidHelperSignup({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  const signupId = clean(params.signupId || params.id);
  const nextStatus = normalizeSignupStatus(params.signupStatus || params.status);
  const shouldDelete = ["delete", "remove", "verwerfen"].includes(clean(params.mode || params.signupAction || params.actionMode).toLowerCase());
  const notifyMessage = clean(params.notifyMessage || params.message || params.reason || "");
  if (!signupId || !isUuid(signupId)) {
    const error = new Error("Anmeldungs-ID fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const existingSignup = await findRaidHelperSignupForAdmin(guildId, signupId);
  if (!existingSignup) {
    const error = new Error("Anmeldung wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  if (shouldDelete) {
    const externalDelete = await query(
      `delete from raid_external_signups
       where guild_id = $1 and id = $2`,
      [guildId, signupId]
    );
    const localDelete = await query(
      `delete from raid_signups rs
       using raids r
       where rs.raid_id = r.id
       and r.guild_id = $1
         and rs.id = $2`,
      [guildId, signupId]
    );
    const deleted = externalDelete.rowCount + localDelete.rowCount;
    const sideEffects = await enqueueRaidHelperAdminSideEffects(guildId, existingSignup, "deleted", notifyMessage);
    return { success: true, deleted, signup: existingSignup, queued: true, ...sideEffects };
  }

  const externalUpdate = await query(
    `update raid_external_signups
     set status = $3,
         updated_at = now()
     where guild_id = $1 and id = $2
     returning *`,
    [guildId, signupId, nextStatus]
  );
  if (externalUpdate.rows[0]) {
    const signup = normalizeRaidSignupRow({ ...externalUpdate.rows[0], source: externalUpdate.rows[0].source || "discord" });
    const sideEffects = await enqueueRaidHelperAdminSideEffects(guildId, { ...existingSignup, ...signup, status: nextStatus }, nextStatus, notifyMessage);
    return { success: true, signup, queued: true, ...sideEffects };
  }

  const localUpdate = await query(
    `update raid_signups rs
     set status = $3,
         updated_at = now()
     from raids r
     where rs.raid_id = r.id
       and r.guild_id = $1
       and rs.id = $2
     returning rs.*`,
    [guildId, signupId, nextStatus]
  );
  if (localUpdate.rows[0]) {
    const signup = normalizeRaidSignupRow(localUpdate.rows[0]);
    const sideEffects = await enqueueRaidHelperAdminSideEffects(guildId, { ...existingSignup, status: nextStatus }, nextStatus, notifyMessage);
    return { success: true, signup, queued: true, ...sideEffects };
  }

  const error = new Error("Anmeldung wurde nicht gefunden.");
  error.statusCode = 404;
  throw error;
}

async function findRaidHelperSignupForAdmin(guildId, signupId) {
  const external = await query(
    `select
       res.id, res.player_name, res.class_name, res.role, res.status, res.note, res.source,
       res.discord_user_id, res.discord_name, res.created_at, res.updated_at,
       r.id as raid_uuid, r.external_raid_id, r.name as raid_name, r.raid_type, r.raid_date, r.raid_time,
       r.discord_channel_id, r.discord_message_id, r.created_by, r.loot_master, r.status_notify_targets
     from raid_external_signups res
     left join raids r on r.id = res.raid_id and r.guild_id = res.guild_id
     where res.guild_id = $1 and res.id = $2
     limit 1`,
    [guildId, signupId]
  );
  if (external.rows[0]) {
    const row = external.rows[0];
    return {
      ...normalizeRaidSignupRow({ ...row, source: row.source || "discord" }),
      raidId: row.external_raid_id || row.raid_uuid || "",
      raidName: row.raid_name || displayRaidName(row.raid_type),
      raidDate: row.raid_date ? row.raid_date.toISOString().slice(0, 10) : "",
      raidTime: row.raid_time || "",
      discordChannelId: row.discord_channel_id || "",
      discordMessageId: row.discord_message_id || "",
      createdBy: row.created_by || "",
      lootMaster: row.loot_master || "",
      statusNotifyTargets: Array.isArray(row.status_notify_targets) ? row.status_notify_targets : []
    };
  }

  const local = await query(
    `select
       rs.id, rs.character_id, rs.status, rs.note, rs.role, rs.source,
       rs.discord_user_id, rs.discord_name, rs.created_at, rs.updated_at,
       c.name as player_name, c.server, c.class_name,
       r.id as raid_uuid, r.external_raid_id, r.name as raid_name, r.raid_type, r.raid_date, r.raid_time,
       r.discord_channel_id, r.discord_message_id, r.created_by, r.loot_master, r.status_notify_targets
     from raid_signups rs
     join raids r on r.id = rs.raid_id and r.guild_id = $1
     join characters c on c.id = rs.character_id
     where rs.id = $2
     limit 1`,
    [guildId, signupId]
  );
  if (!local.rows[0]) return null;
  const row = local.rows[0];
  return {
    ...normalizeRaidSignupRow(row),
    raidId: row.external_raid_id || row.raid_uuid || "",
    raidName: row.raid_name || displayRaidName(row.raid_type),
    raidDate: row.raid_date ? row.raid_date.toISOString().slice(0, 10) : "",
    raidTime: row.raid_time || "",
    discordChannelId: row.discord_channel_id || "",
    discordMessageId: row.discord_message_id || "",
    createdBy: row.created_by || "",
    lootMaster: row.loot_master || "",
    statusNotifyTargets: Array.isArray(row.status_notify_targets) ? row.status_notify_targets : []
  };
}

async function enqueueRaidHelperAdminSideEffects(guildId, signup, action, notifyMessage) {
  let refreshQueued = false;
  let noticeQueued = false;
  let noticeSkipped = "";
  if (signup?.raidId) {
    const refresh = await enqueueBotUpdate({
      guildId,
      type: "raid_announcement_refresh",
      payload: {
        raidId: signup.raidId,
        channelId: signup.discordChannelId || "",
        discordChannelId: signup.discordChannelId || "",
        messageId: signup.discordMessageId || "",
        discordMessageId: signup.discordMessageId || "",
        source: "raid_helper_admin"
      }
    }).catch(() => null);
    refreshQueued = Boolean(refresh?.success);
  }

  const configuredStatusTargets=await notificationTargetsForPermissions(guildId,"raid_status_changes").catch(()=>[]);
  const savedStatusTargets=Array.isArray(signup?.statusNotifyTargets)?signup.statusNotifyTargets:[];
  const statusTargetKeys=new Set();
  const statusTargets=[...savedStatusTargets,...configuredStatusTargets].filter(target=>{const key=`${clean(target?.type)||"name"}:${clean(target?.value||target?.name)}`;if(statusTargetKeys.has(key))return false;statusTargetKeys.add(key);return clean(target?.value||target?.name);});
  const statusMessageTemplate=await notificationMessageTemplate(guildId,"raid_status_changes").catch(()=>"");

  await enqueueBotUpdate({
    guildId,
    type: "raid_status_staff_notice",
    payload: {
      player: clean(signup?.player || signup?.char || ""),
      raidName: clean(signup?.raidName || "Raid"),
      raidDate: clean(signup?.raidDate || ""),
      raidTime: clean(signup?.raidTime || ""),
      action: clean(action || ""),
      message: notifyMessage,
      changedBy: "Gildenleitung",
      createdBy: clean(signup?.createdBy || ""),
      lootMaster: clean(signup?.lootMaster || ""),
      targets: statusTargets,
      messageTemplate: statusMessageTemplate
    }
  }).catch(() => null);

  const userId = clean(signup?.discordUserId || "");
  if (!userId) {
    return { refreshQueued, noticeQueued, noticeSkipped: "missing_discord_user" };
  }
  const notice = await enqueueBotUpdate({
    guildId,
    type: "raid_signup_notice",
    payload: {
      userId,
      discordName: clean(signup.discordName || ""),
      player: clean(signup.player || signup.char || ""),
      raidId: clean(signup.raidId || ""),
      raidName: clean(signup.raidName || "Raid"),
      raidDate: clean(signup.raidDate || ""),
      raidTime: clean(signup.raidTime || ""),
      action: clean(action || ""),
      message: notifyMessage,
      source: "raid_helper_admin"
    }
  }).catch(() => null);
  noticeQueued = Boolean(notice?.success);
  if (!noticeQueued) noticeSkipped = "queue_failed";
  return { refreshQueued, noticeQueued, noticeSkipped };
}

async function saveDiscordSignupRows({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  const rows = Array.isArray(params.rows)
    ? params.rows
    : (() => {
        try {
          const parsed = JSON.parse(clean(params.rows || "[]"));
          return Array.isArray(parsed) ? parsed : [];
        } catch {
          return [];
        }
      })();

  const raid = await findRaidForDiscordImport(guildId, params);
  if (!raid) {
    const error = new Error("Raid für Discord-Anmeldungen wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }
  const incomingChannelId = clean(params.discordChannelId);
  const incomingMessageId = clean(params.raidHelperMessageId || params.discordMessageId);
  if (incomingChannelId || incomingMessageId) {
    await query(
      `update raids
       set discord_channel_id = coalesce(nullif($3, ''), discord_channel_id),
           discord_message_id = coalesce(nullif($4, ''), discord_message_id),
           updated_at = now()
       where guild_id = $1 and id = $2`,
      [guildId, raid.id, incomingChannelId, incomingMessageId]
    );
    raid.discord_channel_id = incomingChannelId || raid.discord_channel_id;
    raid.discord_message_id = incomingMessageId || raid.discord_message_id;
  }

  let written = 0;
  for (const row of rows) {
    const playerName = clean(row.char || row.spieler || row.player || row.name);
    if (!playerName) continue;
    const source = clean(row.quelle || row.source || `Discord:${clean(params.discordChannelId)}:${clean(params.raidHelperMessageId || params.discordMessageId)}`);
    const discordUserId = clean(row.discordUserId);
    const normalizedStatus = normalizeSignupStatus(row.status);
    const normalizedRole = normalizeSignupRole(row.role || row.rolle);
    const rowNote = clean(row.note || row.comment);

    // Status-Schaltflächen bearbeiten die vorhandene, per SpielerLogin
    // angelegte Anmeldung. Ohne diese Prüfung entstand zusätzlich ein
    // externer Datensatz und derselbe Charakter erschien zweimal.
    const localUpdate = await query(
      `update raid_signups rs
       set status = $4,
           role = $5,
           note = $6,
           source = coalesce(nullif($7, ''), rs.source),
           discord_user_id = coalesce(nullif($8, ''), rs.discord_user_id),
           discord_name = coalesce(nullif($9, ''), rs.discord_name),
           updated_at = now()
       from characters c
       where rs.character_id = c.id
         and rs.raid_id = $1
         and lower(c.name) = lower($2)
         and (
           ($3 <> '' and rs.discord_user_id = $3)
           or rs.source = $7
         )
       returning rs.id`,
      [
        raid.id,
        playerName,
        discordUserId,
        normalizedStatus,
        normalizedRole,
        rowNote,
        source,
        discordUserId,
        clean(row.discordName || row.discord)
      ]
    );

    if (localUpdate.rowCount) {
      await query(
        `delete from raid_external_signups
         where guild_id = $1
           and raid_id = $2
           and (
             lower(player_name) = lower($3)
             or ($4 <> '' and discord_user_id = $4)
           )`,
        [guildId, raid.id, playerName, discordUserId]
      );
      written += 1;
      continue;
    }

    const updateResult = await query(
      `update raid_external_signups
       set raid_date = $5,
           raid_time = $6,
           class_name = coalesce(nullif($7, ''), class_name),
           role = $8,
           status = $9,
           discord_user_id = coalesce(nullif($10, ''), discord_user_id),
           discord_name = coalesce(nullif($11, ''), discord_name),
           discord_channel_id = coalesce(nullif($12, ''), discord_channel_id),
           discord_message_id = coalesce(nullif($13, ''), discord_message_id),
           note = $14,
           player_pin = coalesce(nullif($15, ''), player_pin),
           updated_at = now()
       where guild_id = $1
         and raid_id = $2
         and lower(player_name) = lower($3)
         and source = $4`,
      [
        guildId,
        raid.id,
        playerName,
        source,
        parseDateValue(params.raidDate || row.raidDate || raid.raid_date),
        clean(params.raidTime || row.raidTime || raid.raid_time),
        clean(row.klasse || row.className),
        normalizedRole,
        normalizedStatus,
        discordUserId,
        clean(row.discordName || row.discord),
        clean(params.discordChannelId || row.discordChannelId),
        clean(params.raidHelperMessageId || params.discordMessageId || row.raidHelperMessageId || row.discordMessageId),
        rowNote,
        clean(row.playerPin || row.pin || row.spielerLogin)
      ]
    );

    if (!updateResult.rowCount) {
      await query(
        `insert into raid_external_signups (
         raid_id, guild_id, raid_type, raid_date, raid_time, player_name, class_name,
         role, status, source, discord_user_id, discord_name, discord_channel_id,
         discord_message_id, note, player_pin
       )
       values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)`,
        [
          raid.id,
          guildId,
          normalizeRaidType(params.raid || row.raid || raid.raid_type),
          parseDateValue(params.raidDate || row.raidDate || raid.raid_date),
          clean(params.raidTime || row.raidTime || raid.raid_time),
          playerName,
          clean(row.klasse || row.className),
          normalizedRole,
          normalizedStatus,
          source,
          discordUserId,
          clean(row.discordName || row.discord),
          clean(params.discordChannelId || row.discordChannelId),
          clean(params.raidHelperMessageId || params.discordMessageId || row.raidHelperMessageId || row.discordMessageId),
          rowNote,
          clean(row.playerPin || row.pin || row.spielerLogin)
        ]
      );
    }
    written += 1;
  }

  return { success: true, raidId: raidPublicId(raid), written };
}

async function getPublishedPrios({ guildId, query: params }) {
  const raid = await findRaid(guildId, params);
  if (!raid) {
    return { success: true, prios: [], published: false, status: "geschlossen" };
  }

  const result = await query(
    `select
       pr.id,
       pr.comment,
       pr.bench,
       c.name as player,
       c.server,
       c.class_name,
       c.is_main,
       c.created_at as character_created_at,
       i1.name as p1,
       i1.item_id as p1_item_id,
       i2.name as p2,
       i2.item_id as p2_item_id,
       i3.name as p3,
       i3.item_id as p3_item_id
     from prios pr
     join characters c on c.id = pr.character_id
     left join items i1 on i1.id = pr.p1_item_id
     left join items i2 on i2.id = pr.p2_item_id
     left join items i3 on i3.id = pr.p3_item_id
     where pr.raid_id = $1
     order by c.is_main desc, ${prioClassOrderSql("c.class_name")} asc, lower(c.name) asc, c.created_at asc`,
    [raid.id]
  );

  const normalizedRaid = normalizeRaidRow(raid);
  const transferResult = await query(
    `select count(*)::int as count
     from p0plus_points
     where guild_id = $1
       and source = 'Raidlead Transfer'
       and note in ($2, $3, $4)`,
    [guildId, `RaidID: ${raidPublicId(raid)}`, `RaidID: ${raid.id}`, `RaidID: ${raid.raid_pin}`]
  );
  const p0PlusTransferCount = Number(transferResult.rows[0]?.count || 0);
  const raidStatus = normalizeStatus(raid.status);
  const published = ["geöffnet", "veröffentlicht", "published"].includes(raidStatus.toLowerCase());
  return {
    success: true,
    ...normalizedRaid,
    p0PlusTransferred: p0PlusTransferCount > 0,
    p0PlusTransferCount,
    published,
    open: raidStatus !== "geöffnet" && !published,
    prios: result.rows.map((row, index) => {
      const meta = commentMeta(row.comment);
      return {
        id: row.id,
        rowNumber: index + 1,
        Spieler: row.player,
        player: row.player,
        Server: row.server || "",
        server: row.server || "",
        Klasse: row.class_name || "",
        className: row.class_name || "",
        isMain: Boolean(row.is_main),
        main: Boolean(row.is_main),
        P1: row.p1 || "",
        p1: row.p1 || "",
        P1ItemId: row.p1_item_id || "",
        p1ItemId: row.p1_item_id || "",
        P2: row.p2 || "",
        p2: row.p2 || "",
        P2ItemId: row.p2_item_id || "",
        p2ItemId: row.p2_item_id || "",
        P3: row.p3 || "",
        p3: row.p3 || "",
        P3ItemId: row.p3_item_id || "",
        p3ItemId: row.p3_item_id || "",
        P0Plus: meta.p0Plus || "nein",
        p0Plus: meta.p0Plus || "nein",
        Bench: row.bench || "",
        bench: row.bench || ""
      };
    })
  };
}

async function findP0DiscordRaid(guildId, params) {
  const raidType = normalizeRaidType(params.raid || params.raidName);
  const prioPin = clean(params.raidPin || params.prioPin || params.playerPin || params.pin);
  if (prioPin) {
    const raid = await findRaid(guildId, {
      ...params,
      raid: raidType,
      playerPin: prioPin,
      prioPin,
      raidPin: prioPin
    });
    if (raid) {
      const allowed = new Set(["mc", "bwl", "aq40", "naxx", "zg-mittwoch", "zg-prime", "zg-late"]);
      return allowed.has(normalizeRaidType(raid.raid_type)) ? raid : null;
    }
  }

  const rawRaidDate = clean(params.raidDate || params.date || params.datum);
  const raidDate = rawRaidDate ? parseDateValue(rawRaidDate) : "";
  const raidTime = clean(params.raidTime || params.time || params.uhrzeit);
  if (raidType && raidDate) {
    const values = [guildId, raidTypeSearchValues(raidType), raidDate];
    let timeClause = "";
    if (raidTime) {
      values.push(raidTime);
      timeClause = `and coalesce(raid_time, '') = $${values.length}`;
    }
    const result = await query(
      `select *
       from raids
       where guild_id = $1
         and lower(raid_type) = any($2)
         and raid_date = $3
         ${timeClause}
       order by created_at desc
       limit 1`,
      values
    );
    if (result.rows[0]) return result.rows[0];
  }

  const raid = await findRaid(guildId, params);
  if (!raid) return null;
  const allowed = new Set(["mc", "bwl", "aq40", "naxx", "zg-mittwoch", "zg-prime", "zg-late"]);
  return allowed.has(normalizeRaidType(raid.raid_type)) ? raid : null;
}

function normalizeP0SignupRow(row) {
  const approvalStatus = clean(row.approval_status || "pending") || "pending";
  const raidType = row.raid_type || row.raid || "";
  return {
    id: row.id,
    raidId: row.raid_public_id || row.raid_id || "",
    raid: normalizeRaidType(raidType).toUpperCase(),
    raidName: row.raid_name || displayRaidName(raidType),
    raidDate: row.raid_date || "",
    raidTime: row.raid_time || "",
    prioPin: row.player_link || row.prio_pin || "",
    player: row.player_name || "",
    char: row.player_name || "",
    server: row.server || "",
    item: row.item_name || "",
    itemName: row.item_name || "",
    itemId: row.item_id || "",
    discordUserId: row.discord_user_id || "",
    discordName: row.discord_name || "",
    discordChannelId: row.discord_channel_id || "",
    discordMessageId: row.discord_message_id || "",
    approvalStatus,
    approved: approvalStatus === "approved",
    rejected: approvalStatus === "rejected",
    approvedByDiscordId: row.approved_by_discord_id || "",
    approvedByDiscordName: row.approved_by_discord_name || "",
    approvedAt: row.approved_at || "",
    updatedAt: row.updated_at,
    createdAt: row.created_at
  };
}

function isP0PostRefreshRaid(raidType) {
  return new Set(["mc", "bwl", "aq40", "naxx", "zg-mittwoch", "zg-prime", "zg-late"]).has(normalizeRaidType(raidType));
}

async function enqueueP0PostRefreshForRaid(guildId, raid, source) {
  if (!raid || !isP0PostRefreshRaid(raid.raid_type || raid.raid)) {
    return { success: true, skipped: true, reason: "unsupported_raid" };
  }

  const signupChannelResult = await query(
    `select discord_channel_id, discord_message_id
     from p0_discord_signups
     where guild_id = $1
       and raid_id = $2
       and coalesce(discord_channel_id, '') <> ''
     order by updated_at desc, created_at desc
     limit 1`,
    [guildId, raid.id]
  );
  const signupChannel = signupChannelResult.rows[0] || {};
  const channelId = clean(signupChannel.discord_channel_id || raid.discord_channel_id || "");
  if (!channelId) {
    return { success: true, skipped: true, reason: "missing_channel" };
  }
  const normalizedRaid = normalizeRaidRow(raid);

  return enqueueBotUpdate({
    guildId,
    type: "p0_post_refresh",
    payload: {
      raid: raid.raid_type || "",
      raidId: raidPublicId(raid),
      raidDate: normalizedRaid.raidDate,
      raidTime: normalizedRaid.raidTime,
      raidPin: normalizedRaid.playerPin || normalizedRaid.prioPin || "",
      prioPin: normalizedRaid.playerPin || normalizedRaid.prioPin || "",
      playerPin: normalizedRaid.playerPin || normalizedRaid.prioPin || "",
      channelId,
      discordChannelId: channelId,
      messageId: clean(signupChannel.discord_message_id || ""),
      discordMessageId: clean(signupChannel.discord_message_id || ""),
      source
    }
  });
}

async function getP0DiscordSignupList({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  await ensureRaidSchema();
  const rawStatus = clean(params.status || "pending").toLowerCase();
  const statusFilter = rawStatus === "all" ? "" : rawStatus;
  const values = [guildId];
  let statusClause = "";
  if (statusFilter) {
    values.push(statusFilter);
    statusClause = `and lower(pds.approval_status) = $${values.length}`;
  }
  const rawRaidFilter = clean(params.raid || params.raidName);
  const raidFilter = rawRaidFilter ? normalizeRaidType(rawRaidFilter) : "";
  let raidClause = "";
  if (raidFilter) {
    values.push(raidTypeSearchValues(raidFilter));
    raidClause = `and lower(r.raid_type) = any($${values.length})`;
  }

  const result = await query(
    `select
       pds.*,
       r.raid_type,
       r.raid_date,
       r.raid_time,
       r.player_link,
       coalesce(nullif(r.external_raid_id, ''), r.id::text) as raid_public_id
     from p0_discord_signups pds
     join raids r on r.id = pds.raid_id
     where pds.guild_id = $1
       ${statusClause}
       ${raidClause}
     order by
       case pds.approval_status when 'pending' then 0 when 'approved' then 1 else 2 end,
       r.raid_date desc nulls last,
       r.raid_time desc nulls last,
       pds.updated_at desc`,
    values
  );

  return {
    success: true,
    entries: result.rows.map(normalizeP0SignupRow)
  };
}

async function getP0DiscordSignupContext({ guildId, query: params }) {
  await ensureRaidSchema();
  await ensureGuildPoItemsSchema();
  const guildResult = await query(`select lower(slug) as slug from guilds where id = $1 limit 1`, [guildId]);
  const restrictToConfiguredPoItems = guildResult.rows[0]?.slug === "nachtloot";
  const raid = await findP0DiscordRaid(guildId, params);
  if (!raid) {
    const error = new Error("Kein passender PO+-Raid gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const itemResult = await query(
    `select
       i.id, i.raid_type, i.item_id, i.name, i.quality, i.icon_url,
       i.slot, i.type, i.boss, i.bind, i.category, i.wowhead,
       i.stats_text, i.tooltip, i.needed, i.equip, i.price, i.dropchance,
       coalesce(sum(pp.points), 0)::numeric as p0plus_points,
       count(pp.id)::int as p0plus_count
     from items i
     ${restrictToConfiguredPoItems
       ? "join guild_po_items gpi on gpi.guild_id = $2 and gpi.item_id = i.id and gpi.enabled = true"
       : ""}
     left join p0plus_points pp on pp.guild_id = $2 and pp.item_id = i.id
     where lower(i.raid_type) = any($1)
        or lower(regexp_replace(i.raid_type, '[^a-z0-9]+', '-', 'g')) = any($1)
     group by i.id
     order by i.name asc`,
    [raidTypeSearchValues(lootSourceRaidType(raid.raid_type)), guildId]
  );

  const signupResult = await query(
    `select *
     from p0_discord_signups
     where guild_id = $1 and raid_id = $2
     order by item_name asc, player_name asc`,
    [guildId, raid.id]
  );
  const prioResult = await query(
    `select
       pr.id,
       pr.character_id,
       pr.comment,
       pr.created_at,
       pr.updated_at,
       c.name as player_name,
       c.server,
       i.id as item_id,
       i.name as item_name
     from prios pr
     join characters c on c.id = pr.character_id
     join players p on p.id = c.player_id and p.guild_id = $1
     left join items i on i.id = pr.p1_item_id
     where pr.raid_id = $2
     order by lower(coalesce(i.name, '')) asc, lower(c.name) asc`,
    [guildId, raid.id]
  );
  const signupRows = signupResult.rows.map(normalizeP0SignupRow);
  const signupCharacterIds = new Set(signupResult.rows.map(row => clean(row.character_id)).filter(Boolean));
  const signupPlayerKeys = new Set(signupRows.map(row => `${clean(row.player).toLowerCase()}|${clean(row.server).toLowerCase()}`));
  const normalizedRaid = normalizeRaidRow(raid);
  const lichtlootP0Rows = prioResult.rows
    .filter(row => {
      const meta = commentMeta(row.comment);
      return clean(meta.p0Plus).toLowerCase() === "ja" && clean(row.item_name);
    })
    .filter(row => {
      const characterId = clean(row.character_id);
      const playerKey = `${clean(row.player_name).toLowerCase()}|${clean(row.server).toLowerCase()}`;
      return !signupCharacterIds.has(characterId) && !signupPlayerKeys.has(playerKey);
    })
    .map(row => ({
      id: row.id,
      raidId: raidPublicId(raid),
      raid: normalizeRaidType(raid.raid_type).toUpperCase(),
      raidName: normalizedRaid.raidName,
      raidDate: normalizedRaid.raidDate,
      raidTime: normalizedRaid.raidTime,
      prioPin: normalizedRaid.playerPin || normalizedRaid.prioPin || "",
      player: row.player_name || "",
      char: row.player_name || "",
      server: row.server || "",
      item: row.item_name || "",
      itemName: row.item_name || "",
      itemId: row.item_id || "",
      discordUserId: "",
      discordName: "LichtLoot",
      discordChannelId: "",
      discordMessageId: "",
      approvalStatus: "approved",
      approved: true,
      rejected: false,
      approvedByDiscordId: "",
      approvedByDiscordName: "LichtLoot",
      approvedAt: row.updated_at || row.created_at || "",
      updatedAt: row.updated_at,
      createdAt: row.created_at,
      source: "lichtloot"
    }));

  return {
    success: true,
    raid: normalizedRaid,
    raidId: raidPublicId(raid),
    items: itemResult.rows.map(row => ({
      ...normalizeLootItemForApi(row),
      p0PlusPoints: Number(row.p0plus_points || 0),
      p0PlusCount: Number(row.p0plus_count || 0)
    })),
    signups: [...signupRows, ...lichtlootP0Rows].sort((a, b) => {
      const itemCompare = String(a.item || "").localeCompare(String(b.item || ""));
      if (itemCompare) return itemCompare;
      return String(a.player || "").localeCompare(String(b.player || ""));
    })
  };
}

async function findOrCreateDiscordP0Character(client, guildId, params) {
  const player = clean(params.player || params.char || params.spieler);
  const server = clean(params.server);
  const playerPin = normalizePin(params.playerPin || params.pin || params.password || params.passwort || params.meinLichtloot);
  const discordUserId = clean(params.discordUserId);

  if (!player) {
    const error = new Error("Charakter fehlt.");
    error.statusCode = 400;
    throw error;
  }

  if (playerPin) {
    const verified = await findCharacterForPin(guildId, playerPin, player, server);
    if (!verified) {
      const error = new Error("Mein-Lichtloot Login/PIN passt nicht zu diesem Charakter.");
      error.statusCode = 403;
      throw error;
    }

    if (discordUserId) {
      await client.query(
        `insert into discord_player_links (guild_id, discord_user_id, character_id, discord_name, source)
         values ($1, $2, $3, $4, 'discord-p0')
         on conflict (guild_id, discord_user_id, character_id) do update
           set discord_name = coalesce(nullif(excluded.discord_name, ''), discord_player_links.discord_name),
               updated_at = now()`,
        [guildId, discordUserId, verified.id, clean(params.discordName)]
      );
    }
    return verified;
  }

  if (discordUserId) {
    const linked = await client.query(
      `select c.id, c.name, c.server, c.class_name, c.created_at
       from discord_player_links dpl
       join characters c on c.id = dpl.character_id
       join players p on p.id = c.player_id
       where dpl.guild_id = $1
         and dpl.discord_user_id = $2
         and p.guild_id = $1
         and lower(c.name) = lower($3)
       order by
         case when lower(c.server) = lower($4) then 0 else 1 end,
         dpl.updated_at desc
       limit 1`,
      [guildId, discordUserId, player, server]
    );
    if (linked.rows[0]) return linked.rows[0];
  }

  const error = new Error("Bitte einmal deinen Mein-Lichtloot Login/PIN für diesen Charakter eingeben.");
  error.statusCode = 403;
  throw error;
}

async function saveP0DiscordSignup({ guildId, query: params }) {
  await ensureRaidSchema();
  const raid = await findP0DiscordRaid(guildId, params);
  if (!raid) {
    const error = new Error("Kein passender PO+-Raid gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const discordUserId = clean(params.discordUserId);
  const itemId = clean(params.itemId || params.lootItemId);
  const itemName = clean(params.item || params.itemName);
  if (!discordUserId) {
    const error = new Error("Discord-User fehlt.");
    error.statusCode = 400;
    throw error;
  }
  if (!itemId && !itemName) {
    const error = new Error("Item fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const client = await pool.connect();
  try {
    await client.query("begin");
    const item = itemId
      ? (await client.query(
          `select id, name from items where id::text = $1 and lower(raid_type) = any($2) limit 1`,
          [itemId, raidTypeSearchValues(raid.raid_type)]
        )).rows[0]
      : await upsertItem(client, raid.raid_type, itemName);

    if (!item) {
      const error = new Error("Item wurde nicht gefunden.");
      error.statusCode = 404;
      throw error;
    }

    await requireGuildPoItem(guildId, item.id, item.name);

    const character = await findOrCreateDiscordP0Character(client, guildId, params);
    const releaseRaid = normalizePoReleaseRaid(raid.raid_type);
    if (releaseRaid) {
      const releaseResult = await client.query(
        `select 1 from character_po_releases where guild_id = $1 and character_id = $2 and raid_type = $3 limit 1`,
        [guildId, character.id, releaseRaid]
      );
      if (!releaseResult.rows[0]) {
        const error = new Error("du hast keine P0+ Freigabe wende dich an den Raidlead");
        error.statusCode = 403;
        throw error;
      }
    }
    await removeDuplicatePriosForCharacterName(client, raid.id, character);
    const comment = JSON.stringify({
      p0Plus: "ja",
      p0Item: item.name,
      raidTime: raid.raid_time || "",
      source: "discord-p0",
      discordUserId
    });

    await client.query(
      `insert into prios (raid_id, character_id, p1_item_id, p2_item_id, p3_item_id, comment)
       values ($1, $2, $3, null, null, $4)
       on conflict (raid_id, character_id) do update
         set p1_item_id = excluded.p1_item_id,
             p2_item_id = null,
             p3_item_id = null,
             comment = excluded.comment,
             updated_at = now()`,
      [raid.id, character.id, item.id, comment]
    );

    const signupResult = await client.query(
      `insert into p0_discord_signups (
         guild_id, raid_id, character_id, item_id, player_name, server, item_name,
         discord_user_id, discord_name, discord_channel_id, discord_message_id,
         approval_status, approved_by_discord_id, approved_by_discord_name, approved_at
       )
       values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'pending', null, null, null)
       on conflict (guild_id, raid_id, discord_user_id) do update
         set character_id = excluded.character_id,
             item_id = excluded.item_id,
             player_name = excluded.player_name,
             server = excluded.server,
             item_name = excluded.item_name,
             discord_name = excluded.discord_name,
             discord_channel_id = coalesce(nullif(excluded.discord_channel_id, ''), p0_discord_signups.discord_channel_id),
             discord_message_id = coalesce(nullif(excluded.discord_message_id, ''), p0_discord_signups.discord_message_id),
             approval_status = 'pending',
             approved_by_discord_id = null,
             approved_by_discord_name = null,
             approved_at = null,
             updated_at = now()
       returning *`,
      [
        guildId,
        raid.id,
        character.id,
        item.id,
        character.name,
        character.server,
        item.name,
        discordUserId,
        clean(params.discordName),
        clean(params.discordChannelId),
        clean(params.discordMessageId)
      ]
    );
    const itemSignupResult = await client.query(
      `select *
       from p0_discord_signups
       where guild_id = $1
         and raid_id = $2
         and item_id = $3
       order by
         case approval_status when 'approved' then 0 when 'pending' then 1 else 2 end,
         lower(player_name) asc`,
      [guildId, raid.id, item.id]
    );

    await client.query("commit");
    return {
      success: true,
      raid: normalizeRaidRow(raid),
      signup: normalizeP0SignupRow(signupResult.rows[0]),
      itemSignups: itemSignupResult.rows.map(normalizeP0SignupRow),
      syncedPrio: true
    };
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function reviewP0DiscordSignup({ guildId, query: params }) {
  requireMasterOrQueueToken(params);
  await ensureRaidSchema();
  const signupId = clean(params.signupId || params.id);
  const rawStatus = clean(params.status || params.value || params.approvalStatus).toLowerCase();
  const approvedValues = new Set(["approved", "valid", "gueltig", "gültig", "ja", "true", "ok"]);
  const rejectedValues = new Set(["rejected", "invalid", "ungueltig", "ungültig", "nein", "false", "no"]);

  if (!isUuid(signupId)) {
    const error = new Error("P0+-Anmeldung fehlt.");
    error.statusCode = 400;
    throw error;
  }
  if (!approvedValues.has(rawStatus) && !rejectedValues.has(rawStatus)) {
    const error = new Error("Prüfstatus fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const approvalStatus = approvedValues.has(rawStatus) ? "approved" : "rejected";
  const result = await query(
    `update p0_discord_signups
     set approval_status = $3,
         approved_by_discord_id = $4,
         approved_by_discord_name = $5,
         approved_at = case when $3 = 'approved' then now() else null end,
         updated_at = now()
     where guild_id = $1 and id = $2
     returning *`,
    [
      guildId,
      signupId,
      approvalStatus,
      clean(params.reviewerDiscordId || params.discordUserId),
      clean(params.reviewerDiscordName || params.discordName || params.reviewer)
    ]
  );

  if (!result.rows[0]) {
    const error = new Error("P0+-Anmeldung wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const signup = result.rows[0];
  if (clean(signup.discord_channel_id)) {
    const raidResult = await query(`select * from raids where id = $1 and guild_id = $2 limit 1`, [signup.raid_id, guildId]);
    const raid = raidResult.rows[0] || {};
    await enqueueBotUpdate({
      guildId,
      type: "p0_post_refresh",
      payload: {
        raid: raid.raid_type || "",
        raidId: raidPublicId(raid),
        raidDate: raid.raid_date || "",
        raidTime: raid.raid_time || "",
        raidPin: raid.player_link || "",
        channelId: signup.discord_channel_id,
        source: "p0_review"
      }
    }).catch(error => console.warn("P0 Discordpost konnte nicht queued werden:", error.message || error));
  }
  const itemSignupResult = await query(
    `select *
     from p0_discord_signups
     where guild_id = $1
       and raid_id = $2
       and item_id = $3
     order by
       case approval_status when 'approved' then 0 when 'pending' then 1 else 2 end,
       lower(player_name) asc`,
    [guildId, signup.raid_id, signup.item_id]
  );

  return {
    success: true,
    signup: normalizeP0SignupRow(signup),
    itemSignups: itemSignupResult.rows.map(normalizeP0SignupRow)
  };
}

async function getPublicPrioCharacters({ guildId }) {
  const result = await query(
    `select
       c.name,
       c.server,
       c.class_name,
       bool_or(coalesce(c.is_main, false)) as is_main,
       count(distinct pr.raid_id)::int as raid_count,
       max(r.raid_date) as last_raid_date
     from prios pr
     join raids r on r.id = pr.raid_id
     join characters c on c.id = pr.character_id
     where r.guild_id = $1
     group by lower(c.name), lower(coalesce(c.server, '')), c.name, c.server, c.class_name
     order by c.name asc`,
    [guildId]
  );

  return {
    success: true,
    characters: result.rows.map(row => ({
      name: row.name || "",
      server: row.server || "",
      className: row.class_name || "",
      Klasse: row.class_name || "",
      isMain: Boolean(row.is_main),
      raidCount: Number(row.raid_count || 0),
      lastRaidDate: row.last_raid_date ? new Date(row.last_raid_date).toISOString().slice(0, 10) : ""
    }))
  };
}

async function getPrioCheck({ guildId, query: params }) {
  const raid = await findRaid(guildId, params);
  if (!raid) {
    return { success: true, check: null };
  }

  return {
    success: true,
    check: {
      raid: raidPublicId(raid),
      counts: {},
      missingPrio: [],
      updatedAt: new Date().toISOString()
    }
  };
}

async function validateLeadPin({ guildId, query: params }) {
  const leadPin = clean(params.leadPin || params.raidleadPin);
  if (!leadPin) {
    return { success: false, error: "Falsche Raidlead-PIN." };
  }

  const result = await query(
    `select *
     from raids
     where guild_id = $1
       and lower(lead_pin) = lower($2)
     order by raid_date desc, created_at desc
     limit 1`,
    [guildId, leadPin]
  );
  const raid = result.rows[0] || null;

  if (!raid || !clean(raid.lead_pin)) {
    return { success: false, error: "Falsche Raidlead-PIN." };
  }

  return { success: true, ...normalizeRaidRow(raid) };
}

async function findRaidByPrioPin({ guildId, query: params }) {
  const prioPin = clean(params.playerPin || params.prioPin || params.raidPin || params.pin);
  if (!prioPin) {
    return { success: false, error: "Bitte Random PrioPIN eingeben." };
  }

  const raid = await findRaid(guildId, { playerPin: prioPin });
  if (!raid || !clean(raid.raid_pin)) {
    return { success: false, error: "Kein Raid zu dieser Random PrioPIN gefunden." };
  }

  return { success: true, ...normalizeRaidRow(raid) };
}

async function setRaidStatus({ guildId, query: params }) {
  const master = clean(params.masterCode);
  if (master) requireMasterCode(master);

  const raid = await findRaid(guildId, params);
  if (!raid) {
    const error = new Error("Raid wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const leadPin = clean(params.leadPin || params.raidleadPin);
  if (!master && raid.lead_pin && leadPin !== raid.lead_pin) {
    const error = new Error("LeadPIN passt nicht zu diesem Raid.");
    error.statusCode = 403;
    throw error;
  }

  const status = normalizeStatus(params.status || raid.status);
  const p0plus = clean(params.p0PlusFreigabe || params.p0PlusOverride || params.value)
    ? normalizeStatus(params.p0PlusFreigabe || params.p0PlusOverride || params.value)
    : raid.p0plus_freigabe;
  const archiveRequested = ["archiviert", "archive"].includes(status);
  const raidType = normalizeRaidType(raid.raid_type || raid.raid || params.raid);

  if (archiveRequested && ["mc", "bwl", "aq40", "naxx", "zg-mittwoch", "zg-prime", "zg-late"].includes(raidType)) {
    const transferNotes = Array.from(new Set([
      `RaidID: ${raidPublicId(raid)}`,
      `RaidID: ${raid.id}`,
      raid.raid_pin ? `RaidID: ${raid.raid_pin}` : ""
    ].filter(Boolean)));
    const transferResult = await query(
      `select count(*)::int as count
       from p0plus_points
       where guild_id = $1
         and source = 'Raidlead Transfer'
         and note = any($2::text[])`,
      [guildId, transferNotes]
    );
    if (Number(transferResult.rows[0]?.count || 0) < 1) {
      const error = new Error("Raid kann erst archiviert werden, wenn PO+ übertragen wurde.");
      error.statusCode = 409;
      throw error;
    }
  }

  const result = await query(
    `update raids
     set status = $1,
         p0plus_freigabe = $2,
         updated_at = now()
     where id = $3
     returning *`,
    [status, p0plus, raid.id]
  );

  return { success: true, ...normalizeRaidRow(result.rows[0]) };
}

function bossTokenNoticeForRaid(raidType) {
  switch (normalizeRaidType(raidType)) {
    case "bwl":
      return { token: "Kopf von Nefarian", label: "Kopf von Nefarian" };
    case "ony":
      return { token: "Kopf von Onyxia", label: "Kopf von Onyxia" };
    case "zg":
      return { token: "Herz von Hakkar", label: "Herz von Hakkar" };
    default:
      return null;
  }
}

async function queueRaidleadBossTokenNotice({ guildId, query: params }) {
  const raid = await findRaid(guildId, params);
  if (!raid) {
    const error = new Error("Raid wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const leadPin = clean(params.leadPin || params.raidleadPin);
  if (raid.lead_pin && leadPin !== raid.lead_pin) {
    const error = new Error("LeadPIN passt nicht zu diesem Raid.");
    error.statusCode = 403;
    throw error;
  }

  const raidType = normalizeRaidType(params.raid || raid.raid_type || raid.raid || "");
  const notice = bossTokenNoticeForRaid(raidType);
  if (!notice) {
    const error = new Error("Bosskopf-/Herz-Meldungen gibt es nur für BWL, Ony und ZG.");
    error.statusCode = 400;
    throw error;
  }

  const player = clean(params.player || params.charakter || params.character);
  if (!player) {
    const error = new Error("Spieler fehlt.");
    error.statusCode = 400;
    throw error;
  }

  return enqueueBotUpdate({
    guildId,
    type: "boss_token_notice",
    payload: {
      channelId: worldbuffAnnouncementChannelId,
      raid: raidType,
      raidName: raid.raid_name || raid.name || raidType,
      raidId: raidPublicId(raid),
      raidDate: clean(params.raidDate || params.date || "") || (raid.raid_date ? formatCsvDateTime(raid.raid_date).slice(0, 10) : ""),
      raidTime: clean(params.raidTime || params.time || "") || clean(raid.raid_time || ""),
      player,
      server: clean(params.server || ""),
      token: notice.token,
      source: "raidlead_panel"
    }
  });
}

async function setP0PlusOverride({ guildId, query: params }) {
  const enabled = ["true", "ja", "1", "geöffnet", "offen"].includes(clean(params.enabled || params.value).toLowerCase());
  return setRaidStatus({
    guildId,
    query: {
      ...params,
      status: params.status || undefined,
      p0PlusFreigabe: enabled ? "geöffnet" : "geschlossen"
    }
  });
}

async function findPrioForRaidAndPlayer(raidId, player, server) {
  const values = [raidId, clean(player)];
  let serverClause = "";
  if (clean(server)) {
    values.push(clean(server));
    serverClause = `and lower(c.server) = lower($${values.length})`;
  }

  const result = await query(
    `select
       pr.id,
       pr.character_id,
       pr.p1_item_id,
       i.name as item_name,
       c.name as player,
       c.server
     from prios pr
     join characters c on c.id = pr.character_id
     left join items i on i.id = pr.p1_item_id
     where pr.raid_id = $1
       and lower(c.name) = lower($2)
       ${serverClause}
     limit 1`,
    values
  );
  return result.rows[0] || null;
}

async function setPrioBench({ guildId, query: params }) {
  const master = clean(params.masterCode);
  if (master) requireMasterCode(master);

  const raid = await findRaid(guildId, params);
  if (!raid) {
    const error = new Error("Raid wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const leadPin = clean(params.leadPin || params.raidleadPin);
  if (!master && raid.lead_pin && leadPin !== raid.lead_pin) {
    const error = new Error("LeadPIN passt nicht zu diesem Raid.");
    error.statusCode = 403;
    throw error;
  }

  const prio = await findPrioForRaidAndPlayer(raid.id, params.player || params.char || params.spieler, params.server);
  if (!prio) {
    const error = new Error("Prio wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const bench = ["ja", "true", "1", "bench"].includes(clean(params.bench).toLowerCase()) ? "ja" : "";
  const note = `Bench RaidID: ${raidPublicId(raid)}`;
  const client = await pool.connect();

  try {
    await client.query("begin");
    await client.query("update prios set bench = $1, updated_at = now() where id = $2", [bench, prio.id]);

    if (prio.p1_item_id) {
      const oldPoints = await getP0PlusPointTotal(client, guildId, prio.character_id, prio.p1_item_id);
      await client.query(
        `delete from p0plus_points
         where guild_id = $1 and character_id = $2 and item_id = $3 and source = 'Bench' and note = $4`,
        [guildId, prio.character_id, prio.p1_item_id, note]
      );

      if (bench) {
        await client.query(
          `insert into p0plus_points (guild_id, character_id, item_id, points, source, note)
           values ($1, $2, $3, 0.5, 'Bench', $4)`,
          [guildId, prio.character_id, prio.p1_item_id, note]
        );
      }
      const newPoints = await getP0PlusPointTotal(client, guildId, prio.character_id, prio.p1_item_id);
      if (oldPoints !== newPoints) {
        await insertP0PlusAudit(client, {
          guildId,
          characterId: prio.character_id,
          itemId: prio.p1_item_id,
          raidId: raid.id,
          raidType: raid.raid_type,
          playerName: prio.player || "",
          server: prio.server || "",
          itemName: prio.item_name || "",
          oldPoints,
          newPoints,
          action: bench ? "bench_add" : "bench_remove",
          source: "Gildenleitung Bench",
          note
        });
      }
    }

    await client.query("commit");
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }

  return { success: true, bench, player: prio.player, server: prio.server };
}

async function deleteGuildPrio({ guildId, query: params }) {
  const master = clean(params.masterCode);
  if (master) requireMasterCode(master);

  const raid = await findRaid(guildId, params);
  if (!raid) {
    const error = new Error("Raid wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const leadPin = clean(params.leadPin || params.raidleadPin);
  if (!master && raid.lead_pin && leadPin !== raid.lead_pin) {
    const error = new Error("LeadPIN passt nicht zu diesem Raid.");
    error.statusCode = 403;
    throw error;
  }

  const prio = await findPrioForRaidAndPlayer(raid.id, params.player || params.char || params.spieler, params.server);
  if (!prio) return { success: true, deleted: 0 };

  const result = await query("delete from prios where id = $1 returning id", [prio.id]);
  const refresh = await enqueueRaidAnnouncementRefreshAfterPrioChange(guildId, raid, "guild_prio_deleted");
  return { success: true, deleted: result.rowCount, raidAnnouncementRefresh: refresh };
}

async function getP0Plus(guildId, params = {}) {
  const raidType = normalizeRaidType(params.raid || params.raidType || "");
  const values = [guildId];
  let raidClause = "";
  if (raidType && raidType !== "raid") {
    values.push(raidTypeSearchValues(raidType));
    raidClause = `and lower(coalesce(i.raid_type, '')) = any($${values.length})`;
  }
  const result = await query(
    `select
       coalesce(i.raid_type, 'Raid') as raid,
       coalesce(i.name, pp.note, 'P0/P0+') as item,
       coalesce(i.quality, '') as quality,
       c.name as player,
       c.server,
       pp.points,
       pp.source,
       pp.note,
       pp.created_at
     from p0plus_points pp
     join characters c on c.id = pp.character_id
     left join items i on i.id = pp.item_id
     where pp.guild_id = $1
       ${raidClause}
     order by raid asc, item asc, player asc`,
    values
  );

  const grouped = new Map();
  result.rows.forEach(row => {
    const key = [
      clean(row.raid).toLowerCase(),
      clean(row.item).toLowerCase(),
      clean(row.player).toLowerCase(),
      clean(row.server).toLowerCase()
    ].join("|");
    const current = grouped.get(key) || {
      raid: row.raid,
      item: row.item,
      quality: row.quality || "",
      player: row.player,
      server: row.server || "",
      slot: readSlotFromNote(row.note),
      count: 0,
      points: 0,
      source: row.source || "",
      createdAt: row.created_at,
      created_at: row.created_at
    };
    if (row.created_at) {
      const currentTime = current.createdAt ? new Date(current.createdAt).getTime() : 0;
      const rowTime = new Date(row.created_at).getTime();
      if (!Number.isNaN(rowTime) && rowTime > currentTime) {
        current.createdAt = row.created_at;
        current.created_at = row.created_at;
      }
    }
    const points = Number(row.points) || 0;
    current.count += points;
    current.points += points;
    grouped.set(key, current);
  });

  return { success: true, entries: Array.from(grouped.values()).filter(entry => Number(entry.count) > 0) };
}

async function getRaidP0PlusAudit({ guildId, query: params }) {
  requireMasterCode(params.masterCode);

  const raidType = normalizeRaidType(params.raid || "aq40");
  const date = clean(params.date);
  const values = [guildId, raidTypeSearchValues(raidType)];
  let dateClause = "";

  if (date) {
    values.push(date);
    dateClause = `and (r.raid_date = $${values.length}::date or pr.created_at::date = $${values.length}::date)`;
  }

  const priosResult = await query(
    `select
       r.external_raid_id,
       r.raid_type,
       r.name as raid_name,
       r.raid_date,
       r.raid_time,
       r.raid_pin,
       r.status,
       r.created_at as raid_created_at,
       pr.comment,
       pr.created_at as prio_created_at,
       c.name as player,
       c.server,
       c.class_name,
       i1.name as p1,
       i2.name as p2,
       i3.name as p3
     from prios pr
     join raids r on r.id = pr.raid_id
     join characters c on c.id = pr.character_id
     left join items i1 on i1.id = pr.p1_item_id
     left join items i2 on i2.id = pr.p2_item_id
     left join items i3 on i3.id = pr.p3_item_id
     where r.guild_id = $1
       and lower(r.raid_type) = any($2)
       ${dateClause}
     order by r.raid_date desc nulls last, r.created_at desc, c.name asc`,
    values
  );

  const transferValues = [guildId, raidTypeSearchValues(raidType)];
  let transferDateClause = "";
  if (date) {
    transferValues.push(date);
    transferDateClause = `and pp.created_at::date = $${transferValues.length}::date`;
  }
  const transferResult = await query(
    `select
       pp.points,
       pp.source,
       pp.note,
       pp.created_at,
       c.name as player,
       c.server,
       i.name as item,
       i.raid_type
     from p0plus_points pp
     join characters c on c.id = pp.character_id
     left join items i on i.id = pp.item_id
     where pp.guild_id = $1
       and pp.source = 'Raidlead Transfer'
       and lower(coalesce(i.raid_type, '')) = any($2)
       ${transferDateClause}
     order by pp.created_at desc, c.name asc`,
    transferValues
  );

  const prios = priosResult.rows.map(row => {
    const meta = commentMeta(row.comment);
    return {
      raidId: row.external_raid_id || "",
      raid: row.raid_type || "",
      raidName: row.raid_name || "",
      raidDate: row.raid_date || "",
      raidTime: row.raid_time || "",
      raidPin: row.raid_pin || "",
      status: row.status || "",
      player: row.player || "",
      server: row.server || "",
      className: row.class_name || "",
      p1: row.p1 || "",
      p2: row.p2 || "",
      p3: row.p3 || "",
      p0Plus: meta.p0Plus || "nein",
      p0Item: meta.p0Item || "",
      prioCreatedAt: row.prio_created_at,
      raidCreatedAt: row.raid_created_at
    };
  });

  const transfers = transferResult.rows.map(row => ({
    player: row.player || "",
    server: row.server || "",
    item: row.item || "",
    points: Number(row.points || 0),
    note: row.note || "",
    createdAt: row.created_at
  }));

  return {
    success: true,
    raid: raidType,
    date,
    prios,
    p0PlusPrios: prios.filter(row => normalizeStatus(row.p0Plus) === "ja"),
    transfers
  };
}

async function findCharacterByName(guildId, charName, server) {
  const params = [guildId, clean(charName)];
  let serverClause = "";
  if (clean(server)) {
    params.push(clean(server));
    serverClause = `and lower(c.server) = lower($${params.length})`;
  }

  const result = await query(
    `select c.id, c.name, c.server, c.class_name
     from characters c
     join players p on p.id = c.player_id
     where p.guild_id = $1 and lower(c.name) = lower($2)
       ${serverClause}
     order by c.created_at asc
     limit 1`,
    params
  );
  return result.rows[0] || null;
}

async function getP0PlusPointTotal(client, guildId, characterId, itemId) {
  const result = await client.query(
    `select coalesce(sum(points), 0)::numeric as points
     from p0plus_points
     where guild_id = $1 and character_id = $2 and item_id = $3`,
    [guildId, characterId, itemId]
  );
  return Number(result.rows[0]?.points || 0);
}

async function insertP0PlusAudit(client, {
  guildId,
  characterId,
  itemId,
  raidId = null,
  raidType = "",
  playerName = "",
  server = "",
  itemName = "",
  oldPoints = 0,
  newPoints = 0,
  action = "",
  source = "",
  note = ""
}) {
  await client.query(
    `insert into p0plus_point_audit
       (guild_id, character_id, item_id, raid_id, raid_type, player_name, server, item_name,
        old_points, new_points, delta_points, action, source, note)
     values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)`,
    [
      guildId,
      characterId || null,
      itemId || null,
      raidId || null,
      raidType || "",
      playerName || "",
      server || "",
      itemName || "",
      oldPoints,
      newPoints,
      Number(newPoints || 0) - Number(oldPoints || 0),
      action || "",
      source || "",
      note || ""
    ]
  );
}

function formatCsvDateTime(value) {
  if (!value) return "";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return clean(value);
  return date.toISOString();
}

function p0PlusExportKey(player, server, item) {
  return [
    clean(player).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, ""),
    clean(server).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, ""),
    clean(item).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "")
  ].join("|");
}

async function buildP0PlusTransferWorkbook({ guildId, raid, awardedRows, skippedRows = [] }) {
  const raidType = normalizeRaidType(raid?.raid_type || raid?.raid || "");
  const current = await getP0Plus(guildId, { raid: raidType });
  const awardedByKey = new Map();
  for (const row of awardedRows || []) {
    const key = p0PlusExportKey(row.player, row.server, row.item_name || row.item);
    awardedByKey.set(key, (awardedByKey.get(key) || 0) + 1);
  }

  // Bei einer manuellen Sicherung gibt es keine awardedRows aus dem aktuellen
  // Transferlauf. Deshalb werden die heute wirklich übertragenen Punkte aus
  // dem unveränderlichen Audit-Protokoll ergänzt.
  const todayTransferResult = await query(
    `select player_name, server, item_name, old_points, new_points, delta_points,
            source, note, created_at
     from p0plus_point_audit
     where guild_id = $1
       and lower(coalesce(raid_type, '')) = any($2)
       and action = 'raid_transfer'
       and delta_points > 0
       and (created_at at time zone 'Europe/Berlin')::date =
           (now() at time zone 'Europe/Berlin')::date
     order by created_at asc, player_name asc, item_name asc`,
    [guildId, raidTypeSearchValues(raidType)]
  );
  const todayAwardedByKey = new Map();
  for (const row of todayTransferResult.rows) {
    const key = p0PlusExportKey(row.player_name, row.server, row.item_name);
    const transferred = Number(row.delta_points || 0);
    todayAwardedByKey.set(key, (todayAwardedByKey.get(key) || 0) + transferred);
  }
  for (const [key, transferred] of todayAwardedByKey.entries()) {
    awardedByKey.set(key, Math.max(awardedByKey.get(key) || 0, transferred));
  }

  const currentRows = [
    ["Raid", "Spieler", "Server", "Item", "Slot", "PO+ Punkte pre Raid", "Uebertragung", "Aktuelle Punkte", "Quelle", "Letzte Aenderung"]
  ];
  for (const entry of current.entries || []) {
    const currentPoints = Number(entry.count ?? entry.points ?? 0);
    const awarded = awardedByKey.get(p0PlusExportKey(entry.player, entry.server, entry.item)) || 0;
    currentRows.push([
      entry.raid || raidType,
      entry.player || "",
      entry.server || "",
      entry.item || "",
      entry.slot || "",
      currentPoints - awarded,
      awarded,
      currentPoints,
      entry.source || "",
      formatCsvDateTime(entry.createdAt || entry.created_at || "")
    ]);
  }
  if (skippedRows.length) {
    currentRows.push([]);
    currentRows.push(["Uebersprungen"]);
    currentRows.push(["Spieler", "Item", "Grund"]);
    for (const row of skippedRows) {
      currentRows.push([row.player || "", row.item || "", row.reason || ""]);
    }
  }

  const receivedResult = await query(
    `select player_name, server, item_name, old_points, new_points, delta_points, source, note, created_at
     from p0plus_point_audit
     where guild_id = $1
       and lower(coalesce(raid_type, '')) = any($2)
       and action = 'item_received_clear'
     order by created_at desc, player_name asc, item_name asc`,
    [guildId, raidTypeSearchValues(raidType)]
  );
  const receivedRows = [
    ["Spieler", "Server", "Item", "Punkte vorher", "Punkte nachher", "Aenderung", "Quelle", "Notiz", "Datum"]
  ];
  for (const row of receivedResult.rows) {
    receivedRows.push([
      row.player_name || "",
      row.server || "",
      row.item_name || "",
      Number(row.old_points || 0),
      Number(row.new_points || 0),
      Number(row.delta_points || 0),
      row.source || "",
      row.note || "",
      formatCsvDateTime(row.created_at || "")
    ]);
  }
  if (receivedRows.length === 1) {
    receivedRows.push(["", "", "Noch keine protokollierten Items erhalten.", "", "", "", "", "", ""]);
  }
  const todayTransferRows = [
    ["Spieler", "Server", "Item", "Punkte vorher", "Heute uebertragen", "Aktuelle Punkte", "Quelle", "Raid", "Datum"]
  ];
  for (const row of todayTransferResult.rows) {
    todayTransferRows.push([
      row.player_name || "",
      row.server || "",
      row.item_name || "",
      Number(row.old_points || 0),
      Number(row.delta_points || 0),
      Number(row.new_points || 0),
      row.source || "",
      raidType,
      formatCsvDateTime(row.created_at || "")
    ]);
  }
  if (todayTransferRows.length === 1) {
    todayTransferRows.push(["", "", "Heute wurden fuer diesen Raid noch keine PO+ Punkte uebertragen.", "", "", "", "", raidType, ""]);
  }
  return [
    { name: "PO+ aktuell", rows: currentRows },
    { name: "Heute uebertragen", rows: todayTransferRows },
    { name: "Items erhalten", rows: receivedRows }
  ];
}

async function queueP0PlusTransferCsvExport({ guildId, raid, awardedRows, skippedRows, backupChannelIdOverride = "", queueType = "p0plus_transfer_export" }) {
  const guildResult = await query(`select lower(slug) as slug from guilds where id = $1 limit 1`, [guildId]);
  const guildSlug = clean(guildResult.rows[0]?.slug).toLowerCase();
  const fixedNachtlootChannel = guildSlug === "nachtloot" ? "1531288738326642828" : "";
  const backupChannelId = clean(backupChannelIdOverride)
    || fixedNachtlootChannel
    || await resolveGuildBackupChannelId({
      guildId,
      envFallbackChannelId: p0PlusTransferExportChannelId,
      kind: "p0plus"
    });
  if (!backupChannelId) {
    const error = new Error("Kein PO+-Backup-Channel fuer diese Gilde gefunden. Bitte Bot in den PO-Backup-/Sicherungs-Channel einladen oder einen Channel mit 'po-backup', 'p0-backup', 'backup' oder 'sicherung' im Namen anlegen.");
    error.statusCode = 400;
    throw error;
  }
  const raidType = normalizeRaidType(raid?.raid_type || raid?.raid || "");
  const raidDate = raid?.raid_date ? formatCsvDateTime(raid.raid_date).slice(0, 10) : "";
  const fileSafeRaid = clean(raidType || "raid").toLowerCase().replace(/[^a-z0-9]+/g, "-") || "raid";
  const fileSafeDate = clean(raidDate).replace(/[^0-9-]+/g, "") || new Date().toISOString().slice(0, 10);
  const sheets = await buildP0PlusTransferWorkbook({ guildId, raid, awardedRows, skippedRows });
  return enqueueBotUpdate({
    guildId,
    type: queueType,
    payload: {
      channelId: backupChannelId,
      backupKind: queueType === "p0plus_backup_export" ? "p0plus" : "",
      raid: raidType,
      raidName: raid?.name || raidType,
      raidDate,
      raidTime: raid?.raid_time || "",
      raidId: raidPublicId(raid || {}),
      awarded: (awardedRows || []).length,
      skipped: (skippedRows || []).length,
      filename: `po-plus-${fileSafeRaid}-${fileSafeDate}.xlsx`,
      sheets
    }
  });
}

async function queueManualP0PlusBackup({ guildId, query: params }) {
  requireMasterCode(params.masterCode);

  const requestedRaid = clean(params.raid || params.raidType || "all40").toLowerCase();
  const backupChannelIdOverride = clean(params.channelId || params.backupChannelId || params.targetChannelId);
  const raidTypes = requestedRaid === "all" || requestedRaid === "all40" || requestedRaid === "40"
    ? ["naxx", "aq40", "bwl", "mc"]
    : [normalizeRaidType(requestedRaid)];
  const queued = [];
  const today = new Date().toISOString().slice(0, 10);

  for (const raidType of raidTypes.filter(Boolean)) {
    const exportResult = await queueP0PlusTransferCsvExport({
      guildId,
      raid: {
        raid_type: raidType,
        raid: raidType,
        name: raidType.toUpperCase(),
        raid_date: today,
        raid_time: "",
        external_raid_id: `MANUELL-${raidType.toUpperCase()}-${today}`
      },
      awardedRows: [],
      skippedRows: [],
      backupChannelIdOverride,
      queueType: "p0plus_backup_export"
    });
    queued.push({
      raid: raidType,
      rowNumber: exportResult.rowNumber || "",
      skipped: Boolean(exportResult.skipped),
      reason: exportResult.reason || ""
    });
  }

  return { success: true, queued };
}

async function setP0PlusPoints({ guildId, query: params }) {
  requireMasterCode(params.masterCode);

  const raidType = normalizeRaidType(params.raid);
  const player = clean(params.player || params.char || params.spieler);
  const server = clean(params.server);
  const itemName = clean(params.item);
  const slot = clean(params.slot);
  const points = Number(String(params.points || "0").replace(",", "."));

  if (!raidType || !player || !itemName || !Number.isFinite(points) || points < 0) {
    const error = new Error("Raid, Spieler, Item und Punkte werden benötigt.");
    error.statusCode = 400;
    throw error;
  }

  const character = await findCharacterByName(guildId, player, server);
  if (!character) {
    const error = new Error("Dieser Charakter wurde in Railway nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const client = await pool.connect();
  try {
    await client.query("begin");
    const item = await upsertItem(client, raidType, itemName);
    const oldPoints = await getP0PlusPointTotal(client, guildId, character.id, item.id);

    await client.query(
      `delete from p0plus_points
       where guild_id = $1 and character_id = $2 and item_id = $3`,
      [guildId, character.id, item.id]
    );

    if (points > 0) {
      await client.query(
        `insert into p0plus_points (guild_id, character_id, item_id, points, source, note)
         values ($1, $2, $3, $4, $5, $6)`,
        [guildId, character.id, item.id, points, "Gildenleitung", slot ? `Slot: ${slot}` : ""]
      );
    }

    await insertP0PlusAudit(client, {
      guildId,
      characterId: character.id,
      itemId: item.id,
      raidType,
      playerName: character.name || player,
      server: character.server || server,
      itemName,
      oldPoints,
      newPoints: points,
      action: points > 0 ? "manual_set" : "manual_clear",
      source: "Gildenleitung",
      note: slot ? `Slot: ${slot}` : ""
    });

    await client.query("commit");
    return { success: true, deleted: points === 0, raid: raidType, player, item: itemName, slot, count: points, points };
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function clearP0PlusForPlayer({ guildId, query: params }) {
  const raidType = normalizeRaidType(params.raid);
  const requestedRaidId = clean(params.raidId || params.id);
  await requireNachtlootSpecialRaidGuild(guildId, raidType);
  const player = clean(params.player || params.char || params.spieler);
  const server = clean(params.server);
  const itemName = clean(params.item);
  const character = await findCharacterByName(guildId, player, server);

  if (!character) {
    const error = new Error("Dieser Charakter wurde in Railway nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const client = await pool.connect();
  try {
    await client.query("begin");
    let receivedRaidId = null;
    if (requestedRaidId) {
      const raidResult = await client.query(
        `select id
         from raids
         where guild_id = $1
           and lower(raid_type) = any($2)
           and (id::text = $3 or external_raid_id = $3 or raid_pin = $3)
         order by created_at desc
         limit 1`,
        [guildId, raidTypeSearchValues(raidType), requestedRaidId]
      );
      receivedRaidId = raidResult.rows[0]?.id || null;
    }
    let itemResult = await client.query(
      `select id, name
       from items
       where lower(raid_type) = any($1)
         and lower(name) = lower($2)
       order by created_at asc
       limit 1`,
      [raidTypeSearchValues(raidType), itemName]
    );
    if (!itemResult.rowCount) {
      itemResult = await client.query(
        `select id, name
         from items
         where lower(raid_type) = any($1)
           and regexp_replace(lower(name), '[^a-z0-9]+', '', 'g') = regexp_replace(lower($2), '[^a-z0-9]+', '', 'g')
         order by created_at asc
         limit 1`,
        [raidTypeSearchValues(raidType), itemName]
      );
    }
    const item = itemResult.rows[0];
    let deleted = 0;
    let oldPoints = 0;
    if (item) {
      oldPoints = await getP0PlusPointTotal(client, guildId, character.id, item.id);
      const result = await client.query(
        `delete from p0plus_points
         where guild_id = $1 and character_id = $2 and item_id = $3
         returning id`,
        [guildId, character.id, item.id]
      );
      deleted = result.rowCount;
      if (deleted || oldPoints) {
        await insertP0PlusAudit(client, {
          guildId,
          characterId: character.id,
          itemId: item.id,
          raidId: receivedRaidId,
          raidType,
          playerName: character.name || player,
          server: character.server || server,
          itemName: item.name || itemName,
          oldPoints,
          newPoints: 0,
          action: "item_received_clear",
          source: "PO item erhalten",
          note: "PO+ Eintrag entfernt, weil Item erhalten wurde."
        });
      }
    }
    await client.query("commit");
    return { success: true, deleted };
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function resetRaidP0PlusTransfer({ guildId, query: params }) {
  requireMasterCode(params.masterCode);

  const raidType = normalizeRaidType(params.raid);
  const raidId = clean(params.raidId || params.id);
  const values = [guildId, raidType];
  let raidClause = "r.guild_id = $1 and r.raid_type = $2";

  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(raidId)) {
    values.push(raidId);
    raidClause += ` and r.id = $${values.length}`;
  } else if (raidId) {
    values.push(raidId);
    raidClause += ` and (r.external_raid_id = $${values.length} or r.raid_pin = $${values.length})`;
  }

  const raidResult = await query(
    `select r.*
     from raids r
     where ${raidClause}
     order by r.raid_date desc, coalesce(r.raid_time, '') desc, r.created_at desc
     limit 1`,
    values
  );

  const raid = raidResult.rows[0];
  if (!raid) {
    const error = new Error("Raid wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const transferNotes = Array.from(new Set([
    `RaidID: ${raidPublicId(raid)}`,
    `RaidID: ${raid.id}`,
    raid.raid_pin ? `RaidID: ${raid.raid_pin}` : ""
  ].filter(Boolean)));

  const deleteResult = await query(
    `delete from p0plus_points
     where guild_id = $1
       and source = 'Raidlead Transfer'
       and note = any($2::text[])
     returning id`,
    [guildId, transferNotes]
  );

  return {
    success: true,
    raidId: raidPublicId(raid),
    deleted: deleteResult.rowCount,
    p0PlusTransferred: false,
    p0PlusTransferCount: 0
  };
}

async function exportGuildBackup({ guildId, query: params }) {
  requireMasterCode(params.masterCode);

  const [
    guildResult,
    settingsResult,
    playersResult,
    raidsResult,
    priosResult,
    p0plusResult,
    issueReportsResult,
    playerMessagesResult,
    logAnalysesResult,
    hordenbuffEventsResult,
    hordenbuffEntriesResult,
    worldbuffEventsResult,
    worldbuffEntriesResult
  ] = await Promise.all([
    query("select id, name, slug, created_at from guilds where id = $1", [guildId]),
    query("select * from guild_settings where guild_id = $1", [guildId]),
    query(
      `select
         p.id as player_id,
         p.player_pin,
         p.security_question,
         p.security_answer,
         p.approval_status,
         p.approved_at,
         p.approved_by,
         p.is_blocked,
         p.blocked_at,
         p.blocked_reason,
         p.created_at as player_created_at,
         p.updated_at as player_updated_at,
         c.id as character_id,
         c.name as character_name,
         c.server,
         c.class_name,
         c.created_at as character_created_at,
         c.updated_at as character_updated_at
       from players p
       left join characters c on c.player_id = p.id
       where p.guild_id = $1
       order by p.created_at asc, c.created_at asc`,
      [guildId]
    ),
    query(
      `select *
       from raids
       where guild_id = $1
       order by raid_date asc, raid_time asc, created_at asc`,
      [guildId]
    ),
    query(
      `select
         pr.*,
         r.external_raid_id,
         r.raid_type,
         r.name as raid_name,
         r.raid_date,
         r.raid_time,
         r.raid_pin,
         r.lead_pin,
         c.name as player,
         c.server,
         c.class_name,
         i1.name as p1,
         i2.name as p2,
         i3.name as p3
       from prios pr
       join raids r on r.id = pr.raid_id
       join characters c on c.id = pr.character_id
       left join items i1 on i1.id = pr.p1_item_id
       left join items i2 on i2.id = pr.p2_item_id
       left join items i3 on i3.id = pr.p3_item_id
       where r.guild_id = $1
       order by r.raid_date asc, r.raid_time asc, c.name asc`,
      [guildId]
    ),
    query(
      `select
         pp.*,
         c.name as player,
         c.server,
         c.class_name,
         i.raid_type,
         i.name as item_name,
         i.quality
       from p0plus_points pp
       join characters c on c.id = pp.character_id
       left join items i on i.id = pp.item_id
       where pp.guild_id = $1
       order by pp.created_at asc`,
      [guildId]
    ),
    query("select * from issue_reports where guild_id = $1 order by created_at asc", [guildId]),
    query("select * from player_messages where guild_id = $1 order by created_at asc", [guildId]),
    query("select * from log_analyses where guild_id = $1 order by created_at asc", [guildId]),
    query("select * from hordenbuff_events where guild_id = $1 order by event_date asc, event_time asc", [guildId]),
    query(
      `select he.*
       from hordenbuff_entries he
       join hordenbuff_events e on e.id = he.event_id
       where e.guild_id = $1
       order by e.event_date asc, e.event_time asc, he.created_at asc`,
      [guildId]
    ),
    query("select * from worldbuff_events where guild_id = $1 order by event_date asc, event_time asc", [guildId]),
    query(
      `select we.*
       from worldbuff_entries we
       join worldbuff_events e on e.id = we.event_id
       where e.guild_id = $1
       order by e.event_date asc, e.event_time asc, we.created_at asc`,
      [guildId]
    )
  ]);

  return {
    success: true,
    exportedAt: new Date().toISOString(),
    version: 1,
    guild: guildResult.rows[0] || null,
    settings: settingsResult.rows[0] || null,
    playersAndCharacters: playersResult.rows,
    raids: raidsResult.rows,
    prios: priosResult.rows,
    p0plusPoints: p0plusResult.rows,
    issueReports: issueReportsResult.rows,
    playerMessages: playerMessagesResult.rows,
    logAnalyses: logAnalysesResult.rows,
    hordenbuffEvents: hordenbuffEventsResult.rows,
    hordenbuffEntries: hordenbuffEntriesResult.rows,
    worldbuffEvents: worldbuffEventsResult.rows,
    worldbuffEntries: worldbuffEntriesResult.rows
  };
}

function formatBackupDate(value) {
  if (!value) return "";
  if (value instanceof Date) return value.toISOString().slice(0, 10);
  return clean(value);
}

async function getRaidBackupSnapshot({ guildId, query: params }) {
  requireMasterCode(params.masterCode);

  const limit = Math.min(Math.max(Number(params.limit || 120) || 120, 1), 500);
  const raidFilter = clean(params.raid || params.raidType);
  const raidId = clean(params.raidId || params.id);
  const values = [guildId, limit];
  const where = ["r.guild_id = $1"];

  if (raidFilter) {
    values.push(raidTypeSearchValues(raidFilter));
    where.push(`lower(r.raid_type) = any($${values.length})`);
  }

  if (raidId) {
    values.push(raidId);
    where.push(`(r.id::text = $${values.length} or r.external_raid_id = $${values.length} or r.raid_pin = $${values.length})`);
  }

  const raidsResult = await query(
    `select r.*,
            (
              select count(*)::int
              from prios pr
              where pr.raid_id = r.id
            ) as prio_count,
            (
              select count(*)::int
              from p0plus_points pp
              where pp.guild_id = r.guild_id
                and pp.note in (
                  concat('RaidID: ', coalesce(r.external_raid_id, r.id::text)),
                  concat('RaidID: ', r.id::text),
                  concat('RaidID: ', r.raid_pin),
                  concat('Bench RaidID: ', coalesce(r.external_raid_id, r.id::text)),
                  concat('Bench RaidID: ', r.id::text),
                  concat('Bench RaidID: ', r.raid_pin)
                )
            ) as p0plus_transfer_count
     from raids r
     where ${where.join(" and ")}
     order by r.raid_date desc nulls last, coalesce(r.raid_time, '') desc, r.created_at desc
     limit $2`,
    values
  );

  const raidRows = raidsResult.rows;
  const raidIds = raidRows.map(row => row.id);
  if (!raidIds.length) {
    return { success: true, generatedAt: new Date().toISOString(), raids: [] };
  }

  const [priosResult, p0PlusResult, signupCountsResult] = await Promise.all([
    query(
      `select
         pr.id,
         pr.raid_id,
         pr.comment,
         pr.bench,
         pr.created_at,
         pr.updated_at,
         c.name as player,
         c.server,
         c.class_name,
         c.is_main,
         i1.name as p1,
         i2.name as p2,
         i3.name as p3
       from prios pr
       join characters c on c.id = pr.character_id
       left join items i1 on i1.id = pr.p1_item_id
       left join items i2 on i2.id = pr.p2_item_id
       left join items i3 on i3.id = pr.p3_item_id
       where pr.raid_id = any($1::uuid[])
       order by c.is_main desc, ${prioClassOrderSql("c.class_name")} asc, lower(c.name) asc, c.created_at asc`,
      [raidIds]
    ),
    query(
      `select
         r.id as raid_id,
         pp.id,
         pp.points,
         pp.source,
         pp.note,
         pp.created_at,
         c.name as player,
         c.server,
         c.class_name,
         i.name as item,
         i.raid_type,
         i.quality
       from raids r
       join p0plus_points pp
         on pp.guild_id = r.guild_id
        and pp.note in (
          concat('RaidID: ', coalesce(r.external_raid_id, r.id::text)),
          concat('RaidID: ', r.id::text),
          concat('RaidID: ', r.raid_pin),
          concat('Bench RaidID: ', coalesce(r.external_raid_id, r.id::text)),
          concat('Bench RaidID: ', r.id::text),
          concat('Bench RaidID: ', r.raid_pin)
        )
       join characters c on c.id = pp.character_id
       left join items i on i.id = pp.item_id
       where r.id = any($1::uuid[])
       order by pp.created_at desc, c.name asc, i.name asc`,
      [raidIds]
    ),
    query(
      `select
         r.id as raid_id,
         (
           select count(*)::int
           from raid_signups rs
           where rs.raid_id = r.id
         ) +
         (
           select count(*)::int
           from raid_external_signups res
           where res.guild_id = r.guild_id and res.raid_id = r.id
         ) as signup_count
       from raids r
       where r.id = any($1::uuid[])`,
      [raidIds]
    )
  ]);

  const priosByRaid = new Map();
  for (const row of priosResult.rows) {
    const meta = commentMeta(row.comment);
    const entry = {
      id: row.id,
      player: row.player || "",
      server: row.server || "",
      className: row.class_name || "",
      isMain: Boolean(row.is_main),
      p1: row.p1 || "",
      p2: row.p2 || "",
      p3: row.p3 || "",
      p0Plus: meta.p0Plus || "nein",
      p0Item: meta.p0Item || "",
      bench: row.bench || "",
      createdAt: row.created_at,
      updatedAt: row.updated_at
    };
    if (!priosByRaid.has(row.raid_id)) priosByRaid.set(row.raid_id, []);
    priosByRaid.get(row.raid_id).push(entry);
  }

  const p0PlusByRaid = new Map();
  for (const row of p0PlusResult.rows) {
    const entry = {
      id: row.id,
      player: row.player || "",
      server: row.server || "",
      className: row.class_name || "",
      item: row.item || "",
      raid: row.raid_type || "",
      quality: row.quality || "",
      points: Number(row.points || 0),
      source: row.source || "",
      note: row.note || "",
      createdAt: row.created_at
    };
    if (!p0PlusByRaid.has(row.raid_id)) p0PlusByRaid.set(row.raid_id, []);
    p0PlusByRaid.get(row.raid_id).push(entry);
  }

  const signupCountByRaid = new Map();
  for (const row of signupCountsResult.rows) {
    signupCountByRaid.set(row.raid_id, Number(row.signup_count || 0));
  }

  const raids = raidRows.map(row => {
    const prios = priosByRaid.get(row.id) || [];
    const p0Plus = p0PlusByRaid.get(row.id) || [];
    const p0PlusPrios = prios.filter(entry => normalizeStatus(entry.p0Plus).toLowerCase() === "ja");
    const signupCount = signupCountByRaid.get(row.id) || 0;
    const warnings = [];
    if (signupCount > 0 && prios.length === 0) {
      warnings.push("Attendance vorhanden, aber keine Prioliste gespeichert.");
    }
    return {
      ...normalizeRaidRow(row),
      raidDate: formatBackupDate(row.raid_date),
      date: formatBackupDate(row.raid_date),
      createdAt: row.created_at,
      updatedAt: row.updated_at,
      signupCount,
      prioCount: prios.length,
      p0PlusPrioCount: p0PlusPrios.length,
      p0PlusTransferCount: p0Plus.length,
      warnings,
      prios,
      p0PlusPrios,
      p0PlusTransfers: p0Plus
    };
  });

  return {
    success: true,
    generatedAt: new Date().toISOString(),
    count: raids.length,
    raids
  };
}

async function transferP0PlusPoints({ guildId, query: params }) {
  const raidType = normalizeRaidType(params.raid);
  await requireNachtlootSpecialRaidGuild(guildId, raidType);
  const raidId = clean(params.raidId);
  const values = [guildId, raidType];
  let raidClause = "r.guild_id = $1 and r.raid_type = $2";

  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(raidId)) {
    values.push(raidId);
    raidClause += ` and r.id = $${values.length}`;
  } else if (raidId) {
    values.push(raidId);
    raidClause += ` and (r.external_raid_id = $${values.length} or r.raid_pin = $${values.length})`;
  }

  const raidResult = await query(
    `select r.*
     from raids r
     where ${raidClause}
     order by r.raid_date desc, coalesce(r.raid_time, '') desc, r.created_at desc
     limit 1`,
    values
  );

  const raid = raidResult.rows[0];
  if (!raid) {
    const error = new Error("Raid wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  if (raid.raid_date) {
    const raidDateText = raid.raid_date.toISOString().slice(0, 10);
    const raidTimeText = clean(raid.raid_time) || "00:00";
    const raidStartsAtBerlin = new Date(`${raidDateText}T${raidTimeText}:00`);
    const nowBerlin = new Date(new Date().toLocaleString("en-US", { timeZone: "Europe/Berlin" }));
    if (Number.isFinite(raidStartsAtBerlin.getTime()) && nowBerlin < raidStartsAtBerlin) {
      const error = new Error("P0+ Punkte können erst nach Raidbeginn übertragen werden.");
      error.statusCode = 409;
      throw error;
    }
  }

  const transferNotes = Array.from(new Set([
    `RaidID: ${raidPublicId(raid)}`,
    `RaidID: ${raid.id}`,
    raid.raid_pin ? `RaidID: ${raid.raid_pin}` : ""
  ].filter(Boolean)));
  const transferNote = transferNotes[0];

  const priosResult = await query(
    `select
       pr.character_id,
       c.name as player,
       c.server,
       i.id as item_id,
       i.item_id as item_game_id,
       i.name as item_name,
       pr.comment
     from prios pr
     join raids r on r.id = pr.raid_id
     join characters c on c.id = pr.character_id
     join players p on p.id = c.player_id and p.guild_id = $1
     join items i on i.id = pr.p1_item_id
     where ${raidClause}`,
    values
  );

  const normalizeTransferKey = value => clean(value)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
  const receivedResult = await query(
    `select distinct character_id
     from p0plus_point_audit
     where guild_id = $1
       and action = 'item_received_clear'
       and raid_id = $2`,
    [guildId, raid.id]
  );
  const receivedCharacters = new Set(receivedResult.rows.map(row => clean(row.character_id)));
  const candidates = priosResult.rows.filter(row =>
    commentMeta(row.comment).p0Plus === "ja" &&
    !receivedCharacters.has(clean(row.character_id))
  );
  const dedupedCandidates = [];
  const seenCharacters = new Set();
  const skipped = [];

  for (const row of candidates) {
    const characterKey = normalizeTransferKey(row.player) || clean(row.character_id).toLowerCase();

    if (seenCharacters.has(characterKey)) {
      skipped.push({ player: row.player || "", item: row.item_name || "", reason: "charakter-doppelt" });
      continue;
    }

    seenCharacters.add(characterKey);
    dedupedCandidates.push(row);
  }

  const client = await pool.connect();

  try {
    await client.query("begin");
    const oldPointTotals = new Map();
    for (const row of dedupedCandidates) {
      const targetItem = await upsertItem(
        client,
        raid.raid_type,
        row.item_name,
        row.item_game_id
      );
      row.target_item_id = targetItem?.id || row.item_id;
      oldPointTotals.set(
        `${row.character_id}:${row.target_item_id}`,
        await getP0PlusPointTotal(client, guildId, row.character_id, row.target_item_id)
      );
    }
    if (dedupedCandidates.length) {
      const characterIds = dedupedCandidates.map(row => row.character_id);
      const itemNames = dedupedCandidates.map(row => row.item_name);
      await client.query(
        `delete from p0plus_points pp
         using items i
         where pp.item_id = i.id
           and pp.guild_id = $1
           and pp.source = 'Raidlead Transfer'
           and pp.note = any($2::text[])
           and (
             pp.character_id = any($3::uuid[])
             or regexp_replace(lower(i.name), '[^a-z0-9]+', '', 'g') = any($4::text[])
           )`,
        [
          guildId,
          transferNotes,
          characterIds,
          itemNames.map(normalizeTransferKey)
        ]
      );
    }

    for (const row of dedupedCandidates) {
      await client.query(
        `insert into p0plus_points (guild_id, character_id, item_id, points, source, note)
         values ($1, $2, $3, 1, $4, $5)`,
        [guildId, row.character_id, row.target_item_id, "Raidlead Transfer", transferNote]
      );
      const newPoints = await getP0PlusPointTotal(client, guildId, row.character_id, row.target_item_id);
      await insertP0PlusAudit(client, {
        guildId,
        characterId: row.character_id,
        itemId: row.target_item_id,
        raidId: raid.id,
        raidType: raid.raid_type,
        playerName: row.player || "",
        server: row.server || "",
        itemName: row.item_name || "",
        oldPoints: oldPointTotals.get(`${row.character_id}:${row.target_item_id}`) || 0,
        newPoints,
        action: "raid_transfer",
        source: "PO übertragen",
        note: transferNote
      });
    }
    const archivedPoPostEntries = await archivePoPostEntriesForRaid(client, guildId, raid.raid_type);
    await client.query("commit");
    raid.archived_po_post_entries = archivedPoPostEntries;
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }

  const transferResult = await query(
    `select count(*)::int as count
     from p0plus_points
     where guild_id = $1
       and source = 'Raidlead Transfer'
       and note = any($2::text[])`,
    [guildId, transferNotes]
  );
  const p0PlusTransferCount = Number(transferResult.rows[0]?.count || 0);
  const exportResult = await queueP0PlusTransferCsvExport({
    guildId,
    raid,
    awardedRows: dedupedCandidates,
    skippedRows: skipped
  }).catch(error => ({ success: false, error: error.message || String(error) }));

  return {
    success: true,
    awarded: dedupedCandidates.length,
    candidates: candidates.length,
    skipped: skipped.length,
    skippedEntries: skipped,
    archivedPoPostEntries: Number(raid.archived_po_post_entries || 0),
    p0PlusTransferred: p0PlusTransferCount > 0,
    p0PlusTransferCount,
    exportQueued: Boolean(exportResult && exportResult.success && !exportResult.skipped),
    exportResult
  };
}

async function createPlayerWithCharacter({
  guildId,
  playerPin,
  securityQuestion,
  securityAnswer,
  charName,
  server,
  className
}) {
  const pin = normalizePin(playerPin);
  const client = await pool.connect();

  try {
    await client.query("begin");
    await ensurePlayerRoleSchema();

    const existingPlayer = await client.query(
      "select id from players where guild_id = $1 and player_pin = $2",
      [guildId, pin]
    );
    if (existingPlayer.rows.length) {
      const existingCharacter = await client.query(
        `select c.id
         from characters c
         join players p on p.id = c.player_id
         where p.guild_id = $1 and lower(c.name) = lower($2) and lower(c.server) = lower($3)
         limit 1`,
        [guildId, clean(charName), clean(server)]
      );
      if (existingCharacter.rows.length) {
        const error = new Error("Für diesen Charakter existiert bereits ein SpielerLogin.");
        error.statusCode = 409;
        throw error;
      }
      const linkedCharacters = await client.query(
        "select count(*)::int as count from characters where player_id = $1",
        [existingPlayer.rows[0].id]
      );
      if (Number(linkedCharacters.rows[0]?.count || 0) > 0) {
        const error = new Error("Dieser SpielerLogin ist bereits vergeben.");
        error.statusCode = 409;
        throw error;
      }
      const characterResult = await client.query(
        `insert into characters (player_id, name, server, class_name, is_main)
         values ($1, $2, $3, $4, true)
         returning id, name, server, class_name, created_at`,
        [existingPlayer.rows[0].id, clean(charName), clean(server), clean(className)]
      );
      const playerResult = await client.query(
        `select id, player_pin, approval_status, created_at
         from players
         where id = $1`,
        [existingPlayer.rows[0].id]
      );
      await client.query("commit");
      return { player: playerResult.rows[0], character: normalizeCharacter({ ...characterResult.rows[0], approval_status: playerResult.rows[0]?.approval_status || "pending" }) };
    }

    const existingCharacter = await client.query(
      `select c.id
       from characters c
       join players p on p.id = c.player_id
       where p.guild_id = $1 and lower(c.name) = lower($2) and lower(c.server) = lower($3)
       limit 1`,
      [guildId, clean(charName), clean(server)]
    );
    if (existingCharacter.rows.length) {
      const error = new Error("Für diesen Charakter existiert bereits ein SpielerLogin.");
      error.statusCode = 409;
      throw error;
    }

    const playerResult = await client.query(
      `insert into players (guild_id, player_pin, security_question, security_answer, approval_status)
       values ($1, $2, $3, $4, 'pending')
       returning id, player_pin, approval_status, created_at`,
      [guildId, pin, clean(securityQuestion) || null, clean(securityAnswer) || null]
    );

    const characterResult = await client.query(
      `insert into characters (player_id, name, server, class_name, is_main)
       values ($1, $2, $3, $4, true)
       returning id, name, server, class_name, created_at`,
      [playerResult.rows[0].id, clean(charName), clean(server), clean(className)]
    );

    await client.query("commit");
    return { player: playerResult.rows[0], character: normalizeCharacter({ ...characterResult.rows[0], approval_status: "pending" }) };
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function addCharacterToPlayer({ guildId, pin, charName, server, className }) {
  const player = await findPlayerByPin(guildId, pin);
  if (!player) {
    const error = new Error("Dieser SpielerLogin wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const existingCharacter = await findCharacter(guildId, charName, server);
  if (existingCharacter) {
    const error = new Error("Dieser Charakter ist bereits gespeichert.");
    error.statusCode = 409;
    throw error;
  }

  const result = await query(
    `insert into characters (player_id, name, server, class_name)
     values ($1, $2, $3, $4)
     returning id, name, server, class_name, created_at`,
    [player.id, clean(charName), clean(server), clean(className)]
  );

  return normalizeCharacter(result.rows[0]);
}

async function deleteCharacterFromPlayer({ guildId, pin, charName, server }) {
  const player = await findPlayerByPin(guildId, pin);
  if (!player) {
    const error = new Error("Dieser SpielerLogin wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const client = await pool.connect();
  try {
    await client.query("begin");

    const countResult = await client.query(
      "select count(*)::int as count from characters where player_id = $1",
      [player.id]
    );

    if (Number(countResult.rows[0]?.count || 0) <= 1) {
      const error = new Error("Der letzte Charakter dieses SpielerLogins kann nicht gelöscht werden.");
      error.statusCode = 400;
      throw error;
    }

    const deleteResult = await client.query(
      `delete from characters
       where player_id = $1
         and lower(name) = lower($2)
         and lower(server) = lower($3)
       returning id, name, server, class_name`,
      [player.id, clean(charName), clean(server)]
    );

    if (!deleteResult.rows.length) {
      const error = new Error("Dieser Charakter gehört nicht zu diesem SpielerLogin.");
      error.statusCode = 404;
      throw error;
    }

    const mainResult = await client.query(
      "select count(*)::int as count from characters where player_id = $1 and is_main = true",
      [player.id]
    );

    if (Number(mainResult.rows[0]?.count || 0) === 0) {
      await client.query(
        `update characters
         set is_main = true, updated_at = now()
         where id = (
           select id from characters
           where player_id = $1
           order by created_at asc
           limit 1
         )`,
        [player.id]
      );
    }

    await client.query("commit");
    return { success: true, deleted: 1, character: normalizeCharacter(deleteResult.rows[0]) };
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function setMainCharacter({ guildId, pin, charName, server }) {
  const player = await findPlayerByPin(guildId, pin);
  if (!player) {
    const error = new Error("Dieser SpielerLogin wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const client = await pool.connect();
  try {
    await client.query("begin");
    await client.query(
      "update characters set is_main = false, updated_at = now() where player_id = $1",
      [player.id]
    );
    const result = await client.query(
      `update characters
       set is_main = true, updated_at = now()
       where player_id = $1
         and lower(name) = lower($2)
         and lower(server) = lower($3)
       returning id, name, server, class_name, is_main, created_at, name as main_char`,
      [player.id, clean(charName), clean(server)]
    );
    if (!result.rows.length) {
      const error = new Error("Dieser Charakter gehört nicht zu diesem SpielerPin.");
      error.statusCode = 404;
      throw error;
    }
    await client.query("commit");
    return normalizeCharacter(result.rows[0]);
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function resetPlayerPin({ guildId, charName, server, oldPin, newPin, className }) {
  const character = await findCharacter(guildId, charName, server);
  if (!character) {
    const error = new Error("Dieser Charakter wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  if (normalizePin(character.player_pin) !== normalizePin(oldPin)) {
    const error = new Error("Der alte SpielerLogin passt nicht zu diesem Charakter.");
    error.statusCode = 403;
    throw error;
  }

  const pin = normalizePin(newPin);
  await query(
    `update players p
     set player_pin = $1, updated_at = now()
     from characters c
     where c.player_id = p.id
       and p.guild_id = $2
       and lower(c.name) = lower($3)
       and lower(c.server) = lower($4)`,
    [pin, guildId, clean(charName), clean(server)]
  );

  if (clean(className)) {
    await query(
      `update characters c
       set class_name = $1, updated_at = now()
       from players p
       where c.player_id = p.id
         and p.guild_id = $2
         and lower(c.name) = lower($3)
         and lower(c.server) = lower($4)`,
      [clean(className), guildId, clean(charName), clean(server)]
    );
  }

  return pin;
}

async function deletePlayerLogin({ guildId, query: params }) {
  requireMasterCode(params.masterCode);

  const playerId = clean(params.playerId || params.player_id || params.id);
  const playerPin = normalizePin(params.playerPin || params.pin);
  const charName = clean(params.char || params.player || params.spieler);
  const server = clean(params.server);
  let character = null;
  let player = null;
  if (playerId) {
    const playerResult = await query(
      "select id, player_pin from players where guild_id = $1 and id::text = $2 limit 1",
      [guildId, playerId]
    );
    player = playerResult.rows[0] || null;
  } else if (playerPin) {
    const playerResult = await query(
      "select id, player_pin from players where guild_id = $1 and player_pin = $2 limit 1",
      [guildId, playerPin]
    );
    player = playerResult.rows[0] || null;
  } else {
    character = await findCharacter(guildId, charName, server);
    player = character ? { id: character.player_id, player_pin: character.player_pin } : null;
  }
  if (!player) {
    const error = new Error("Dieser SpielerLogin wurde in dieser Gilde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const client = await pool.connect();
  try {
    await client.query("begin");
    const countResult = await client.query(
      "select count(*)::int as count from characters where player_id = $1",
      [player.id]
    );
    const characterIdsResult = await client.query(
      "select id from characters where player_id = $1",
      [player.id]
    );
    const characterIds = characterIdsResult.rows.map(row => row.id);
    if (characterIds.length) {
      await client.query(
        "delete from raid_signups where character_id = any($1::uuid[])",
        [characterIds]
      );
      await client.query(
        "delete from discord_player_links where guild_id = $1 and character_id = any($2::uuid[])",
        [guildId, characterIds]
      );
      await client.query(
        "delete from prios where character_id = any($1::uuid[])",
        [characterIds]
      );
      await client.query(
        "delete from p0plus_points where guild_id = $1 and character_id = any($2::uuid[])",
        [guildId, characterIds]
      );
      await client.query(
        "update p0plus_point_audit set character_id = null where guild_id = $1 and character_id = any($2::uuid[])",
        [guildId, characterIds]
      );
      await client.query(
        "update p0_discord_signups set character_id = null where guild_id = $1 and character_id = any($2::uuid[])",
        [guildId, characterIds]
      );
    }
    await client.query(
      "delete from player_messages where guild_id = $1 and player_pin = $2",
      [guildId, player.player_pin]
    );
    await client.query(
      "delete from characters where player_id = $1",
      [player.id]
    );
    const deleteResult = await client.query(
      "delete from players where guild_id = $1 and id = $2 returning id",
      [guildId, player.id]
    );
    await client.query("commit");
    return {
      success: true,
      deleted: deleteResult.rowCount,
      deletedCharacters: Number(countResult.rows[0]?.count || 0),
      player: character?.name || "",
      server: character?.server || ""
    };
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function setPlayerLoginRole({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  const playerId = clean(params.playerId || params.player_id || params.id);
  const playerPin = normalizePin(params.playerPin || params.pin);
  const role = normalizePlayerRole(params.role || params.playerRole);
  const values = [guildId, role];
  const clauses = [];

  if (playerId) {
    values.push(playerId);
    clauses.push(`id::text = $${values.length}`);
  }

  if (playerPin) {
    values.push(playerPin);
    clauses.push(`player_pin = $${values.length}`);
  }

  if (!clauses.length) {
    const error = new Error("SpielerLogin fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const result = await query(
    `update players
     set role = $2, updated_at = now()
     where guild_id = $1
       and (${clauses.join(" or ")})
     returning id, player_pin, role`,
    values
  );

  if (!result.rows.length) {
    const error = new Error("SpielerLogin wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  return {
    success: true,
    playerId: result.rows[0].id,
    playerPin: result.rows[0].player_pin,
    role: normalizePlayerRole(result.rows[0].role),
    roleLabel: playerRoleLabel(result.rows[0].role),
    canCreateRaid: canPlayerRoleCreateRaid(result.rows[0].role)
  };
}

async function setPlayerLoginAccess({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  await ensurePlayerRoleSchema();
  const playerId = clean(params.playerId || params.player_id || params.id);
  const playerPin = normalizePin(params.playerPin || params.pin);
  const parseList = value => {
    if (Array.isArray(value)) return value;
    try { const parsed=JSON.parse(clean(value) || "[]"); return Array.isArray(parsed) ? parsed : []; } catch(error) { return clean(value).split(",").filter(Boolean); }
  };
  const allowedPermissions = new Set([
    "create_raids","manage_worldbuffs","guild_admin",
    "loot_master","notify_player_logins","notify_worldbuff_changes","notify_po_releases"
  ]);
  const permissions = [...new Set(parseList(params.permissions).map(clean).filter(value=>allowedPermissions.has(value)))];
  const discordRoleIds = [...new Set(parseList(params.discordRoleIds || params.discordRoles).map(clean).filter(Boolean))];
  const notificationDiscordNames=[...new Set(parseList(params.notificationDiscordNames || params.notificationNames).map(clean).filter(Boolean))];
  const values=[guildId,JSON.stringify(discordRoleIds),JSON.stringify(permissions),JSON.stringify(notificationDiscordNames)];
  const clauses=[];
  if(playerId){ values.push(playerId); clauses.push(`id::text=$${values.length}`); }
  if(playerPin){ values.push(playerPin); clauses.push(`player_pin=$${values.length}`); }
  if(!clauses.length){ const error=new Error("SpielerLogin fehlt."); error.statusCode=400; throw error; }
  const result=await query(`update players set discord_role_ids=$2::jsonb,permissions=$3::jsonb,notification_discord_names=$4::jsonb,updated_at=now() where guild_id=$1 and (${clauses.join(" or ")}) returning id,player_pin,discord_role_ids,permissions,notification_discord_names`,values);
  if(!result.rows[0]){ const error=new Error("SpielerLogin wurde nicht gefunden."); error.statusCode=404; throw error; }
  return {success:true,playerId:result.rows[0].id,playerPin:result.rows[0].player_pin,discordRoleIds:result.rows[0].discord_role_ids||[],permissions:result.rows[0].permissions||[],notificationDiscordNames:result.rows[0].notification_discord_names||[]};
}

async function notificationDiscordRoleIds(guildId, permission){
  await ensurePlayerRoleSchema();
  const result=await query(
    `select distinct jsonb_array_elements_text(coalesce(discord_role_ids,'[]'::jsonb)) as role_id
     from players
     where guild_id=$1 and coalesce(permissions,'[]'::jsonb) ? $2`,
    [guildId,clean(permission)]
  );
  return result.rows.map(row=>clean(row.role_id)).filter(Boolean);
}

async function notificationDiscordNames(guildId,permission){
  await ensurePlayerRoleSchema();
  const result=await query(`select distinct jsonb_array_elements_text(coalesce(notification_discord_names,'[]'::jsonb)) as discord_name from players where guild_id=$1 and coalesce(permissions,'[]'::jsonb) ? $2`,[guildId,clean(permission)]);
  return result.rows.map(row=>clean(row.discord_name)).filter(Boolean);
}

async function notificationTargetsForPermissions(guildId, permissions){
  const permissionList=[...new Set((Array.isArray(permissions)?permissions:[permissions]).map(clean).filter(Boolean))];
  const targets=[];
  for(const permission of permissionList){
    await ensureGuildNotificationSettingsSchema();
    const central=await query(`select targets from guild_notification_settings where guild_id=$1 and notification_key=$2`,[guildId,permission]);
    if(central.rows.length){
      (Array.isArray(central.rows[0].targets)?central.rows[0].targets:[]).forEach(target=>targets.push(target));
      continue;
    }
    const [roleIds,names]=await Promise.all([
      notificationDiscordRoleIds(guildId,permission),
      notificationDiscordNames(guildId,permission)
    ]);
    roleIds.forEach(value=>targets.push({type:"role",value,label:value}));
    names.forEach(value=>targets.push({type:"name",value,label:value}));
  }
  const seen=new Set();
  return targets.filter(target=>{const key=`${target.type}:${target.value}`;if(seen.has(key))return false;seen.add(key);return true;});
}

async function setPlayerLoginBlocked({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  await ensurePlayerRoleSchema();
  const playerId = clean(params.playerId || params.player_id || params.id);
  const playerPin = normalizePin(params.playerPin || params.pin);
  const blockedValue = clean(params.blocked || params.isBlocked || params.mode).toLowerCase();
  const isBlocked = ["1", "true", "yes", "ja", "sperren", "block", "blocked"].includes(blockedValue);
  const reason = clean(params.reason || params.blockedReason);
  const values = [guildId, isBlocked, reason];
  const clauses = [];

  if (playerId) {
    values.push(playerId);
    clauses.push(`id::text = $${values.length}`);
  }

  if (playerPin) {
    values.push(playerPin);
    clauses.push(`player_pin = $${values.length}`);
  }

  if (!clauses.length) {
    const error = new Error("SpielerLogin fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const result = await query(
    `update players
     set is_blocked = $2,
         blocked_at = case when $2 then coalesce(blocked_at, now()) else null end,
         blocked_reason = case when $2 then coalesce(nullif($3, ''), 'Durch Gildenleitung gesperrt') else '' end,
         updated_at = now()
     where guild_id = $1
       and (${clauses.join(" or ")})
     returning id, player_pin, role, is_blocked, blocked_at, blocked_reason`,
    values
  );

  if (!result.rows.length) {
    const error = new Error("SpielerLogin wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  return {
    success: true,
    playerId: result.rows[0].id,
    playerPin: result.rows[0].player_pin,
    role: normalizePlayerRole(result.rows[0].role),
    roleLabel: playerRoleLabel(result.rows[0].role),
    isBlocked: Boolean(result.rows[0].is_blocked),
    blockedAt: result.rows[0].blocked_at || null,
    blockedReason: result.rows[0].blocked_reason || ""
  };
}

async function setPlayerLoginApproved({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  await ensurePlayerRoleSchema();
  const playerId = clean(params.playerId || params.player_id || params.id);
  const playerPin = normalizePin(params.playerPin || params.pin);
  const approvedBy = clean(params.approvedBy || params.by) || "Gildenleitung";
  const values = [guildId, approvedBy];
  const clauses = [];

  if (playerId) {
    values.push(playerId);
    clauses.push(`id::text = $${values.length}`);
  }

  if (playerPin) {
    values.push(playerPin);
    clauses.push(`player_pin = $${values.length}`);
  }

  if (!clauses.length) {
    const error = new Error("SpielerLogin fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const result = await query(
    `update players
     set approval_status = 'approved',
         approved_at = now(),
         approved_by = $2,
         updated_at = now()
     where guild_id = $1
       and (${clauses.join(" or ")})
     returning id, player_pin, role, approval_status, approved_at, approved_by, is_blocked, blocked_at, blocked_reason`,
    values
  );

  if (!result.rows.length) {
    const error = new Error("SpielerLogin wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  return {
    success: true,
    playerId: result.rows[0].id,
    playerPin: result.rows[0].player_pin,
    role: normalizePlayerRole(result.rows[0].role),
    roleLabel: playerRoleLabel(result.rows[0].role),
    approvalStatus: normalizePlayerApprovalStatus(result.rows[0].approval_status),
    approvalLabel: playerApprovalLabel(result.rows[0].approval_status),
    isApproved: true,
    approvedAt: result.rows[0].approved_at || null,
    approvedBy: result.rows[0].approved_by || "",
    isBlocked: Boolean(result.rows[0].is_blocked),
    blockedAt: result.rows[0].blocked_at || null,
    blockedReason: result.rows[0].blocked_reason || ""
  };
}

async function setGuildMasterCode({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  const newCode = clean(params.newMasterCode || params.newCode || params.password);
  if (newCode.length < 4) {
    const error = new Error("Der neue Master-Code muss mindestens 4 Zeichen haben.");
    error.statusCode = 400;
    throw error;
  }

  await query(
    `insert into guild_master_codes (guild_id, master_code, updated_at)
     values ($1, $2, now())
     on conflict (guild_id) do update
       set master_code = excluded.master_code,
           updated_at = now()`,
    [guildId, newCode]
  );
  masterCodeOverrides.set(String(guildId), newCode);
  return { success: true };
}

async function seedDefaultLootItemsOnce() {
  return { success: true, skipped: true, source: "railway-only" };
}

async function applyLootItemCorrectionsOnce() {
  return { success: true, skipped: true, source: "railway-only" };
}

async function applyLootSetPieceCleanupOnce() {
  return { success: true, skipped: true, source: "railway-only" };
}

async function applyKaeseItemIdCorrection() {
  const client = await pool.connect();
  try {
    await client.query("begin");
    const aliases = ["Kaese", "Käse", "Cheese"];
    const raidTypes = ["mc", "bwl", "aq40", "naxx", "zg", "zg-mittwoch", "zg-prime", "zg-late", "aq20", "ony"];
    for (const raidType of raidTypes) {
      await upsertLootItemRecord(client, {
        raid: raidType,
        itemId: "133993",
        name: "Kaese",
        quality: "",
        iconName: "inv_misc_food_37"
      });
    }
    await client.query(
      `update items
       set item_id = $1,
           icon_url = coalesce(nullif(icon_url, ''), 'inv_misc_food_37')
       where lower(name) = any($2)`,
      ["133993", aliases.map(name => name.toLowerCase())]
    );
    await client.query("commit");
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function ensureLootItemMetadataColumns() {
  await query(
    `alter table items
       add column if not exists slot text,
       add column if not exists type text,
       add column if not exists boss text,
       add column if not exists bind text,
       add column if not exists category text,
       add column if not exists wowhead text,
       add column if not exists stats_text text,
       add column if not exists tooltip text,
       add column if not exists needed text,
       add column if not exists equip text,
       add column if not exists price text,
       add column if not exists dropchance text,
       add column if not exists token_group text,
       add column if not exists token_name text,
       add column if not exists token_item_id text`
  );
}

async function ensureItemIdentitySchema() {
  await query(`alter table items drop constraint if exists items_raid_type_name_key`);
  await query(`create index if not exists items_raid_type_name_idx on items (lower(raid_type), lower(name))`);
  await query(`create index if not exists items_raid_type_item_id_idx on items (lower(raid_type), item_id) where item_id is not null`);
}

function definedItemField(value) {
  const text = clean(value);
  return text ? text : null;
}

async function upsertLootItemRecord(client, rawItem, options = {}) {
  const raidType = normalizeRaidType(rawItem.raid_type || rawItem.raidType || rawItem.raid || "");
  const name = clean(rawItem.name || rawItem.item || rawItem.Item || "");
  const itemId = clean(rawItem.item_id || rawItem.itemId || rawItem.ItemID || "");
  if (!raidType || !name) return null;

  const preserveExisting = options.preserveExisting !== false;
  const lookupValues = [raidType];
  let lookupClause = "";
  if (itemId) {
    lookupValues.push(itemId);
    lookupClause = "lower(raid_type) = $1 and item_id = $2";
  } else {
    lookupValues.push(name);
    lookupClause = "lower(raid_type) = $1 and lower(name) = lower($2) and item_id is null";
  }

  const existing = await client.query(
    `select id from items where ${lookupClause} order by created_at asc limit 1`,
    lookupValues
  );

  const values = [
    raidType,
    itemId,
    name,
    definedItemField(rawItem.quality),
    definedItemField(rawItem.icon_url || rawItem.iconUrl || rawItem.iconName || rawItem.icon),
    definedItemField(rawItem.slot),
    definedItemField(rawItem.type || rawItem.itemType),
    definedItemField(rawItem.boss),
    definedItemField(rawItem.bind),
    definedItemField(rawItem.category),
    definedItemField(rawItem.wowhead),
    definedItemField(rawItem.stats_text || rawItem.statsText),
    definedItemField(rawItem.tooltip),
    definedItemField(rawItem.needed),
    definedItemField(rawItem.equip),
    definedItemField(rawItem.price),
    definedItemField(rawItem.dropchance || rawItem.dropChance),
    definedItemField(rawItem.token_group || rawItem.tokenGroup),
    definedItemField(rawItem.token_name || rawItem.tokenName),
    definedItemField(rawItem.token_item_id || rawItem.tokenItemId)
  ];

  const setValue = preserveExisting ? "coalesce($VALUE, COLUMN)" : "$VALUE";
  if (existing.rows.length) {
    const id = existing.rows[0].id;
    const result = await client.query(
      `update items
       set raid_type = $1,
           item_id = ${setValue.replace("$VALUE", "$2").replace("COLUMN", "item_id")},
           name = $3,
           quality = ${setValue.replace("$VALUE", "$4").replace("COLUMN", "quality")},
           icon_url = ${setValue.replace("$VALUE", "$5").replace("COLUMN", "icon_url")},
           slot = ${setValue.replace("$VALUE", "$6").replace("COLUMN", "slot")},
           type = ${setValue.replace("$VALUE", "$7").replace("COLUMN", "type")},
           boss = ${setValue.replace("$VALUE", "$8").replace("COLUMN", "boss")},
           bind = ${setValue.replace("$VALUE", "$9").replace("COLUMN", "bind")},
           category = ${setValue.replace("$VALUE", "$10").replace("COLUMN", "category")},
           wowhead = ${setValue.replace("$VALUE", "$11").replace("COLUMN", "wowhead")},
           stats_text = ${setValue.replace("$VALUE", "$12").replace("COLUMN", "stats_text")},
           tooltip = ${setValue.replace("$VALUE", "$13").replace("COLUMN", "tooltip")},
           needed = ${setValue.replace("$VALUE", "$14").replace("COLUMN", "needed")},
           equip = ${setValue.replace("$VALUE", "$15").replace("COLUMN", "equip")},
           price = ${setValue.replace("$VALUE", "$16").replace("COLUMN", "price")},
           dropchance = ${setValue.replace("$VALUE", "$17").replace("COLUMN", "dropchance")},
           token_group = ${setValue.replace("$VALUE", "$18").replace("COLUMN", "token_group")},
           token_name = ${setValue.replace("$VALUE", "$19").replace("COLUMN", "token_name")},
           token_item_id = ${setValue.replace("$VALUE", "$20").replace("COLUMN", "token_item_id")}
       where id = $21
       returning id, raid_type, item_id, name, quality, icon_url,
                 slot, type, boss, bind, category, wowhead,
                 stats_text, tooltip, needed, equip, price, dropchance,
                 token_group, token_name, token_item_id`,
      [...values, id]
    );
    return result.rows[0] || null;
  }

  const result = await client.query(
    `insert into items (
       raid_type, item_id, name, quality, icon_url,
       slot, type, boss, bind, category, wowhead,
       stats_text, tooltip, needed, equip, price, dropchance,
       token_group, token_name, token_item_id
     )
     values (
       $1, nullif($2, ''), $3, $4, $5,
       $6, $7, $8, $9, $10, $11,
       $12, $13, $14, $15, $16, $17,
       $18, $19, $20
     )
     returning id, raid_type, item_id, name, quality, icon_url,
               slot, type, boss, bind, category, wowhead,
               stats_text, tooltip, needed, equip, price, dropchance,
               token_group, token_name, token_item_id`,
    values
  );
  return result.rows[0] || null;
}

async function importLootItemMetadata() {
  return { success: true, skipped: true, source: "railway-only" };
}

async function restoreLootItemsFromStaticDataOnce() {
  return { success: true, skipped: true, source: "railway-only" };
}

const ONY_LOOT_METADATA_BACKFILL = [
  {
    itemId: "18205",
    name: "Eskhandars Halsband",
    quality: "Episch",
    iconName: "inv_belt_12",
    slot: "Hals",
    type: "Verschiedenes",
    boss: "Onyxia",
    statsText: "Hals | +17 Ausdauer | Anlegen: Erhöht Eure Chance, einem Angriff auszuweichen, um 1%. | Anlegen: Erhöht Eure Chance, einen kritischen Treffer zu erzielen, um 1%. | Seele des Eskhandar (0/4) | Eskhandars rechte Klaue | Eskhandars linke Klaue | Eskhandars Pelz | (4) Set : 1% Chance bei einem kritischen Nahkampftreffer den Geist von Eskhandar herbeizurufen, um euch für 2 Min. im Kampf zu unterstützen. (Procchance: 1%, 2Min. Abklingzeit)",
    tooltip: "Eskhandars Halsband | Gegenstandsstufe 71 | Wird beim Aufheben gebunden | Einzigartig | Hals | +17 Ausdauer | Benötigt Stufe 60 | Anlegen: Erhöht Eure Chance, einem Angriff auszuweichen, um 1%. | Anlegen: Erhöht Eure Chance, einen kritischen Treffer zu erzielen, um 1%. | Seele des Eskhandar (0/4) | Eskhandars rechte Klaue | Eskhandars linke Klaue | Eskhandars Pelz | Eskhandars Halsband | (4) Set : 1% Chance bei einem kritischen Nahkampftreffer den Geist von Eskhandar herbeizurufen, um euch für 2 Min. im Kampf zu unterstützen. (Procchance: 1%, 2Min. Abklingzeit) | Verkaufspreis: 3 32 87"
  },
  {
    itemId: "18813",
    name: "Ring der Bindung",
    quality: "Episch",
    iconName: "inv_jewelry_ring_13",
    slot: "Finger",
    type: "Verschiedenes",
    boss: "Onyxia",
    statsText: "Finger | +10 Arkanwiderstand | +10 Feuerwiderstand | +10 Naturwiderstand | +10 Frostwiderstand | +10 Schattenwiderstand | Anlegen: Verteidigung +4.",
    tooltip: "Ring der Bindung | Gegenstandsstufe 73 | Wird beim Aufheben gebunden | Einzigartig | Finger | 60 Rüstung | +10 Arkanwiderstand | +10 Feuerwiderstand | +10 Naturwiderstand | +10 Frostwiderstand | +10 Schattenwiderstand | Benötigt Stufe 60 | Anlegen: Verteidigung +4. | Verkaufspreis: 8 91 3"
  },
  {
    itemId: "17078",
    name: "Saphirontuch",
    quality: "Episch",
    iconName: "inv_misc_cape_16",
    slot: "Rücken",
    type: "Stoff",
    boss: "Onyxia",
    statsText: "Rücken | +10 Ausdauer | +17 Intelligenz | +6 Arkanwiderstand | +6 Frostwiderstand | Anlegen: Erhöht durch Zauber und magische Effekte zugefügten Schaden und Heilung um bis zu 14.",
    tooltip: "Saphirontuch | Gegenstandsstufe 72 | Wird beim Aufheben gebunden | Rücken | 55 Rüstung | +10 Ausdauer | +17 Intelligenz | +6 Arkanwiderstand | +6 Frostwiderstand | Benötigt Stufe 60 | Anlegen: Erhöht durch Zauber und magische Effekte zugefügten Schaden und Heilung um bis zu 14. | Verkaufspreis: 3 72 3"
  },
  {
    itemId: "17064",
    name: "Splitter der Schuppe",
    quality: "Episch",
    iconName: "inv_misc_monsterscales_15",
    slot: "Schmuck",
    type: "Verschiedenes",
    boss: "Onyxia",
    statsText: "Schmuck | Anlegen: Stellt alle 5 Sek. 16 Punkt(e) Mana wieder her. | Scherbe der Götter (0/2) | Splitter der Flamme | (2) Set : +10 zu allen Widerstandsarten.",
    tooltip: "Splitter der Schuppe | Gegenstandsstufe 71 | Wird beim Aufheben gebunden | Einzigartig | Schmuck | Benötigt Stufe 60 | Anlegen: Stellt alle 5 Sek. 16 Punkt(e) Mana wieder her. | Scherbe der Götter (0/2) | Splitter der Flamme | Splitter der Schuppe | (2) Set : +10 zu allen Widerstandsarten. | Verkaufspreis: 4 59 14"
  },
  {
    itemId: "17068",
    name: "Todesbringer",
    quality: "Episch",
    iconName: "inv_axe_09",
    slot: "Einhändig",
    type: "Axt",
    boss: "Onyxia",
    statsText: "Einhändig Axt | 114 - 213 Schaden Tempo 2.90 | (56.38 Schaden pro Sekunde) | Trefferchance: Schleudert einen Schattenblitz auf den Feind und verursacht 110 bis 140 Punkt(e) Schattenschaden.",
    tooltip: "Todesbringer | Gegenstandsstufe 75 | Wird beim Aufheben gebunden | Einhändig Axt | 114 - 213 Schaden Tempo 2.90 | (56.38 Schaden pro Sekunde) | Haltbarkeit 105 / 105 | Benötigt Stufe 60 | Trefferchance: Schleudert einen Schattenblitz auf den Feind und verursacht 110 bis 140 Punkt(e) Schattenschaden. | Verkaufspreis: 13 48 32"
  },
  {
    itemId: "17075",
    name: "Vis'kag der Blutvergießer",
    quality: "Episch",
    iconName: "inv_sword_18",
    slot: "Einhändig",
    type: "Schwert",
    boss: "Onyxia",
    statsText: "Einhändig Schwert | 100 - 187 Schaden Tempo 2.60 | (55.19 Schaden pro Sekunde) | Trefferchance: Fügt eine tödliche Wunde und 240 Punkt(e) Schaden zu.",
    tooltip: "Vis'kag der Blutvergießer | Gegenstandsstufe 74 | Wird beim Aufheben gebunden | Einzigartig | Einhändig Schwert | 100 - 187 Schaden Tempo 2.60 | (55.19 Schaden pro Sekunde) | Haltbarkeit 105 / 105 | Benötigt Stufe 60 | Trefferchance: Fügt eine tödliche Wunde und 240 Punkt(e) Schaden zu. | Verkaufspreis: 13 52 66"
  },
  {
    itemId: "17067",
    name: "Zauberfoliant des uralten Grundsteins",
    quality: "Episch",
    iconName: "inv_misc_book_07",
    slot: "Schildhand",
    type: "Verschiedenes",
    boss: "Onyxia",
    statsText: "In Schildhand geführt | +10 Ausdauer | +15 Intelligenz | +11 Willenskraft | Benutzen: Beschwört ein Skelett, das Euch 1 Min. lang beschützt. (15 Min Abklingzeit)",
    tooltip: "Zauberfoliant des uralten Grundsteins | Gegenstandsstufe 76 | Wird beim Aufheben gebunden | In Schildhand geführt | +10 Ausdauer | +15 Intelligenz | +11 Willenskraft | Benötigt Stufe 60 | Benutzen: Beschwört ein Skelett, das Euch 1 Min. lang beschützt. (15 Min Abklingzeit) | Verkaufspreis: 7 54 52"
  },
  {
    itemId: "18713",
    name: "Rhok'delar, Langbogen der uralten Bewahrer",
    quality: "Episch",
    iconName: "inv_weapon_bow_01",
    slot: "Distanz",
    type: "Bogen",
    boss: "Onyxia",
    statsText: "Distanz Bogen | 89 - 166 Schaden Tempo 2.90 | (43.97 Schaden pro Sekunde) | Klassen: Jäger | Anlegen: Erhöht Eure Chance, einen kritischen Treffer zu erzielen, um 1%. | Anlegen: +17 Distanzangriffskraft.",
    tooltip: "Rhok'delar, Langbogen der uralten Bewahrer | Gegenstandsstufe 75 | Wird beim Aufheben gebunden | Einzigartig | Distanz Bogen | 89 - 166 Schaden Tempo 2.90 | (43.97 Schaden pro Sekunde) | Haltbarkeit 90 / 90 | Klassen: Jäger | Benötigt Stufe 60 | Anlegen: Erhöht Eure Chance, einen kritischen Treffer zu erzielen, um 1%. | Anlegen: +17 Distanzangriffskraft."
  },
  {
    itemId: "18423",
    name: "Onyxias Kopf",
    quality: "Episch",
    iconName: "inv_misc_head_dragon_01",
    slot: "",
    type: "Quest",
    boss: "Onyxia",
    statsText: "Dieser Gegenstand startet eine Quest. | \"Der Kopf der Brutmutter des schwarzen Drachenschwarms\"",
    tooltip: "Onyxias Kopf | Gegenstandsstufe 60 | Wird beim Aufheben gebunden | Einzigartig | Dieser Gegenstand startet eine Quest. | Benötigt Stufe 60 | \"Der Kopf der Brutmutter des schwarzen Drachenschwarms\""
  },
  {
    itemId: "22388",
    name: "Pläne: Gamaschen der Titanen",
    quality: "Episch",
    iconName: "inv_scroll_05",
    slot: "",
    type: "Rezept",
    boss: "Onyxia",
    statsText: "Benötigt Schmiedekunst (300) | Benötigt Rüstungsschmied | Benutzen: Lehrt Euch die Herstellung von Gamaschen der Titanen. | Gamaschen der Titanen | Beine Platte | +30 Stärke | Anlegen: Verbessert Eure Trefferchance um 2%. | Anlegen: Erhöht Eure Chance, einen kritischen Treffer zu erzielen, um 1%.",
    tooltip: "Pläne: Gamaschen der Titanen | Gegenstandsstufe 61 | Benötigt Schmiedekunst (300) | Benötigt Rüstungsschmied | Benutzen: Lehrt Euch die Herstellung von Gamaschen der Titanen."
  },
  {
    itemId: "12717",
    name: "Pläne: Löwenherzhelm",
    quality: "Episch",
    iconName: "inv_scroll_05",
    slot: "",
    type: "Rezept",
    boss: "Onyxia",
    statsText: "Benötigt Schmiedekunst (300) | Benötigt Rüstungsschmied | Benutzen: Lehrt Euch die Herstellung eines Löwenherzhelms. | Löwenherzhelm | Kopf Platte | +18 Stärke | Anlegen: Erhöht Eure Chance, einen kritischen Treffer zu erzielen, um 2%. | Anlegen: Verbessert Eure Trefferchance um 2%.",
    tooltip: "Pläne: Löwenherzhelm | Gegenstandsstufe 61 | Benötigt Schmiedekunst (300) | Benötigt Rüstungsschmied | Benutzen: Lehrt Euch die Herstellung eines Löwenherzhelms."
  },
  {
    itemId: "13493",
    name: "Rezept: Großes Arkanelixier",
    quality: "Ungewöhnlich",
    iconName: "inv_scroll_06",
    slot: "",
    type: "Rezept",
    boss: "Onyxia",
    statsText: "Benötigt Alchimie (285) | Benutzen: Lehrt Euch die Herstellung eines großen Arkanelixiers. | Großes Arkanelixier | Benutzen: Erhöht die Schadenswirkung von Zaubern 1 Stunde lang um 35. (3 Sek. Abklingzeit)",
    tooltip: "Rezept: Großes Arkanelixier | Gegenstandsstufe 57 | Benötigt Alchimie (285) | Benutzen: Lehrt Euch die Herstellung eines großen Arkanelixiers."
  },
  {
    itemId: "13486",
    name: "Rezept: Untod zu Wasser transmutieren",
    quality: "Selten",
    iconName: "inv_scroll_06",
    slot: "",
    type: "Rezept",
    boss: "Onyxia",
    statsText: "Benötigt Alchimie (275) | Benutzen: Lehrt Euch die Transmutation von Essenz des Untodes in Essenz des Wassers.",
    tooltip: "Rezept: Untod zu Wasser transmutieren | Gegenstandsstufe 55 | Benötigt Alchimie (275) | Benutzen: Lehrt Euch die Transmutation von Essenz des Untodes in Essenz des Wassers."
  },
  {
    itemId: "16253",
    name: "Formel: Brust - Große Werte",
    quality: "Ungewöhnlich",
    iconName: "inv_misc_note_01",
    slot: "",
    type: "Rezept",
    boss: "Onyxia",
    statsText: "Benötigt Verzauberkunst (300) | Benutzen: Lehrt Euch, wie man ein Teil der Brustrüstung dauerhaft so verzaubert, dass jedes der fünf Attribute um +4 erhöht wird.",
    tooltip: "Formel: Brust - Große Werte | Gegenstandsstufe 62 | Benötigt Verzauberkunst (300) | Benutzen: Lehrt Euch, wie man ein Teil der Brustrüstung dauerhaft so verzaubert, dass jedes der fünf Attribute um +4 erhöht wird."
  },
  {
    itemId: "4500",
    name: "Reiserucksack",
    quality: "Ungewöhnlich",
    iconName: "inv_misc_bag_08",
    slot: "Tasche",
    type: "Behälter",
    boss: "Onyxia",
    statsText: "16 Platz Behälter",
    tooltip: "Reiserucksack | Gegenstandsstufe 55 | 16 Platz Behälter | Verkaufspreis: 87 50"
  }
];

async function applyOnyLootMetadataBackfillOnce() {
  await ensureLootItemMetadataColumns();
  const client = await pool.connect();
  try {
    await client.query("begin");
    let updated = 0;
    for (const item of ONY_LOOT_METADATA_BACKFILL) {
      const result = await client.query(
        `update items
         set quality = coalesce(nullif(quality, ''), $3),
             icon_url = coalesce(nullif(icon_url, ''), $4),
             slot = coalesce(nullif(slot, ''), $5),
             type = coalesce(nullif(type, ''), $6),
             boss = coalesce(nullif(boss, ''), $7),
             stats_text = case
               when coalesce(stats_text, '') = '' then $8
               else stats_text
             end,
             tooltip = case
               when coalesce(tooltip, '') = ''
                 or lower(tooltip) = lower(name)
                 or coalesce(stats_text, '') = ''
               then $9
               else tooltip
             end
         where lower(raid_type) = 'ony'
           and item_id = $1
           and lower(name) = lower($2)
         returning id`,
        [
          item.itemId,
          item.name,
          item.quality,
          item.iconName,
          item.slot,
          item.type,
          item.boss,
          item.statsText,
          item.tooltip
        ]
      );
      updated += result.rowCount || 0;
    }
    await client.query("commit");
    return { success: true, source: "ony-metadata-backfill", checked: ONY_LOOT_METADATA_BACKFILL.length, updated };
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function applyMcCoreFelclothBagPatternCorrectionOnce() {
  await ensureLootItemMetadataColumns();
  const result = await query(
    `update items
     set item_id = '21371',
         name = 'Muster: Kernteufelsstofftasche',
         quality = 'Selten',
         icon_url = 'inv_scroll_05',
         slot = '',
         type = 'Schneiderei',
         boss = coalesce(nullif(boss, ''), 'All bosses'),
         stats_text = 'Benutzen: Lehrt Euch wie man eine Teufelsstofftasche näht. | Klassen: Hexenmeister',
         tooltip = 'Muster: Kernteufelsstofftasche | Benötigt Schneiderei (300) | Benutzen: Lehrt Euch wie man eine Teufelsstofftasche näht. |  | Kernteufelsstofftasche | Wird beim Anlegen gebunden | 28 Platz Seelentasche | Klassen: Hexenmeister |  | Benötigt Teufelsstoff (20), Kernleder (16), Blutrebe (8), Essenz des Feuers (4), Eisenweberseide (4)'
     where lower(raid_type) = 'mc'
       and (
         item_id = '21371'
         or regexp_replace(lower(name), '[^a-z0-9]+', '', 'g') = regexp_replace(lower('Kernteufelsstofftasche'), '[^a-z0-9]+', '', 'g')
       )
     returning id`,
    []
  );
  return { success: true, source: "mc-core-felcloth-bag-pattern-correction", updated: result.rowCount || 0 };
}

async function applyZgHakkariOffhandCorrectionOnce() {
  const markerKey = "zg-hakkari-same-name-distinct-ids-v2";
  const client = await pool.connect();
  try {
    await client.query("begin");
    await client.query(
      `create table if not exists app_state (
         key text primary key,
         value text,
         updated_at timestamptz not null default now()
       )`
    );
    const marker = await client.query("select value from app_state where key = $1", [markerKey]);
    if (marker.rows.length) {
      await client.query("commit");
      return;
    }

    const items = [
      {
        raid: "zg",
        itemId: "19866",
        name: "Kriegsklinge der Hakkari",
        quality: "epic",
        iconName: "inv_sword_55",
        slot: "Schildhand",
        type: "Einhandschwerter",
        boss: "Bloodlord Mandokir",
        bind: "Wird beim Aufheben gebunden",
        category: "Waffe",
        statsText: "Anlegen: +40 Angriffskraft. | (2) Set: Schwerter +6.",
        tooltip: "Kriegsklinge der Hakkari | Gegenstandsstufe 66 | Wird beim Aufheben gebunden | Einzigartig | Schildhand Schwert | 57 - 106 Schaden Tempo 1,70 | (47.94 Schaden pro Sekunde) | Haltbarkeit 105 / 105 | Benötigt Stufe 60 | Anlegen: +40 Angriffskraft. | '...den brodelnden Flammen des Hasses.' | Die Zwillingsklingen von Hakkari (0/2) | Kriegsklinge der Hakkari | Kriegsklinge der Hakkari | (2) Set: Schwerter +6.",
        needed: "Benötigt Stufe 60",
        equip: "Anlegen: +40 Angriffskraft.",
        dropchance: ""
      },
      {
        raid: "zg",
        itemId: "19865",
        name: "Kriegsklinge der Hakkari",
        quality: "epic",
        iconName: "inv_sword_55",
        slot: "Waffenhand",
        type: "Einhandschwerter",
        boss: "Hakkar",
        bind: "Wird beim Aufheben gebunden",
        category: "Waffe",
        statsText: "Anlegen: +28 Angriffskraft. | Anlegen: Erhöht Eure Chance, einen kritischen Treffer zu erzielen, um 1%. | (2) Set: Schwerter +6.",
        tooltip: "Kriegsklinge der Hakkari | Gegenstandsstufe 66 | Wird beim Aufheben gebunden | Einzigartig | Waffenhand Schwert | 59 - 110 Schaden Tempo 1,70 | (49.7 Schaden pro Sekunde) | Benötigt Stufe 60 | Anlegen: +28 Angriffskraft. | Anlegen: Erhöht Eure Chance, einen kritischen Treffer zu erzielen, um 1%. | Die Zwillingsklingen von Hakkari (0/2) | Kriegsklinge der Hakkari | Kriegsklinge der Hakkari | (2) Set: Schwerter +6. | 'Geschmiedet in...'",
        needed: "Benötigt Stufe 60",
        equip: "Anlegen: +28 Angriffskraft. | Anlegen: Erhöht Eure Chance, einen kritischen Treffer zu erzielen, um 1%.",
        dropchance: "Nov 56%"
      }
    ];

    let upserted = 0;
    for (const item of items) {
      const result = await upsertLootItemRecord(client, item, { preserveExisting: false });
      if (result) upserted += 1;
    }

    const mainhand = await client.query(
      `select id from items
       where lower(raid_type) = 'zg'
         and item_id = '19865'
       order by created_at asc
       limit 1`
    );
    const mainhandId = mainhand.rows[0]?.id || "";
    const offhand = await client.query(
      `select id from items
       where lower(raid_type) = 'zg'
         and item_id = '19866'
       order by created_at asc
       limit 1`
    );
    const offhandId = offhand.rows[0]?.id || "";
    let removedOldOffhandRows = 0;
    let movedReferences = 0;
    if (offhandId) {
      const oldOffhandRows = await client.query(
        `select id from items
         where lower(raid_type) = 'zg'
           and item_id = '135365'`
      );
      for (const row of oldOffhandRows.rows) {
        const p1 = await client.query("update prios set p1_item_id = $1 where p1_item_id = $2", [offhandId, row.id]);
        const p2 = await client.query("update prios set p2_item_id = $1 where p2_item_id = $2", [offhandId, row.id]);
        const p3 = await client.query("update prios set p3_item_id = $1 where p3_item_id = $2", [offhandId, row.id]);
        const p0 = await client.query("update p0plus_points set item_id = $1 where item_id = $2", [offhandId, row.id]);
        movedReferences += p1.rowCount + p2.rowCount + p3.rowCount + p0.rowCount;
        const deleted = await client.query("delete from items where id = $1", [row.id]);
        removedOldOffhandRows += deleted.rowCount;
      }
    }

    await client.query(
      `insert into app_state (key, value, updated_at)
       values ($1, $2, now())
       on conflict (key) do update set value = excluded.value, updated_at = now()`,
      [markerKey, JSON.stringify({ upserted, itemIds: ["19866", "19865"], removedOldOffhandRows, movedReferences })]
    );
    await client.query("commit");
    console.log("ZG-Hakkari-Zwillingsklingen korrigiert: 19866 Offhand und 19865 Waffenhand mit gleichem Namen");
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function applyLootRaidAssignmentCorrectionsOnce() {
  const markerKey = "loot-raid-assignment-corrections-v1";
  const corrections = [
    ["16900", "ony"],
    ["16939", "ony"],
    ["16914", "ony"],
    ["16955", "ony"],
    ["16908", "ony"],
    ["16929", "ony"],
    ["16963", "ony"],
    ["16921", "ony"],
    ["16947", "ony"],
    ["16901", "mc"],
    ["16938", "mc"],
    ["16915", "mc"],
    ["16954", "mc"],
    ["16909", "mc"],
    ["16930", "mc"],
    ["16962", "mc"],
    ["16922", "mc"],
    ["16946", "mc"]
  ];
  const client = await pool.connect();
  try {
    await client.query("begin");
    await client.query(
      `create table if not exists app_state (
         key text primary key,
         value text,
         updated_at timestamptz not null default now()
       )`
    );
    const marker = await client.query("select value from app_state where key = $1", [markerKey]);
    if (marker.rows.length) {
      await client.query("commit");
      return;
    }

    let movedReferences = 0;
    let removedWrongRows = 0;
    let reassignedRows = 0;
    for (const [itemId, targetRaid] of corrections) {
      const targetResult = await client.query(
        `select id
         from items
         where item_id = $1
           and lower(raid_type) = $2
         order by created_at asc
         limit 1`,
        [itemId, targetRaid]
      );
      const wrongResult = await client.query(
        `select id
         from items
         where item_id = $1
           and lower(raid_type) = 'bwl'`,
        [itemId]
      );
      if (!wrongResult.rows.length) continue;

      let targetId = targetResult.rows[0]?.id || "";
      if (!targetId) {
        const reassigned = await client.query(
          `update items
           set raid_type = $2
           where id = $1
           returning id`,
          [wrongResult.rows[0].id, targetRaid]
        );
        targetId = reassigned.rows[0]?.id || "";
        reassignedRows += reassigned.rowCount;
      }

      for (const wrongRow of wrongResult.rows) {
        if (!targetId || wrongRow.id === targetId) continue;
        const p1 = await client.query("update prios set p1_item_id = $1 where p1_item_id = $2", [targetId, wrongRow.id]);
        const p2 = await client.query("update prios set p2_item_id = $1 where p2_item_id = $2", [targetId, wrongRow.id]);
        const p3 = await client.query("update prios set p3_item_id = $1 where p3_item_id = $2", [targetId, wrongRow.id]);
        const p0 = await client.query("update p0plus_points set item_id = $1 where item_id = $2", [targetId, wrongRow.id]);
        movedReferences += p1.rowCount + p2.rowCount + p3.rowCount + p0.rowCount;
        const deleted = await client.query("delete from items where id = $1", [wrongRow.id]);
        removedWrongRows += deleted.rowCount;
      }
    }

    await client.query(
      `insert into app_state (key, value, updated_at)
       values ($1, $2, now())
       on conflict (key) do update set value = excluded.value, updated_at = now()`,
      [markerKey, JSON.stringify({ corrections: corrections.length, movedReferences, removedWrongRows, reassignedRows })]
    );
    await client.query("commit");
    console.log(`Loot-Raid-Zuordnungen korrigiert: ${removedWrongRows} BWL-Duplikate entfernt, ${movedReferences} Referenzen verschoben`);
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function applyEterniumLockboxRaidItemsOnce() {
  const markerKey = "eternium-lockbox-raid-items-v2";
  const raidTypes = ["mc", "bwl", "naxx"];
  const client = await pool.connect();
  try {
    await client.query("begin");
    await client.query(
      `create table if not exists app_state (
         key text primary key,
         value text,
         updated_at timestamptz not null default now()
       )`
    );
    const marker = await client.query("select value from app_state where key = $1", [markerKey]);
    if (marker.rows.length) {
      await client.query("commit");
      return;
    }

    let upserted = 0;
    for (const raidType of raidTypes) {
      const result = await upsertLootItemRecord(client, {
        raid: raidType,
        itemId: "5760",
        name: "Eterniumschließkassette",
        quality: "common",
        iconName: "Inv_misc_ornatebox",
        slot: "Sonstiges",
        type: "Sonstiges",
        boss: "Trash",
        category: "Sonstiges"
      }, { preserveExisting: false });
      if (result) upserted += 1;
    }

    await client.query(
      `insert into app_state (key, value, updated_at)
       values ($1, $2, now())
       on conflict (key) do update set value = excluded.value, updated_at = now()`,
      [markerKey, JSON.stringify({ raidTypes, upserted })]
    );
    await client.query("commit");
    console.log("Eterniumschließkassette für MC, BWL und Naxx ergänzt");
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function applyNaxxPoItemAliasCleanupOnce() {
  const markerKey = "naxx-po-item-alias-cleanup-v2";
  const raidTypes = raidTypeSearchValues("naxx").map(value => value.toLowerCase());
  const corrections = [
    {
      targetName: "Amulett von Vek'nilash",
      aliases: ["Amulett von Veknilash"]
    },
    {
      targetName: "Die gebundene Essenz Saphirons",
      aliases: ["Gebundene Essenz von Saphiron", "Gebundene Essenz Saphirons"]
    }
  ];
  const client = await pool.connect();
  try {
    await client.query("begin");
    await client.query(
      `create table if not exists app_state (
         key text primary key,
         value text,
         updated_at timestamptz not null default now()
       )`
    );
    const marker = await client.query("select value from app_state where key = $1", [markerKey]);
    if (marker.rows.length) {
      await client.query("commit");
      return;
    }

    const itemsResult = await client.query(
      `select id, name, raid_type
       from items
       where lower(raid_type) = any($1)
       order by created_at asc`,
      [raidTypes]
    );
    const naxxItems = itemsResult.rows || [];
    const itemByLookup = new Map();
    for (const item of naxxItems) {
      const key = itemLookupKey(item.name);
      if (key && !itemByLookup.has(key)) itemByLookup.set(key, item);
    }

    let movedReferences = 0;
    let removedDuplicateItems = 0;
    let renamedItems = 0;
    let rewrittenComments = 0;
    let removedDuplicateP0PlusRows = 0;
    let mergedDuplicatePrioGroups = 0;
    let removedDuplicatePrioRows = 0;
    let movedDuplicateP0PlusRows = 0;

    for (const correction of corrections) {
      const targetKey = itemLookupKey(correction.targetName);
      const aliasKeys = new Set(correction.aliases.map(itemLookupKey).filter(Boolean));
      let targetItem = itemByLookup.get(targetKey);
      if (!targetItem) {
        const aliasItem = naxxItems.find(item => aliasKeys.has(itemLookupKey(item.name)));
        if (!aliasItem) continue;
        const renamed = await client.query(
          `update items
           set name = $2
           where id = $1
           returning id, name, raid_type`,
          [aliasItem.id, correction.targetName]
        );
        targetItem = renamed.rows[0];
        renamedItems += renamed.rowCount;
        itemByLookup.set(targetKey, targetItem);
        aliasKeys.delete(itemLookupKey(aliasItem.name));
      }

      const duplicateItems = naxxItems.filter(item => {
        if (!targetItem || item.id === targetItem.id) return false;
        return aliasKeys.has(itemLookupKey(item.name));
      });

      for (const duplicate of duplicateItems) {
        const p1 = await client.query("update prios set p1_item_id = $1 where p1_item_id = $2", [targetItem.id, duplicate.id]);
        const p2 = await client.query("update prios set p2_item_id = $1 where p2_item_id = $2", [targetItem.id, duplicate.id]);
        const p3 = await client.query("update prios set p3_item_id = $1 where p3_item_id = $2", [targetItem.id, duplicate.id]);
        const p0 = await client.query("update p0plus_points set item_id = $1 where item_id = $2", [targetItem.id, duplicate.id]);
        movedReferences += p1.rowCount + p2.rowCount + p3.rowCount + p0.rowCount;
        const deleted = await client.query("delete from items where id = $1", [duplicate.id]);
        removedDuplicateItems += deleted.rowCount;
      }

      const comments = await client.query(
        `select pr.id, pr.comment
         from prios pr
         join raids r on r.id = pr.raid_id
         where lower(r.raid_type) = any($1)
           and pr.comment is not null
           and pr.comment <> ''`,
        [raidTypes]
      );
      for (const row of comments.rows || []) {
        let meta;
        try {
          meta = JSON.parse(row.comment || "{}") || {};
        } catch {
          continue;
        }
        if (!meta.p0Item || !aliasKeys.has(itemLookupKey(meta.p0Item))) continue;
        meta.p0Item = correction.targetName;
        const updated = await client.query(
          "update prios set comment = $2, updated_at = now() where id = $1",
          [row.id, JSON.stringify(meta)]
        );
        rewrittenComments += updated.rowCount;
      }

      const deduped = await client.query(
        `delete from p0plus_points pp
         using (
           select ctid
           from (
             select ctid,
                    row_number() over (
                      partition by guild_id, character_id, item_id, source, coalesce(note, '')
                      order by ctid
                    ) as rn
             from p0plus_points
             where item_id = $1
           ) ranked
           where rn > 1
         ) duplicate_rows
         where pp.ctid = duplicate_rows.ctid`,
        [targetItem.id]
      );
      removedDuplicateP0PlusRows += deduped.rowCount;
    }

    const duplicatePrioGroups = await client.query(
      `select
         r.id as raid_id,
         lower(trim(c.name)) as character_key,
         lower(coalesce(trim(c.server), '')) as server_key,
         array_agg(pr.id order by
           ((case when pr.p1_item_id is not null then 1 else 0 end) +
            (case when pr.p2_item_id is not null then 1 else 0 end) +
            (case when pr.p3_item_id is not null then 1 else 0 end)) desc,
           case when pr.comment is not null and pr.comment <> '' then 1 else 0 end desc,
           pr.updated_at desc nulls last,
           pr.created_at desc nulls last
         ) as prio_ids,
         array_agg(pr.character_id order by
           ((case when pr.p1_item_id is not null then 1 else 0 end) +
            (case when pr.p2_item_id is not null then 1 else 0 end) +
            (case when pr.p3_item_id is not null then 1 else 0 end)) desc,
           case when pr.comment is not null and pr.comment <> '' then 1 else 0 end desc,
           pr.updated_at desc nulls last,
           pr.created_at desc nulls last
         ) as character_ids
       from prios pr
       join raids r on r.id = pr.raid_id
       join characters c on c.id = pr.character_id
       where lower(r.raid_type) = any($1)
         and nullif(trim(c.name), '') is not null
       group by r.id, lower(trim(c.name)), lower(coalesce(trim(c.server), ''))
       having count(*) > 1`,
      [raidTypes]
    );

    for (const group of duplicatePrioGroups.rows || []) {
      const prioIds = Array.isArray(group.prio_ids) ? group.prio_ids.filter(Boolean) : [];
      const characterIds = Array.isArray(group.character_ids) ? group.character_ids.filter(Boolean) : [];
      if (prioIds.length < 2 || !characterIds.length) continue;

      const keepPrioId = prioIds[0];
      const keepCharacterId = characterIds[0];
      const duplicateCharacterIds = [...new Set(characterIds.slice(1).filter(id => id !== keepCharacterId))];

      const mergeRowsResult = await client.query(
        `select id, p1_item_id, p2_item_id, p3_item_id, comment, bench
         from prios
         where id = any($1::uuid[])`,
        [prioIds]
      );
      const rows = mergeRowsResult.rows || [];
      const keep = rows.find(row => String(row.id) === String(keepPrioId)) || rows[0] || {};
      const pickItem = key => keep[key] || (rows.find(row => row[key]) || {})[key] || null;
      const pickText = key => clean(keep[key]) || clean((rows.find(row => clean(row[key])) || {})[key]);

      if (duplicateCharacterIds.length) {
        const movedP0Plus = await client.query(
          `update p0plus_points
           set character_id = $1
           where character_id = any($2::uuid[])`,
          [keepCharacterId, duplicateCharacterIds]
        );
        movedDuplicateP0PlusRows += movedP0Plus.rowCount;
      }

      await client.query(
        `update prios
         set p1_item_id = $2,
             p2_item_id = $3,
             p3_item_id = $4,
             comment = nullif($5, ''),
             bench = $6,
             updated_at = now()
         where id = $1`,
        [
          keepPrioId,
          pickItem("p1_item_id"),
          pickItem("p2_item_id"),
          pickItem("p3_item_id"),
          pickText("comment"),
          pickText("bench")
        ]
      );

      const deletedDuplicatePrios = await client.query(
        `delete from prios
         where id = any($1::uuid[])
           and id <> $2`,
        [prioIds, keepPrioId]
      );
      removedDuplicatePrioRows += deletedDuplicatePrios.rowCount;

      const dedupedMovedP0Plus = await client.query(
        `delete from p0plus_points pp
         using (
           select ctid
           from (
             select ctid,
                    row_number() over (
                      partition by guild_id, character_id, item_id, source, coalesce(note, '')
                      order by ctid
                    ) as rn
             from p0plus_points
             where character_id = $1
           ) ranked
           where rn > 1
         ) duplicate_rows
         where pp.ctid = duplicate_rows.ctid`,
        [keepCharacterId]
      );
      removedDuplicateP0PlusRows += dedupedMovedP0Plus.rowCount;
      mergedDuplicatePrioGroups += 1;
    }

    await client.query(
      `insert into app_state (key, value, updated_at)
       values ($1, $2, now())
       on conflict (key) do update set value = excluded.value, updated_at = now()`,
      [
        markerKey,
        JSON.stringify({
          corrections: corrections.length,
          movedReferences,
          removedDuplicateItems,
          renamedItems,
          rewrittenComments,
          removedDuplicateP0PlusRows,
          mergedDuplicatePrioGroups,
          removedDuplicatePrioRows,
          movedDuplicateP0PlusRows
        })
      ]
    );
    await client.query("commit");
    console.log(
      `Naxx-PO-Item-Dubletten bereinigt: ${removedDuplicateItems} Items entfernt, ${movedReferences} Referenzen verschoben, ${mergedDuplicatePrioGroups} Prio-Gruppen zusammengeführt`
    );
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function loadLootMetadataSourceItems(raidType) {
  return { items: [], source: "railway-only" };
}

async function adminSearchItems({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  const searchTerms = clean(params.search || params.item || "")
    .split(/\s+/)
    .map(term => term.trim())
    .filter(Boolean)
    .slice(0, 6);
  const raidType = normalizeRaidType(params.raid);
  const values = [];
  const searchClauses = [];
  for (const term of searchTerms) {
    values.push(`%${term}%`);
    searchClauses.push(`i.name ilike $${values.length}`);
  }
  const searchClause = searchClauses.length ? `and ${searchClauses.join(" and ")}` : "";
  let raidClause = "";
  if (raidType) {
    values.push(raidTypeSearchValues(raidType));
    raidClause = `and (
      lower(i.raid_type) = any($${values.length})
      or lower(regexp_replace(i.raid_type, '[^a-z0-9]+', '-', 'g')) = any($${values.length})
    )`;
  }

  const result = await query(
    `select
       i.id,
       i.raid_type,
       i.item_id,
       i.name,
       i.quality,
       i.icon_url,
       i.slot,
       i.type,
       i.boss,
       i.bind,
       i.category,
       i.wowhead,
       i.stats_text,
       i.tooltip,
       i.needed,
       i.equip,
       i.dropchance,
       (select count(*)::int from prios pr where pr.p1_item_id = i.id or pr.p2_item_id = i.id or pr.p3_item_id = i.id) as prio_count,
       (select count(*)::int from p0plus_points pp where pp.guild_id = $${values.length + 1} and pp.item_id = i.id) as p0plus_count
     from items i
     where 1 = 1
       ${searchClause}
       ${raidClause}
     order by i.raid_type asc, i.name asc
     limit 80`,
    [...values, guildId]
  );
  return { success: true, items: result.rows };
}

async function getLootItems({ query: params }) {
  const raidType = normalizeRaidType(params.raid || params.raidType || "");
  if (!raidType || raidType === "raid") {
    const error = new Error("Raid fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const result = await query(
    `select id, raid_type, item_id, name, quality, icon_url,
            slot, type, boss, bind, category, wowhead,
            stats_text, tooltip, needed, equip, price, dropchance,
            token_group, token_name, token_item_id
     from items
     where lower(raid_type) = any($1)
        or lower(regexp_replace(raid_type, '[^a-z0-9]+', '-', 'g')) = any($1)
     order by name asc`,
    [raidTypeSearchValues(raidType)]
  );

  const mergedItems = result.rows.map(row => normalizeLootItemForApi(row));

  mergedItems.sort((a, b) => clean(a.name).localeCompare(clean(b.name), "de"));

  return {
    success: true,
    raid: raidType,
    source: "Railway",
    enriched: true,
    items: mergedItems
  };
}

async function ensureGuildPoItemsSchema() {
  await query(
    `create table if not exists guild_po_items (
       guild_id uuid not null references guilds(id) on delete cascade,
       item_id uuid not null references items(id) on delete cascade,
       raid_type text not null,
       enabled boolean not null default true,
       updated_by text,
       updated_at timestamptz not null default now(),
       primary key (guild_id, item_id)
     )`
  );
  await query(`create index if not exists guild_po_items_guild_raid_idx on guild_po_items (guild_id, raid_type, enabled)`);
}

async function getGuildPoItems({ guild, query: params = {} }) {
  await ensureGuildPoItemsSchema();
  const raidType = normalizeRaidType(params.raid || params.raidType || "");
  const values = [guild.id];
  let raidClause = "";
  if (raidType && raidType !== "raid") {
    values.push(raidTypeSearchValues(lootSourceRaidType(raidType)));
    raidClause = `and (lower(i.raid_type) = any($2) or lower(regexp_replace(i.raid_type, '[^a-z0-9]+', '-', 'g')) = any($2))`;
  }
  const result = await query(
    `select i.id, i.raid_type, i.item_id, i.name, i.quality, i.icon_url,
            i.slot, i.type, i.boss,
            coalesce(gpi.enabled, false) as po_enabled
     from items i
     left join guild_po_items gpi on gpi.guild_id = $1 and gpi.item_id = i.id
     where 1 = 1 ${raidClause}
     order by lower(i.raid_type), lower(i.name)`,
    values
  );
  const enabledOnly = clean(params.enabledOnly).toLowerCase() === "true" || clean(params.enabledOnly) === "1";
  const rows = enabledOnly ? result.rows.filter(row => Boolean(row.po_enabled)) : result.rows;
  return {
    success: true,
    raid: raidType,
    items: rows.map(row => ({ ...normalizeLootItemForApi(row), poEnabled: Boolean(row.po_enabled) }))
  };
}

async function setGuildPoItem({ guild, query: params = {} }) {
  requireMasterCodeForGuild(guild, params.masterCode);
  if (clean(guild?.slug).toLowerCase() !== "nachtloot") {
    const error = new Error("PO-Items werden nur für Nachtwächter verwaltet.");
    error.statusCode = 403;
    throw error;
  }
  await ensureGuildPoItemsSchema();
  const itemId = clean(params.itemId || params.id);
  const enabled = String(params.enabled).toLowerCase() === "true" || String(params.enabled) === "1";
  if (!itemId) {
    const error = new Error("Item-ID fehlt.");
    error.statusCode = 400;
    throw error;
  }
  const itemResult = await query(`select id, raid_type, name from items where id::text = $1 or item_id = $1 limit 1`, [itemId]);
  const item = itemResult.rows[0];
  if (!item) {
    const error = new Error("Item wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }
  await query(
    `insert into guild_po_items (guild_id, item_id, raid_type, enabled, updated_by, updated_at)
     values ($1, $2, $3, $4, $5, now())
     on conflict (guild_id, item_id) do update
       set raid_type = excluded.raid_type,
           enabled = excluded.enabled,
           updated_by = excluded.updated_by,
           updated_at = now()`,
    [guild.id, item.id, normalizeRaidType(item.raid_type), enabled, clean(params.updatedBy) || "Gildenleitung"]
  );
  return { success: true, itemId: item.id, itemName: item.name, raid: normalizeRaidType(item.raid_type), enabled };
}

async function requireGuildPoItem(guildId, itemId, itemName = "") {
  const guildResult = await query(`select lower(slug) as slug from guilds where id = $1 limit 1`, [guildId]);
  if (guildResult.rows[0]?.slug !== "nachtloot") return { bypassed: true };
  await ensureGuildPoItemsSchema();
  const result = await query(
    `select i.id, i.name
     from items i
     join guild_po_items gpi on gpi.guild_id = $1 and gpi.item_id = i.id and gpi.enabled = true
     where i.id::text = $2 or ($3 <> '' and lower(i.name) = lower($3))
     limit 1`,
    [guildId, clean(itemId), clean(itemName)]
  );
  if (!result.rows[0]) {
    const error = new Error("Dieses Item ist von der Gildenleitung nicht als PO-Item freigegeben.");
    error.statusCode = 403;
    throw error;
  }
  return result.rows[0];
}

async function loadStaticLootItems(raidType) {
  return [];
}

function normalizeLootItemForApi(row, detail = {}) {
  const raidType = normalizeRaidType(row?.raid_type || detail.raid_type || detail.raid || "");
  const itemId = clean(row?.item_id || detail.item_id || detail.itemId || detail.ItemID || "");
  const name = clean(row?.name || detail.name || detail.Item || "");
  const icon = clean(row?.icon_url || detail.iconName || detail.icon_url || detail.icon || detail.IconName || "");
  const quality = clean(row?.quality || detail.quality || detail["Qualität"] || "");
  const stats = Array.isArray(detail.stats)
    ? detail.stats
    : clean(row?.stats_text || detail.statsText || detail.Stats_DE || "").split("|").map(line => line.trim()).filter(Boolean);
  const tooltip = clean(row?.tooltip || detail.tooltip || detail.Tooltip || detail.Tooltip_DE || "");
  const slot = clean(row?.slot || detail.slot || detail.Slot || detail.Slot_DE || "");
  const type = clean(row?.type || detail.type || detail.Typ || detail.Typ_DE || "");
  const boss = clean(row?.boss || detail.boss || detail.Boss || "");
  const dropChance = clean(row?.dropchance || detail.dropChance || detail.dropchance || detail.Dropchance || "");
  const statsText = clean(row?.stats_text || detail.statsText || detail.Stats_DE || stats.join("|"));

  return {
    id: row?.id || itemId || name,
    raid: row?.raid_type || detail.raid || raidType,
    raidKey: raidType,
    itemId,
    ItemID: itemId,
    name,
    item: name,
    Item: name,
    quality,
    icon,
    iconName: icon,
    IconName: icon,
    slot,
    Slot: slot,
    Slot_DE: slot,
    type,
    Typ: type,
    Typ_DE: type,
    boss,
    Boss: boss,
    stats,
    statsText,
    Stats_DE: statsText,
    tooltip,
    Tooltip: tooltip,
    Tooltip_DE: tooltip,
    dropChance,
    dropchance: dropChance,
    Dropchance: dropChance,
    bind: clean(row?.bind || detail.bind || detail.Bindung || detail.Bind || ""),
    category: clean(row?.category || detail.category || detail.Kategorie || detail.Category || ""),
    wowhead: clean(row?.wowhead || detail.wowhead || detail.Wowhead || detail.WowheadLink || ""),
    needed: clean(row?.needed || detail.needed || detail["Benötigt"] || detail.Benötigt || ""),
    equip: clean(row?.equip || detail.equip || detail.Anlegen || ""),
    price: clean(row?.price || detail.price || detail.Preis || ""),
    tokenGroup: clean(row?.token_group || detail.tokenGroup || detail.TokenGroup || detail.tokenKey || detail.TokenKey || ""),
    tokenName: clean(row?.token_name || detail.tokenName || detail.TokenName || ""),
    tokenItemId: clean(row?.token_item_id || detail.tokenItemId || detail.TokenItemId || "")
  };
}

function isLootPageSetPiece(item) {
  if (!item) return false;
  const stats = Array.isArray(item.stats) ? item.stats.join(" | ") : "";
  const text = [
    item.name,
    item.slot,
    item.type,
    item.category,
    item.tooltipText,
    item.tooltip,
    item.statsText,
    item.Stats_DE,
    stats
  ].join(" | ");

  const hasSetBonus = /\(\d+\)\s*Set:/i.test(text) || /\(\d+\/\d+\)/.test(text);
  if (!hasSetBonus) return false;

  const hasClassRestriction = /Klassen:/i.test(text);
  const hasTokenRewardLink = Boolean(item.tokenGroup || item.tokenItemId || item.tokenName);
  const armorSlots = /^(Kopf|Schulter|Brust|Handgelenke|Hände|Taille|Beine|Füße|Finger)$/i;
  const isArmorReward = armorSlots.test(clean(item.slot));

  return hasClassRestriction || hasTokenRewardLink || isArmorReward;
}

async function adminUpdateItem({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  const id = clean(params.id || params.itemId);
  if (!isUuid(id)) {
    const error = new Error("Item-ID fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const result = await query(
    `update items
     set icon_url = coalesce(nullif($2, ''), icon_url),
         quality = coalesce(nullif($3, ''), quality),
         item_id = coalesce(nullif($4, ''), item_id)
     where id = $1
     returning id, raid_type, item_id, name, quality, icon_url`,
    [id, clean(params.iconUrl || params.icon || params.icon_url), clean(params.quality), clean(params.itemGameId || params.item_id)]
  );
  if (!result.rows.length) {
    const error = new Error("Item wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }
  return { success: true, item: result.rows[0] };
}

async function adminCreateItem({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  const raidType = normalizeRaidType(params.raid || params.raidType);
  const name = clean(params.name || params.itemName || params.item);
  const itemId = clean(params.itemGameId || params.item_id || params.itemId);
  const quality = clean(params.quality);
  const iconUrl = clean(params.iconUrl || params.icon || params.icon_url);
  const slot = clean(params.slot);
  const type = clean(params.type || params.itemType);
  const boss = clean(params.boss);
  const bind = clean(params.bind);
  const category = clean(params.category);
  const wowhead = clean(params.wowhead);
  const statsText = clean(params.statsText || params.stats_text).replace(/\r?\n/g, "|");
  const tooltip = clean(params.tooltip);
  const needed = clean(params.needed);
  const equip = clean(params.equip);
  const price = clean(params.price);
  const dropchance = clean(params.dropchance || params.dropChance);

  if (!raidType || raidType === "raid") {
    const error = new Error("Raid fehlt.");
    error.statusCode = 400;
    throw error;
  }
  if (!name) {
    const error = new Error("Itemname fehlt.");
    error.statusCode = 400;
    throw error;
  }
  if (!itemId || !iconUrl) {
    const error = new Error("Item-ID und Icon-ID sind Pflicht. Platzhalter-Items werden nicht mehr erstellt.");
    error.statusCode = 400;
    throw error;
  }

  const client = await pool.connect();
  try {
    const item = await upsertLootItemRecord(client, {
      raid: raidType,
      itemId,
      name,
      quality,
      iconName: iconUrl,
      slot,
      type,
      boss,
      bind,
      category,
      wowhead,
      statsText,
      tooltip,
      needed,
      equip,
      price,
      dropchance
    });
    return { success: true, item };
  } finally {
    client.release();
  }
}

async function adminDeleteItem({ guildId, query: params }) {
  requireMasterCode(params.masterCode);
  const id = clean(params.id || params.itemId);
  if (!isUuid(id)) {
    const error = new Error("Item-ID fehlt.");
    error.statusCode = 400;
    throw error;
  }

  const client = await pool.connect();
  try {
    await client.query("begin");
    await client.query("delete from p0plus_points where guild_id = $1 and item_id = $2", [guildId, id]);
    await client.query("update prios set p1_item_id = null where p1_item_id = $1", [id]);
    await client.query("update prios set p2_item_id = null where p2_item_id = $1", [id]);
    await client.query("update prios set p3_item_id = null where p3_item_id = $1", [id]);
    const deleted = await client.query("delete from items where id = $1 returning name, raid_type", [id]);
    await client.query("commit");
    return { success: true, deleted: deleted.rowCount, item: deleted.rows[0] || null };
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

async function resetPlayerPinBySecurity({
  guildId,
  charName,
  server,
  securityQuestion,
  securityAnswer,
  newPin
}) {
  const result = await query(
    `select p.id, p.security_question, p.security_answer
     from players p
     join characters c on c.player_id = p.id
     where p.guild_id = $1 and lower(c.name) = lower($2) and lower(c.server) = lower($3)
     limit 1`,
    [guildId, clean(charName), clean(server)]
  );

  const player = result.rows[0];
  if (!player) {
    const error = new Error("Dieser Charakter wurde nicht gefunden.");
    error.statusCode = 404;
    throw error;
  }

  const questionMatches = clean(player.security_question) === clean(securityQuestion);
  const answerMatches = clean(player.security_answer).toLowerCase() === clean(securityAnswer).toLowerCase();
  if (!questionMatches || !answerMatches) {
    const error = new Error("Sicherheitsfrage oder Antwort ist nicht korrekt.");
    error.statusCode = 403;
    throw error;
  }

  const pin = normalizePin(newPin);
  await query("update players set player_pin = $1, updated_at = now() where id = $2", [pin, player.id]);
  return pin;
}

app.get("/api/apps-script", async (req, res, next) => {
  try {
    const action = clean(req.query.action);

    if (action === "listGuilds") {
      const guilds = await listGuilds();
      return res.json(guilds);
    }

    if (action === "lichtbotListGuilds") {
      const guilds = await listGuildsForBot({ query: req.query });
      return res.json(guilds);
    }

    if (action === "lichtbotGetQueueAllGuilds") {
      const queue = await getBotQueueAllGuilds({ query: req.query });
      return res.json(queue);
    }

    if (action === "resolveGuildByPin") {
      const resolved = await resolveGuildByPin({ query: req.query });
      return res.json(resolved);
    }

    if (action === "createGuild") {
      const created = await createGuild({ query: req.query });
      return res.json(created);
    }

    if (action === "updateGuildConfig") {
      const saved = await updateGuildConfig({ query: req.query });
      return res.json(saved);
    }

    if (action === "submitGuildApplication") {
      const saved = await submitGuildApplication({ query: req.query });
      return res.json(saved);
    }

    if (action === "guildGetApplications") {
      const applications = await getGuildApplications({ query: req.query });
      return res.json(applications);
    }

    if (action === "guildApproveApplication") {
      const approved = await approveGuildApplication({ query: req.query });
      return res.json(approved);
    }

    if (action === "guildRejectApplication") {
      const rejected = await rejectGuildApplication({ query: req.query });
      return res.json(rejected);
    }

    if (action === "getGuildSetup") {
      const setup = await getGuildSetup({ query: req.query });
      return res.json(setup);
    }

    if (action === "completeGuildSetup") {
      const completed = await completeGuildSetup({ query: req.query });
      return res.json(completed);
    }

    const guild = await requireGuild(resolveGuildSlug(req.query.guild));
    await loadWorldbuffAccessCode(guild.id);
    await loadLootMasterAccessCode(guild.id);
    if (clean(req.query.masterCode)) {
      if (action === "transferP0PlusPoints" || action === "clearP0PlusForPlayer") {
        requireRaidleadP0MasterCodeForGuild(guild, req.query.masterCode);
      } else {
        requireMasterCodeForGuild(guild, req.query.masterCode, action, req.query);
      }
    }

    if (action === "getCharactersByPin") {
      const characters = await getCharactersByPin(guild.id, req.query.pin);
      return res.json({ success: true, guild: guild.slug, characters, entries: characters, chars: characters });
    }

    if (action === "getPlayerPrioHistory") {
      const history = await getPlayerPrioHistory(guild.id, req.query);
      return res.json({ ...history, guild: guild.slug });
    }

    if (action === "getPoReleaseDisplaySettings") {
      const settings = await getPoReleaseDisplaySettings(guild.id);
      return res.json({ ...settings, guild: guild.slug });
    }

    if (action === "getGuildLeadershipOverview") {
      const overview = await getGuildLeadershipOverview(guild.id, req.query);
      return res.json({ ...overview, guild: guild.slug });
    }

    if (action === "getActiveRaids") {
      const result = await query(
        `select r.*,
                (
                  select count(*)
                  from p0plus_points pp
                  where pp.guild_id = r.guild_id
                    and pp.source = 'Raidlead Transfer'
                    and pp.note in (
                      concat('RaidID: ', coalesce(r.external_raid_id, r.id::text)),
                      concat('RaidID: ', r.id::text),
                      concat('RaidID: ', r.raid_pin)
                    )
                ) as p0plus_transfer_count
         from raids r
         where r.guild_id = $1
           and raid_date >= current_date - interval '1 day'
           and coalesce(status, '') not in ('archiviert', 'archive')
         order by
           case when raid_date >= current_date then 0 else 1 end,
           case when raid_date >= current_date then raid_date end asc,
           case when raid_date < current_date then raid_date end desc,
           coalesce(raid_time, '') asc,
           created_at desc
         limit 50`,
        [guild.id]
      );
      const raids = result.rows.map(row => {
        const raid = normalizeRaidRow(row);
        return { ...raid, leadPin: "", LeadPin: "" };
      });
      return res.json({ success: true, guild: guild.slug, raids, allRaids: raids, activeRaids: raids });
    }

    if (action === "getRaidHelper" || action === "getRaidSignups") {
      const helper = await getRaidHelper({ guildId: guild.id, query: req.query });
      return res.json({ ...helper, guild: guild.slug });
    }

    if (action === "guildGetDiscordBotChannels") {
      const channels = await getDiscordBotChannels({ guildId: guild.id, query: req.query });
      return res.json({ ...channels, guild: guild.slug });
    }
    if (action === "guildGetDiscordBotRoles") {
      const roles = await getDiscordBotRoles({ guildId: guild.id, query: req.query });
      return res.json({ ...roles, guild: guild.slug });
    }
    if (action === "guildGetDiscordBotMembers") {
      const members = await getDiscordBotMembers({ guildId: guild.id, query: req.query });
      return res.json({ ...members, guild: guild.slug });
    }
    if(action==="guildGetNotificationSettings"){
      const settings=await getGuildNotificationSettings({guildId:guild.id,query:req.query});return res.json({...settings,guild:guild.slug});
    }

    if (action === "guildGetRaidHelperTemplates") {
      const templates = await getRaidHelperTemplates({ guildId: guild.id, query: req.query });
      return res.json({ ...templates, guild: guild.slug });
    }

    if (action === "guildGetRaidHelperSchedules") {
      const schedules = await getRaidHelperSchedules({ guildId: guild.id, query: req.query });
      return res.json({ ...schedules, guild: guild.slug });
    }

    if (action === "guildExportBackup" || action === "exportGuildBackup") {
      const backup = await exportGuildBackup({ guildId: guild.id, query: req.query });
      return res.json({ ...backup, guild: guild.slug });
    }

    if (action === "guildRaidBackupSnapshot" || action === "raidBackupSnapshot") {
      const backup = await getRaidBackupSnapshot({ guildId: guild.id, query: req.query });
      return res.json({ ...backup, guild: guild.slug });
    }

    if (action === "reportIssue") {
      const report = await reportIssue({ guildId: guild.id, query: req.query });
      return res.json({ ...report, guild: guild.slug });
    }

    if (action === "guildGetIssueReports") {
      const reports = await getIssueReports({ guildId: guild.id, query: req.query });
      return res.json({ ...reports, guild: guild.slug });
    }

    if (action === "guildGetLogAnalyses") {
      const analyses = await getLogAnalyses({ guildId: guild.id, query: req.query });
      return res.json({ ...analyses, guild: guild.slug });
    }

    if (action === "getPublicLogAnalyses") {
      const analyses = await getPublicLogAnalyses({ guildId: guild.id, query: req.query });
      return res.json({ ...analyses, guild: guild.slug });
    }

    if (action === "getPublicLogAnalysisWeb") {
      const webAnalysis = await getPublicLogAnalysisWeb({ guildId: guild.id, query: req.query });
      return res.json({ ...webAnalysis, guild: guild.slug });
    }

    if (action === "getPublicLogAnalysisWebLegacy") {
      const webAnalysis = await getPublicLogAnalysisWebLegacy({ guildId: guild.id, query: req.query });
      return res.json({ ...webAnalysis, guild: guild.slug });
    }

    if (action === "importRaidLogAnalysis") {
      const imported = await importRaidLogAnalysis({ guildId: guild.id, query: req.query });
      return res.json({ ...imported, guild: guild.slug });
    }

    if (action === "debugRaidLogAnalysisScopes") {
      const debugged = await debugRaidLogAnalysisScopes({ guildId: guild.id, query: req.query });
      return res.json({ ...debugged, guild: guild.slug });
    }

    if (action === "setPublicLogAnalysisRaidRoles") {
      const saved = await setPublicLogAnalysisRaidRoles({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildSaveLogAnalysis") {
      const saved = await saveLogAnalysis({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildRunLogAnalysis") {
      const started = await runLogAnalysis({ guildId: guild.id, query: req.query });
      return res.json({ ...started, guild: guild.slug });
    }

    if (action === "guildSetLogAnalysisSheetUrl") {
      const saved = await setLogAnalysisSheetUrl({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildSaveLogAnalysisSheetExport" || action === "saveLogAnalysisSheetExport") {
      const saved = await saveLogAnalysisSheetExport({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildImportLogAnalysisSheetExport") {
      const imported = await importLogAnalysisSheetExportFromUrl({ guildId: guild.id, query: req.query });
      return res.json({ ...imported, guild: guild.slug });
    }

    if (action === "guildDownloadLogAnalysis") {
      return await downloadLogAnalysis({ guildId: guild.id, query: req.query, res });
    }

    if (action === "guildResetLogAnalyses") {
      const reset = await resetLogAnalyses({ guildId: guild.id, query: req.query });
      return res.json({ ...reset, guild: guild.slug });
    }

    if (action === "guildResolveIssueReport") {
      const resolved = await resolveIssueReport({ guildId: guild.id, query: req.query });
      return res.json({ ...resolved, guild: guild.slug });
    }

    if (action === "guildDeletePlayerLogin") {
      const deleted = await deletePlayerLogin({ guildId: guild.id, query: req.query });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "guildSetPlayerLoginRole") {
      const saved = await setPlayerLoginRole({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }
    if(action==="guildVerifyWorldbuffAccess") return res.json({success:true,scope:"manage_worldbuffs",guild:guild.slug});
    if(action==="guildSetWorldbuffAccessPassword"){
      const saved=await setWorldbuffAccessPassword({guildId:guild.id,query:req.query});return res.json({...saved,guild:guild.slug});
    }
    if(action==="guildSetLootMasterAccessPassword"){
      const saved=await setLootMasterAccessPassword({guildId:guild.id,query:req.query});return res.json({...saved,guild:guild.slug});
    }
    if (action === "guildSetPlayerLoginAccess") {
      const saved = await setPlayerLoginAccess({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }
    if(action==="guildSetNotificationSetting"){
      const saved=await setGuildNotificationSetting({guildId:guild.id,query:req.query});return res.json({...saved,guild:guild.slug});
    }
    if(action==="guildSetRaidLootMasterTargets"){
      const saved=await setRaidLootMasterTargets({guildId:guild.id,query:req.query});return res.json({...saved,guild:guild.slug});
    }

    if (action === "guildSetPlayerLoginBlocked") {
      const saved = await setPlayerLoginBlocked({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildApprovePlayerLogin" || action === "guildSetPlayerLoginApproved") {
      const saved = await setPlayerLoginApproved({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildSetMasterCode") {
      const saved = await setGuildMasterCode({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildAdminSearchItems") {
      const items = await adminSearchItems({ guildId: guild.id, query: req.query });
      return res.json({ ...items, guild: guild.slug });
    }

    if (action === "refreshLootMetadata" || action === "guildRefreshLootMetadata") {
      requireMasterCode(req.query.masterCode);
      await ensureLootItemMetadataColumns();
      const metadata = await importLootItemMetadata();
      const onyBackfill = await applyOnyLootMetadataBackfillOnce();
      const mcCoreFelclothPattern = await applyMcCoreFelclothBagPatternCorrectionOnce();
      return res.json({ ...metadata, onyBackfill, mcCoreFelclothPattern, guild: guild.slug });
    }

    if (action === "getLootItems" || action === "guildGetLootItems") {
      const items = await getLootItems({ query: req.query });
      return res.json({ ...items, guild: guild.slug });
    }

    if (action === "guildGetPoItems" || action === "getGuildPoItems") {
      const items = await getGuildPoItems({ guild, query: req.query });
      return res.json({ ...items, guild: guild.slug });
    }

    if (action === "guildAdminUpdateItem") {
      const item = await adminUpdateItem({ guildId: guild.id, query: req.query });
      return res.json({ ...item, guild: guild.slug });
    }

    if (action === "guildAdminCreateItem" || action === "guildAdminCreateltem") {
      const item = await adminCreateItem({ guildId: guild.id, query: req.query });
      return res.json({ ...item, guild: guild.slug });
    }

    if (action === "guildAdminDeleteItem") {
      const deleted = await adminDeleteItem({ guildId: guild.id, query: req.query });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "sendPlayerMessage") {
      const message = await sendPlayerMessage({ guildId: guild.id, query: req.query });
      return res.json({ ...message, guild: guild.slug });
    }

    if (action === "sendPlayerMessageFromPlayer" || action === "sendPlayerMessageAsPlayer") {
      const message = await sendPlayerMessageFromPlayer({ guildId: guild.id, query: req.query });
      return res.json({ ...message, guild: guild.slug });
    }

    if (action === "getPlayerMessages") {
      const messages = await getPlayerMessages({ guildId: guild.id, query: req.query });
      return res.json({ ...messages, guild: guild.slug });
    }

    if (action === "getPlayerSentMessages") {
      const messages = await getPlayerSentMessages({ guildId: guild.id, query: req.query });
      return res.json({ ...messages, guild: guild.slug });
    }

    if (action === "guildGetSentPlayerMessages") {
      const messages = await getGuildSentMessages({ guildId: guild.id, query: req.query });
      return res.json({ ...messages, guild: guild.slug });
    }

    if (action === "guildGetWorldbuffs" || action === "getPublicWorldbuffs") {
      const buffs = await getWorldbuffs({ guildId: guild.id, query: req.query });
      return res.json({ ...buffs, guild: guild.slug });
    }

    if (action === "guildQueueWorldbuffBackup") {
      const queued = await queueWorldbuffBackup({ guildId: guild.id, query: req.query });
      return res.json({ ...queued, guild: guild.slug });
    }

    if (action === "guildGetHordenbuffs" || action === "getPublicHordenbuffs") {
      const buffs = await getHordenbuffs({ guildId: guild.id, query: req.query });
      return res.json({ ...buffs, guild: guild.slug });
    }

    if (action === "getPlayerWorldbuffs") {
      const buffs = await getPlayerWorldbuffs({ guildId: guild.id, query: req.query });
      return res.json({ ...buffs, guild: guild.slug });
    }

    if (action === "claimPlayerWorldbuff") {
      const saved = await claimPlayerWorldbuff({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "movePlayerWorldbuff") {
      const moved = await movePlayerWorldbuff({ guildId: guild.id, query: req.query });
      return res.json({ ...moved, guild: guild.slug });
    }
    if (action === "cancelPlayerWorldbuff") {
      const cancelled = await cancelPlayerWorldbuff({ guildId: guild.id, query: req.query });
      return res.json({ ...cancelled, guild: guild.slug });
    }

    if (action === "guildDeleteWorldbuffTerm") {
      const deleted = await deleteWorldbuffTerm({ guildId: guild.id, query: req.query });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "guildRestoreDeletedWorldbuffTerms") {
      requireMasterOrQueueToken(req.query);
      return res.json({ success: true, guild: guild.slug, restored: 0, skipped: 0 });
    }

    if (action === "lichtbotGetQueue") {
      const queue = await getBotQueue({ guildId: guild.id, query: req.query });
      return res.json({ ...queue, guild: guild.slug });
    }

    if (action === "markPlayerMessageRead") {
      const message = await markPlayerMessageRead({ guildId: guild.id, query: req.query });
      return res.json({ ...message, guild: guild.slug });
    }

    if (action === "deletePlayerMessage") {
      const deleted = await deletePlayerMessage({ guildId: guild.id, query: req.query });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "guildDeletePlayerMessage") {
      const deleted = await deleteGuildPlayerMessage({ guildId: guild.id, query: req.query });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "createRaid") {
      const writeGuild = await requireGuild(requireExplicitGuildSlug(req.query.guild));
      const created = await createRaid({ guildId: writeGuild.id, query: req.query });
      return res.json({ ...created, guild: writeGuild.slug });
    }

    if (action === "lichtbotCreateRaid") {
      const writeGuild = await requireGuild(requireExplicitGuildSlug(req.query.guild));
      const created = await createRaidForBot({ guildId: writeGuild.id, query: req.query });
      return res.json({ ...created, guild: writeGuild.slug });
    }

    if (action === "createRandomRaid") {
      const writeGuild = await requireGuild(requireExplicitGuildSlug(req.query.guild));
      const created = await createRandomRaid({ guildId: writeGuild.id, query: req.query });
      return res.json({ ...created, guild: writeGuild.slug });
    }

    if (action === "saveRaidSignup") {
      const saved = await saveRaidSignup({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "deleteRaidSignup") {
      const deleted = await deleteRaidSignup({ guildId: guild.id, query: req.query });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "guildUpdateRaidHelperSignup") {
      const saved = await adminUpdateRaidHelperSignup({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "saveDiscordSignupRows") {
      const saved = await saveDiscordSignupRows({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildSaveRaidHelperTemplate") {
      const saved = await saveRaidHelperTemplate({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildDeleteRaidHelperTemplate") {
      const deleted = await deleteRaidHelperTemplate({ guildId: guild.id, query: req.query });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "guildSaveRaidHelperSchedule") {
      const saved = await saveRaidHelperSchedule({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildDeleteRaidHelperSchedule") {
      const deleted = await deleteRaidHelperSchedule({ guildId: guild.id, query: req.query });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "guildProcessRaidHelperSchedules") {
      requireMasterCode(req.query.masterCode);
      const processed = await processRaidHelperSchedules({ guildId: guild.id, force: clean(req.query.force).toLowerCase() === "true" });
      return res.json({ success: true, processed, guild: guild.slug });
    }

    if (action === "guildImportRaidHelperHistory") {
      const imported = await importRaidHelperHistory({ guildId: guild.id, query: req.query });
      return res.json({ ...imported, guild: guild.slug });
    }

    if (action === "guildDeleteRaid" || action === "deleteRaid") {
      const deleted = await deleteRaid({ guildId: guild.id, query: req.query });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "getPublishedPrios") {
      const prios = await getPublishedPrios({ guildId: guild.id, query: req.query });
      return res.json({ ...prios, guild: guild.slug });
    }

    if (action === "getPublicPrioCharacters") {
      const characters = await getPublicPrioCharacters({ guildId: guild.id });
      return res.json({ ...characters, guild: guild.slug });
    }

    if (action === "lichtbotGetP0SignupContext" || action === "getP0DiscordSignupContext") {
      const context = await getP0DiscordSignupContext({ guildId: guild.id, query: req.query });
      return res.json({ ...context, guild: guild.slug });
    }

    if (action === "getP0DiscordSignups" || action === "guildGetP0DiscordSignups") {
      const list = await getP0DiscordSignupList({ guildId: guild.id, query: req.query });
      return res.json({ ...list, guild: guild.slug });
    }

    if (action === "getPoPostEntries" || action === "guildGetPoPostEntries" || action === "lichtbotGetPoPostEntries") {
      const list = await getPoPostEntries({ guildId: guild.id, query: req.query });
      return res.json({ ...list, guild: guild.slug });
    }

    if (action === "guildGetCharacterPoReleases" || action === "getCharacterPoReleases") {
      const list = await getCharacterPoReleases({ guildId: guild.id, query: req.query });
      return res.json({ ...list, guild: guild.slug });
    }

    if (action === "getMyPoReleaseRequests") {
      const list = await getPoReleaseRequests({ guildId: guild.id, query: req.query });
      return res.json({ ...list, guild: guild.slug });
    }
    if (action === "guildGetPoReleaseRequests") {
      const list = await getPoReleaseRequests({ guildId: guild.id, query: req.query, management: true });
      return res.json({ ...list, guild: guild.slug });
    }
    if (action === "submitPoReleaseRequest") {
      const saved = await submitPoReleaseRequest({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }
    if (action === "guildReviewPoReleaseRequest") {
      const saved = await reviewPoReleaseRequest({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }
    if (action === "guildDeletePoReleaseRequest") {
      const deleted = await deletePoReleaseRequest({ guildId: guild.id, query: req.query });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "guildSetCharacterPoRelease" || action === "setCharacterPoRelease") {
      const saved = await setCharacterPoRelease({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }
    if(action === "guildSendPoReleaseGrantedDm"){
      const sent=await sendPoReleaseGrantedDm({guildId:guild.id,query:req.query});
      return res.json({...sent,guild:guild.slug});
    }

    if (action === "guildSetCharacterRecruitStatusLift") {
      const saved = await setCharacterRecruitStatusLift({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildImportCharacterPoReleases" || action === "importCharacterPoReleases") {
      const imported = await importCharacterPoReleases({ guildId: guild.id, query: req.query });
      return res.json({ ...imported, guild: guild.slug });
    }

    if (action === "lichtbotCheckPoRelease" || action === "checkCharacterPoRelease") {
      const checked = await checkCharacterPoRelease({ guildId: guild.id, query: req.query });
      return res.json({ ...checked, guild: guild.slug });
    }

    if (action === "lichtbotGetPoPostApprovals" || action === "getPoPostApprovals") {
      const list = await getPoPostApprovals({ guildId: guild.id, query: req.query });
      return res.json({ ...list, guild: guild.slug });
    }

    if (action === "lichtbotCanReviewPoPost" || action === "canReviewPoPost") {
      const permission = await canReviewPoPost({ guildId: guild.id, query: req.query });
      return res.json({ ...permission, guild: guild.slug });
    }

    if (action === "lichtbotResolvePoPostPlayers" || action === "resolvePoPostPlayers") {
      const resolved = await resolvePoPostPlayers({ guildId: guild.id, query: req.query });
      return res.json({ ...resolved, guild: guild.slug });
    }

    if (action === "getPrioCheck") {
      const check = await getPrioCheck({ guildId: guild.id, query: req.query });
      return res.json({ ...check, guild: guild.slug });
    }

    if (action === "getCharacterGearFromWCL") {
      const gear = await getCharacterGearFromWCL({ query: req.query });
      return res.json({ ...gear, guild: guild.slug });
    }

    if (action === "findRaidByPrioPin") {
      const raid = await findRaidByPrioPin({ guildId: guild.id, query: req.query });
      return res.json({ ...raid, guild: guild.slug });
    }

    if (action === "validateLeadPin") {
      const raid = await validateLeadPin({ guildId: guild.id, query: req.query });
      return res.json({ ...raid, guild: guild.slug });
    }

    if (action === "queueRaidleadBossTokenNotice") {
      const queued = await queueRaidleadBossTokenNotice({ guildId: guild.id, query: req.query });
      return res.json({ ...queued, guild: guild.slug });
    }

    if (action === "savePrio") {
      const saved = await savePrio({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildSavePrio" || action === "raidleadSavePrio") {
      const saved = await savePrioAsRaidlead({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "lichtbotSavePoSignupPrio") {
      const saved = await savePoSignupPrioFromBot({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildSyncPoSignupPrios") {
      const synced = await syncPoSignupPrios({ guildId: guild.id, query: req.query });
      return res.json({ ...synced, guild: guild.slug });
    }

    if (action === "deletePrio" || action === "deletePlayerPrio") {
      const deleted = await deletePrio({ guildId: guild.id, query: req.query });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "guildDeletePrio" || action === "deleteGuildPrio") {
      const deleted = await deleteGuildPrio({ guildId: guild.id, query: req.query });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "guildSetRaidStatus" || action === "setRaidStatus") {
      const saved = await setRaidStatus({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "setP0PlusOverride") {
      const saved = await setP0PlusOverride({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildSetPrioBench") {
      const saved = await setPrioBench({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "lichtbotSaveP0Signup" || action === "saveP0DiscordSignup") {
      const saved = await saveP0DiscordSignup({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "lichtbotReviewP0Signup" || action === "reviewP0DiscordSignup") {
      const reviewed = await reviewP0DiscordSignup({ guildId: guild.id, query: req.query });
      return res.json({ ...reviewed, guild: guild.slug });
    }

    if (action === "lichtbotSavePoPostEntries" || action === "savePoPostEntries") {
      const saved = await savePoPostEntries({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "lichtbotSetPoPostMessage" || action === "setPoPostMessage") {
      const saved = await setPoPostDiscordMessage({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "reviewPoPostEntry" || action === "guildReviewPoPostEntry") {
      const reviewed = await reviewPoPostEntry({ guildId: guild.id, query: req.query });
      return res.json({ ...reviewed, guild: guild.slug });
    }

    if (action === "updatePoPostEntry" || action === "guildUpdatePoPostEntry") {
      const updated = await updatePoPostEntry({ guildId: guild.id, query: req.query });
      return res.json({ ...updated, guild: guild.slug });
    }

    if (action === "lichtbotDeletePoPostEntry" || action === "deletePoPostEntry") {
      const deleted = await deletePoPostEntry({ guildId: guild.id, query: req.query });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "lichtbotSetPoPostLuck" || action === "setPoPostEntryLuck") {
      const saved = await setPoPostEntryLuck({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildDeletePoPost" || action === "lichtbotDeletePoPost" || action === "deletePoPost") {
      const deleted = await deletePoPost({ guildId: guild.id, query: req.query });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "guildRestorePoPost" || action === "lichtbotRestorePoPost" || action === "restorePoPost") {
      const restored = await restorePoPost({ guildId: guild.id, query: req.query });
      return res.json({ ...restored, guild: guild.slug });
    }

    if (action === "lichtbotSavePoPostEntry" || action === "savePoPostEntry") {
      const saved = await savePoPostEntry({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "getP0Plus") {
      const points = await getP0Plus(guild.id, req.query);
      return res.json({ ...points, guild: guild.slug });
    }

    if (action === "getP0ReleaseList") {
      const releases = await getP0ReleaseList(guild.id);
      return res.json({ ...releases, guild: guild.slug });
    }

    if (action === "getRaidP0PlusAudit") {
      const audit = await getRaidP0PlusAudit({ guildId: guild.id, query: req.query });
      return res.json({ ...audit, guild: guild.slug });
    }

    if (action === "guildSetP0PlusPoints") {
      const saved = await setP0PlusPoints({ guildId: guild.id, query: req.query });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildQueueP0PlusBackup") {
      const queued = await queueManualP0PlusBackup({ guildId: guild.id, query: req.query });
      return res.json({ ...queued, guild: guild.slug });
    }

    if (action === "clearP0PlusForPlayer") {
      requireRaidleadP0MasterCodeForGuild(guild, req.query.masterCode);
      const cleared = await clearP0PlusForPlayer({ guildId: guild.id, query: req.query });
      return res.json({ ...cleared, guild: guild.slug });
    }

    if (action === "resetRaidP0PlusTransfer") {
      const reset = await resetRaidP0PlusTransfer({ guildId: guild.id, query: req.query });
      return res.json({ ...reset, guild: guild.slug });
    }

    if (action === "transferP0PlusPoints") {
      requireRaidleadP0MasterCodeForGuild(guild, req.query.masterCode);
      const transferred = await transferP0PlusPoints({ guildId: guild.id, query: req.query });
      return res.json({ ...transferred, guild: guild.slug });
    }

    if (action === "getPlayerPin") {
      const character = await findCharacter(guild.id, req.query.char, req.query.server);
      return res.json({
        success: true,
        exists: Boolean(character),
        className: character?.class_name || "",
        char: character?.name || "",
        server: character?.server || ""
      });
    }

    if (action === "createPlayerPin") {
      const result = await createPlayerWithCharacter({
        guildId: guild.id,
        playerPin: req.query.customPin,
        securityQuestion: req.query.securityQuestion,
        securityAnswer: req.query.securityAnswer,
        charName: req.query.char,
        server: req.query.server,
        className: req.query.className
      });
      if (normalizePlayerApprovalStatus(result.player.approval_status) !== "approved") {
        const notificationTargets=await notificationTargetsForPermissions(guild.id,"notify_player_logins");
        const notificationRoleIds=notificationTargets.filter(target=>target.type==="role").map(target=>target.value);
        const notificationNames=notificationTargets.filter(target=>target.type==="name").map(target=>target.value);
        const messageTemplate=await notificationMessageTemplate(guild.id,"notify_player_logins").catch(()=>"");
        await enqueueBotUpdate({
          guildId: guild.id,
          type: "player_login_approval_notice",
          payload: {
            guildSlug: guild.slug,
            guildName: guild.name || guild.guild_name || guild.slug,
            playerPin: result.player.player_pin,
            character: result.character?.name || clean(req.query.char),
            server: result.character?.server || clean(req.query.server),
            className: result.character?.className || result.character?.class_name || clean(req.query.className),
            notificationRoleIds,
            notificationNames,
            messageTemplate,
            createdAt: result.player.created_at || new Date().toISOString()
          }
        }).catch(error => {
          console.warn("SpielerLogin-Freigabehinweis konnte nicht queued werden:", error.message || error);
        });
      }
      return res.json({
        success: true,
        guild: guild.slug,
        pin: result.player.player_pin,
        character: result.character,
        approvalStatus: normalizePlayerApprovalStatus(result.player.approval_status),
        needsApproval: normalizePlayerApprovalStatus(result.player.approval_status) !== "approved"
      });
    }

    if (action === "addTwink") {
      const character = await addCharacterToPlayer({
        guildId: guild.id,
        pin: req.query.pin,
        charName: req.query.char,
        server: req.query.server,
        className: req.query.className
      });
      return res.json({ success: true, guild: guild.slug, character });
    }

    if (action === "deleteTwink" || action === "deleteCharacter") {
      const deleted = await deleteCharacterFromPlayer({
        guildId: guild.id,
        pin: req.query.pin,
        charName: req.query.char,
        server: req.query.server
      });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "setMainCharacter") {
      const character = await setMainCharacter({
        guildId: guild.id,
        pin: req.query.pin,
        charName: req.query.char,
        server: req.query.server
      });
      return res.json({ success: true, guild: guild.slug, character });
    }

    if (action === "resetPlayerPin") {
      const pin = await resetPlayerPin({
        guildId: guild.id,
        charName: req.query.char,
        server: req.query.server,
        oldPin: req.query.oldPin,
        newPin: req.query.customPin,
        className: req.query.className
      });
      return res.json({ success: true, guild: guild.slug, pin });
    }

    if (action === "resetPlayerPinBySecurity") {
      const pin = await resetPlayerPinBySecurity({
        guildId: guild.id,
        charName: req.query.char,
        server: req.query.server,
        securityQuestion: req.query.securityQuestion,
        securityAnswer: req.query.securityAnswer,
        newPin: req.query.customPin
      });
      return res.json({ success: true, guild: guild.slug, pin });
    }

    return res.status(404).json({ success: false, error: `Unsupported action: ${action}` });
  } catch (error) {
    next(error);
  }
});

app.post("/api/combat-log/import", async (req, res, next) => {
  try {
    const guild = await requireGuild(resolveGuildSlug(req.query.guild));
    const imported = await importCombatLogAnalysis({
      guildId: guild.id,
      query: req.query,
      text: req.body
    });
    return res.json({ ...imported, guild: guild.slug });
  } catch (error) {
    next(error);
  }
});

app.post("/api/apps-script", async (req, res, next) => {
  try {
    const action = clean(req.body?.action || req.query?.action);

    if (action === "updateGuildConfig") {
      const saved = await updateGuildConfig({ query: req.query, body: req.body });
      return res.json(saved);
    }

    if (action === "resolveGuildByPin") {
      const resolved = await resolveGuildByPin({ query: req.query, body: req.body });
      return res.json(resolved);
    }

    if (action === "submitGuildApplication") {
      const saved = await submitGuildApplication({ query: req.query, body: req.body });
      return res.json(saved);
    }

    if (action === "guildApproveApplication") {
      const approved = await approveGuildApplication({ query: req.query, body: req.body });
      return res.json(approved);
    }

    if (action === "guildRejectApplication") {
      const rejected = await rejectGuildApplication({ query: req.query, body: req.body });
      return res.json(rejected);
    }

    if (action === "completeGuildSetup") {
      const completed = await completeGuildSetup({ query: req.query, body: req.body });
      return res.json(completed);
    }

    const postParams = { ...(req.query || {}), ...(req.body || {}) };

    if (action === "lichtbotListGuilds") {
      const guilds = await listGuildsForBot({ query: postParams });
      return res.json(guilds);
    }

    if (action === "lichtbotGetQueueAllGuilds") {
      const queue = await getBotQueueAllGuilds({ query: postParams });
      return res.json(queue);
    }

    const guild = await requireGuild(requireExplicitGuildSlug(postParams.guild));
    await loadWorldbuffAccessCode(guild.id);
    await loadLootMasterAccessCode(guild.id);
    if (clean(postParams.masterCode)) {
      if (action === "transferP0PlusPoints" || action === "clearP0PlusForPlayer") requireRaidleadP0MasterCodeForGuild(guild, postParams.masterCode);
      else requireMasterCodeForGuild(guild, postParams.masterCode, action, postParams);
    }

    if (action === "lichtbotSaveDiscordChannels") {
      const saved = await saveDiscordBotChannels({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }
    if (action === "lichtbotSaveDiscordRoles") {
      const saved = await saveDiscordBotRoles({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }
    if (action === "lichtbotSaveDiscordMembers") {
      const saved = await saveDiscordBotMembers({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }
    if (action === "guildSetPoItem") {
      const saved = await setGuildPoItem({ guild, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildSetHordenbuffEntry" || action === "lichtbotSetHordenbuffEntry") {
      const saved = await setHordenbuffEntry({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildCreateBuffTerm" || action === "guildCreateWorldbuffTerm" || action === "lichtbotCreateWorldbuffTerm") {
      const target = clean(postParams.target).toLowerCase();
      const created = target === "worldbuff" || action === "guildCreateWorldbuffTerm" || action === "lichtbotCreateWorldbuffTerm"
        ? await createWorldbuffTerm({ guildId: guild.id, query: postParams })
        : await createHordenbuffTerm({ guildId: guild.id, query: postParams });
      return res.json({ ...created, guild: guild.slug });
    }

    if (action === "guildSetWorldbuffCaster" || action === "lichtbotSetWorldbuffCaster" || action === "lichtbotClaimWorldbuffSlot") {
      const saved = await setWorldbuffCaster({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "claimPlayerWorldbuff") {
      const saved = await claimPlayerWorldbuff({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "movePlayerWorldbuff") {
      const moved = await movePlayerWorldbuff({ guildId: guild.id, query: postParams });
      return res.json({ ...moved, guild: guild.slug });
    }
    if (action === "cancelPlayerWorldbuff") {
      const cancelled = await cancelPlayerWorldbuff({ guildId: guild.id, query: postParams });
      return res.json({ ...cancelled, guild: guild.slug });
    }

    if (action === "guildSetPlayerLoginRole") {
      const saved = await setPlayerLoginRole({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }
    if(action==="guildVerifyWorldbuffAccess") return res.json({success:true,scope:"manage_worldbuffs",guild:guild.slug});
    if(action==="guildSetWorldbuffAccessPassword"){
      const saved=await setWorldbuffAccessPassword({guildId:guild.id,query:postParams});return res.json({...saved,guild:guild.slug});
    }
    if(action==="guildSetLootMasterAccessPassword"){
      const saved=await setLootMasterAccessPassword({guildId:guild.id,query:postParams});return res.json({...saved,guild:guild.slug});
    }
    if (action === "guildSetPlayerLoginAccess") {
      const saved = await setPlayerLoginAccess({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }
    if(action==="guildSetNotificationSetting"){
      const saved=await setGuildNotificationSetting({guildId:guild.id,query:postParams});return res.json({...saved,guild:guild.slug});
    }
    if(action==="guildSetPoReleaseDisplaySettings"){
      const saved=await setPoReleaseDisplaySettings({guildId:guild.id,query:postParams});return res.json({...saved,guild:guild.slug});
    }
    if(action==="guildSetRaidLootMasterTargets"){
      const saved=await setRaidLootMasterTargets({guildId:guild.id,query:postParams});return res.json({...saved,guild:guild.slug});
    }

    if (action === "guildSetPlayerLoginBlocked") {
      const saved = await setPlayerLoginBlocked({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildApprovePlayerLogin" || action === "guildSetPlayerLoginApproved") {
      const saved = await setPlayerLoginApproved({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildDeletePlayerLogin") {
      const deleted = await deletePlayerLogin({ guildId: guild.id, query: postParams });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "createRaid") {
      const created = await createRaid({ guildId: guild.id, query: postParams });
      return res.json({ ...created, guild: guild.slug });
    }

    if (action === "lichtbotCreateRaid") {
      const created = await createRaidForBot({ guildId: guild.id, query: postParams });
      return res.json({ ...created, guild: guild.slug });
    }

    if (action === "createRandomRaid") {
      const created = await createRandomRaid({ guildId: guild.id, query: postParams });
      return res.json({ ...created, guild: guild.slug });
    }

    if (action === "getRaidHelper" || action === "getRaidSignups") {
      const helper = await getRaidHelper({ guildId: guild.id, query: postParams });
      return res.json({ ...helper, guild: guild.slug });
    }

    if (action === "lichtbotGetP0SignupContext" || action === "getP0DiscordSignupContext") {
      const context = await getP0DiscordSignupContext({ guildId: guild.id, query: postParams });
      return res.json({ ...context, guild: guild.slug });
    }

    if (action === "getP0DiscordSignups" || action === "guildGetP0DiscordSignups") {
      const list = await getP0DiscordSignupList({ guildId: guild.id, query: postParams });
      return res.json({ ...list, guild: guild.slug });
    }

    if (action === "getPoPostEntries" || action === "guildGetPoPostEntries" || action === "lichtbotGetPoPostEntries") {
      const list = await getPoPostEntries({ guildId: guild.id, query: postParams });
      return res.json({ ...list, guild: guild.slug });
    }

    if (action === "guildGetCharacterPoReleases" || action === "getCharacterPoReleases") {
      const list = await getCharacterPoReleases({ guildId: guild.id, query: postParams });
      return res.json({ ...list, guild: guild.slug });
    }

    if (action === "getMyPoReleaseRequests") {
      const list = await getPoReleaseRequests({ guildId: guild.id, query: postParams });
      return res.json({ ...list, guild: guild.slug });
    }
    if (action === "guildGetPoReleaseRequests") {
      const list = await getPoReleaseRequests({ guildId: guild.id, query: postParams, management: true });
      return res.json({ ...list, guild: guild.slug });
    }
    if (action === "submitPoReleaseRequest") {
      const saved = await submitPoReleaseRequest({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }
    if (action === "guildReviewPoReleaseRequest") {
      const saved = await reviewPoReleaseRequest({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }
    if (action === "guildDeletePoReleaseRequest") {
      const deleted = await deletePoReleaseRequest({ guildId: guild.id, query: postParams });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "guildSetCharacterPoRelease" || action === "setCharacterPoRelease") {
      const saved = await setCharacterPoRelease({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }
    if(action === "guildSendPoReleaseGrantedDm"){
      const sent=await sendPoReleaseGrantedDm({guildId:guild.id,query:postParams});
      return res.json({...sent,guild:guild.slug});
    }

    if (action === "guildSetCharacterRecruitStatusLift") {
      const saved = await setCharacterRecruitStatusLift({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildImportCharacterPoReleases" || action === "importCharacterPoReleases") {
      const imported = await importCharacterPoReleases({ guildId: guild.id, query: postParams });
      return res.json({ ...imported, guild: guild.slug });
    }

    if (action === "lichtbotCheckPoRelease" || action === "checkCharacterPoRelease") {
      const checked = await checkCharacterPoRelease({ guildId: guild.id, query: postParams });
      return res.json({ ...checked, guild: guild.slug });
    }

    if (action === "lichtbotGetPoPostApprovals" || action === "getPoPostApprovals") {
      const list = await getPoPostApprovals({ guildId: guild.id, query: postParams });
      return res.json({ ...list, guild: guild.slug });
    }

    if (action === "lichtbotCanReviewPoPost" || action === "canReviewPoPost") {
      const permission = await canReviewPoPost({ guildId: guild.id, query: postParams });
      return res.json({ ...permission, guild: guild.slug });
    }

    if (action === "lichtbotResolvePoPostPlayers" || action === "resolvePoPostPlayers") {
      const resolved = await resolvePoPostPlayers({ guildId: guild.id, query: postParams });
      return res.json({ ...resolved, guild: guild.slug });
    }

    if (action === "lichtbotSaveP0Signup" || action === "saveP0DiscordSignup") {
      const saved = await saveP0DiscordSignup({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "lichtbotReviewP0Signup" || action === "reviewP0DiscordSignup") {
      const reviewed = await reviewP0DiscordSignup({ guildId: guild.id, query: postParams });
      return res.json({ ...reviewed, guild: guild.slug });
    }

    if (action === "lichtbotSavePoPostEntries" || action === "savePoPostEntries") {
      const saved = await savePoPostEntries({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "lichtbotSetPoPostMessage" || action === "setPoPostMessage") {
      const saved = await setPoPostDiscordMessage({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "reviewPoPostEntry" || action === "guildReviewPoPostEntry") {
      const reviewed = await reviewPoPostEntry({ guildId: guild.id, query: postParams });
      return res.json({ ...reviewed, guild: guild.slug });
    }

    if (action === "updatePoPostEntry" || action === "guildUpdatePoPostEntry") {
      const updated = await updatePoPostEntry({ guildId: guild.id, query: postParams });
      return res.json({ ...updated, guild: guild.slug });
    }

    if (action === "lichtbotDeletePoPostEntry" || action === "deletePoPostEntry") {
      const deleted = await deletePoPostEntry({ guildId: guild.id, query: postParams });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "lichtbotSetPoPostLuck" || action === "setPoPostEntryLuck") {
      const saved = await setPoPostEntryLuck({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildDeletePoPost" || action === "lichtbotDeletePoPost" || action === "deletePoPost") {
      const deleted = await deletePoPost({ guildId: guild.id, query: postParams });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "guildRestorePoPost" || action === "lichtbotRestorePoPost" || action === "restorePoPost") {
      const restored = await restorePoPost({ guildId: guild.id, query: postParams });
      return res.json({ ...restored, guild: guild.slug });
    }

    if (action === "lichtbotSavePoPostEntry" || action === "savePoPostEntry") {
      const saved = await savePoPostEntry({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "lichtbotSavePoSignupPrio") {
      const saved = await savePoSignupPrioFromBot({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildSyncPoSignupPrios") {
      const synced = await syncPoSignupPrios({ guildId: guild.id, query: postParams });
      return res.json({ ...synced, guild: guild.slug });
    }

    if (action === "saveRaidSignup") {
      const saved = await saveRaidSignup({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "deleteRaidSignup") {
      const deleted = await deleteRaidSignup({ guildId: guild.id, query: postParams });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "guildUpdateRaidHelperSignup") {
      const saved = await adminUpdateRaidHelperSignup({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "saveDiscordSignupRows") {
      const saved = await saveDiscordSignupRows({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildSaveRaidHelperTemplate") {
      const saved = await saveRaidHelperTemplate({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildDeleteRaidHelperTemplate") {
      const deleted = await deleteRaidHelperTemplate({ guildId: guild.id, query: postParams });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "guildSaveRaidHelperSchedule") {
      const saved = await saveRaidHelperSchedule({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildDeleteRaidHelperSchedule") {
      const deleted = await deleteRaidHelperSchedule({ guildId: guild.id, query: postParams });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "guildProcessRaidHelperSchedules") {
      requireMasterCode(postParams.masterCode);
      const processed = await processRaidHelperSchedules({ guildId: guild.id, force: clean(postParams.force).toLowerCase() === "true" });
      return res.json({ success: true, processed, guild: guild.slug });
    }

    if (action === "guildImportRaidHelperHistory") {
      const imported = await importRaidHelperHistory({ guildId: guild.id, query: postParams });
      return res.json({ ...imported, guild: guild.slug });
    }

    if (action === "guildAdminCreateItem" || action === "guildAdminCreateltem") {
      const item = await adminCreateItem({ guildId: guild.id, query: postParams });
      return res.json({ ...item, guild: guild.slug });
    }

    if (action === "guildDeleteHordenbuffEntry" || action === "lichtbotDeleteHordenbuffEntry") {
      const deleted = await deleteHordenbuffEntry({ guildId: guild.id, query: postParams });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "guildDeleteWorldbuffTerm" || action === "lichtbotDeleteWorldbuffTerm") {
      const deleted = await deleteWorldbuffTerm({ guildId: guild.id, query: postParams });
      return res.json({ ...deleted, guild: guild.slug });
    }

    if (action === "guildSyncPublicBuffTerms" || action === "guildImportWorldbuffsFromSheets" || action === "lichtbotSyncWorldbuffTicker") {
      const imported = await importWorldbuffsFromSheets({ guildId: guild.id, query: postParams });
      return res.json({ ...imported, guild: guild.slug });
    }

    if (action === "guildRestoreDeletedWorldbuffTerms") {
      return res.json({ success: true, guild: guild.slug, restored: 0, skipped: 0 });
    }

    if (action === "guildRequestWorldbuffReplacement") {
      const targetChannelId = clean(
        postParams.targetChannelId
        || postParams.channelId
        || await getGuildLayoutValue(guild.id, "worldbuffReplacementChannelId")
      );
      const queued = await enqueueBotUpdate({
        guildId: guild.id,
        type: "worldbuff_replacement",
        payload: {
          guild: guild.slug,
          guildSlug: guild.slug,
          targetChannelId,
          channelId: targetChannelId,
          target: clean(postParams.target || "both"),
          buff: clean(postParams.buff),
          datum: clean(postParams.datum),
          uhrzeit: clean(postParams.uhrzeit),
          gilde: clean(postParams.gilde),
          charakter: clean(postParams.charakter),
          note: clean(postParams.note)
        }
      });
      return res.json({ ...queued, guild: guild.slug });
    }

    if (action === "guildQueueWorldbuffBotUpdate") {
      const queued = await queueBotUpdate({ guildId: guild.id, query: postParams });
      return res.json({ ...queued, guild: guild.slug });
    }

    if (action === "guildQueueWorldbuffBackup") {
      const queued = await queueWorldbuffBackup({ guildId: guild.id, query: postParams });
      return res.json({ ...queued, guild: guild.slug });
    }

    if (action === "guildQueueP0PlusBackup") {
      const queued = await queueManualP0PlusBackup({ guildId: guild.id, query: postParams });
      return res.json({ ...queued, guild: guild.slug });
    }

    if (action === "guildQueueRaidAnnouncement") {
      const queued = await queueRaidAnnouncement({ guildId: guild.id, query: postParams });
      return res.json({ ...queued, guild: guild.slug });
    }

    if (action === "guildQueueRaidAnnouncementNotice") {
      const queued = await queueRaidAnnouncementNotice({ guildId: guild.id, query: postParams });
      return res.json({ ...queued, guild: guild.slug });
    }

    if (action === "guildQueueRaidAnnouncementRefresh") {
      const queued = await queueRaidAnnouncementRefresh({ guildId: guild.id, query: postParams });
      return res.json({ ...queued, guild: guild.slug });
    }

    if (action === "guildQueuePoPost") {
      const queued = await queuePoPost({ guildId: guild.id, query: postParams });
      return res.json({ ...queued, guild: guild.slug });
    }

    if (action === "lichtbotSetRaidDiscordMessage") {
      const saved = await setRaidDiscordMessage({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildQueueLogAnalysisPost") {
      const queued = await queueLogAnalysisDiscordPost({ guildId: guild.id, query: postParams });
      return res.json({ ...queued, guild: guild.slug });
    }

    if (action === "lichtbotResolveQueue") {
      const resolved = await resolveBotQueue({ guildId: guild.id, query: postParams });
      return res.json({ ...resolved, guild: guild.slug });
    }

    if (action === "lichtbotClaimQueue") {
      const claimed = await claimBotQueue({ guildId: guild.id, query: postParams });
      return res.json({ ...claimed, guild: guild.slug });
    }

    if (action === "guildSaveLogAnalysis" || action === "lichtbotSaveLogAnalysis") {
      const saved = await saveLogAnalysis({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildRunLogAnalysis") {
      const started = await runLogAnalysis({ guildId: guild.id, query: postParams });
      return res.json({ ...started, guild: guild.slug });
    }

    if (action === "guildCompleteLogAnalysis" || action === "logAnalysisGeneratorCallback") {
      const completed = await completeExternalLogAnalysis({ guildId: guild.id, query: postParams });
      return res.json({ ...completed, guild: guild.slug });
    }

    if (action === "guildSetLogAnalysisSheetUrl") {
      const saved = await setLogAnalysisSheetUrl({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildSaveLogAnalysisSheetExport" || action === "saveLogAnalysisSheetExport") {
      const saved = await saveLogAnalysisSheetExport({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildImportLogAnalysisSheetExport") {
      const imported = await importLogAnalysisSheetExportFromUrl({ guildId: guild.id, query: postParams });
      return res.json({ ...imported, guild: guild.slug });
    }

    if (action === "setPublicLogAnalysisRaidRoles") {
      const saved = await setPublicLogAnalysisRaidRoles({ guildId: guild.id, query: postParams });
      return res.json({ ...saved, guild: guild.slug });
    }

    if (action === "guildCleanupIncompleteClaAnalyses") {
      const cleaned = await cleanupIncompleteClaAnalyses({ guildId: guild.id, query: postParams });
      return res.json({ ...cleaned, guild: guild.slug });
    }

    if (action === "guildCleanupIncompleteRpbAnalyses") {
      const cleaned = await cleanupIncompleteRpbAnalyses({ guildId: guild.id, query: postParams });
      return res.json({ ...cleaned, guild: guild.slug });
    }

    if (action === "guildResetLogAnalyses") {
      const reset = await resetLogAnalyses({ guildId: guild.id, query: postParams });
      return res.json({ ...reset, guild: guild.slug });
    }

    if (action === "guildClearLogAnalysisType") {
      const cleared = await clearLogAnalysisType({ guildId: guild.id, query: postParams });
      return res.json({ ...cleared, guild: guild.slug });
    }

    const error = new Error("Unbekannte POST-Aktion.");
    error.statusCode = 404;
    throw error;
  } catch (error) {
    next(error);
  }
});

app.get("/api/guilds/:guildSlug", async (req, res, next) => {
  try {
    const guild = await requireGuild(resolveGuildSlug(req.params.guildSlug));
    res.json({ success: true, guild });
  } catch (error) {
    next(error);
  }
});

app.get("/api/guilds/:guildSlug/characters", async (req, res, next) => {
  try {
    const guild = await requireGuild(resolveGuildSlug(req.params.guildSlug));
    const result = await query(
      `select c.id, c.name, c.server, c.class_name, c.created_at
       from characters c
       join players p on p.id = c.player_id
       where p.guild_id = $1
       order by c.name asc`,
      [guild.id]
    );
    res.json({ success: true, guild: guild.slug, characters: result.rows });
  } catch (error) {
    next(error);
  }
});

app.get("/api/guilds/:guildSlug/players/by-pin/:pin/characters", async (req, res, next) => {
  try {
    const guild = await requireGuild(resolveGuildSlug(req.params.guildSlug));
    await ensurePlayerRoleSchema();
    const result = await query(
      `select c.id, c.name, c.server, c.class_name, c.created_at
       from players p
       join characters c on c.player_id = p.id
       where p.guild_id = $1
         and p.player_pin = $2
         and coalesce(p.is_blocked, false) = false
         and p.approval_status = 'approved'
       order by c.name asc`,
      [guild.id, req.params.pin]
    );
    res.json({ success: true, guild: guild.slug, characters: result.rows });
  } catch (error) {
    next(error);
  }
});

app.post("/api/guilds/:guildSlug/players", async (req, res, next) => {
  const client = await pool.connect();
  try {
    const guild = await requireGuild(resolveGuildSlug(req.params.guildSlug));
    const { playerPin, securityQuestion, securityAnswer, character } = req.body || {};

    if (!playerPin || !character?.name || !character?.server || !character?.className) {
      return res.status(400).json({
        success: false,
        error: "playerPin, character.name, character.server and character.className are required"
      });
    }

    await client.query("begin");
    await ensurePlayerRoleSchema();
    const playerResult = await client.query(
      `insert into players (guild_id, player_pin, security_question, security_answer, approval_status)
       values ($1, $2, $3, $4, 'pending')
       returning id, player_pin, approval_status, created_at`,
      [guild.id, playerPin, securityQuestion || null, securityAnswer || null]
    );
    const player = playerResult.rows[0];
    const characterResult = await client.query(
      `insert into characters (player_id, name, server, class_name)
       values ($1, $2, $3, $4)
       returning id, name, server, class_name, created_at`,
      [player.id, character.name, character.server, character.className]
    );
    await client.query("commit");

    if (normalizePlayerApprovalStatus(player.approval_status) !== "approved") {
      const notificationTargets = await notificationTargetsForPermissions(guild.id, "notify_player_logins");
      const notificationRoleIds = notificationTargets
        .filter(target => target.type === "role")
        .map(target => target.value);
      const notificationNames = notificationTargets
        .filter(target => target.type === "name")
        .map(target => target.value);
      const messageTemplate = await notificationMessageTemplate(guild.id, "notify_player_logins").catch(() => "");
      await enqueueBotUpdate({
        guildId: guild.id,
        type: "player_login_approval_notice",
        payload: {
          guildSlug: guild.slug,
          guildName: guild.name || guild.guild_name || guild.slug,
          playerPin: player.player_pin,
          character: characterResult.rows[0]?.name || character.name,
          server: characterResult.rows[0]?.server || character.server,
          className: characterResult.rows[0]?.class_name || character.className,
          notificationRoleIds,
          notificationNames,
          messageTemplate,
          createdAt: player.created_at || new Date().toISOString()
        }
      }).catch(error => {
        console.warn("SpielerLogin-Freigabehinweis konnte nicht queued werden:", error.message || error);
      });
    }

    res.status(201).json({
      success: true,
      guild: guild.slug,
      player,
      character: characterResult.rows[0],
      approvalStatus: normalizePlayerApprovalStatus(player.approval_status),
      needsApproval: normalizePlayerApprovalStatus(player.approval_status) !== "approved"
    });
  } catch (error) {
    await client.query("rollback").catch(() => {});
    next(error);
  } finally {
    client.release();
  }
});

app.use((req, res) => {
  res.status(404).json({ success: false, error: "Route not found" });
});

app.use((error, req, res, next) => {
  console.error(error);
  res.status(error.statusCode || 500).json({
    success: false,
    error: error.message || "Internal server error"
  });
});

async function runRequestedArieeJuksiPrioCleanupOnce() {
  const actionKey = "manual-prio-cleanup-2026-08-04-ariee-juksi-naxx-zg";
  const client = await pool.connect();
  try {
    await client.query("begin");
    await client.query(
      `create table if not exists maintenance_actions (
         action_key text primary key,
         completed_at timestamptz not null default now()
       )`
    );
    const marker = await client.query(
      "select 1 from maintenance_actions where action_key = $1 for update",
      [actionKey]
    );
    if (marker.rows.length) {
      await client.query("commit");
      return { skipped: true, deleted: 0, entries: [] };
    }
    const deleted = await client.query(
      `delete from prios pr
       using raids r, characters c, players p, guilds g
       where pr.raid_id = r.id
         and pr.character_id = c.id
         and c.player_id = p.id
         and p.guild_id = g.id
         and r.guild_id = g.id
         and lower(g.slug) = 'nachtloot'
         and upper(r.raid_pin) in ('QLU', 'MYU')
         and lower(c.name) in ('ariee', 'juksi')
       returning pr.id, c.name, c.server, r.raid_type, r.raid_pin`
    );
    await client.query(
      "insert into maintenance_actions(action_key) values($1)",
      [actionKey]
    );
    await client.query("commit");
    return { skipped: false, deleted: deleted.rowCount, entries: deleted.rows };
  } catch (error) {
    await client.query("rollback").catch(() => {});
    throw error;
  } finally {
    client.release();
  }
}

app.listen(port, () => {
  console.log(`LichtLoot API listening on port ${port}`);
  runRequestedArieeJuksiPrioCleanupOnce()
    .then(result => console.log(`Manuelle Prio-Bereinigung Ariee/Juksi: ${result.deleted || 0} gelöscht`, result.entries || []))
    .catch(error => console.warn("Manuelle Prio-Bereinigung Ariee/Juksi fehlgeschlagen:", error.message || error));
  applyOnyLootMetadataBackfillOnce()
    .then(result => console.log(`Ony-Lootmetadaten geprüft: ${result.updated || 0}/${result.checked || 0} aktualisiert`))
    .catch(error => console.warn("Ony-Lootmetadaten konnten nicht korrigiert werden:", error.message || error));
  applyMcCoreFelclothBagPatternCorrectionOnce()
    .then(result => console.log(`MC-Kernteufelsstofftasche geprüft: ${result.updated || 0} aktualisiert`))
    .catch(error => console.warn("MC-Kernteufelsstofftasche konnte nicht korrigiert werden:", error.message || error));
});
