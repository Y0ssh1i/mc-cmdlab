// Spawn N offline fake players into the local test server (mineflayer).
// usage: node bots.js <host> <port> <version> <count> <prefix>
// Prints one JSON line per event on stdout so the Python side can follow along.
const mineflayer = require('mineflayer');

const [host, port, version, countArg, prefix] = process.argv.slice(2);
const count = parseInt(countArg || '3', 10);
const bots = [];

function log(obj) { process.stdout.write(JSON.stringify(obj) + '\n'); }

for (let i = 1; i <= count; i++) {
  const username = `${prefix || 'Tester'}${i}`;
  setTimeout(() => {
    const bot = mineflayer.createBot({ host, port: parseInt(port, 10), username, version, auth: 'offline' });
    bot.once('spawn', () => log({ event: 'spawn', username }));
    bot.on('messagestr', (msg) => log({ event: 'chat', username, msg }));
    bot.on('title', (text) => log({ event: 'title', username, text: String(text) }));
    bot.on('actionBar', (msg) => log({ event: 'actionbar', username, msg: String(msg) }));
    bot.on('kicked', (reason) => log({ event: 'kicked', username, reason: String(reason) }));
    bot.on('error', (err) => log({ event: 'error', username, err: String(err) }));
    bots.push(bot);
  }, i * 400); // join one by one; the server rejects rapid logins
}

process.stdin.on('data', (d) => {
  if (String(d).trim() === 'quit') { bots.forEach((b) => b.quit()); setTimeout(() => process.exit(0), 500); }
});
