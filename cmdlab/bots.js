// Fake players for the local test server (mineflayer), plus what each one would see on screen.
// usage: node bots.js <host> <port> <version> <names comma separated>
// stdout: one JSON line per event. stdin: "state" -> prints a screen snapshot for every player; "quit".
const mineflayer = require('mineflayer');

const [host, port, version, namesArg] = process.argv.slice(2);
const names = (namesArg || 'Tester1,Tester2,Tester3').split(',').map((s) => s.trim()).filter(Boolean);
const bots = {};
const screen = {}; // per player: title, subtitle, actionbar, bossbars, chat

function log(obj) { process.stdout.write(JSON.stringify(obj) + '\n'); }
function txt(x) {
  if (x == null) return '';
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
  const teams = Object.values(bot.teams || {}).map((t) => ({ name: t.team, prefix: motd(t.prefix), suffix: motd(t.suffix), color: t.color, members: [...(t.membersMap ? Object.keys(t.membersMap) : t.members || [])] }));
  return {
    name, online: true,
    health: bot.health, food: bot.food, gamemode: bot.game && bot.game.gameMode,
    position: bot.entity.position && { x: +bot.entity.position.x.toFixed(1), y: +bot.entity.position.y.toFixed(1), z: +bot.entity.position.z.toFixed(1) },
    title: s.title, subtitle: s.subtitle, actionbar: s.actionbar,
    bossbars: Object.values(s.bossbars),
    sidebar, tab, teams,
    tabHeader: motd(bot.tablist && bot.tablist.header), tabFooter: motd(bot.tablist && bot.tablist.footer),
    chat: s.chat.slice(-10),
    held: bot.heldItem ? bot.heldItem.name : null,
    inventory: bot.inventory ? bot.inventory.items().map((i) => `${i.name} x${i.count}`).slice(0, 20) : [],
  };
}

function join(username, attempt) {
    const bot = mineflayer.createBot({ host, port: parseInt(port, 10), username, version, auth: 'offline' });
    bots[username] = bot;
    screen[username] = { title: '', subtitle: '', actionbar: '', bossbars: {}, chat: [] };
    const s = screen[username];
    bot.once('spawn', () => log({ event: 'spawn', username }));
    bot.on('messagestr', (msg, position) => {
      if (position === 'game_info') { s.actionbar = msg; log({ event: 'actionbar', username, msg }); return; }
      s.chat.push(msg); log({ event: 'chat', username, msg });
    });
    bot.on('title', (text, type) => {
      const t = txt(text);
      if (type === 'actionbar' || type === 'action_bar') { s.actionbar = t; log({ event: 'actionbar', username, msg: t }); return; }
      if (type === 'subtitle') s.subtitle = t; else s.title = t;
      log({ event: 'title', username, text: t, type: type || 'title' });
    });
    bot.on('actionBar', (msg) => { s.actionbar = txt(msg); log({ event: 'actionbar', username, msg: s.actionbar }); });
    // Some versions send the action bar as its own packet that mineflayer does not surface as an event.
    bot._client.on('packet', (data, meta) => {
      if (!/action_bar/.test(meta.name)) return;
      let t = data.text;
      try { t = new (require('prismarine-chat')(bot.registry))(typeof t === 'string' ? JSON.parse(t) : t).toString(); } catch (e) { t = txt(t); }
      s.actionbar = t; log({ event: 'actionbar', username, msg: t });
    });
    const bb = (b) => { s.bossbars[b.entityUUID] = { title: motd(b.title), health: b.health, color: b.color, dividers: b.dividers }; };
    bot.on('bossBarCreated', bb);
    bot.on('bossBarUpdated', bb);
    bot.on('bossBarDeleted', (b) => { delete s.bossbars[b.entityUUID]; });
    bot.on('kicked', (reason) => log({ event: 'kicked', username, reason: txt(reason) }));
    bot.on('error', (err) => log({ event: 'error', username, err: String(err) }));
    // retry when a join fails before spawning (the first login right after start is sometimes dropped)
    bot.once('end', () => { if (!bot.entity && attempt < 4) setTimeout(() => join(username, attempt + 1), 1500); });
}

names.forEach((username, idx) => {
  setTimeout(() => join(username, 1), 1000 + idx * 600); // join one by one; the server rejects rapid logins
});

let buf = '';
process.stdin.on('data', (d) => {
  buf += String(d);
  let i;
  while ((i = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
    if (line === 'state') log({ event: 'state', screens: names.map(snapshot) });
    if (line === 'clear') names.forEach((n) => { if (screen[n]) { screen[n].title = ''; screen[n].subtitle = ''; screen[n].actionbar = ''; } });
    if (line === 'quit') { Object.values(bots).forEach((b) => b.quit()); setTimeout(() => process.exit(0), 500); }
  }
});
