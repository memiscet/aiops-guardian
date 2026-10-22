"""Layered handling of untrusted text (container logs, event messages, termination and condition messages).

Detection is only one layer and is explicitly incomplete (a keyword or phrase list can never cover every language or phrasing). The layers are:
  1. signals(): language-aware phrase lists (English plus a dozen languages), role markers and chat-template tokens, references to the control
     vocabulary (our action identifiers, kubectl verbs), JSON/YAML text that imitates analyst or reviewer output, and obfuscation (invisible or
     bidirectional characters, mixed-script words). Used to flag and to tighten behavior, never to loosen it.
  2. defang(): removes obfuscation characters, neutralizes role markers and analyst-shaped JSON/YAML so the text cannot pose as protocol.
  3. Structural controls elsewhere that do not depend on detection: untrusted text can never be the basis of a diagnosis (guardrails.py),
     remediation proposals are held when injection is suspected or when an action name is echoed from untrusted text (workflow.py), the action
     policy and approval gate are deterministic, and the reviewer can only tighten.
"""
import json
import re
import unicodedata

PROTECTED_KEYS = frozenset({"category", "action", "verdict", "findings", "decision", "approved", "root_cause", "confidence", "plan", "evidence",
                            "severity", "uncertainty", "diagnosis", "review", "resume"})
HIGH_RISK_KEYS = frozenset({"verdict", "approved", "decision", "findings", "root_cause"})
HIGH_RISK_VALUES = frozenset({"pass", "fail", "approve", "approved", "reject", "rejected", "denied", True, False})
ACTION_IDS = ("delete_namespace", "delete_cluster", "delete_pvc", "exec_shell", "restart_deployment", "rollback_deployment",
              "change_memory_limit", "collect_logs", "create_report")
_CONFUSABLES = str.maketrans({"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "һ": "h",
                              "ɡ": "g", "ο": "o", "ρ": "p", "ν": "v", "ι": "i", "α": "a", "ε": "e", "τ": "t", "κ": "k", "ı": "i", "ӏ": "l"})
_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\u00ad\U000e0000-\U000e007f]")

_EN = re.compile(
    r"(ignore (all |any )?(previous|prior|above)|disregard (the )?(previous|above|instructions)|system prompt|you are now|new instructions|"
    r"\bassistant\s*:|\bsystem\s*:|kubectl\s+(delete|exec|apply|patch|scale)|rm\s+-rf|approve (the )?(action|request)|set (confidence|action)|"
    r"note to (the )?(ai|assistant|analyst|model)|forget (all |everything|your)|override (the )?(policy|safety|instructions))")

# Folded-text patterns (lower case, accents removed, homoglyphs mapped). Languages deliberately NOT listed (for example Polish, Hindi, Swahili)
# are covered only by the structural layers; tests rely on that.
_PHRASES = {
    "de": r"(ignorier\w*|vergiss\w*|missachte\w*|uberspring\w*)\s+(sie\s+|bitte\s+)?(alle[ns]?\s+|die\s+|samtliche\s+)?(vorherigen?\s+|bisherigen?\s+|fruheren?\s+)?(anweisungen|instruktionen|befehle|regeln|vorgaben)|"
          r"(alle|die|samtliche)\s+(vorherigen\s+|bisherigen\s+)?(anweisungen|instruktionen|befehle|regeln)\s+(vergessen|ignorieren|missachten)|neue\s+(anweisungen|instruktionen)",
    "fr": r"(ignor\w+|oubli\w+|neglig\w+)\s+(toutes?\s+)?(les\s+|vos\s+|tes\s+)?(instructions?|consignes?|regles?)(\s+(precedentes?|anterieures?))?",
    "es": r"(ignor\w+|olvid\w+)\s+(todas?\s+)?(las\s+|tus\s+)?(instrucciones|ordenes|reglas)(\s+(anteriores|previas))?",
    "pt": r"(ignor\w+|esquec\w+)\s+(todas?\s+)?(as\s+)?(instrucoes|ordens|regras)",
    "it": r"(ignor\w+|dimentic\w+)\s+(tutte\s+)?(le\s+)?(istruzioni|regole)",
    "nl": r"(negeer|vergeet)\s+(alle\s+)?(vorige\s+|eerdere\s+)?(instructies|opdrachten|regels)",
    "tr": r"(onceki|tum|butun)\s+(talimatlari|talimatlar|yonergeleri|komutlari)\s+(yoksay|unut|gormezden)\w*|(yoksay|unut)\w*\s+(tum\s+|onceki\s+)?(talimat|yonerge|komut)",
    "ru": r"(игнорир\w+|забудь\w*|не\s+учитывай\w*)\s+(все\s+|всё\s+)?(предыдущие\s+|прежние\s+|прошлые\s+)?(инструкции|указания|команды|правила)",
    "zh": r"(忽略|无视|忽视|忘记|無視|忘記).{0,8}(指令|指示|说明|說明|规则|規則|提示)",
    "ja": r"(以前|これまで|前).{0,4}(指示|命令|指令).{0,4}(無視|忘れ)|(無視|忘れ).{0,6}(指示|命令)",
    "ko": r"(이전|모든).{0,6}(지시|명령).{0,6}(무시|잊)",
    "ar": r"(تجاهل|انس)\w*\s+.{0,12}(التعليمات|الأوامر)",
}
_NATIVE = {"ru", "zh", "ja", "ko", "ar"}
_LATIN_RES = [re.compile(p) for k, p in _PHRASES.items() if k not in _NATIVE]
_NATIVE_RES = [re.compile(p) for k, p in _PHRASES.items() if k in _NATIVE]
_ROLE_LINE = re.compile(r"(?im)^\s*(system|assistant|developer)\s*[:>\]]")
_CHAT_TOKENS = re.compile(r"(?i)<\|[a-z_]+\|>|\[/?inst\]|<</?sys>>|</?s>|</?system>|</?assistant>|^#{2,3}\s*(system|instruction)s?\b", re.M)
_VOCAB = re.compile(r"(?i)\b(" + "|".join(ACTION_IDS) + r")\b|kubectl\s+(delete|exec|apply|patch|scale|edit|drain|cordon|replace|create)\b")
_ID_SPOOF = re.compile(r"\[(?:[FMDL]\d{1,3}(?:\.\d{1,3})?)(?: [TUQD])?\]|(?m:^[FMD]\d{1,3} [TUQD] \| )")
_YAML_KEY = re.compile(r"(?im)^\s*[\"']?(" + "|".join(sorted(PROTECTED_KEYS)) + r")[\"']?\s*[:=]\s*\S")


def fold(text: str, latin_accents: bool = True) -> str:
    """Canonical form for matching: NFKC, invisible characters removed, homoglyphs mapped, case-folded, Latin accents removed."""
    t = unicodedata.normalize("NFKC", _INVISIBLE.sub("", text)).translate(_CONFUSABLES).casefold()
    if latin_accents:
        t = "".join(ch for ch in unicodedata.normalize("NFD", t) if not 0x300 <= ord(ch) <= 0x36f).replace("ß", "ss")
        t = unicodedata.normalize("NFC", t)
    return t


def _scripts(word: str) -> set[str]:
    out = set()
    for ch in word:
        if ch.isalpha():
            name = unicodedata.name(ch, "")
            for script in ("LATIN", "CYRILLIC", "GREEK"):
                if name.startswith(script):
                    out.add(script)
    return out


def _json_objects(text: str, limit: int = 200):
    """Yield (start, end, obj) for JSON objects embedded anywhere in text (also double-escaped JSON via the caller)."""
    dec, i, seen = json.JSONDecoder(), text.find("{"), 0
    while i != -1 and seen < limit:
        seen += 1
        try:
            obj, end = dec.raw_decode(text[i:])
        except ValueError:
            i = text.find("{", i + 1)
            continue
        if isinstance(obj, dict):
            yield i, i + end, obj
            i = text.find("{", i + end)
        else:
            i = text.find("{", i + 1)


def _is_spoof(obj) -> bool:
    if isinstance(obj, list):
        return any(_is_spoof(x) for x in obj)
    if not isinstance(obj, dict):
        return False
    keys = {k.lower() for k in obj if isinstance(k, str)}
    if len(keys & PROTECTED_KEYS) >= 2:
        return True
    if any(k in HIGH_RISK_KEYS and (v.lower() if isinstance(v, str) else v) in HIGH_RISK_VALUES for k, v in ((k.lower(), obj[k]) for k in obj if isinstance(k, str)) if not isinstance(v, (dict, list))):
        return True
    return any(_is_spoof(v) for v in obj.values())


def _unescaped(text: str) -> str:
    return text.replace('\\"', '"') if '\\"' in text else text


def signals(text: str) -> list[str]:
    """Names of the (non-exclusive) warning signals found in the text. Empty does NOT mean safe."""
    found: list[str] = []
    folded = fold(text)
    native = unicodedata.normalize("NFKC", _INVISIBLE.sub("", text)).casefold()
    if _EN.search(folded):
        found.append("instruction-phrase-en")
    if any(p.search(folded) for p in _LATIN_RES) or any(p.search(native) for p in _NATIVE_RES):
        found.append("instruction-phrase-multilingual")
    if _ROLE_LINE.search(text) or _CHAT_TOKENS.search(text):
        found.append("role-marker")
    if _VOCAB.search(folded):
        found.append("control-vocabulary")
    probe = _unescaped(text)
    if any(_is_spoof(o) for _, _, o in _json_objects(probe)) or len(_YAML_KEY.findall(probe)) >= 2:
        found.append("role-spoof-structure")
    if _ID_SPOOF.search(text):
        found.append("evidence-id-spoof")
    if _INVISIBLE.search(text):
        found.append("obfuscation-chars")
    if any(len(_scripts(w)) > 1 for w in re.findall(r"\w+", text)[:2000]):
        found.append("mixed-script")
    return found


def defang(text: str) -> tuple[str, list[str]]:
    """Neutralize obfuscation, role markers and analyst-shaped JSON/YAML. Returns (text, signals that were acted on)."""
    acted: list[str] = []
    clean = _INVISIBLE.sub("", text)
    if clean != text:
        acted.append("obfuscation-chars")
    probe = _unescaped(clean)
    spans = [(s, e, o) for s, e, o in _json_objects(probe) if _is_spoof(o)]
    if spans:
        out, pos = [], 0
        for s, e, o in spans:
            out += [probe[pos:s], f"[defanged JSON that imitates analyst output; keys: {', '.join(sorted(str(k) for k in o)[:8])}]"]
            pos = e
        clean = "".join(out) + probe[pos:]
        acted.append("role-spoof-structure")
    if len(_YAML_KEY.findall(clean)) >= 2:
        clean = _YAML_KEY.sub("[defanged analyst-style key]", clean)
        if "role-spoof-structure" not in acted:
            acted.append("role-spoof-structure")
    spoofless = _ID_SPOOF.sub("[id-like text removed]", clean)
    if spoofless != clean:
        acted.append("evidence-id-spoof")
        clean = spoofless
    new = _ROLE_LINE.sub("[role-prefix removed]", clean)
    new = _CHAT_TOKENS.sub("[chat-token removed]", new)
    if new != clean:
        acted.append("role-marker")
    return new, acted


def action_echo(action: str, untrusted_text: str) -> bool:
    """True if the proposed action's identifier appears in untrusted text (language-independent: identifiers are protocol tokens)."""
    return bool(action) and action.lower() in fold(untrusted_text, latin_accents=False)
