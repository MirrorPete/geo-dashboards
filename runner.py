"""
GEO baseline runner. Designed to run in GitHub Actions.

For each brand config in configs/, runs all four engines, scores each query,
and writes data/{slug}.json in the format dashboard.html expects.

Reads API keys from env: PERPLEXITY_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY.
Skips any engine whose key is missing.

Usage:
    python3 runner.py                          # all brands, all engines
    python3 runner.py --brand eight-sleep      # one brand
    python3 runner.py --engine claude          # one engine across all brands
"""

import json
import os
import sys
import time
import datetime
import urllib.parse
import argparse
from pathlib import Path

import requests


# ---------- scoring ----------

def score_mention(text, titles, brand_aliases, person_aliases):
    blob = (text + "\n" + "\n".join(titles)).lower()
    needles = [s.lower() for s in (brand_aliases or []) + (person_aliases or [])]
    return any(n in blob for n in needles)


def score_citation(urls, owned_domains):
    for url in urls:
        try:
            host = (urllib.parse.urlparse(url).hostname or "").lower()
            for d in owned_domains:
                if host == d or host.endswith("." + d) or d in host:
                    return True
        except Exception:
            pass
    return False


def to_code(m, c):
    if m and c: return "MC"
    if m: return "M"
    if c: return "C"
    return "-"


def extract_top_domains(urls, owned_domains, max_n=4):
    """Return up to max_n unique cited second-level domains, excluding owned."""
    out = []
    seen = set()
    for url in urls:
        try:
            host = (urllib.parse.urlparse(url).hostname or "").lower()
            if not host:
                continue
            host = host.replace("www.", "")
            if any(d == host or host.endswith("." + d) or d in host for d in owned_domains):
                continue
            parts = host.split(".")
            key = parts[-2] if len(parts) >= 2 else host
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
            if len(out) >= max_n:
                break
        except Exception:
            continue
    return out


def find_competitors(text, titles, competitors, max_n=5):
    """Return list of competitor brand names found in answer text or source titles."""
    blob = (text + "\n" + "\n".join(titles)).lower()
    found = []
    seen = set()
    for c in competitors:
        cl = c.lower()
        if cl in blob and cl not in seen:
            seen.add(cl)
            found.append(c)
            if len(found) >= max_n:
                break
    return found


# ---------- engine adapters ----------

def run_perplexity(query):
    key = os.environ["PERPLEXITY_API_KEY"]
    r = requests.post(
        "https://api.perplexity.ai/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": "sonar", "messages": [{"role": "user", "content": query}]},
        timeout=120,
    )
    r.raise_for_status()
    data = r.json()
    text = data["choices"][0]["message"]["content"]
    urls = data.get("citations", []) or []
    return text, [], urls


def run_openai(query):
    key = os.environ["OPENAI_API_KEY"]
    r = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": "gpt-4.1", "input": query, "tools": [{"type": "web_search_preview"}]},
        timeout=180,
    )
    r.raise_for_status()
    data = r.json()
    text_chunks, titles, urls = [], [], []
    for item in data.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    text_chunks.append(content.get("text", ""))
                    for ann in content.get("annotations", []) or []:
                        if ann.get("type") == "url_citation":
                            urls.append(ann.get("url", ""))
                            titles.append(ann.get("title", ""))
    return "\n".join(text_chunks), titles, urls


def run_anthropic(query):
    key = os.environ["ANTHROPIC_API_KEY"]
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={
            "model": "claude-sonnet-4-5",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": query}],
            "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
        },
        timeout=180,
    )
    r.raise_for_status()
    data = r.json()
    text_chunks, titles, urls = [], [], []
    for block in data.get("content", []):
        bt = block.get("type")
        if bt == "text":
            text_chunks.append(block.get("text", ""))
            for cite in block.get("citations", []) or []:
                if cite.get("type") == "web_search_result_location":
                    urls.append(cite.get("url", ""))
                    titles.append(cite.get("title", ""))
        elif bt == "web_search_tool_result":
            for it in block.get("content", []) or []:
                if it.get("type") == "web_search_result":
                    urls.append(it.get("url", ""))
                    titles.append(it.get("title", ""))
    return "\n".join(text_chunks), titles, urls


def run_gemini(query):
    key = os.environ["GEMINI_API_KEY"]
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={key}"
    )
    r = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        json={
            "contents": [{"parts": [{"text": query}]}],
            "tools": [{"google_search": {}}],
        },
        timeout=180,
    )
    r.raise_for_status()
    data = r.json()
    cand = (data.get("candidates") or [{}])[0]
    text_chunks = [
        p.get("text", "") for p in cand.get("content", {}).get("parts", []) if "text" in p
    ]
    titles, urls = [], []
    grounding = cand.get("groundingMetadata", {}) or {}
    for chunk in grounding.get("groundingChunks", []) or []:
        web = chunk.get("web", {}) or {}
        if web.get("uri"):
            urls.append(web["uri"])
            titles.append(web.get("title", ""))
    return "\n".join(text_chunks), titles, urls


ENGINES = {
    "perplexity": ("PERPLEXITY_API_KEY", run_perplexity),
    "chatgpt":    ("OPENAI_API_KEY",     run_openai),
    "claude":     ("ANTHROPIC_API_KEY",  run_anthropic),
    "gemini":     ("GEMINI_API_KEY",     run_gemini),
}

ENGINE_SLEEP = {
    "perplexity": 0.5,
    "chatgpt":    1.0,
    "claude":     0.5,
    "gemini":     5.0,
}


def call_with_retry(fn, query, max_retries=3):
    last_err = None
    for attempt in range(max_retries):
        try:
            return fn(query)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            last_err = e
            if status in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                wait = 10 * (2 ** attempt)
                print(f"    retry in {wait}s (got {status})", flush=True)
                time.sleep(wait)
                continue
            raise
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(10 * (attempt + 1))
                continue
            raise
    if last_err:
        raise last_err


def run_brand(config_path, engine_filter=None):
    cfg = json.loads(Path(config_path).read_text())
    slug = cfg["slug"]
    subject = cfg["subject"]
    queries = cfg["queries"]

    today = datetime.date.today().isoformat()
    data_path = Path(__file__).parent / "data" / f"{slug}.json"

    # Load existing data file if present, otherwise scaffold
    if data_path.exists():
        out = json.loads(data_path.read_text())
    else:
        out = {
            "brand": subject["brand"],
            "url": subject.get("url", ""),
            "person": subject.get("person"),
            "queries": queries,
            "results": {},
        }

    out["lastRun"] = today
    out["queries"] = queries  # always sync from config
    out.setdefault("results", {})

    engines_to_run = (
        {engine_filter: ENGINES[engine_filter]} if engine_filter else ENGINES
    )

    for engine_id, (env_var, fn) in engines_to_run.items():
        if env_var not in os.environ or not os.environ[env_var]:
            print(f"[{slug}/{engine_id}] skipping — {env_var} not set", flush=True)
            continue

        # Fresh per-run results (don't carry forward stale data)
        engine_results = {}
        print(f"[{slug}/{engine_id}] {len(queries)} queries", flush=True)
        for i, q in enumerate(queries):
            try:
                text, titles, urls = call_with_retry(fn, q["q"])
                m = score_mention(text, titles, subject.get("brand_aliases", []), subject.get("person_aliases", []))
                c = score_citation(urls, subject.get("owned_domains", []))
                code = to_code(m, c)
                cited_domains = extract_top_domains(urls, subject.get("owned_domains", []))
                competitors_named = find_competitors(text, titles, subject.get("competitors", []))
                engine_results[str(i)] = {
                    "code": code,
                    "cited_domains": cited_domains,
                    "competitors_named": competitors_named,
                }
                detail = ""
                if competitors_named:
                    detail = f"  [comp: {', '.join(competitors_named[:3])}]"
                elif cited_domains:
                    detail = f"  [cite: {', '.join(cited_domains[:3])}]"
                print(f"  q{i+1:2d} {code}  {q['q'][:55]}{detail}", flush=True)
            except Exception as e:
                msg = str(e)[:120]
                print(f"  q{i+1:2d} ERR  {q['q'][:60]}: {msg}", flush=True)
                engine_results[str(i)] = {"code": "ERR"}
            time.sleep(ENGINE_SLEEP.get(engine_id, 0.5))

        out["results"][engine_id] = engine_results
        data_path.write_text(json.dumps(out, indent=2))

    print(f"[{slug}] wrote {data_path}", flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand", help="Run only this brand slug. Default: all configs in configs/.")
    p.add_argument("--engine", choices=list(ENGINES.keys()), help="Run only this engine.")
    args = p.parse_args()

    configs_dir = Path(__file__).parent / "configs"
    if args.brand:
        config_paths = [configs_dir / f"{args.brand}.json"]
    else:
        config_paths = sorted(configs_dir.glob("*.json"))

    for cp in config_paths:
        run_brand(cp, engine_filter=args.engine)


if __name__ == "__main__":
    main()
