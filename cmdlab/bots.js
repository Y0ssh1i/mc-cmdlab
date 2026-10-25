// Fake players for the local test server (mineflayer), plus what each one would see on screen.
// usage: node bots.js <host> <port> <version> <names comma separated>
// stdout: one JSON line per event. stdin: "state" -> prints a screen snapshot for every player;
// "do {json}" -> one player acts (chat, command, move, goto, look_at, attack, jump, sneak, select, use, respawn); "quit".
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
let pf = null;
try { pf = require('mineflayer-pathfinder'); } catch (e) { pf = null; }  // optional: real path finding for goto

const [host, port, version, namesArg] = process.argv.slice(2);
const names = (namesArg || 'Tester1,Tester2,Tester3').split(',').map((s) => s.trim()).filter(Boolean);
const bots = {};
const deadAt = {}; // username -> time of the last death (so an attacker stops when the target is down)
const screen = {}; // per player: title, subtitle, actionbar, bossbars, chat

function log(obj) { process.stdout.write(JSON.stringify(obj) + '\n'); }
// 1.20.3+ sends chat/title text as NBT ({"type":"compound","value":...}); turn it back into plain text.
function nbtPlain(o) {
  if (o && typeof o === 'object' && 'type' in o && 'value' in o) {
    if (o.type === 'compound') { const r = {}; for (const k of Object.keys(o.value)) r[k] = nbtPlain(o.value[k]); return r; }
    if (o.type === 'list') return (o.value.value || []).map((v) => nbtPlain(o.value.type === 'compound' || o.value.type === 'list' ? { type: o.value.type, value: v } : v));
    return o.value;
  }
  return o;
}
function compText(c) {
  if (c == null) return '';
  if (typeof c === 'string' || typeof c === 'number') return String(c);
  if (Array.isArray(c)) return c.map(compText).join('');
  let s = c.text != null ? String(c.text) : (c[''] != null ? String(c['']) : (c.translate || ''));
  if (c.score && c.text == null) s += c.score.value != null ? String(c.score.value) : `[${c.score.name}:${c.score.objective}]`;
  if (c.selector) s += `[${c.selector}]`;
  if (c.nbt) s += `[${c.nbt}]`;
  return s + (c.extra ? c.extra.map(compText).join('') : '');
}
function txt(x) {
  if (x == null) return '';
  if (typeof x === 'string' && x.startsWith('{"') && x.includes('"type"')) {
    try { return compText(nbtPlain(JSON.parse(x))); } catch (e) { /* fall through */ }
  }
  if (typeof x === 'string') return x;
  if (typeof x.toString === 'function' && x.toString !== Object.prototype.toString) return x.toString();
  try { return JSON.stringify(x); } catch (e) { return String(x); }
}
function motd(x) { try { return x && x.toMotd ? x.toMotd() : txt(x); } catch (e) { return txt(x); } }

function snapshot(name) {
  const bot = bots[name];
  if (!bot || !bot.entity) return { name, online: false };
  const s = screen[name];
  const sb = bot.scoreboard || {};
  const side = sb.sidebar || (bot.scoreboards && Object.values(bot.scoreboards).find((o) => o.position === 1));
  const sidebar = side ? {
    title: motd(side.displayName || side.title || side.name),
    items: (side.items || []).map((i) => ({ name: motd(i.displayName || i.name), score: i.value })).sort((a, b) => b.score - a.score).slice(0, 15),
  } : null;
  const tab = Object.values(bot.players || {}).map((p) => ({
    name: p.username, display: motd(p.displayName), ping: p.ping, gamemode: p.gamemode,
  }));
  const boards = bot.scoreboards ? Object.values(bot.scoreboards) : [];
  const below = boards.find((o) => o.position === 2);
  const belowName = below ? { title: motd(below.displayName || below.title || below.name), scores: (below.items || []).map((i) => ({ name: i.name, score: i.value })) } : null;
  const teamSidebars = boards.filter((o) => o.position >= 3 && o.position <= 18).map((o) => ({ position: o.position, title: motd(o.displayName || o.title || o.name) }));
  const teams = Object.values(bot.teams || {}).map((t) => ({ name: t.team, prefix: motd(t.prefix), suffix: motd(t.suffix), color: t.color, members: [...(t.membersMap ? Object.keys(t.membersMap) : t.members || [])] }));
  return {
    name, online: true,
    health: bot.health, food: bot.food, gamemode: bot.game && bot.game.gameMode,
    position: bot.entity.position && { x: +bot.entity.position.x.toFixed(1), y: +bot.entity.position.y.toFixed(1), z: +bot.entity.position.z.toFixed(1) },
    title: s.title, subtitle: s.subtitle, actionbar: s.actionbar,
    bossbars: Object.values(s.bossbars),
    effects: Object.values(bot.entity.effects || {}).map((e) => ({ name: (bot.registry.effects && bot.registry.effects[e.id] ? bot.registry.effects[e.id].name : 'effect#' + e.id), level: (e.amplifier || 0) + 1, seconds: Math.round((e.duration || 0) / 20) })),
    sidebar, tab, teams, belowName, teamSidebars, sounds: s.sounds.slice(-10), window: s.window,
    tabHeader: motd(bot.tablist && bot.tablist.header), tabFooter: motd(bot.tablist && bot.tablist.footer),
    chat: s.chat.slice(-10),
    held: bot.heldItem ? bot.heldItem.name : null,
    inventory: bot.inventory ? bot.inventory.items().map((i) => `${i.name} x${i.count}`).slice(0, 20) : [],
  };
}

function join(username, attempt) {
    const bot = mineflayer.createBot({ host, port: parseInt(port, 10), username, version, auth: 'offline' });
    bots[username] = bot;
    screen[username] = { title: '', subtitle: '', actionbar: '', bossbars: {}, chat: [], sounds: [], window: null };
    const s = screen[username];
    bot.once('spawn', () => {
      if (pf) { try { bot.loadPlugin(pf.pathfinder); const m = new pf.Movements(bot); m.canDig = false; bot.pathfinder.setMovements(m); } catch (e) { /* walk straight instead */ } }
      log({ event: 'spawn', username });
    });
    const snd = (name) => { s.sounds.push(String(name)); if (s.sounds.length > 15) s.sounds.shift(); log({ event: 'sound', username, name: String(name) }); };
    bot.on('soundEffectHeard', (name) => snd(name));
    bot.on('hardcodedSoundEffectHeard', (id) => snd('sound#' + id));
    bot.on('windowOpen', (w) => {
      s.window = { title: txt(w.title), slots: w.slots.slice(0, w.inventoryStart || w.slots.length).map((it, i) => it ? { slot: i, name: it.name, count: it.count, label: it.customName ? txt(it.customName) : null } : null).filter(Boolean) };
      log({ event: 'window', username, title: s.window.title, items: s.window.slots.length });
    });
    bot.on('windowClose', () => { s.window = null; });
    bot.on('messagestr', (msg, position) => {
      if (position === 'game_info') { s.actionbar = msg; log({ event: 'actionbar', username, msg }); return; }
      s.chat.push(msg); log({ event: 'chat', username, msg });
    });
    bot.on('title', (text, type) => {
      const t = txt(text);
      if (type === 'actionbar' || type === 'action_bar') { s.actionbar = t; log({ event: 'actionbar', username, msg: t }); return; }
      // title/subtitle text comes from the raw packet hook above (keeps score parts)
    });
    bot.on('actionBar', (msg) => { s.actionbar = txt(msg); log({ event: 'actionbar', username, msg: s.actionbar }); });
    // Some versions send the action bar as its own packet that mineflayer does not surface as an event.
    bot._client.on('packet', (data, meta) => {
      // titles: read the packet ourselves so score / selector parts are not lost (1.20 JSON text and 1.20.3+ NBT text)
      if (meta.name === 'set_title_text' || meta.name === 'set_title_subtitle') {
        let t = data.text;
        try { t = compText(nbtPlain(typeof t === 'string' ? JSON.parse(t) : t)); } catch (e) { t = txt(t); }
        if (meta.name === 'set_title_text') s.title = t; else s.subtitle = t;
        log({ event: 'title', username, text: t, type: meta.name === 'set_title_text' ? 'title' : 'subtitle' });
        return;
      }
      if (!/action_bar/.test(meta.name)) return;
      let t = data.text;
      try { t = new (require('prismarine-chat')(bot.registry))(typeof t === 'string' ? JSON.parse(t) : t).toString(); } catch (e) { t = txt(t); }
      s.actionbar = t; log({ event: 'actionbar', username, msg: t });
    });
    const bb = (b) => { s.bossbars[b.entityUUID] = { title: motd(b.title), health: b.health, color: b.color, dividers: b.dividers }; };
    bot.on('bossBarCreated', bb);
    bot.on('bossBarUpdated', bb);
    bot.on('bossBarDeleted', (b) => { delete s.bossbars[b.entityUUID]; });
    bot.on('death', () => { deadAt[username] = Date.now(); log({ event: 'death', username }); });
    bot.on('health', () => log({ event: 'health', username, health: bot.health, food: bot.food }));
    bot.on('entityHurt', (ent) => { if (ent && ent.type === 'player' && ent.username) log({ event: 'hurt', username, who: ent.username }); });
    bot.on('kicked', (reason) => log({ event: 'kicked', username, reason: txt(reason) }));
    bot.on('error', (err) => log({ event: 'error', username, err: String(err) }));
    // retry when a join fails before spawning (the first login right after start is sometimes dropped)
    bot.once('end', () => { if (!bot.entity && attempt < 4) setTimeout(() => join(username, attempt + 1), 1500); });
}

names.forEach((username, idx) => {
  setTimeout(() => join(username, 1), 1000 + idx * 600); // join one by one; the server rejects rapid logins
});

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function playerEntity(bot, name) {
  const p = bot.players[name];
  return p && p.entity ? p.entity : null;
}
// One player does one thing, like a real person would (needed for tag, PvP, werewolf votes ...).
async function act(a) {
  const bot = bots[a.name];
  const done = (ok, extra) => log(Object.assign({ event: 'did', username: a.name, action: a.action, ok }, extra || {}));
  if (!bot || !bot.entity) return done(false, { error: 'player is not online' });
  try {
    const ms = Math.round((a.seconds || 1) * 1000);
    switch (a.action) {
      case 'chat': bot.chat(String(a.text || '')); break;            // also "/trigger vote set 2" etc.
      case 'command': bot.chat('/' + String(a.text || '').replace(/^\//, '')); break;
      case 'move': {
        const dir = a.dir || 'forward';
        if (a.sprint) bot.setControlState('sprint', true);
        bot.setControlState(dir, true); await sleep(ms); bot.setControlState(dir, false);
        bot.setControlState('sprint', false); break;
      }
      case 'goto': {
        if (pf && bot.pathfinder) {                                  // real path finding (around walls, up steps)
          const y = a.y != null ? a.y : bot.entity.position.y;
          const go = bot.pathfinder.goto(new pf.goals.GoalNear(a.x, y, a.z, a.range || 1));
          const timeout = new Promise((_, rej) => setTimeout(() => rej(new Error('did not arrive in time')), ms + 20000));
          try { await Promise.race([go, timeout]); } finally { bot.pathfinder.setGoal(null); bot.clearControlStates(); }
          break;
        }
      }
      // falls through when there is no path finder: walk straight
      case 'walk': {                                                 // walk straight to x z (no path finding)
        const t0 = Date.now();
        while (Date.now() - t0 < ms + 10000) {
          const dx = a.x - bot.entity.position.x, dz = a.z - bot.entity.position.z;
          if (Math.hypot(dx, dz) < 1.2) break;
          await bot.lookAt(bot.entity.position.offset(dx, 0, dz).offset(0, bot.entity.height, 0), true);
          bot.setControlState('forward', true); bot.setControlState('sprint', !!a.sprint);
          await sleep(100);
        }
        bot.clearControlStates(); break;
      }
      case 'look_at': {
        const e = playerEntity(bot, a.target);
        if (!e) return done(false, { error: `cannot see ${a.target}` });
        await bot.lookAt(e.position.offset(0, e.height, 0), true); break;
      }
      case 'attack': {                                               // hit another player; step closer when knocked back
        let hits = 0;
        const t0 = Date.now();
        while (hits < (a.times || 1) && Date.now() - t0 < 20000) {
          if ((deadAt[a.target] || 0) >= t0) break;                  // the target went down: stop like a player would
          const e = playerEntity(bot, a.target);
          if (!e) return done(false, { error: `cannot see ${a.target}`, hits });
          const d = bot.entity.position.distanceTo(e.position);
          if (d > 3.0) {
            if (hits === 0 && d > 8 && !a.chase) return done(false, { error: `${a.target} is ${d.toFixed(1)} blocks away (reach is about 3)` });
            await bot.lookAt(e.position.offset(0, e.height, 0), true);
            bot.setControlState('forward', true); bot.setControlState('sprint', true);
            await sleep(150); bot.clearControlStates(); continue;
          }
          await bot.lookAt(e.position.offset(0, e.height * 0.8, 0), true);
          bot.attack(e); hits++; await sleep(650);
        }
        bot.clearControlStates();
        const killed = (deadAt[a.target] || 0) >= t0;
        if (hits < (a.times || 1) && !killed) return done(false, { error: `only ${hits} hit(s) landed`, hits });
        break;
      }
      case 'use_block': {                                            // right click a button, lever, sign, door, chest ...
        const b = bot.blockAt(new Vec3(a.x, a.y, a.z));
        if (!b || b.name === 'air') return done(false, { error: `no block at ${a.x} ${a.y} ${a.z}` });
        await bot.lookAt(b.position.offset(0.5, 0.5, 0.5), true);
        await bot.activateBlock(b); await sleep(300);
        return done(true, { block: b.name });
      }
      case 'use_entity': {                                           // right click a villager / mob / player / armor stand
        const e = a.target && bot.players[a.target] ? bot.players[a.target].entity
          : bot.nearestEntity((x) => x !== bot.entity && (!a.type || x.name === a.type) && (!a.name || (x.displayName || x.username || '') === a.name || (x.getCustomName && txt(x.getCustomName()) === a.name)));
        if (!e) return done(false, { error: `no ${a.target || a.type || a.name || 'entity'} nearby` });
        await bot.lookAt(e.position.offset(0, e.height * 0.8, 0), true);
        await bot.activateEntity(e); await sleep(300);
        return done(true, { entity: e.name || e.username });
      }
      case 'dig': {
        const b = bot.blockAt(new Vec3(a.x, a.y, a.z));
        if (!b || b.name === 'air') return done(false, { error: `no block at ${a.x} ${a.y} ${a.z}` });
        if (!bot.canDigBlock(b)) return done(false, { error: `${b.name} cannot be broken from here (too far, or adventure mode)` });
        await bot.dig(b); return done(true, { block: b.name });
      }
      case 'place': {                                                // place the held block (or "item") on top of x y-1 z
        if (a.item) { const it = bot.inventory.items().find((i) => i.name === a.item); if (!it) return done(false, { error: `no ${a.item} in the inventory` }); await bot.equip(it, 'hand'); }
        const ref = bot.blockAt(new Vec3(a.x, a.y - 1, a.z));
        if (!ref || ref.name === 'air') return done(false, { error: `nothing to place against under ${a.x} ${a.y} ${a.z}` });
        await bot.placeBlock(ref, new Vec3(0, 1, 0)); return done(true, { placed: bot.heldItem ? bot.heldItem.name : a.item });
      }
      case 'click_slot': {                                           // click a slot in the open chest / menu (shops, kit pickers)
        if (!bot.currentWindow) return done(false, { error: 'no window is open' });
        await bot.clickWindow(a.slot, a.button || 0, a.mode || 0); await sleep(300);
        return done(true, { window: txt(bot.currentWindow && bot.currentWindow.title) });
      }
      case 'close_window': if (bot.currentWindow) bot.closeWindow(bot.currentWindow); break;
      case 'drop': if (bot.heldItem) await bot.tossStack(bot.heldItem); break;
      case 'jump': bot.setControlState('jump', true); await sleep(400); bot.setControlState('jump', false); break;
      case 'sneak': bot.setControlState('sneak', a.on !== false); break;
      case 'select': bot.setQuickBarSlot(Math.max(0, Math.min(8, a.slot || 0))); break;
      case 'use': bot.activateItem(); await sleep(ms); bot.deactivateItem(); break;
      case 'respawn': bot.respawn(); break;
      default: return done(false, { error: `unknown action ${a.action}` });
    }
    done(true, bot.entity ? { position: { x: +bot.entity.position.x.toFixed(1), y: +bot.entity.position.y.toFixed(1), z: +bot.entity.position.z.toFixed(1) } } : {});
  } catch (e) { bot.clearControlStates && bot.clearControlStates(); done(false, { error: String(e && e.message || e) }); }
}

let buf = '';
process.stdin.on('data', (d) => {
  buf += String(d);
  let i;
  while ((i = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
    if (line === 'state') log({ event: 'state', screens: names.map(snapshot) });
    if (line === 'clear') names.forEach((n) => { if (screen[n]) { screen[n].title = ''; screen[n].subtitle = ''; screen[n].actionbar = ''; } });
    if (line.startsWith('do ')) { try { act(JSON.parse(line.slice(3))); } catch (e) { log({ event: 'did', ok: false, error: 'bad action json' }); } }
    if (line === 'quit') { Object.values(bots).forEach((b) => b.quit()); setTimeout(() => process.exit(0), 500); }
  }
});
