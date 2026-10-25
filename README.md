# mc-cmdlab

Test Minecraft Java Edition commands on your own PC, without gathering people or placing command blocks.
(日本語の説明は下にあります)

- Pick a Minecraft version (1.20.1 first; add a version by adding one file in `versions/`).
- One click starts a local, offline test server from the official server jar.
- Add fake players (`Tester1`, `Tester2`, ...) so commands that need several people can be tested alone.
- Run a script of one-off commands and command block lines (impulse, chain, repeat, conditional, always active or redstone-powered).
- Each step shows what it does in Japanese or English, whether it passed, what each player saw, and where an error is.
- Check a data pack against the chosen version before running it (pack format, folder names, syntax that the version does not have).
- Ask Claude to write the commands for a game idea, run them, and let it fix the steps that failed.
- Works in Chrome (a local web page), from the terminal, and as an MCP server for Claude Code / Claude Desktop.

## Quick start

Requirements: Python 3.10+, Java (17 for 1.20.1, 21 for 1.21.x), Node.js 18+.

```bash
git clone https://github.com/Y0ssh1i/mc-cmdlab
cd mc-cmdlab
npm install            # fake players (mineflayer)
pip install anthropic  # only if you use the AI features; set ANTHROPIC_API_KEY
python -m cmdlab ui    # open http://127.0.0.1:8765 in Chrome
```

In the page: choose the version, accept the Minecraft EULA, press Prepare and Start, add players, then Run.

From the terminal:

```bash
python -m cmdlab setup --version 1.20.1 --accept-eula
python -m cmdlab lint path/to/datapack --version 1.20.1
python -m cmdlab run examples/teams_and_scores.json --players 3
python -m cmdlab ai "Split players into red and blue, show a start title, keep score" --version 1.20.1
```

As an MCP server (Claude Code):

```bash
claude mcp add mc-cmdlab -- python -m cmdlab mcp
```

## Script format

```json
{
  "version": "1.20.1",
  "players": 3,
  "datapacks": ["path/to/pack"],
  "steps": [
    {"run": "scoreboard objectives add points dummy"},
    {"run": "scoreboard players add @s points 1", "as": "Tester1"},
    {"run": "scoreboard players get Tester1 points", "expect": {"output_regex": "has 1 "}},
    {"run": "title @a title {\"text\":\"Start\"}", "wait": 1, "expect": {"seen_by": "Tester2", "seen_contains": "Start"}},
    {"blocks": [
        {"type": "impulse", "cmd": "scoreboard players add Tester2 points 5"},
        {"type": "chain", "cmd": "execute if score Tester2 points matches 5 run say five"},
        {"type": "chain", "cmd": "say conditional", "conditional": true}
      ], "origin": [0, -59, 0], "wait": 1}
  ]
}
```

- `run`: a one-off command. `as`: run it as that player.
- `blocks`: a command block line placed east of `origin`, facing east. `type` is `impulse`, `chain` or `repeat`.
  `conditional` and `auto` (always active) are supported; an impulse block without `auto` is powered once.
  Each block's `SuccessCount` and `LastOutput` are read back after `wait` seconds.
- `expect`: `output_contains`, `output_regex`, `seen_by` + `seen_contains`.

## Safety

- The server listens on 127.0.0.1 only and runs in offline mode for local fake players. Do not expose it.
- The server jar is downloaded from Mojang and checked with SHA-1. It is not redistributed here. You accept the
  [Minecraft EULA](https://aka.ms/MinecraftEULA) yourself.
- Scripts cannot run `stop`, `op`, `ban`, `whitelist` and similar commands.
- Your API key stays in your environment. It is never written to the repository.

---

## 日本語

マイクラ(Java 版)のコマンドを、人を集めずに、コマンドブロックを置かずに、自分の PC だけで試す道具です。

- **版を選べます。** 最初は 1.20.1 です。版を足すときは、`versions/` に表を1つ足すだけです。
- **テスト用のサーバー:** ボタン1つで、公式のサーバーから手元だけの検証用サーバーを立てます。
- **偽のプレイヤー:** `Tester1`、`Tester2` … を入れられるので、何人も要るコマンドも1人で試せます。
- **台本で流せます。** 1回きりのコマンドも、コマンドブロック(インパルス・チェーン・リピート、条件付き、常時実行かレッドストーン)の連結も、台本にして流せます。
- **結果の見え方:** 段ごとに、していること(日本語か英語)、成功か失敗か、プレイヤーに見えたもの、エラーの場所を出します。
- **データパックの点検:** 流す前に、選んだ版に合っているかを点検します(形式の番号、フォルダの名前、その版に無い書き方)。
- **AI につなげます。** 企画を書くと Claude がコマンドを作り、流して、失敗した段を直させられます。
- **使い方は3通り:** Chrome で開く画面、ターミナル、Claude Code や Claude Desktop の MCP のサーバー。

使い方は上の Quick start と同じです。画面は `python -m cmdlab ui` のあと Chrome で http://127.0.0.1:8765 を開きます。
右上で言語(日本語と English)を選べます。

## License

MIT
