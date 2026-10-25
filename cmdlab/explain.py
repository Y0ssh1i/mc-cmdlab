"""Say what a command does, in Japanese or English, and point at where an error is.

Rule-based on purpose: it runs offline and instantly for every step. Unknown commands get a generic line.
"""
from __future__ import annotations

import re

T = {
    "say": ("全員のチャットに「{0}」と表示する", "Show \"{0}\" in everyone's chat"),
    "tellraw": ("{0} に文字を表示する(tellraw)", "Show formatted text to {0} (tellraw)"),
    "title": ("{0}の画面に{1}を表示する", "Show a {1} on {0}'s screen"),
    "obj_add": ("スコアボードの項目「{0}」を作る", "Create scoreboard objective \"{0}\""),
    "obj_rm": ("スコアボードの項目「{0}」を消す", "Remove scoreboard objective \"{0}\""),
    "obj_display": ("項目「{1}」を {0} に表示する", "Display objective \"{1}\" in {0}"),
    "sc_add": ("{0} の「{1}」に {2} 足す", "Add {2} to {0}'s \"{1}\""),
    "sc_remove": ("{0} の「{1}」から {2} 引く", "Subtract {2} from {0}'s \"{1}\""),
    "sc_set": ("{0} の「{1}」を {2} にする", "Set {0}'s \"{1}\" to {2}"),
    "sc_get": ("{0} の「{1}」の値を確かめる", "Read {0}'s \"{1}\""),
    "sc_reset": ("{0} のスコアを消す", "Reset {0}'s scores"),
    "team_add": ("チーム「{0}」を作る", "Create team \"{0}\""),
    "team_join": ("{1} をチーム「{0}」に入れる", "Put {1} on team \"{0}\""),
    "team_leave": ("{0} をチームから外す", "Remove {0} from their team"),
    "team_modify": ("チーム「{0}」の設定 {1} を変える", "Change team \"{0}\" option {1}"),
    "function": ("関数 {0} を実行する(データパックの中の処理)", "Run function {0} (logic inside the data pack)"),
    "give": ("{0}に {1} を渡す", "Give {1} to {0}"),
    "clear": ("{0} の持ち物を消す", "Clear {0}'s items"),
    "tp": ("{0} を移動させる", "Teleport {0}"),
    "effect": ("{0} に効果をかける/消す", "Apply or clear effects on {0}"),
    "gamemode": ("{1} のゲームモードを {0} にする", "Set {1}'s game mode to {0}"),
    "setblock": ("{0} にブロックを置く", "Place a block at {0}"),
    "fill": ("範囲をブロックで埋める", "Fill an area with blocks"),
    "summon": ("{0} を出現させる", "Summon {0}"),
    "kill": ("{0} を倒す/消す", "Kill {0}"),
    "data": ("データを読む/書く(data {0})", "Read or write data (data {0})"),
    "schedule": ("{0} を後で実行する予定を入れる", "Schedule {0} to run later"),
    "reload": ("データパックを読み直す", "Reload data packs"),
    "gamerule": ("ゲームのルール {0} を {1} にする", "Set game rule {0} to {1}"),
    "bossbar": ("ボスバーを操作する", "Change a boss bar"),
    "bb_add": ("ボスバー「{0}」を作る", "Create boss bar \"{0}\""),
    "bb_value": ("ボスバー「{0}」の値を {1} にする", "Set boss bar \"{0}\" value to {1}"),
    "bb_max": ("ボスバー「{0}」の最大を {1} にする", "Set boss bar \"{0}\" max to {1}"),
    "bb_players": ("ボスバー「{0}」を {1} に見せる", "Show boss bar \"{0}\" to {1}"),
    "bb_color": ("ボスバー「{0}」の色を {1} にする", "Set boss bar \"{0}\" color to {1}"),
    "bb_name": ("ボスバー「{0}」の文字を変える", "Change boss bar \"{0}\" text"),
    "bb_remove": ("ボスバー「{0}」を消す", "Remove boss bar \"{0}\""),
    "playsound": ("{1} に音を鳴らす", "Play a sound to {1}"),
    "tag": ("{0} にタグを付ける/外す", "Add or remove a tag on {0}"),
    "execute_as": ("{0} として", "As {0}, "),
    "execute_if": ("条件({0})が成り立つとき", "If ({0}), "),
    "execute_unless": ("条件({0})が成り立たないとき", "Unless ({0}), "),
    "generic": ("{0} コマンドを実行する", "Run the {0} command"),
    "blocks": ("コマンドブロックを {0} 個並べて動かす", "Place and run a line of {0} command blocks"),
    "ok": ("成功", "OK"),
    "fail": ("失敗", "Failed"),
    "where": ("エラーの場所: {0} 文字目付近「{1}」", "Error near column {0}: \"{1}\""),
    "rejected": ("サーバーがコマンドを受け付けなかった", "The server rejected the command"),
}

TARGET = {"@a": ("全員", "everyone"), "@p": ("一番近いプレイヤー", "the nearest player"), "@s": ("実行者自身", "the executor"),
          "@e": ("全エンティティ", "all entities"), "@r": ("ランダムな1人", "a random player")}


def split_args(cmd: str) -> list[str]:
    """Split a command on spaces, keeping {...} [...] and "..." / '...' together (NBT, JSON text, selectors)."""
    out, cur, depth, quote, esc = [], "", 0, "", False
    for ch in cmd:
        if quote:
            cur += ch
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
        if ch == " " and depth <= 0:
            if cur:
                out.append(cur)
            cur = ""
            continue
        cur += ch
    if cur:
        out.append(cur)
    return out


def json_text(arg: str) -> str:
    """The plain text inside a JSON text component ("..." / {"text":...} / [..]), for explanations."""
    import json as _json
    try:
        v = _json.loads(arg)
    except ValueError:
        return arg[:60]

    def walk(x) -> str:
        if isinstance(x, str):
            return x
        if isinstance(x, list):
            return "".join(walk(i) for i in x)
        if isinstance(x, dict):
            own = x.get("text") or x.get("translate") or ""
            if "score" in x:
                own = "[" + str(x["score"].get("name", "")) + ":" + str(x["score"].get("objective", "")) + "]"
            if "selector" in x:
                own = "[" + str(x["selector"]) + "]"
            return str(own) + "".join(walk(i) for i in x.get("extra", []))
        return ""
    return walk(v)[:80]


# execute sub-commands: how many arguments each one takes after its name
EXEC_ARGS = {"as": 1, "at": 1, "align": 1, "anchored": 1, "in": 1, "on": 1, "summon": 1}
COND_ARGS = {"entity": 1, "predicate": 1, "dimension": 1, "function": 1, "block": 4, "biome": 4, "loaded": 3}
STORE_ARGS = {"score": 2, "bossbar": 2, "block": 6, "entity": 4, "storage": 4}


def parse_execute(words: list[str]) -> tuple[list[tuple[str, list[str]]], list[str]]:
    """Walk 'execute ... run ...' and return [(sub-command, args)], plus the words after 'run'."""
    parts, i = [], 1
    while i < len(words):
        w = words[i]
        if w == "run":
            return parts, words[i + 1:]
        if w in EXEC_ARGS:
            n = EXEC_ARGS[w]
        elif w in ("positioned", "rotated", "facing"):
            if i + 1 < len(words) and words[i + 1] in ("as", "over"):
                n = 2
            elif w == "facing" and i + 1 < len(words) and words[i + 1] == "entity":
                n = 3
            else:
                n = 3 if w != "rotated" else 2
        elif w in ("if", "unless"):
            kind = words[i + 1] if i + 1 < len(words) else ""
            if kind == "score":
                n = 5 if i + 4 < len(words) and words[i + 4] == "matches" else 6
            elif kind == "data":
                n = 5 if words[i + 2:i + 3] == ["block"] else 4
            elif kind == "blocks":
                n = 11
            elif kind == "items":
                n = 5 if words[i + 2:i + 3] == ["block"] else 4
            else:
                n = 1 + COND_ARGS.get(kind, 1)
        elif w == "store":
            kind = words[i + 2] if i + 2 < len(words) else ""
            n = 2 + STORE_ARGS.get(kind, 2)
        else:
            n = 0
        parts.append((w, words[i + 1:i + 1 + n]))
        i += 1 + n
    return parts, []


EXEC_JA = {"as": "{0}として", "at": "{0}の位置で", "positioned": "位置 {0} で", "rotated": "向き {0} で", "facing": "{0} の方を向いて",
           "align": "座標をそろえて({0})", "anchored": "{0} を基準に", "in": "ディメンション {0} で", "on": "{0} に対して",
           "summon": "{0} を出して", "if": "もし {0} なら", "unless": "もし {0} でなければ", "store": "{0} に入れつつ"}
EXEC_EN = {"as": "as {0}, ", "at": "at {0}, ", "positioned": "at position {0}, ", "rotated": "rotated {0}, ", "facing": "facing {0}, ",
           "align": "aligned ({0}), ", "anchored": "anchored at {0}, ", "in": "in {0}, ", "on": "on {0}, ",
           "summon": "summoning {0}, ", "if": "if {0}, ", "unless": "unless {0}, ", "store": "storing the result in {0}, "}


def _cond(args: list[str], lang: str) -> str:
    if not args:
        return "?"
    k = args[0]
    if k == "entity" and len(args) > 1:
        return (_who(args[1], lang) + ("がいる" if lang == "ja" else " exists"))
    if k == "score" and len(args) >= 4:
        if args[3] == "matches":
            return f"{_who(args[1], lang)} の「{args[2]}」が {args[4] if len(args) > 4 else '?'}" if lang == "ja" else                 f"{_who(args[1], lang)}'s {args[2]} is in {args[4] if len(args) > 4 else '?'}"
        return " ".join(args[1:])
    if k == "block" and len(args) >= 5:
        return (f"{' '.join(args[1:4])} が {args[4]}" if lang == "ja" else f"block at {' '.join(args[1:4])} is {args[4]}")
    return " ".join(args)[:60]


def _exec_prefix(parts, lang: str) -> str:
    out = ""
    for name, args in parts:
        if name not in EXEC_JA:
            continue
        if name == "as" or name == "at":
            arg = _who(args[0], lang) if args else "?"
        elif name in ("if", "unless"):
            arg = _cond(args, lang)
        elif name == "store" and len(args) > 1:
            what = {"result": ("結果", "result"), "success": ("成否", "success")}.get(args[0], (args[0], args[0]))
            where = " ".join(args[1:])
            out += (f"{what[0]}を {where} に入れつつ、" if lang == "ja" else f"storing the {what[1]} in {where}, ")
            continue
        else:
            arg = " ".join(args)[:50]
        out += (EXEC_JA if lang == "ja" else EXEC_EN)[name].format(arg) + ("、" if lang == "ja" else "")
    return out


def _q(text: str, lang: str) -> str:
    return f"「{text}」" if lang == "ja" else f' "{text}"'


def _t(key: str, lang: str, *args) -> str:
    ja, en = T[key]
    return (ja if lang == "ja" else en).format(*args)


def _who(sel: str, lang: str) -> str:
    base = sel.split("[")[0]
    if base in TARGET:
        return TARGET[base][0 if lang == "ja" else 1] + (sel[len(base):] if "[" in sel else "")
    return sel


def describe(cmd: str, lang: str = "ja") -> str:
    c = cmd.strip().lstrip("/")
    prefix = ""
    m0 = re.match(r"execute\s+as\s+([A-Za-z0-9_]{3,16})\s+(?:at\s+@s\s+)?run\s+(.*)$", c)
    if m0:  # a plain "run as this player": say the player's name instead of "the executor"
        return describe(m0.group(2).replace("@s", m0.group(1)), lang)
    if c.startswith("execute "):
        parts, rest = parse_execute(split_args(c))
        prefix = _exec_prefix(parts, lang)
        if not rest:
            return prefix.rstrip("、, ") + ("(実行するコマンドが無い・条件だけを確かめる)" if lang == "ja" else " (only checks the condition)")
        c = " ".join(rest)
    w = split_args(c)
    if not w:
        return prefix
    head = w[0]
    try:
        if head == "say":
            s = _t("say", lang, " ".join(w[1:]))
        elif head == "tellraw":
            s = _t("tellraw", lang, _who(w[1], lang)) + (_q(json_text(' '.join(w[2:])), lang) if len(w) > 2 else "")
        elif head == "title":
            kinds = {"title": ("大きな文字", "title"), "subtitle": ("小さな文字", "subtitle"), "actionbar": ("アクションバー", "action bar")}
            k = kinds.get(w[2], (w[2], w[2]))[0 if lang == "ja" else 1]
            s = _t("title", lang, _who(w[1], lang), k) + (_q(json_text(' '.join(w[3:])), lang) if len(w) > 3 else "")
        elif head == "scoreboard" and w[1] == "objectives":
            s = {"add": lambda: _t("obj_add", lang, w[3]), "remove": lambda: _t("obj_rm", lang, w[3]),
                 "setdisplay": lambda: _t("obj_display", lang, w[3], w[4] if len(w) > 4 else "")}.get(w[2], lambda: _t("generic", lang, head))()
        elif head == "scoreboard" and w[1] == "players":
            op = w[2]
            if op in ("add", "remove", "set"):
                s = _t({"add": "sc_add", "remove": "sc_remove", "set": "sc_set"}[op], lang, _who(w[3], lang), w[4], w[5])
            elif op == "get":
                s = _t("sc_get", lang, _who(w[3], lang), w[4])
            elif op == "reset":
                s = _t("sc_reset", lang, _who(w[3], lang))
            else:
                s = _t("generic", lang, f"scoreboard players {op}")
        elif head == "team":
            s = {"add": lambda: _t("team_add", lang, w[2]), "join": lambda: _t("team_join", lang, w[2], _who(" ".join(w[3:]) or "@s", lang)),
                 "leave": lambda: _t("team_leave", lang, _who(w[2], lang)), "modify": lambda: _t("team_modify", lang, w[2], w[3])}.get(
                w[1], lambda: _t("generic", lang, head))()
        elif head == "function":
            s = _t("function", lang, w[1])
        elif head == "give":
            s = _t("give", lang, _who(w[1], lang), " ".join(w[2:]))
        elif head in ("tp", "teleport"):
            s = _t("tp", lang, _who(w[1], lang))
        elif head == "gamemode":
            s = _t("gamemode", lang, w[1], _who(w[2] if len(w) > 2 else "@s", lang))
        elif head in ("setblock",):
            s = _t("setblock", lang, " ".join(w[1:4]))
        elif head in ("summon",):
            s = _t("summon", lang, w[1])
        elif head in ("kill", "clear", "effect", "tag"):
            s = _t(head, lang, _who(w[1] if head != "effect" else w[2] if len(w) > 2 else "", lang))
        elif head in ("data", "schedule"):
            s = _t(head, lang, w[1] if head == "data" else " ".join(w[2:3]))
        elif head == "gamerule":
            s = _t("gamerule", lang, w[1], w[2] if len(w) > 2 else "?")
        elif head == "playsound":
            s = _t("playsound", lang, w[1], _who(w[3] if len(w) > 3 else "", lang))
        elif head == "bossbar":
            op = w[1]
            if op == "add":
                s = _t("bb_add", lang, w[2])
            elif op == "remove":
                s = _t("bb_remove", lang, w[2])
            elif op == "set":
                key = {"value": "bb_value", "max": "bb_max", "players": "bb_players", "color": "bb_color", "name": "bb_name"}.get(w[3])
                arg = _who(w[4], lang) if w[3] == "players" and len(w) > 4 else (w[4] if len(w) > 4 else "")
                s = _t(key, lang, w[2], arg) if key else _t("bossbar", lang)
            else:
                s = _t("bossbar", lang)
        elif head in ("fill", "reload"):
            s = _t(head, lang)
        else:
            s = _t("generic", lang, head)
    except IndexError:
        s = _t("generic", lang, head)
    if prefix and lang == "en":
        s = s[:1].lower() + s[1:]
    return prefix + s


def error_location(cmd: str, server_reply: str, lang: str = "ja") -> str:
    """Minecraft marks the bad spot as '...text<--[HERE]'. Turn it into a column and the nearby text."""
    m = re.search(r"\.\.\.(.*?)<--\[HERE\]", server_reply) or re.search(r"(\S*?)<--\[HERE\]", server_reply)
    if not m:
        return ""
    tail = m.group(1)
    col = cmd.find(tail.lstrip(".")) + len(tail.lstrip(".")) if tail.lstrip(".") and tail.lstrip(".") in cmd else -1
    return _t("where", lang, col if col >= 0 else "?", tail.strip()[-30:])


FUNC_ERR = re.compile(r"Failed to load function ([\w:/.-]+)|Couldn't (?:load|parse) function ([\w:/.-]+)|"
                      r"Whilst parsing command on line (\d+): (.*)")


def function_errors(log_lines: list[str]) -> list[str]:
    """Pick the data pack load errors (which function, which line, why) out of the server log after /reload."""
    out = []
    for line in log_lines:
        if FUNC_ERR.search(line) or ("ERROR" in line and "function" in line.lower()):
            out.append(line.split("]: ", 1)[-1].strip())
    return out[-50:]
