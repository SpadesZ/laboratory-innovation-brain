"""Phase B of the Lumi Agent blind benchmark: bootstrap the reasoning corpus, auditably.

    python benchmarks/lumi_agent/bootstrap_corpus.py

THE QUERIES ARE FIXED HERE, BEFORE ANY RESULT IS READ. Each is derived from problem_statement.md
(kind DERIVED) or is a deliberate search for a CONTRASTING or CONTRADICTING approach (kind
CONTRAST), with its reason. None names the target, its title words or its authors; none uses the
target's solution vocabulary (see holdout.json, preparer_exposure).

SOURCES, AND WHAT EACH IS TAKEN AS.
    OpenAlex (api.openalex.org)   scholarly works: title, authors, venue, date, DOI, licence,
                                  retraction flag and ABSTRACT. A work in a journal or conference
                                  source is PEER_REVIEWED; a repository source (arXiv, ...) or a
                                  `preprint` type is PREPRINT -- the provider's own report,
                                  recorded, not upgraded.
    GitHub (api.github.com)       repositories: TECHNICAL prior art, never peer-reviewed evidence.
                                  Name, description, dates, licence, URL only.

SELECTION IS A FIXED RULE, NOT A JUDGEMENT. Per query, in the provider's relevance order, the first
`PER_QUERY` works that pass every rule below; duplicates across queries are kept once, with every
query that found them.
    - published before the temporal cutoff (holdout.json);
    - not excluded by holdout.json (target DOI, a title naming the target);
    - a DOI (the product's literature connector locates passages by DOI);
    - an English abstract of at least MIN_ABSTRACT characters (the evidence text is the source's
      own abstract; nothing is written by the preparer);
    - (rule v2) published on or after the query's `since`, and its title or abstract mentions a term
      from EVERY group in the query's `must` (RULES).

RULE v2, AND WHY. Rule v1 ranked by OpenAlex's full-text relevance alone. Its log (`v1/`) shows the
result: mostly highly cited, off-topic works (a numerical library, a digit recogniser, proton
therapy, power-grid inverters) and no work from the language-model era the problem concerns. v2
searches title and abstract only, and adds, per query and before any v2 result was read, the terms a
work must mention to be on the query's subject, and a lower date bound for language-model queries
(no code-writing language model predates 2021). v1 is kept, whole, for audit.

EVERYTHING IS KEPT. The raw responses are snapshots (snapshots/, with SHA-256 in search_log.json);
excluded works are listed with the rule that excluded them.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CUTOFF = "2026-03-23"  # exclusive; holdout.json
TARGET_DOI = "10.1145/3787109.3816402"
PER_QUERY = 4
MIN_ABSTRACT = 400
USER_AGENT = "lab-brain-benchmark-bootstrap/1.0 (research corpus; no personal data)"
RULE_VERSION = "v2"

_LLM = ["language model", "llm"]
#: Rule v2, per query: (since, must). `must` is a list of groups; a work's title or abstract must
#: mention at least one term of EVERY group (case-insensitive).
RULES: dict[str, tuple[str | None, list[list[str]]]] = {
    "D01": ("2021-01-01", [_LLM, ["fdtd", "finite-difference time-domain", "simulation"]]),
    "D02": ("2021-01-01", [_LLM, ["photonic"]]),
    "D03": ("2021-01-01", [_LLM, ["photonic", "optical", "optics"]]),
    "D04": ("2021-01-01", [_LLM, ["simulation", "scientific"]]),
    "D05": ("2021-01-01", [_LLM, ["api", "library", "libraries"]]),
    "D06": ("2019-01-01", [["retriev"], ["code"]]),
    "D07": ("2021-01-01", [_LLM, ["electromagnetic", "simulation"]]),
    "D08": (
        None,
        [["fdtd", "finite-difference time-domain"], ["mesh", "convergence", "grid", "accuracy"]],
    ),
    "D09": ("2021-01-01", [_LLM, ["code"]]),
    "D10": ("2021-01-01", [_LLM, ["engineering", "design", "cad", "tool"]]),
    "D11": (
        "2021-01-01",
        [_LLM, ["electronic design automation", "eda", "hardware", "verilog", "circuit"]],
    ),
    "C01": (None, [["inverse design"], ["photonic"]]),
    "C02": (
        None,
        [
            ["surrogate", "neural network", "deep learning"],
            ["photonic", "electromagnetic", "nanophotonic"],
        ],
    ),
    "C03": (
        None,
        [["photonic"], ["design flow", "workflow", "automation", "automated", "pdk", "parametric"]],
    ),
    "C04": ("2021-01-01", [_LLM, ["hallucinat"], ["code"]]),
    "C05": ("2021-01-01", [_LLM, ["planning", "multi-step", "reasoning"]]),
    "C06": ("2021-01-01", [_LLM, ["benchmark"], ["scientific", "science"]]),
    "C07": (
        None,
        [["verification", "validation", "convergence"], ["electromagnetic", "fdtd", "maxwell"]],
    ),
}

QUERIES: list[dict[str, str]] = [
    # -- DERIVED from problem_statement.md --------------------------------------------------------
    {
        "id": "D01",
        "kind": "DERIVED",
        "text": "large language model FDTD simulation script generation",
        "reason": "Problem: turning intent into an executable FDTD simulation program.",
    },
    {
        "id": "D02",
        "kind": "DERIVED",
        "text": "large language model photonic device simulation",
        "reason": "Problem: photonic device simulation driven by a language model.",
    },
    {
        "id": "D03",
        "kind": "DERIVED",
        "text": "large language models photonics design",
        "reason": "Problem domain: language models applied to photonics design.",
    },
    {
        "id": "D04",
        "kind": "DERIVED",
        "text": "natural language to scientific simulation code generation language model",
        "reason": "Problem: natural-language intent to simulation code.",
    },
    {
        "id": "D05",
        "kind": "DERIVED",
        "text": "language model code generation for low-resource proprietary library API",
        "reason": "Motivation: the Lumerical interface is proprietary; little public data.",
    },
    {
        "id": "D06",
        "kind": "DERIVED",
        "text": "retrieval augmented code generation from API documentation",
        "reason": "Motivation: the model lacks knowledge of a sparsely documented API.",
    },
    {
        "id": "D07",
        "kind": "DERIVED",
        "text": "large language model electromagnetic simulation automation",
        "reason": "Problem: automating electromagnetic (FDTD) simulation.",
    },
    {
        "id": "D08",
        "kind": "DERIVED",
        "text": "FDTD waveguide simulation mesh convergence accuracy setup",
        "reason": "Constraint/success: a physically meaningful setup (mesh, sources, monitors).",
    },
    {
        "id": "D09",
        "kind": "DERIVED",
        "text": "executable correctness of code generated by large language models for scientific computing",
        "reason": "Success criterion: the produced simulation actually executes.",
    },
    {
        "id": "D10",
        "kind": "DERIVED",
        "text": "large language model engineering design tool scripting automation",
        "reason": "Problem: generating programs for a commercial engineering tool.",
    },
    {
        "id": "D11",
        "kind": "DERIVED",
        "text": "large language models electronic design automation code generation",
        "reason": "Adjacent field: generating programs for proprietary design-automation tools.",
    },
    # -- CONTRAST: other ways to the same end, and evidence against the obvious one ------------------
    {
        "id": "C01",
        "kind": "CONTRAST",
        "text": "photonic inverse design adjoint optimization FDTD",
        "reason": "Alternative: optimisation-driven design instead of generating setups from text.",
    },
    {
        "id": "C02",
        "kind": "CONTRAST",
        "text": "deep learning surrogate model nanophotonic simulation",
        "reason": "Alternative: replace or reduce FDTD runs with learned surrogates.",
    },
    {
        "id": "C03",
        "kind": "CONTRAST",
        "text": "automated parametric simulation workflow photonic integrated circuit design",
        "reason": "Alternative: conventional scripted/parametric automation without language models.",
    },
    {
        "id": "C04",
        "kind": "CONTRAST",
        "text": "hallucination in code generated by large language models",
        "reason": "Contradicting: evidence that generated code is unreliable.",
    },
    {
        "id": "C05",
        "kind": "CONTRAST",
        "text": "limitations of large language models in multi-step planning and reasoning",
        "reason": "Contradicting: evidence that multi-step automation by language models fails.",
    },
    {
        "id": "C06",
        "kind": "CONTRAST",
        "text": "benchmark of language models on scientific code",
        "reason": "Evaluation evidence: how well models actually write scientific code.",
    },
    {
        "id": "C07",
        "kind": "CONTRAST",
        "text": "verification and validation of electromagnetic simulation results",
        "reason": "Contrasting emphasis: checking simulations rather than generating them.",
    },
]

GITHUB_QUERIES: list[dict[str, str]] = [
    {
        "id": "G01",
        "kind": "DERIVED",
        "text": "lumerical language model",
        "reason": "Technical prior art: language models used with Lumerical.",
    },
    {
        "id": "G02",
        "kind": "DERIVED",
        "text": "lumerical python automation",
        "reason": "Technical prior art: automating Lumerical from Python (with or without models).",
    },
    {
        "id": "G03",
        "kind": "DERIVED",
        "text": "fdtd llm",
        "reason": "Technical prior art: language models with any FDTD solver.",
    },
]


def _get(url: str, attempts: int = 8) -> tuple[bytes, str]:
    """GET, waiting as long as the provider asks when it is rate-limiting (HTTP 429)."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read()
            return body, dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        except urllib.error.HTTPError as refused:
            if refused.code != 429 or attempt == attempts - 1:
                raise
            wait = int(refused.headers.get("Retry-After") or 30) + 2
            print(f"  rate-limited; waiting {wait}s as asked", flush=True)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def _abstract(inverted: dict[str, list[int]] | None) -> str:
    if not inverted:
        return ""
    words: dict[int, str] = {}
    for word, positions in inverted.items():
        for p in positions:
            words[p] = word
    return " ".join(words[i] for i in sorted(words))


def _licence(value: str | None) -> str | None:
    """OpenAlex's licence id, in the form the product's connector classifies (SEC-004)."""
    if not value:
        return None
    upper = value.upper()
    if upper.startswith("CC0") or upper == "PUBLIC-DOMAIN":
        return "CC0"
    if upper.startswith("CC-BY"):
        return upper
    return value  # anything else is UNKNOWN to the product: kept as an excerpt only


def _passages(text: str) -> list[dict[str, str]]:
    """The abstract, in consecutive spans of about three sentences. Verbatim; nothing added."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text) if s.strip()]
    spans: list[str] = []
    for s in sentences:
        if spans and len(spans[-1]) < 420:
            spans[-1] = f"{spans[-1]} {s}"
        else:
            spans.append(s)
    return [
        {"id": f"abs{i + 1}", "section": "Abstract", "page": "", "text": t}
        for i, t in enumerate(spans)
    ]


def _excluded(work: dict[str, Any], query_id: str) -> str | None:
    doi = (work.get("doi") or "").lower().removeprefix("https://doi.org/")
    title = (work.get("title") or "").lower()
    date = work.get("publication_date") or ""
    if doi == TARGET_DOI:
        return "the target"
    if "lumi agent" in title:
        return "names the target"
    if not date or date >= CUTOFF:
        return f"published {date or '(no date)'}, not before the cutoff {CUTOFF}"
    if not doi:
        return "no DOI (the product's literature connector locates passages by DOI)"
    if (work.get("language") or "en") != "en":
        return f"language {work.get('language')}"
    abstract = _abstract(work.get("abstract_inverted_index"))
    if len(abstract) < MIN_ABSTRACT:
        return f"no abstract of at least {MIN_ABSTRACT} characters"
    since, must = RULES[query_id]
    if since is not None and date < since:
        return f"published {date}, before this query's window ({since})"
    text = f"{title} {abstract}".lower()
    for group in must:
        if not any(term in text for term in group):
            return f"off the query's subject: mentions none of {group}"
    return None


def _paper(work: dict[str, Any], queries: list[str], snapshot: str) -> dict[str, Any]:
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    preprint = work.get("type") == "preprint" or source.get("type") == "repository"
    doi = work["doi"].lower().removeprefix("https://doi.org/")
    return {
        "doi": doi,
        "version": f"openalex-{work['publication_date']}",
        "title": work["title"],
        "authors": [a["author"]["display_name"] for a in work.get("authorships", [])][:8],
        "venue": source.get("display_name") or "",
        "year": work.get("publication_year"),
        "peer_reviewed": not preprint,
        "license": _licence(location.get("license")),
        "status": "RETRACTED" if work.get("is_retracted") else "ACTIVE",
        "passages": _passages(_abstract(work.get("abstract_inverted_index"))),
        "provenance": {
            "provider": "OpenAlex",
            "openalex_id": work["id"],
            "publication_date": work["publication_date"],
            "type": work.get("type"),
            "source_type": source.get("type"),
            "found_by": queries,
            "snapshot": snapshot,
            "status_basis": "OpenAlex is_retracted (Retraction Watch data); not a full erratum check",
            "evidence_text": "the work's own abstract as OpenAlex holds it; the full text was not read",
        },
    }


def main() -> None:
    snapshots = HERE / "snapshots"
    (snapshots / "openalex").mkdir(parents=True, exist_ok=True)
    (snapshots / "github").mkdir(parents=True, exist_ok=True)
    log: dict[str, Any] = {
        "benchmark": "lumi-agent-blind-v1",
        "cutoff_exclusive": CUTOFF,
        "per_query": PER_QUERY,
        "min_abstract_chars": MIN_ABSTRACT,
        "rule_version": RULE_VERSION,
        "rules": {k: {"since": v[0], "must": v[1]} for k, v in RULES.items()},
        "superseded": "v1/ (rule v1: full-text relevance only; see the module docstring)",
        "queries": [],
        "github": [],
    }
    selected: dict[str, dict[str, Any]] = {}
    fields = (
        "id,doi,title,publication_date,publication_year,type,language,primary_location,"
        "authorships,is_retracted,abstract_inverted_index,relevance_score"
    )
    for q in QUERIES:
        params = {
            "per_page": "50",
            "select": fields,
            "sort": "relevance_score:desc",
            "filter": f"title_and_abstract.search:{q['text']},to_publication_date:{CUTOFF}",
        }
        url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
        body, at = _get(url)
        path = snapshots / "openalex" / f"{q['id']}.json"
        path.write_bytes(body)
        results = json.loads(body)["results"]
        entry: dict[str, Any] = {
            **q,
            "url": url,
            "retrieved_at": at,
            "snapshot": path.relative_to(HERE).as_posix(),
            "sha256": hashlib.sha256(body).hexdigest(),
            "results": len(results),
            "selected": [],
            "excluded": [],
        }
        taken = 0
        for work in results:
            reason = _excluded(work, q["id"])
            label = f"{work.get('title')} ({work.get('publication_date')})"
            if reason is not None:
                entry["excluded"].append({"work": label, "doi": work.get("doi"), "why": reason})
                continue
            if taken >= PER_QUERY:
                continue
            doi = work["doi"].lower().removeprefix("https://doi.org/")
            if doi in selected:
                selected[doi]["provenance"]["found_by"].append(q["id"])
            else:
                selected[doi] = _paper(work, [q["id"]], entry["snapshot"])
            entry["selected"].append(doi)
            taken += 1
        log["queries"].append(entry)
        time.sleep(3)

    technical: list[dict[str, Any]] = []
    for q in GITHUB_QUERIES:
        params = {"q": f"{q['text']} created:<{CUTOFF}", "sort": "stars", "per_page": "10"}
        url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(params)
        body, at = _get(url)
        path = snapshots / "github" / f"{q['id']}.json"
        path.write_bytes(body)
        items = json.loads(body).get("items", [])
        entry = {
            **q,
            "url": url,
            "retrieved_at": at,
            "snapshot": path.relative_to(HERE).as_posix(),
            "sha256": hashlib.sha256(body).hexdigest(),
            "results": len(items),
            "selected": [],
            "excluded": [],
        }
        for repo in items:
            name = repo["full_name"]
            text = f"{name} {repo.get('description') or ''}".lower()
            if "lumi agent" in text or "lumi-agent" in text:
                entry["excluded"].append({"work": name, "why": "names the target"})
                continue
            if repo["created_at"][:10] >= CUTOFF:
                entry["excluded"].append({"work": name, "why": "created after the cutoff"})
                continue
            if any(t["full_name"] == name for t in technical):
                entry["selected"].append(name)
                continue
            technical.append(
                {
                    "full_name": name,
                    "url": repo["html_url"],
                    "description": repo.get("description") or "",
                    "created_at": repo["created_at"],
                    "pushed_at": repo["pushed_at"],
                    "licence": (repo.get("license") or {}).get("spdx_id"),
                    "stars": repo.get("stargazers_count"),
                    "trust": "TECHNICAL_ARTIFACT -- not peer-reviewed",
                    "found_by": q["id"],
                }
            )
            entry["selected"].append(name)
        log["github"].append(entry)
        time.sleep(7)  # unauthenticated search: 10 requests per minute

    papers = sorted(selected.values(), key=lambda p: (p["provenance"]["found_by"][0], p["doi"]))
    corpus = {
        "description": (
            "Lumi Agent blind benchmark v1 reasoning corpus: public scholarly works published "
            f"before {CUTOFF}, selected by bootstrap_corpus.py's fixed rule; each passage is the "
            "work's own abstract text (OpenAlex). The target and its derivatives are excluded "
            "(holdout.json)."
        ),
        "papers": papers,
    }
    (HERE / "corpus.json").write_text(
        json.dumps(corpus, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    (HERE / "technical_prior_art.json").write_text(
        json.dumps(
            {"cutoff_exclusive": CUTOFF, "repositories": technical}, ensure_ascii=False, indent=1
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    log["corpus"] = {
        "papers": len(papers),
        "peer_reviewed": sum(p["peer_reviewed"] for p in papers),
        "preprints": sum(not p["peer_reviewed"] for p in papers),
        "passages": sum(len(p["passages"]) for p in papers),
    }
    log["technical_prior_art"] = len(technical)
    (HERE / "search_log.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(log["corpus"]), "technical:", len(technical))


if __name__ == "__main__":
    main()
