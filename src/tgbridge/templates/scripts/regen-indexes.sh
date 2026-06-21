#!/usr/bin/env bash
# regen-indexes.sh — reconstrói os índices da memória/projetos a partir do frontmatter,
# reescrevendo só as regiões entre marcadores <!-- regen:<tipo>:start/end -->.
# Idempotente; não toca em conteúdo fora dos marcadores. Rode da pasta scripts/ ou de qualquer lugar.
set -euo pipefail
WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "$WS" <<'PY'
import sys, re, glob, os
WS = sys.argv[1]

def frontmatter(path):
    """Parser mínimo de frontmatter YAML escalar (sem dependências)."""
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fm = {}
    for line in text[3:end].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, v = line.split(":", 1)
        fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm

def replace_region(path, tag, rows_md):
    if not os.path.exists(path):
        return False
    text = open(path, encoding="utf-8").read()
    start = "<!-- regen:%s:start -->" % tag
    end = "<!-- regen:%s:end -->" % tag
    pat = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    if not pat.search(text):
        return False
    block = start + "\n" + rows_md.rstrip() + "\n" + end
    open(path, "w", encoding="utf-8").write(pat.sub(lambda _: block, text, count=1))
    return True

# 1) memory/INDEX.md  <- topics/*.md
rows = ["| Topic | Private | Description |", "|-------|---------|-------------|"]
topics = sorted(p for p in glob.glob(os.path.join(WS, "memory/topics/*.md"))
                if not os.path.basename(p).startswith("_"))
for p in topics:
    fm = frontmatter(p)
    name = fm.get("name") or os.path.splitext(os.path.basename(p))[0]
    priv = "🔒" if str(fm.get("private", "")).lower() == "true" else ""
    rows.append("| [[%s]] | %s | %s |" % (name, priv, fm.get("description", "")))
if len(rows) == 2:
    rows.append("| _(nenhum tópico ainda)_ | | |")
replace_region(os.path.join(WS, "memory/INDEX.md"), "topics", "\n".join(rows))

# 2) projects/leads/INDEX.md  <- leads/L*/README.md agrupados por stage
STAGES = ["proposta-enviada", "negociação", "negociacao", "novo", "qualificação",
          "qualificacao", "stand-by", "arquivado"]
leads = {}
for p in glob.glob(os.path.join(WS, "projects/leads/*/README.md")):
    fm = frontmatter(p)
    st = (fm.get("stage") or "sem-estágio").strip()
    leads.setdefault(st, []).append(fm)
if leads:
    rows = ["| Estágio | Itens | Próxima ação |", "|---------|-------|--------------|"]
    for st in sorted(leads):
        items = leads[st]
        nxt = "; ".join(f.get("next_action", "") for f in items if f.get("next_action"))[:80]
        names = ", ".join("[[%s]]" % (f.get("name") or "?") for f in items)
        rows.append("| %s | %s | %s |" % (st, names, nxt))
    replace_region(os.path.join(WS, "projects/leads/INDEX.md"), "leads", "\n".join(rows))

# 3) projects/<categoria>/INDEX.md  <- <CODE>-<slug>/README.md daquela categoria
for cat_index in glob.glob(os.path.join(WS, "projects/*/INDEX.md")):
    cat_dir = os.path.dirname(cat_index)
    if os.path.basename(cat_dir) == "leads":
        continue
    rows = ["| # | Projeto | Status | Próxima ação | Atualizado |",
            "|---|---------|--------|--------------|------------|"]
    found = False
    for readme in sorted(glob.glob(os.path.join(cat_dir, "*/README.md"))):
        fm = frontmatter(readme)
        found = True
        rows.append("| %s | [[%s]] | %s | %s | %s |" % (
            fm.get("code", ""), fm.get("name") or os.path.basename(os.path.dirname(readme)),
            fm.get("status", ""), fm.get("next_action", ""), fm.get("updated", "")))
    if not found:
        rows.append("| | _(vazio)_ | | | |")
    replace_region(cat_index, "projects", "\n".join(rows))

print("✓ índices regenerados")
PY
