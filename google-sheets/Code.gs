/**
 * Roblox Config Pipeline
 * Google Sheets -> GitHub (single atomic commit)
 *
 * Sheet names expected by this script are supplied in Roblox_Config_Pipeline.xlsx.
 * Store the GitHub token in Script Properties, never in a cell.
 */

const GITHUB_API_VERSION = '2026-03-10';

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('⚙️ Configs')
    .addItem('Validate all', 'validateAll')
    .addItem('Preview JSON', 'previewAll')
    .addSeparator()
    .addItem('Push all to GitHub', 'pushAllToGit')
    .addSeparator()
    .addItem('Set GitHub token', 'setGitHubToken')
    .addItem('Clear GitHub token', 'clearGitHubToken')
    .addToUi();
}

function setGitHubToken() {
  const ui = SpreadsheetApp.getUi();
  const r = ui.prompt(
    'GitHub token',
    'Paste a fine-grained PAT with Contents: Read and write for this repository. It will be stored in Apps Script Properties, not in the sheet.',
    ui.ButtonSet.OK_CANCEL
  );
  if (r.getSelectedButton() !== ui.Button.OK) return;
  const token = r.getResponseText().trim();
  if (!token) throw new Error('Empty token.');
  PropertiesService.getScriptProperties().setProperty('GITHUB_TOKEN', token);
  ui.alert('GitHub token saved in Script Properties.');
}

function clearGitHubToken() {
  PropertiesService.getScriptProperties().deleteProperty('GITHUB_TOKEN');
  SpreadsheetApp.getUi().alert('GitHub token removed.');
}

function validateAll() {
  const result = validateOrThrow_();
  SpreadsheetApp.getUi().alert(`Validation OK. ${result.configCount} configs, ${result.totalBytes} JSON bytes.`);
}

function previewAll() {
  const validation = validateOrThrow_();
  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName('_JSON_PREVIEW');
  if (!sh) sh = ss.insertSheet('_JSON_PREVIEW');
  sh.clear();
  sh.getRange(1, 1, 1, 5).setValues([['configName', 'outputFile', 'bytes', 'robloxKey', 'json']]);
  sh.getRange(1, 1, 1, 5).setFontWeight('bold').setBackground('#5B35D5').setFontColor('#FFFFFF');

  const settings = getControlSettings_();
  const manifest = getManifest_().filter(x => x.enabled);
  const configs = buildAllConfigs_();
  const rows = manifest.map(m => {
    const json = JSON.stringify(configs[m.configName], null, 2) + '\n';
    return [
      m.configName,
      m.outputFile,
      Utilities.newBlob(json).getBytes().length,
      replacePlaceId_(m.robloxEntryKey, settings.placeId),
      json,
    ];
  });
  if (rows.length) sh.getRange(2, 1, rows.length, 5).setValues(rows);
  sh.setFrozenRows(1);
  sh.autoResizeColumns(1, 4);
  sh.setColumnWidth(5, 700);
  sh.getRange(2, 5, Math.max(rows.length, 1), 1).setWrap(true);
  SpreadsheetApp.getUi().alert(`Preview generated. ${validation.configCount} configs.`);
}

function pushAllToGit() {
  const ui = SpreadsheetApp.getUi();
  const validation = validateOrThrow_();
  const settings = getControlSettings_();
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('GITHUB_TOKEN is not set. Use ⚙️ Configs -> Set GitHub token.');

  const owner = settings.githubOwner;
  const repo = settings.githubRepo;
  const branch = settings.githubBranch;
  if (!owner || !repo || !branch || owner.startsWith('YOUR_') || repo.startsWith('YOUR_')) {
    throw new Error('Fill GitHub owner/repo/branch on _CONTROL first.');
  }

  const manifest = getManifest_().filter(x => x.enabled);
  const configs = buildAllConfigs_();

  // 1) Read current branch head and tree.
  const branchRef = githubRequest_(
    `/repos/${enc_(owner)}/${enc_(repo)}/git/ref/heads/${enc_(branch)}`,
    'get', null, token
  );
  const baseCommitSha = branchRef.object.sha;
  const baseCommit = githubRequest_(
    `/repos/${enc_(owner)}/${enc_(repo)}/git/commits/${baseCommitSha}`,
    'get', null, token
  );
  const baseTreeSha = baseCommit.tree.sha;

  // 2) Create one blob per generated JSON.
  const treeEntries = manifest.map(m => {
    const json = JSON.stringify(configs[m.configName], null, 2) + '\n';
    const blob = githubRequest_(
      `/repos/${enc_(owner)}/${enc_(repo)}/git/blobs`,
      'post', { content: json, encoding: 'utf-8' }, token
    );
    return { path: m.gitPath, mode: '100644', type: 'blob', sha: blob.sha };
  });

  // 3) New tree based on current branch tree, then one commit and one ref update.
  const newTree = githubRequest_(
    `/repos/${enc_(owner)}/${enc_(repo)}/git/trees`,
    'post', { base_tree: baseTreeSha, tree: treeEntries }, token
  );

  if (newTree.sha === baseTreeSha) {
    appendLog_('PUSH_GIT', baseCommitSha, manifest.length, 'NO_CHANGES', 'Generated configs are identical to GitHub.');
    ui.alert('No changes: GitHub already has the same configs.');
    return;
  }

  const now = Utilities.formatDate(new Date(), Session.getScriptTimeZone() || 'Etc/UTC', 'yyyy-MM-dd HH:mm:ss');
  const commit = githubRequest_(
    `/repos/${enc_(owner)}/${enc_(repo)}/git/commits`,
    'post',
    {
      message: `configs: update from Google Sheets (${now})`,
      tree: newTree.sha,
      parents: [baseCommitSha],
    },
    token
  );

  githubRequest_(
    `/repos/${enc_(owner)}/${enc_(repo)}/git/refs/heads/${enc_(branch)}`,
    'patch', { sha: commit.sha, force: false }, token
  );

  appendLog_('PUSH_GIT', commit.sha, manifest.length, 'OK', `${validation.totalBytes} JSON bytes`);
  ui.alert(`Pushed ${manifest.length} configs in one commit.\n${commit.sha}`);
}

function validateOrThrow_() {
  const configs = buildAllConfigs_();
  const manifest = getManifest_().filter(x => x.enabled);
  const settings = getControlSettings_();

  // Basic uniqueness.
  assertUnique_(configs.Arenas.map(x => String(x.id)), 'Arenas.id');
  assertUnique_(configs.Pets.map(x => x.id), 'Pets.id');
  assertUnique_(configs.Pickaxes.map(x => x.modelName), 'Pickaxes.modelName');
  assertUnique_(configs.Rooms.rooms.map(x => String(x.index)), 'Rooms.index');
  assertUnique_(configs.SellItems.items.map(x => x.id), 'SellItems.id');
  assertUnique_(configs.Upgrades.map(x => x.id), 'Upgrades.id');

  // RoomDrops: exactly 100 total weight per room and every item must exist in SellItems.
  const sellIds = new Set(configs.SellItems.items.map(x => x.id));
  configs.RoomDrops.forEach(room => {
    const total = room.drops.reduce((s, d) => s + Number(d.weight), 0);
    if (Math.abs(total - 100) > 1e-9) {
      throw new Error(`RoomDrops room ${room.index}: weight sum is ${total}, expected 100.`);
    }
    room.drops.forEach(d => {
      if (!sellIds.has(d.itemId)) throw new Error(`RoomDrops room ${room.index}: ${d.itemId} missing in SellItems.`);
    });
  });

  // Upgrades: number of prices must match maxLevel.
  configs.Upgrades.forEach(u => {
    if (u.prices.length !== Number(u.maxLevel)) {
      throw new Error(`Upgrades ${u.id}: ${u.prices.length} prices, maxLevel=${u.maxLevel}.`);
    }
  });

  let totalBytes = 0;
  manifest.forEach(m => {
    if (!(m.configName in configs)) throw new Error(`Manifest references unknown config ${m.configName}.`);
    const json = JSON.stringify(configs[m.configName]);
    const bytes = Utilities.newBlob(json).getBytes().length;
    totalBytes += bytes;
    if (bytes > 4_000_000) throw new Error(`${m.configName} is too large for one Roblox DataStore entry: ${bytes} bytes.`);

    if (settings.placeId && !String(settings.placeId).startsWith('YOUR_')) {
      const key = replacePlaceId_(m.robloxEntryKey, settings.placeId);
      if (key.length > 50) throw new Error(`Roblox key is longer than 50 characters: ${key}`);
    }
  });

  return { configCount: manifest.length, totalBytes };
}

function buildAllConfigs_() {
  return {
    Arenas: buildArenas_(),
    Pets: buildPets_(),
    Pickaxes: buildPickaxes_(),
    Rebirth: buildRebirth_(),
    RoomDrops: buildRoomDrops_(),
    Rooms: buildRooms_(),
    SellItems: buildSellItems_(),
    Upgrades: buildUpgrades_(),
  };
}

function buildArenas_() {
  return rowsAsObjects_('Arenas').map(r => {
    const o = { id: number_(r.id), multiplier: number_(r.multiplier) };
    if (!blank_(r.requiredRebirths)) o.requiredRebirths = number_(r.requiredRebirths);
    return o;
  });
}

function buildPets_() {
  return rowsAsObjects_('Pets').map(r => ({
    id: text_(r.id), currencyPrice: number_(r.currencyPrice), power: number_(r.power),
  }));
}

function buildPickaxes_() {
  return rowsAsObjects_('Pickaxes').map(r => ({
    modelName: text_(r.modelName), currencyPrice: number_(r.currencyPrice), power: number_(r.power),
  }));
}

function buildRebirth_() {
  const firstRequirements = rowsAsObjects_('Rebirth_FirstReq')
    .sort((a, b) => number_(a.index) - number_(b.index))
    .map(r => number_(r.requirement));
  const growth = rowsAsObjects_('Rebirth_Growth')
    .sort((a, b) => number_(a.order) - number_(b.order))
    .map(r => ({ upTo: number_(r.upTo), multiplier: number_(r.multiplier) }));
  const settings = keyValueSheet_('Rebirth_Settings');
  return {
    firstRequirements,
    growth,
    strengthPerRebirth: number_(settings.strengthPerRebirth),
    cashPerRebirth: number_(settings.cashPerRebirth),
  };
}

function buildRoomDrops_() {
  const rows = rowsAsObjects_('RoomDrops')
    .sort((a, b) => number_(a.roomIndex) - number_(b.roomIndex) || number_(a.dropOrder) - number_(b.dropOrder));
  const grouped = new Map();
  rows.forEach(r => {
    const index = number_(r.roomIndex);
    if (!grouped.has(index)) grouped.set(index, []);
    grouped.get(index).push({ itemId: text_(r.itemId), weight: number_(r.weight) });
  });
  return Array.from(grouped.entries()).map(([index, drops]) => ({ index, drops }));
}

function buildRooms_() {
  const rooms = rowsAsObjects_('Rooms').map(r => ({
    index: number_(r.index),
    blockMaxHP: number_(r.blockMaxHP_text),
    roomLengthCells: number_(r.roomLengthCells),
    barrierLayers: number_(r.barrierLayers),
  }));
  const b = keyValueSheet_('Rooms_Beyond');
  return {
    rooms,
    beyondLastRoom: {
      blockMaxHP: number_(b.blockMaxHP),
      roomLengthCells: number_(b.roomLengthCells),
      barrierLayers: number_(b.barrierLayers),
      hpMultiplier: number_(b.hpMultiplier),
      hpGrowthEveryStages: number_(b.hpGrowthEveryStages),
      maxBlockHP: number_(b.maxBlockHP),
    },
  };
}

function buildSellItems_() {
  const s = keyValueSheet_('SellSettings');
  return {
    settings: {
      minimumItemsPerRoom: number_(s.minimumItemsPerRoom),
      maximumItemsPerRoom: number_(s.maximumItemsPerRoom),
    },
    items: rowsAsObjects_('SellItems').map(r => ({ id: text_(r.id), sellPrice: number_(r.sellPrice) })),
  };
}

function buildUpgrades_() {
  const priceRows = rowsAsObjects_('UpgradePrices')
    .sort((a, b) => text_(a.upgradeId).localeCompare(text_(b.upgradeId)) || number_(a.level) - number_(b.level));
  const prices = new Map();
  priceRows.forEach(r => {
    const id = text_(r.upgradeId);
    if (!prices.has(id)) prices.set(id, []);
    prices.get(id).push(number_(r.price));
  });
  return rowsAsObjects_('Upgrades').map(r => ({
    id: text_(r.id),
    maxLevel: number_(r.maxLevel),
    prices: prices.get(text_(r.id)) || [],
    baseValue: number_(r.baseValue),
    valuePerLevel: number_(r.valuePerLevel),
  }));
}

function getManifest_() {
  return rowsAsObjects_('_MANIFEST').map(r => ({
    configName: text_(r.configName),
    enabled: r.enabled === true || String(r.enabled).toLowerCase() === 'true',
    sourceSheets: text_(r.sourceSheets),
    outputFile: text_(r.outputFile),
    gitPath: text_(r.gitPath),
    robloxEntryKey: text_(r.robloxEntryKey),
    structure: text_(r.structure),
  }));
}

function getControlSettings_() {
  const sh = requireSheet_('_CONTROL');
  const vals = sh.getRange('A3:B11').getValues();
  const m = {};
  vals.forEach(([k, v]) => { if (!blank_(k)) m[String(k)] = v; });
  return {
    githubOwner: text_(m['GitHub owner']),
    githubRepo: text_(m['GitHub repo']),
    githubBranch: text_(m['Git branch']),
    gitConfigPath: text_(m['Git config path']),
    universeId: text_(m['Roblox Universe ID']),
    placeId: text_(m['Roblox Place ID']),
    dataStore: text_(m['Roblox DataStore']),
    keyPrefix: text_(m['Roblox key prefix']),
  };
}

function rowsAsObjects_(sheetName) {
  const sh = requireSheet_(sheetName);
  const values = sh.getDataRange().getValues();
  if (values.length < 2) return [];
  const headers = values[0].map(x => String(x).trim());
  return values.slice(1)
    .filter(row => row.some(v => !blank_(v)))
    .map(row => {
      const obj = {};
      headers.forEach((h, i) => { if (h) obj[h] = row[i]; });
      return obj;
    });
}

function keyValueSheet_(sheetName) {
  const out = {};
  rowsAsObjects_(sheetName).forEach(r => { out[text_(r.key)] = r.value !== undefined ? r.value : r.value_text; });
  return out;
}

function requireSheet_(name) {
  const sh = SpreadsheetApp.getActive().getSheetByName(name);
  if (!sh) throw new Error(`Missing sheet: ${name}`);
  return sh;
}

function number_(v) {
  if (typeof v === 'number') return v;
  const n = Number(String(v).replace(/\s/g, '').replace(',', '.'));
  if (!Number.isFinite(n)) throw new Error(`Expected number, got: ${v}`);
  return n;
}

function text_(v) { return blank_(v) ? '' : String(v).trim(); }
function blank_(v) { return v === null || v === undefined || String(v).trim() === ''; }
function replacePlaceId_(template, placeId) { return String(template).replace('{PLACE_ID}', String(placeId)); }
function enc_(s) { return encodeURIComponent(String(s)); }

function assertUnique_(values, fieldName) {
  const seen = new Set();
  values.forEach(v => {
    if (!v) throw new Error(`${fieldName}: blank value.`);
    if (seen.has(v)) throw new Error(`${fieldName}: duplicate value ${v}.`);
    seen.add(v);
  });
}

function githubRequest_(path, method, payload, token) {
  const options = {
    method: method || 'get',
    muteHttpExceptions: true,
    headers: {
      Accept: 'application/vnd.github+json',
      Authorization: `Bearer ${token}`,
      'X-GitHub-Api-Version': GITHUB_API_VERSION,
    },
  };
  if (payload !== null && payload !== undefined) {
    options.contentType = 'application/json';
    options.payload = JSON.stringify(payload);
  }
  const response = UrlFetchApp.fetch(`https://api.github.com${path}`, options);
  const code = response.getResponseCode();
  const body = response.getContentText();
  if (code < 200 || code >= 300) {
    throw new Error(`GitHub API ${code}: ${body}`);
  }
  return body ? JSON.parse(body) : {};
}

function appendLog_(action, commitSha, configCount, status, details) {
  const sh = requireSheet_('_EXPORT_LOG');
  sh.appendRow([new Date(), action, commitSha, configCount, status, details]);
}
