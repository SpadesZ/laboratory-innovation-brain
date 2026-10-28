"""Structural bilingual parity of one research report's renderings (G0-B, G0-P): an offline check.

WHAT THIS CHECKS, AND WHAT IT CANNOT. Given the English and the Traditional Chinese rendering of
the same report on the same surface (the episode page, the exported summary, `report.md`), it
checks that the two say the same things structurally: every element one rendering shows, the other
shows, in the same place and non-empty; every number with its sign and unit, every identifier and
digest, every stored status and its words (from the product's own `i18n` table), every negation and
every confirmation claim, is the same in both; every simulation that could not run is labelled not
performed, with its reason and what it needs, in both; and the translated rendering is really in
the other language. It does not and cannot judge whether a sentence is a GOOD translation: a
fluent wrong rendering with the same numbers, identifiers and negations passes. Genuine semantic
quality of bilingual scientific prose needs an independent bilingual reviewer.

HOW THE HTML IS COMPARED. Each L1/L2/L3 section (`<section id="v-...">` / `<details id="v-...">`)
is parsed into its blocks -- paragraphs, list items, cells, headings, quotes, and the spans that
carry meaning (a stored status, a line's kind, an identifier in a tooltip) -- and the two
renderings' blocks are aligned in document order by their shape. Locale-only markup is not part
of the shape: the "(untranslated)" marker, its `lang="en"` wrapper, and each locale's own table of
renderings beside their originals (`v.l3.originals`), which instead supplies the curated pairs
the negation check reads. A shape that differs is reported where it first diverges; when shapes
agree, each aligned pair is compared field by field.

NOTHING HERE READS OR WRITES THE RECORD, except `canonical_snapshot`, which only reads: a digest of
every row of every table, so a caller can show that rendering both languages changed no record.
"""

from __future__ import annotations

import functools
import hashlib
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from lab_brain.interfaces.web.i18n import Messages, templates
from lab_brain.interfaces.web.i18n import keys as message_keys
from lab_brain.research.report import EpisodeReport

EN = "en"
ZH = "zh-TW"

#: The checks, by name, as findings name them.
CHECKS = (
    "STRUCTURE",
    "COVERAGE",
    "NON_EMPTY",
    "NUMBERS",
    "IDENTIFIERS",
    "STATUS",
    "NEGATION",
    "CLAIM",
    "NOT_PERFORMED",
    "LANGUAGE",
    "SINGLE_LANGUAGE",
    "CITATIONS",
    "ORIGINAL",
    "CANONICAL",
)

#: The science content categories (G0-B) and where each lives on an HTML rendering: the sections
#: whose blocks carry it, and the line-kind tag (`pages._tag`) that marks it, if any.
CATEGORIES: Mapping[str, tuple[tuple[str, ...], str | None]] = {
    "hypotheses": (("hypotheses", "support"), "hyp"),
    "predictions": (("support", "next"), "pred"),
    "observations": (("tested", "support"), "obs"),
    "interpretations": (("support", "reasoning"), "interp"),
    "conclusions": (("result",), None),
    "uncertainty": (("why",), None),
    "limitations": (("why",), None),
    "citations": (("reasoning", "citations"), None),
    "next_steps": (("next",), None),
}

#: The status families `pages.status` renders: `<span class="state state-V fam-V" title="V">`.
_FAMILIES = ("bs", "cs", "ws", "ep", "rt", "es", "ps", "so")

#: Sections whose zh-TW text must be in Chinese, or shown in English and marked untranslated.
_READ_IN_LOCALE = ("result", "hypotheses", "tested", "support", "why", "next")

_BLOCK_TAGS = frozenset(
    {"p", "li", "td", "th", "h2", "h3", "blockquote", "summary", "dt", "dd", "pre"}
)
_VOID = frozenset({"br", "hr", "img", "input", "meta", "link", "col", "wbr"})
#: Elements whose text is never run together with their neighbours' when flattened.
_SEPARATED = _BLOCK_TAGS | {"div", "ul", "ol", "tr", "table", "section", "details", "br"}

_CJK = re.compile(r"[㐀-鿿豈-﫿]")
_LATIN_WORD = re.compile(r"[A-Za-z]{3,}")
_NUMBER = re.compile(
    r"(?<![\w.])(?P<sign>[-+−])?(?P<value>\d+(?:[.,]\d+)*(?:[eE][-+]?\d+)?)"
    r"(?:\s?(?P<unit>(?:[kMGTmunpfµ]?(?:Ω|ohm|Hz|eV|V|A|F|W|m|s|S)|dBm?|%|°C|K)"
    r"(?:[·/*][A-Za-zµΩ]+\d?)*)(?![A-Za-z]))?"
)
_IDENT = re.compile(
    r"\b(?:sha256:[0-9a-f]{16,}|[a-z][a-z0-9_]{1,15}:[A-Za-z0-9][A-Za-z0-9._:/@-]*[A-Za-z0-9])"
)
_EN_NEGATION = re.compile(
    r"\b(?:not|no|never|none|neither|nor|without|cannot|nothing|nobody|nowhere)\b|n't\b"
    r"|\bun(?!der|til|it\b|its\b|ion|ique|iform|iversal|less|like)[a-z]{3,}\b"
    r"|\bdis(?:continuous|continuity|continuities|agrees?|agreement|connected|proved?)\b"
    r"|\bin(?:conclusive|sufficient|consistent|correct|valid|complete|sensitive|variant)\b",
    re.IGNORECASE,
)
_ZH_NEGATION = re.compile(r"[不沒未無非否]")
_EN_CONFIRM = re.compile(r"\bconfirm(?:s|ed|ing|ation|ations)?\b", re.IGNORECASE)
_ZH_CONFIRM = re.compile(r"確認")
_GLOSS = re.compile(r"（[^（）\u3400-\u9fff]*）")
_LATIN_RUN = re.compile(r"[A-Za-z]+")
#: Chinese words that carry a negation character but negate nothing.
_ZH_NOT_NEGATIONS = ("否證", "是否", "無論", "非常")


@dataclass(frozen=True)
class Finding:
    """One way the two renderings disagree. `check` is one of `CHECKS`."""

    check: str
    where: str
    detail: str


@dataclass(frozen=True)
class Unavailable:
    """A verification action that could not run here, as the canonical report records it."""

    capability_id: str
    reason: str
    requires: str


@dataclass(frozen=True)
class ParityResult:
    """The parity of one surface's two renderings."""

    surface: str
    findings: tuple[Finding, ...]
    #: category -> (blocks in English, blocks in zh-TW).
    coverage: Mapping[str, tuple[int, int]] = field(default_factory=dict)
    #: Aligned block pairs compared field by field.
    aligned: int = 0
    #: zh-TW passages shown in English and marked untranslated (honest, not a finding).
    untranslated: int = 0

    @property
    def ok(self) -> bool:
        return not self.findings

    def checks(self) -> frozenset[str]:
        return frozenset(f.check for f in self.findings)


def unavailable_simulations(report: EpisodeReport) -> tuple[Unavailable, ...]:
    """Every pending action the report names as unable to run here -- what both languages must
    label not performed, with its reason and what it needs."""
    return tuple(
        Unavailable(p.capability_id, p.blocked_because, p.requires) for p in report.pending
    )


# -- a light tree ---------------------------------------------------------------------------------


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str]
    children: list[_Node | str] = field(default_factory=list)

    @property
    def classes(self) -> tuple[str, ...]:
        return tuple(self.attrs.get("class", "").split())

    def text(self, *, skip_marked: bool = False) -> str:
        parts: list[str] = []
        for child in self.children:
            if isinstance(child, str):
                parts.append(child)
            elif skip_marked and "untr" in child.classes:
                continue
            elif child.tag in _SEPARATED:
                parts.append(" " + child.text(skip_marked=skip_marked) + " ")
            else:
                parts.append(child.text(skip_marked=skip_marked))
        return "".join(parts)

    def walk(self) -> Iterable[_Node]:
        yield self
        for child in self.children:
            if isinstance(child, _Node):
                yield from child.walk()


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {})
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag, {k: v or "" for k, v in attrs})
        self._stack[-1].children.append(node)
        if tag not in _VOID:
            self._stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        for depth in range(len(self._stack) - 1, 0, -1):
            if self._stack[depth].tag == tag:
                del self._stack[depth:]
                return

    def handle_data(self, data: str) -> None:
        self._stack[-1].children.append(data)


def _parse(markup: str) -> _Node:
    builder = _Builder()
    builder.feed(markup)
    builder.close()
    return builder.root


def _sections(root: _Node) -> dict[str, _Node]:
    found: dict[str, _Node] = {}
    for node in root.walk():
        key = node.attrs.get("id", "")
        if node.tag in ("section", "details") and key.startswith("v-"):
            found.setdefault(key[2:], node)
    return found


def _flat(text: str) -> str:
    return " ".join(text.split())


# -- the shape of a section -----------------------------------------------------------------------


def _status_of(node: _Node) -> tuple[str, str] | None:
    """(family, stored value) of a `pages.status` span, or None."""
    if node.tag != "span" or "state" not in node.classes:
        return None
    value = node.attrs.get("title") or _flat(node.text())
    family = next((c.split("-", 1)[0] for c in node.classes if c.split("-", 1)[0] in _FAMILIES), "")
    return family, value


def _shape(node: _Node) -> str | None:
    """A block's shape, without anything a language changes; None: not a block."""
    if node.tag == "span":
        if "untr" in node.classes:
            return None
        if "state" in node.classes:
            status = _status_of(node)
            return f"span.state.{status[0] if status else ''}"
        if "tag" in node.classes:
            return "span." + ".".join(c for c in node.classes if c.startswith("tag-"))
        if "title" in node.attrs:
            return "span[title]"
        return None
    if node.tag == "code":
        return "code"
    if node.tag in _BLOCK_TAGS:
        return node.tag
    if node.tag in ("div", "section", "details", "ul", "ol", "table") and node.classes:
        return node.tag + "." + ".".join(sorted(node.classes))
    return None


def _without_originals(section: _Node, locale: str) -> _Node:
    """The section without this locale's table of renderings beside their originals (`h3`
    `v.l3.originals` up to the next `h3`): that table exists to differ between locales."""
    m = Messages(locale)
    heading = m("v.l3.originals")
    kept: list[_Node | str] = []
    skipping = False
    for child in section.children:
        if isinstance(child, _Node) and child.tag == "h3":
            skipping = _flat(child.text()) == heading
        if not skipping:
            kept.append(
                _without_rows(
                    child, {m("sum.untranslated"), m("sum.exported"), m("sum.source_lang")}
                )
            )
    return _Node(section.tag, section.attrs, kept)


def _without_rows(node: _Node | str, labels: set[str]) -> _Node | str:
    """The node without table rows headed by one of `labels`: the count of passages shown
    untranslated, which is the locale's by construction (none in the language research is
    written in), when this rendering was made, which is each rendering's own moment, and the
    digest of `report.md` in this rendering's language, which is each language's own file (both
    languages name the SAME record export digest, compared as usual)."""
    if isinstance(node, str):
        return node
    kept: list[_Node | str] = []
    for child in node.children:
        if isinstance(child, _Node) and child.tag == "tr":
            cells = [c for c in child.children if isinstance(c, _Node) and c.tag in ("td", "th")]
            if cells and _flat(cells[0].text()) in labels:
                continue
        kept.append(_without_rows(child, labels))
    return _Node(node.tag, node.attrs, kept)


def _originals(section: _Node, locale: str) -> list[tuple[str, str]]:
    """(rendering shown, original) pairs from the originals table, in this locale."""
    heading = Messages(locale)("v.l3.originals")
    pairs: list[tuple[str, str]] = []
    inside = False
    for child in section.children:
        if isinstance(child, _Node) and child.tag == "h3":
            inside = _flat(child.text()) == heading
        elif inside and isinstance(child, _Node):
            for row in child.walk():
                if row.tag == "tr":
                    cells = [c for c in row.children if isinstance(c, _Node) and c.tag == "td"]
                    if len(cells) >= 2:
                        pairs.append((_flat(cells[0].text()), _flat(cells[1].text())))
    return pairs


@dataclass(frozen=True)
class _Block:
    shape: str
    path: str
    text: str
    #: Text without status/tag/identifier spans, codes and untranslated markers: the prose.
    prose: str
    titles: tuple[str, ...]
    codes: tuple[str, ...]
    status: tuple[str, str] | None
    marked: int


def _prose(node: _Node) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag == "code" or (
            child.tag == "span"
            and ({"untr", "state", "tag"} & set(child.classes) or "title" in child.attrs)
        ):
            parts.append(" ")
        elif child.tag in _SEPARATED:
            parts.append(" " + _prose(child) + " ")
        else:
            parts.append(_prose(child))
    return "".join(parts)


def _blocks(section: _Node, key: str) -> list[_Block]:
    out: list[_Block] = []

    def visit(node: _Node, path: str) -> None:
        shape = _shape(node)
        here = f"{path}/{shape}" if shape else path
        if shape is not None and node is not section:
            out.append(
                _Block(
                    shape=shape,
                    path=here,
                    text=_flat(node.text(skip_marked=True)),
                    prose=_flat(_prose(node)),
                    titles=tuple(
                        n.attrs["title"]
                        for n in node.walk()
                        if "title" in n.attrs and n.tag != "time"
                    ),
                    codes=tuple(_flat(n.text()) for n in node.walk() if n.tag == "code"),
                    status=_status_of(node),
                    marked=sum(1 for n in node.walk() if "untr" in n.classes),
                )
            )
        for child in node.children:
            if isinstance(child, _Node) and child.tag not in ("form", "script", "style"):
                visit(child, here)

    visit(section, f"v-{key}")
    return out


# -- field comparisons ----------------------------------------------------------------------------


def numbers(text: str) -> Counter[str]:
    """Every number with its sign and unit, as a multiset. Identifiers are not numbers."""
    cleaned = _IDENT.sub(" ", text)
    found: Counter[str] = Counter()
    for m in _NUMBER.finditer(cleaned):
        sign = "-" if m.group("sign") in ("-", "−") else (m.group("sign") or "")
        unit = (m.group("unit") or "").replace("ohm", "Ω").replace("u", "µ", 1)
        found[f"{sign}{m.group('value')}{unit}"] += 1
    return found


def identifiers(text: str) -> Counter[str]:
    """Every identifier and digest the text names, as a multiset."""
    return Counter(_IDENT.findall(text))


def negations(text: str) -> int:
    """How many negations the text makes: English markers in its Latin text, Chinese ones in its
    Chinese text. A curated rendering's English gloss -- `不連續（discontinuous）` -- is not
    counted again, and nor are the lexicalised compounds that negate nothing (`否證`, falsify)."""
    plain = _GLOSS.sub(" ", text).replace("_", " ")
    for compound in _ZH_NOT_NEGATIONS:
        plain = plain.replace(compound, " ")
    return len(_EN_NEGATION.findall(plain)) + len(_ZH_NEGATION.findall(plain))


def confirmations(text: str) -> int:
    """How many times the text speaks of confirming -- the strongest claim the product makes."""
    plain = _GLOSS.sub(" ", text)
    return len(_EN_CONFIRM.findall(plain)) + len(_ZH_CONFIRM.findall(plain))


@functools.cache
def _template_fragments() -> tuple[str, ...]:
    """The fixed words of every interface message in every locale (`i18n`), longest first: the
    product's own sentences, a reviewed vocabulary pair rather than report content, so they are
    taken out before negations and claims are counted. Only messages of at least four words in
    English AND six characters in Chinese, and never a status's words (compared as the stored
    status), so a content word is not taken for a template in one language only."""
    found: set[str] = set()
    for key in message_keys():
        if key.split(".", 1)[0] in _FAMILIES:
            continue  # a stored status's words: compared as the status, never as prose
        english, chinese = templates(key)
        if len(_LATIN_RUN.findall(english)) < 4 or len(_CJK.findall(chinese)) < 6:
            continue  # too short to be told from content in one language or the other
        for template in (english, chinese):
            for fragment in re.split(r"\{[^}]*\}", template):
                fragment = " ".join(fragment.split())
                if len(_CJK.findall(fragment)) >= 2 or len(_LATIN_RUN.findall(fragment)) >= 2:
                    found.add(fragment)
    return tuple(sorted(found, key=len, reverse=True))


def content(text: str) -> str:
    """The text without the interface's own sentences: what the report or the pack says."""
    for fragment in _template_fragments():
        if fragment in text:
            text = text.replace(fragment, " ")
    return " ".join(text.split())


def _diff(a: Counter[str], b: Counter[str]) -> str:
    only_a = sorted((a - b).elements())
    only_b = sorted((b - a).elements())
    return f"English only {only_a}; zh-TW only {only_b}"


def _words(family: str, value: str, locale: str) -> str | None:
    try:
        return Messages(locale)(f"{family}.{value}")
    except KeyError:
        return None


def _compare(en: _Block, zh: _Block, findings: list[Finding]) -> None:
    where = en.path
    if bool(en.text) != bool(zh.text):
        findings.append(
            Finding("NON_EMPTY", where, f"English {en.text[:80]!r}; zh-TW {zh.text[:80]!r}")
        )
    if en.status != zh.status:
        findings.append(Finding("STATUS", where, f"English {en.status}; zh-TW {zh.status}"))
    elif en.status is not None and en.status[0]:
        family, value = en.status
        for locale, block in ((EN, en), (ZH, zh)):
            expected = _words(family, value, locale)
            if expected is not None and block.text != expected:
                findings.append(
                    Finding(
                        "STATUS",
                        where,
                        f"{locale} says {block.text!r} for {family}.{value}; "
                        f"the product's words are {expected!r}",
                    )
                )
    if Counter(en.titles) != Counter(zh.titles) or Counter(en.codes) != Counter(zh.codes):
        findings.append(
            Finding(
                "IDENTIFIERS",
                where,
                _diff(Counter(en.titles + en.codes), Counter(zh.titles + zh.codes)),
            )
        )
    elif identifiers(en.text) != identifiers(zh.text):
        findings.append(
            Finding("IDENTIFIERS", where, _diff(identifiers(en.text), identifiers(zh.text)))
        )
    if numbers(en.text) != numbers(zh.text):
        findings.append(Finding("NUMBERS", where, _diff(numbers(en.text), numbers(zh.text))))
    if en.shape in ("span[title]", "code") or en.status is not None:
        return
    en_said, zh_said = content(en.prose), content(zh.prose)
    if negations(en_said) != negations(zh_said):
        findings.append(
            Finding(
                "NEGATION",
                where,
                f"English {negations(en_said)} in {en_said[:90]!r}; "
                f"zh-TW {negations(zh_said)} in {zh_said[:90]!r}",
            )
        )
    if confirmations(en_said) != confirmations(zh_said):
        findings.append(
            Finding(
                "CLAIM",
                where,
                f"English speaks of confirming {confirmations(en_said)} time(s), "
                f"zh-TW {confirmations(zh_said)}: {zh_said[:90]!r}",
            )
        )


def _coverage(blocks: Mapping[str, Sequence[_Block]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for category, (keys, tag) in CATEGORIES.items():
        selected = [b for k in keys for b in blocks.get(k, ())]
        if tag is not None:
            counts[category] = sum(1 for b in selected if b.shape == f"span.tag-{tag}")
        else:
            counts[category] = sum(1 for b in selected if b.text and not b.shape.startswith("span"))
    return counts


def _pair_negations(pairs: Sequence[tuple[str, str]], findings: list[Finding]) -> None:
    """The curated renderings the zh-TW rendering showed, each against its original."""
    none = Messages(ZH)("tr.none")
    for shown, original in pairs:
        if shown == none or not _CJK.search(shown):
            continue
        if negations(original) != negations(shown):
            findings.append(
                Finding(
                    "NEGATION",
                    "translations beside their originals",
                    f"{original[:80]!r} has {negations(original)} negation(s); "
                    f"its rendering {shown[:80]!r} has {negations(shown)}",
                )
            )
        if confirmations(original) != confirmations(shown):
            findings.append(
                Finding(
                    "CLAIM",
                    "translations beside their originals",
                    f"{original[:80]!r} / its rendering {shown[:80]!r}",
                )
            )


def _html_not_performed(
    sections: Mapping[str, _Node],
    locale: str,
    unavailable: Sequence[Unavailable],
    renderings: Mapping[str, str],
    findings: list[Finding],
) -> None:
    """Each unavailable check: a list item naming it with the stored status BLOCKED in this
    locale's words, and an element naming it with its reason and what it needs."""
    blocked_words = Messages(locale)("ws.BLOCKED")
    nodes = [n for s in sections.values() for n in s.walk()]
    for item in unavailable:

        def names(n: _Node, cap: str = item.capability_id) -> bool:
            return any(
                x.attrs.get("title") == cap or (x.tag == "code" and _flat(x.text()) == cap)
                for x in n.walk()
            )

        labelled = any(
            n.tag == "li"
            and names(n)
            and any(
                _status_of(x) == ("ws", "BLOCKED") and _flat(x.text()) == blocked_words
                for x in n.walk()
            )
            for n in nodes
        )
        if not labelled:
            findings.append(
                Finding(
                    "NOT_PERFORMED",
                    f"{locale} {item.capability_id}",
                    "no list item names it with the status BLOCKED (not performed)",
                )
            )
        #: Each text in this locale's words: as written, or (zh-TW) its curated rendering.
        wanted = [
            {_flat(x), _flat(renderings.get(_flat(x), x))}
            for x in (item.reason, item.requires)
            if x
        ]
        explained = any(
            n.tag in ("div", "li")
            and names(n)
            and all(any(w in _flat(n.text(skip_marked=True)) for w in ws) for ws in wanted)
            and sum(1 for x in n.walk() if x.attrs.get("title", "").startswith("cap:")) <= 2
            for n in nodes
        )
        if not explained:
            findings.append(
                Finding(
                    "NOT_PERFORMED",
                    f"{locale} {item.capability_id}",
                    "no element names it together with why it could not run and what it needs",
                )
            )


def check_html(
    en_markup: str,
    zh_markup: str,
    *,
    surface: str,
    unavailable: Sequence[Unavailable] = (),
) -> ParityResult:
    """The parity of an HTML surface's English and zh-TW renderings (see the module doc)."""
    findings: list[Finding] = []
    en_root, zh_root = _parse(en_markup), _parse(zh_markup)
    for locale, root in ((EN, en_root), (ZH, zh_root)):
        html_node = next((n for n in root.walk() if n.tag == "html"), None)
        if html_node is not None and html_node.attrs.get("lang", locale) != locale:
            findings.append(
                Finding("LANGUAGE", surface, f"<html lang> is {html_node.attrs.get('lang')!r}")
            )
    en_sections, zh_sections = _sections(en_root), _sections(zh_root)
    if set(en_sections) != set(zh_sections):
        findings.append(
            Finding(
                "STRUCTURE",
                surface,
                f"sections English only {sorted(set(en_sections) - set(zh_sections))}; "
                f"zh-TW only {sorted(set(zh_sections) - set(en_sections))}",
            )
        )
    pairs = [p for s in zh_sections.values() for p in _originals(s, ZH)]
    renderings = {original: shown for shown, original in pairs}
    _pair_negations(pairs, findings)
    en_blocks: dict[str, list[_Block]] = {}
    zh_blocks: dict[str, list[_Block]] = {}
    aligned = 0
    for key in [k for k in en_sections if k in zh_sections]:
        en_list = _blocks(_without_originals(en_sections[key], EN), key)
        zh_list = _blocks(_without_originals(zh_sections[key], ZH), key)
        en_blocks[key], zh_blocks[key] = en_list, zh_list
        en_shape = [b.path for b in en_list]
        zh_shape = [b.path for b in zh_list]
        if en_shape != zh_shape:
            at = next(
                (i for i, (a, b) in enumerate(zip(en_shape, zh_shape, strict=False)) if a != b),
                min(len(en_shape), len(zh_shape)),
            )
            findings.append(
                Finding(
                    "STRUCTURE",
                    f"{surface} v-{key}",
                    f"{len(en_shape)} English block(s), {len(zh_shape)} zh-TW; first differ at "
                    f"#{at}: English {en_shape[at] if at < len(en_shape) else '-'} "
                    f"{en_list[at].text[:60] if at < len(en_list) else ''!r}; zh-TW "
                    f"{zh_shape[at] if at < len(zh_shape) else '-'} "
                    f"{zh_list[at].text[:60] if at < len(zh_list) else ''!r}",
                )
            )
            continue
        for en_block, zh_block in zip(en_list, zh_list, strict=True):
            _compare(en_block, zh_block, findings)
            aligned += 1
            if (
                key in _READ_IN_LOCALE
                and zh_block.shape not in ("code", "span[title]")
                and zh_block.prose
                and not _CJK.search(zh_block.prose)
                and _LATIN_WORD.search(_IDENT.sub(" ", zh_block.prose))
                and not zh_block.marked
            ):
                findings.append(
                    Finding(
                        "LANGUAGE",
                        zh_block.path,
                        f"shown in English and not marked untranslated: {zh_block.prose[:90]!r}",
                    )
                )
    en_cov, zh_cov = _coverage(en_blocks), _coverage(zh_blocks)
    coverage = {c: (en_cov[c], zh_cov[c]) for c in CATEGORIES}
    for category, (a, b) in coverage.items():
        if a != b:
            findings.append(Finding("COVERAGE", f"{surface} {category}", f"English {a}; zh-TW {b}"))
    science = [b for k in _READ_IN_LOCALE for b in zh_blocks.get(k, ())]
    if science and not any(_CJK.search(b.text) for b in science):
        findings.append(
            Finding("SINGLE_LANGUAGE", surface, "the zh-TW rendering's science body has no Chinese")
        )
    for locale, sections in ((EN, en_sections), (ZH, zh_sections)):
        _html_not_performed(
            sections, locale, unavailable, renderings if locale == ZH else {}, findings
        )
    _compare_citations(_html_citations(en_root), _html_citations(zh_root), surface, findings)
    _compare_quotes(_html_quotes(en_root), _html_quotes(zh_root), surface, findings)
    untranslated = sum(1 for n in zh_root.walk() if "untr" in n.classes)
    return ParityResult(surface, tuple(findings), coverage, aligned, untranslated)


def _html_citations(root: _Node) -> list[tuple[str, ...]]:
    """Each citation (`pages._citations_html`, `li.cite`): its locator as the report states it,
    then every identifier and digest the record gave it, in order."""
    out: list[tuple[str, ...]] = []
    for node in root.walk():
        if node.tag == "li" and "cite" in node.classes:
            locator = next(
                (_flat(x.text()) for x in node.walk() if x.tag == "span" and "loc" in x.classes),
                "",
            )
            out.append((locator, *(_flat(x.text()) for x in node.walk() if x.tag == "code")))
    return out


def _html_quotes(root: _Node) -> list[str]:
    """Every quoted passage, exactly as it reads: original text is never translated."""
    return [node.text() for node in root.walk() if node.tag == "blockquote"]


def _compare_citations(
    en: Sequence[tuple[str, ...]], zh: Sequence[tuple[str, ...]], surface: str, out: list[Finding]
) -> None:
    """The same attestations, locators, artifacts, hashes and units, in the same order."""
    if list(en) == list(zh):
        return
    first = next(
        (i for i, (a, b) in enumerate(zip(en, zh, strict=False)) if a != b), min(len(en), len(zh))
    )
    out.append(
        Finding(
            "CITATIONS",
            surface,
            f"{len(en)} English citation(s), {len(zh)} zh-TW; first differ at #{first}: "
            f"English {en[first] if first < len(en) else '-'}; "
            f"zh-TW {zh[first] if first < len(zh) else '-'}",
        )
    )


def _compare_quotes(en: Sequence[str], zh: Sequence[str], surface: str, out: list[Finding]) -> None:
    """Each quoted passage byte-identical in both languages: never overwritten by a rendering."""
    if len(en) != len(zh):
        out.append(Finding("ORIGINAL", surface, f"{len(en)} English quote(s), {len(zh)} zh-TW"))
        return
    for n, (a, b) in enumerate(zip(en, zh, strict=True)):
        if a != b:
            out.append(
                Finding("ORIGINAL", f"{surface} quote #{n + 1}", f"{a[:80]!r} / zh-TW {b[:80]!r}")
            )


# -- Markdown -------------------------------------------------------------------------------------


_MD_CODE = re.compile(r"`([^`]+)`")
#: A stored value named in words (`pages.MarkdownWords.status`): `VALUE〔words〕`.
_MD_GLOSS = re.compile(r"〔([^〕]*)〕")
#: A cited excerpt (`render.render_markdown`'s evidence line, in either language).
_MD_CITE = re.compile(r"^- `(?P<att>[^`]+)`[^\[]*\[(?P<loc>.*?)\]\s*[:：]\s*'(?P<quote>.*)'$")
#: Stored values and other upper-case tokens, which both languages keep as stored.
_UPPER = re.compile(r"\b[A-Z][A-Z_]{2,}\b")
#: A run of English prose: two or more words in a row.
_PROSE_RUN = re.compile(r"[A-Za-z]{3,}(?:[ \-][A-Za-z]{3,})+")
#: The families whose stored values the Markdown export names in words.
_MD_FAMILIES = frozenset({*_FAMILIES, "stage", "ss", "role", "origin", "act", "is", "pd", "flag"})


def _md_lines(text: str) -> list[tuple[str, str]]:
    """(shape, text) per non-empty line: heading level, list depth, table row, or paragraph."""
    out: list[tuple[str, str]] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        stripped = raw.lstrip()
        if stripped.startswith("#"):
            shape = "h" + str(len(stripped) - len(stripped.lstrip("#")))
        elif stripped.startswith(("- ", "* ")) or re.match(r"\d+\. ", stripped):
            shape = f"li{(len(raw) - len(stripped)) // 2}"
        elif stripped.startswith("|"):
            shape = "row" + str(stripped.count("|"))
        else:
            shape = "p"
        out.append((shape, stripped))
    return out


@dataclass(frozen=True)
class _MdExport:
    """One language's Markdown export, split as `pages.markdown_export` writes it."""

    #: The report's lines: what the two languages must agree on, line by line.
    lines: list[tuple[str, str]]
    #: (rendering shown, original) from the trailing table of renderings beside their originals.
    pairs: list[tuple[str, str]]
    #: Passages shown as written and marked original-language text (`tr.md_untranslated`).
    untranslated: int
    #: Per line: how many original-language marks it carries.
    marks: list[int]
    #: Per line: stored values named in words the product does not use for them.
    glosses: list[list[str]]
    #: Per line: what follows its last original-language mark, without stored values and their
    #: words -- what must read in the export's language.
    probes: list[str]


def _md_status_words() -> dict[str, set[str]]:
    """zh-TW words -> the stored values the product names with them (`i18n`, by family)."""
    m = Messages(ZH)
    found: dict[str, set[str]] = {}
    for key in message_keys():
        family, _, value = key.partition(".")
        if family in _MD_FAMILIES and value:
            found.setdefault(m.template(key), set()).add(value)
    return found


def _md_cells(row: str) -> list[str]:
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", row)[1:-1]]


def _md_split(text: str, locale: str) -> _MdExport:
    """The report's lines, without what exists only in a rendering in another language: the notes
    under its title (`> `, each saying what it is derived from) and, after the report, its table
    of renderings beside their originals (which instead supplies the curated pairs)."""
    m = Messages(locale)
    heading = "## " + m("v.l3.originals")
    raw = text.splitlines()
    cut = next((i for i, line in enumerate(raw) if line.strip() == heading), len(raw))
    pairs: list[tuple[str, str]] = []
    for line in raw[cut + 1 :]:
        cells = _md_cells(line) if line.startswith("|") else []
        if len(cells) >= 2 and not set(cells[0]) <= {"-"} and cells[0] != m("col.shown"):
            pairs.append((cells[0], cells[1]))
    marks_of = (Messages(ZH)("tr.md_untranslated"), Messages(ZH)("tr.md_quote"))
    words_of = _md_status_words() if locale == ZH else {}
    lines: list[tuple[str, str]] = []
    marks: list[int] = []
    glosses: list[list[str]] = []
    probes: list[str] = []
    untranslated = 0
    for shape, line in _md_lines("\n".join(raw[:cut])):
        if line.startswith(">"):
            continue
        untranslated += line.count(marks_of[0])
        marks.append(sum(line.count(x) for x in marks_of))
        # What follows the last mark: a passage before a mark is honestly marked, English after
        # it is not -- the language check reads only this.
        tail = line[max((line.rfind(x) + len(x) for x in marks_of if x in line), default=0) :]
        for mark in marks_of:
            line = line.replace(mark, "")
        _, bad = _without_named_values(line, words_of)
        glosses.append(bad)
        probes.append(_without_named_values(tail, words_of)[0])
        lines.append((shape, _MD_GLOSS.sub("", line)))
    return _MdExport(lines, pairs, untranslated, marks, glosses, probes)


def _without_named_values(text: str, words_of: Mapping[str, set[str]]) -> tuple[str, list[str]]:
    """The text without each stored value named in words (`VALUE〔words〕`), and every naming
    whose words the product does not use for the value before them."""
    bad: list[str] = []
    for g in reversed(list(_MD_GLOSS.finditer(text))):
        before = text[: g.start()].rstrip("*")
        value = next((v for v in words_of.get(g.group(1), ()) if before.endswith(v)), None)
        if value is None:
            bad.append(f"{before[-40:]!r} named {g.group(0)!r}")
            text = text[: g.start()] + " " + text[g.end() :]
            continue
        text = text[: len(before) - len(value)] + " " + text[g.end() :]
    return text, bad


def _md_citations(lines: Sequence[tuple[str, str]]) -> list[tuple[tuple[str, str], str]]:
    """((attestation, locator), quoted excerpt) for every cited excerpt, in order."""
    out: list[tuple[tuple[str, str], str]] = []
    for _, line in lines:
        cite = _MD_CITE.match(line)
        if cite is not None:
            out.append(((cite["att"], cite["loc"]), cite["quote"]))
    return out


def check_markdown(
    en_text: str,
    zh_text: str,
    *,
    surface: str = "report.md",
    unavailable: Sequence[Unavailable] = (),
) -> ParityResult:
    """The parity of a Markdown export's English and zh-TW renderings, line by line.

    The zh-TW export may carry what exists only in a rendering (`pages.markdown_export`): notes
    under its title (`> `) and a trailing table of renderings beside their originals; neither is
    aligned, and the table supplies the curated pairs. A stored value named in words
    (`VALUE〔words〕`) must be named in the product's own words for it (STATUS), and both
    languages keep the same stored values; a passage marked original-language text is honest,
    English left unmarked is not (LANGUAGE). Every cited excerpt has the same attestation and
    locator (CITATIONS) and the same bytes (ORIGINAL) in both.
    """
    findings: list[Finding] = []
    if not _CJK.search(zh_text):
        findings.append(
            Finding(
                "SINGLE_LANGUAGE",
                surface,
                "the zh-TW export has no Chinese"
                + (": it is the English export, byte for byte" if zh_text == en_text else ""),
            )
        )
    en, zh = _md_split(en_text, EN), _md_split(zh_text, ZH)
    en_lines, zh_lines = en.lines, zh.lines
    _pair_negations(zh.pairs, findings)
    aligned = 0
    if [s for s, _ in en_lines] != [s for s, _ in zh_lines]:
        en_shape, zh_shape = [s for s, _ in en_lines], [s for s, _ in zh_lines]
        at = next(
            (i for i, (a, b) in enumerate(zip(en_shape, zh_shape, strict=False)) if a != b),
            min(len(en_shape), len(zh_shape)),
        )
        findings.append(
            Finding(
                "STRUCTURE",
                surface,
                f"{len(en_lines)} English line(s), {len(zh_lines)} zh-TW line(s); first differ "
                f"at #{at}: English {en_lines[at] if at < len(en_lines) else '-'!r}; "
                f"zh-TW {zh_lines[at] if at < len(zh_lines) else '-'!r}",
            )
        )
    else:
        for n, ((shape, a), (_, b)) in enumerate(zip(en_lines, zh_lines, strict=True)):
            where = f"{surface} line {n + 1} ({shape})"
            if Counter(_MD_CODE.findall(a)) != Counter(_MD_CODE.findall(b)):
                findings.append(
                    Finding(
                        "IDENTIFIERS",
                        where,
                        _diff(Counter(_MD_CODE.findall(a)), Counter(_MD_CODE.findall(b))),
                    )
                )
            if numbers(a) != numbers(b):
                findings.append(Finding("NUMBERS", where, _diff(numbers(a), numbers(b))))
            prose_a, prose_b = _MD_CODE.sub(" ", a), _MD_CODE.sub(" ", b)
            if Counter(_UPPER.findall(prose_a)) != Counter(_UPPER.findall(prose_b)):
                findings.append(
                    Finding(
                        "STATUS",
                        where,
                        _diff(Counter(_UPPER.findall(prose_a)), Counter(_UPPER.findall(prose_b))),
                    )
                )
            for bad in zh.glosses[n]:
                findings.append(Finding("STATUS", where, f"not the product's words: {bad}"))
            # Unlike a page, every fixed word of the export is a curated pair with the same
            # negations and claims (`i18n._MARKDOWN_ZH`), so nothing is taken out before counting:
            # another message's fragment must not be taken out of one language only.
            said_a, said_b = prose_a, prose_b
            if negations(said_a) != negations(said_b):
                findings.append(Finding("NEGATION", where, f"{a[:80]!r} / {b[:80]!r}"))
            if confirmations(said_a) != confirmations(said_b):
                findings.append(Finding("CLAIM", where, f"{a[:80]!r} / {b[:80]!r}"))
            probe = _MD_CODE.sub(" ", zh.probes[n])
            probe = _UPPER.sub(" ", _IDENT.sub(" ", _GLOSS.sub(" ", probe)))
            if _PROSE_RUN.search(probe):
                findings.append(
                    Finding(
                        "LANGUAGE",
                        where,
                        f"shown in English and not marked as original-language text: {b[:90]!r}",
                    )
                )
            aligned += 1
    en_cites, zh_cites = _md_citations(en_lines), _md_citations(zh_lines)
    _compare_citations([c for c, _ in en_cites], [c for c, _ in zh_cites], surface, findings)
    _compare_quotes([q for _, q in en_cites], [q for _, q in zh_cites], surface, findings)
    renderings = {original: shown for shown, original in zh.pairs}
    for locale, lines in ((EN, en_lines), (ZH, zh_lines)):
        for item in unavailable:
            blocked = [
                i
                for i, (_, line) in enumerate(lines)
                if f"`{item.capability_id}`" in line and "**BLOCKED**" in line
            ]
            if not blocked:
                findings.append(
                    Finding(
                        "NOT_PERFORMED",
                        f"{locale} {item.capability_id}",
                        "no line names it as **BLOCKED** (not performed)",
                    )
                )
                continue
            #: Each text as this locale shows it: as written, or (zh-TW) its curated rendering.
            reason = {item.reason, renderings.get(item.reason, item.reason)}
            needs = {item.requires, renderings.get(item.requires, item.requires)}
            if not any(
                any(x in lines[i][1] for x in reason)
                and any(x in line for _, line in lines[i : i + 5] for x in needs)
                for i in blocked
            ):
                findings.append(
                    Finding(
                        "NOT_PERFORMED",
                        f"{locale} {item.capability_id}",
                        "its reason or what it needs is missing",
                    )
                )
    return ParityResult(surface, tuple(findings), {}, aligned, zh.untranslated)


# -- the record, before and after -----------------------------------------------------------------


def canonical_snapshot(connection: Any, *, exclude: Iterable[str] = ()) -> dict[str, str]:
    """A SHA-256 of every row of every table in the current schema, by table. Read only."""
    skip = set(exclude)
    tables = [
        str(row[0])
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'"
            " ORDER BY table_name"
        ).fetchall()
        if str(row[0]) not in skip
    ]
    digests: dict[str, str] = {}
    for table in tables:
        rows = connection.execute(
            f'SELECT row_to_json(t)::text FROM "{table}" t'  # table names come from the catalog
        ).fetchall()
        digest = hashlib.sha256()
        for (text,) in sorted(rows):
            digest.update(str(text).encode("utf-8") + b"\n")
        digests[table] = digest.hexdigest()
    return digests


def compare_canonical(before: Mapping[str, str], after: Mapping[str, str]) -> tuple[Finding, ...]:
    """Every table whose rows differ between two snapshots."""
    return tuple(
        Finding("CANONICAL", table, "rows changed while the renderings were made")
        for table in sorted(set(before) | set(after))
        if before.get(table) != after.get(table)
    )


__all__ = [
    "CATEGORIES",
    "CHECKS",
    "Finding",
    "ParityResult",
    "Unavailable",
    "canonical_snapshot",
    "check_html",
    "check_markdown",
    "compare_canonical",
    "confirmations",
    "content",
    "identifiers",
    "negations",
    "numbers",
    "unavailable_simulations",
]
