"""Say what a command does, in Japanese or English, and point at where an error is.

Rule-based on purpose: it runs offline and instantly for every step. Unknown commands get a generic line.
"""
from __future__ import annotations

import re

T = {
    "say": ("全員のチャットに「{0}」と表示する", "Show \"{0}\" in everyone's chat"),
    "tellraw": ("{0} に文字を表示する(tellraw)", "Show formatted text to {0} (tellraw)"),
    "title": ("{0} の画面に {1} を表示する", "Show a {1} on {0}'s screen"),
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
    "give": ("{0} に {1} を渡す", "Give {1} to {0}"),
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
    # peel execute ... run
    while c.startswith("execute "):
        m = re.match(r"execute\s+(.*?)\s+run\s+(.*)$", c)
        if not m:
            return _t("generic", lang, "execute")
        mods, c = m.group(1), m.group(2)
        for kind, arg in re.findall(r"\b(as|if|unless)\s+(\S+(?:\s+\S+){0,3})", mods):
            key = {"as": "execute_as", "if": "execute_if", "unless": "execute_unless"}[kind]
            prefix += _t(key, lang, _who(arg.split()[0], lang) if kind == "as" else arg)
    w = c.split()
    if not w:
        return prefix
    head = w[0]
    try:
        if head == "say":
            s = _t("say", lang, " ".join(w[1:]))
        elif head == "tellraw":
            s = _t("tellraw", lang, _who(w[1], lang))
        elif head == "title":
            kinds = {"title": ("大きな文字", "title"), "subtitle": ("小さな文字", "subtitle"), "actionbar": ("アクションバー", "action bar")}
            k = kinds.get(w[2], (w[2], w[2]))[0 if lang == "ja" else 1]
            s = _t("title", lang, _who(w[1], lang), k)
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
        elif head in ("fill", "reload", "bossbar"):
            s = _t(head, lang)
        else:
            s = _t("generic", lang, head)
    except IndexError:
        s = _t("generic", lang, head)
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
