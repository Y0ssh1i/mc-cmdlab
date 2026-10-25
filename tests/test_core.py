import json
from pathlib import Path

from cmdlab import lint, rcon, runner


def test_rcon_roundtrip():
    pkt = rcon.pack(7, rcon.COMMAND, "say hi")
    assert rcon.unpack(pkt[4:]) == (7, rcon.COMMAND, "say hi")


def _pack(tmp: Path, fmt: int, folder: str) -> Path:
    (tmp / "data" / "demo" / folder).mkdir(parents=True)
    (tmp / "pack.mcmeta").write_text(json.dumps({"pack": {"pack_format": fmt, "description": "t"}}), encoding="utf-8")
    (tmp / "data" / "demo" / folder / "start.mcfunction").write_text("say ok\ngive @s diamond_sword[damage=1]\n", encoding="utf-8")
    return tmp


def test_lint_flags_wrong_version(tmp_path):
    found = lint.lint_pack(_pack(tmp_path, 80, "function"), "1.20.1")
    msgs = " ".join(f.message for f in found)
    assert "pack_format 80" in msgs
    assert "'function/'" in msgs
    assert "item components" in msgs


def test_lint_ok_on_matching_version(tmp_path):
    (tmp_path / "p").mkdir()
    p = tmp_path / "p"
    (p / "data" / "demo" / "functions").mkdir(parents=True)
    (p / "pack.mcmeta").write_text(json.dumps({"pack": {"pack_format": 15, "description": "t"}}), encoding="utf-8")
    (p / "data" / "demo" / "functions" / "a.mcfunction").write_text("say ok\n", encoding="utf-8")
    assert lint.lint_pack(p, "1.20.1") == []


def test_build_and_judge():
    assert runner.build_command({"run": "/say hi", "as": "Tester1"}) == "execute as Tester1 at @s run say hi"
    ok, _ = runner.judge({"expect": {"output_regex": "has 3 "}}, "Tester1 has 3 [points]", [])
    assert ok
    ok, why = runner.judge({}, "Unknown or incomplete command, see below for error", [])
    assert not ok and "rejected" in why
    ok, _ = runner.judge({"expect": {"seen_by": "Tester2", "seen_contains": "開始"}}, "",
                         [{"event": "title", "username": "Tester2", "text": "ゲーム開始"}])
    assert ok


class FakeRcon:
    def __init__(self):
        self.sent = []

    def command(self, c):
        self.sent.append(c)
        return "ok"


def test_place_command_block_line():
    r = FakeRcon()
    pos = runner.place_blocks(r, {"origin": [0, -59, 0], "blocks": [
        {"type": "impulse", "cmd": 'say "a"'}, {"type": "chain", "cmd": "say b", "conditional": True},
        {"type": "repeat", "cmd": "say c", "auto": True}]})
    assert pos == [(0, -59, 0), (1, -59, 0), (2, -59, 0)]
    joined = "\n".join(r.sent)
    assert "minecraft:command_block[facing=east,conditional=false]" in joined
    assert "minecraft:chain_command_block[facing=east,conditional=true]" in joined and "auto:1b" in joined
    assert "minecraft:repeating_command_block" in joined
    assert 'Command:"say \\"a\\""' in joined
    assert "redstone_block" in joined  # impulse without auto is powered once


def test_blocked_commands():
    assert not runner.SAFE.match("stop")
    assert not runner.SAFE.match("/op Tester1")
    assert runner.SAFE.match("say stopwatch")


def test_execute_chain_is_explained_in_order():
    from cmdlab import explain
    c = 'execute as @a[team=red] at @s if score @s points matches 5.. positioned ~ ~1 ~ run tellraw @s {"text":"win"}'
    ja = explain.describe(c, "ja")
    assert ja.index("として") < ja.index("なら") < ja.index("tellraw") and "「win」" in ja
    en = explain.describe(c, "en")
    assert en.startswith("as everyone[team=red]") and '"win"' in en


def test_split_args_keeps_nbt_and_json_together():
    from cmdlab import explain
    w = explain.split_args('give @s diamond_sword{display:{Name:\'{"text":"a b"}\'}} 1')
    assert w == ["give", "@s", 'diamond_sword{display:{Name:\'{"text":"a b"}\'}}', "1"]


def test_lint_finds_unclosed_brackets_and_bad_json_text():
    from cmdlab import lint
    f = lint.lint_lines(['tellraw @a {"text":"hi"', 'tellraw @a {text:"hi"}', 'say [ok] it\'s fine'], "1.20.1")
    assert [(x.line, x.level) for x in f] == [(1, "error"), (2, "warn")]


def test_every_provider_is_listed_with_a_key_source():
    from cmdlab import ai
    assert {"anthropic", "openai", "gemini", "openrouter", "ollama", "openai_compatible"} <= set(ai.PROVIDERS)
    assert ai._players(["Alice", "Bob"]) == "Alice, Bob" and ai._players(2) == "Tester1, Tester2"
