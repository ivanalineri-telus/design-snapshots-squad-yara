"""Tira um snapshot de um frame do Figma e salva em snapshots/{TASK_ID}/{TIMESTAMP}/.

Inputs (via env): FIGMA_TOKEN, FIGMA_URL, TASK_ID.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

FIGMA_API = "https://api.figma.com/v1"
LOG_PREFIX = "[snapshot]"
REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS_DIR = REPO_ROOT / "snapshots"


def log(msg: str) -> None:
    print(f"{LOG_PREFIX} {msg}", flush=True)


def die(msg: str, code: int = 1) -> None:
    print(f"{LOG_PREFIX} ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def parse_figma_url(url: str) -> tuple[str, list[str]]:
    """Extrai (file_key, [node_ids]) da URL do Figma. Falha com mensagem clara se inválida."""
    parsed = urlparse(url)
    if not parsed.netloc.endswith("figma.com"):
        die(f"URL não parece ser do Figma: {url}")

    parts = [p for p in parsed.path.split("/") if p]
    file_key = None
    for marker in ("design", "file"):
        if marker in parts:
            idx = parts.index(marker)
            if idx + 1 < len(parts):
                file_key = parts[idx + 1]
                break
    if not file_key:
        die(
            "Não consegui extrair FILE_KEY da URL. "
            "Esperado formato /design/<KEY>/... ou /file/<KEY>/..."
        )

    qs = parse_qs(parsed.query)
    node_id_raw = qs.get("node-id", [None])[0]
    if not node_id_raw:
        die("URL não contém o parâmetro `node-id`. Adicione na URL e tente de novo.")

    # Figma usa `-` na URL mas a API quer `:`. Aceita lista separada por vírgula.
    node_ids = [n.replace("-", ":") for n in node_id_raw.split(",") if n]
    return file_key, node_ids


def figma_get(path: str, token: str, params: dict | None = None) -> dict:
    """GET autenticado na Figma API com tratamento de 401/404."""
    url = f"{FIGMA_API}{path}"
    resp = requests.get(url, headers={"X-Figma-Token": token}, params=params, timeout=30)
    if resp.status_code == 401:
        die(
            "401 Unauthorized do Figma. Verifique se o secret/env `FIGMA_TOKEN` "
            "está correto e tem os escopos `file_content:read` e `file_metadata:read`."
        )
    if resp.status_code == 403:
        die(
            "403 Forbidden do Figma. O token é válido mas não tem acesso a esse arquivo "
            "ou faltam escopos. Verifique os escopos do token e se o arquivo é acessível."
        )
    if resp.status_code == 404:
        die(f"404 do Figma em {path}. Verifique o FILE_KEY/NODE_ID extraídos da URL.")
    resp.raise_for_status()
    return resp.json()


def fetch_node_metadata(file_key: str, node_ids: list[str], token: str) -> dict:
    log(f"Buscando metadados de {len(node_ids)} node(s) em {file_key}…")
    data = figma_get(f"/files/{file_key}/nodes", token, params={"ids": ",".join(node_ids)})
    nodes = data.get("nodes", {})
    missing = [nid for nid in node_ids if nodes.get(nid) is None]
    if missing:
        die(
            f"Node(s) não encontrado(s) no arquivo: {missing}. "
            f"Confira na URL — IDs traduzidos com ':' são: {node_ids}."
        )
    return nodes


def fetch_image_urls(file_key: str, node_ids: list[str], token: str) -> dict[str, str]:
    log("Pedindo URLs de imagem (PNG @2x)…")
    data = figma_get(
        f"/images/{file_key}",
        token,
        params={"ids": ",".join(node_ids), "scale": 2, "format": "png"},
    )
    if data.get("err"):
        die(f"Figma retornou erro ao gerar imagens: {data['err']}")
    images = data.get("images", {})
    missing = [nid for nid in node_ids if not images.get(nid)]
    if missing:
        die(f"Figma não retornou URL de imagem para: {missing}")
    return images


def download_image(url: str, dest: Path) -> None:
    last_exc: Exception | None = None
    for attempt in (1, 2):
        try:
            log(f"  download tentativa {attempt} → {dest.name}")
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            return
        except requests.RequestException as exc:
            last_exc = exc
            if attempt == 1:
                time.sleep(1)
    die(f"Falha ao baixar imagem após 2 tentativas ({dest.name}): {last_exc}")


def fetch_latest_version(file_key: str, token: str) -> dict:
    log("Consultando versão mais recente do arquivo…")
    data = figma_get(f"/files/{file_key}/versions", token)
    versions = data.get("versions", [])
    if not versions:
        die("API retornou lista de versões vazia — arquivo sem histórico?")
    latest = versions[0]
    return {
        "id": latest.get("id"),
        "created_at": latest.get("created_at"),
        "label": latest.get("label") or None,
    }


def save_snapshot(
    *,
    task_id: str,
    figma_url: str,
    file_key: str,
    node_ids: list[str],
    nodes: dict,
    images: dict[str, str],
    version: dict,
    token: str,
) -> Path:
    now = datetime.now(timezone.utc)
    timestamp_dir = now.strftime("%Y%m%d-%H%M%S")
    captured_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    out_dir = SNAPSHOTS_DIR / task_id / timestamp_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"Salvando em {out_dir.relative_to(REPO_ROOT)}/")

    multiple = len(node_ids) > 1
    frames_meta = []
    for nid in node_ids:
        safe_nid = nid.replace(":", "-")
        filename = f"frame_{safe_nid}.png" if multiple else "frame.png"
        download_image(images[nid], out_dir / filename)
        node_doc = nodes.get(nid, {}).get("document", {}) or {}
        frames_meta.append(
            {
                "node_id": nid,
                "name": node_doc.get("name", "<unknown>"),
                "image_file": filename,
            }
        )

    metadata = {
        "task_id": task_id,
        "captured_at_utc": captured_at,
        "figma": {
            "url": figma_url,
            "file_key": file_key,
            "node_ids": node_ids,
            "current_version_id": version["id"],
            "current_version_created_at": version["created_at"],
            "current_version_label": version["label"],
        },
        "frames": frames_meta,
    }
    (out_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out_dir


def main() -> None:
    token = os.environ.get("FIGMA_TOKEN")
    figma_url = os.environ.get("FIGMA_URL")
    task_id = os.environ.get("TASK_ID")

    missing = [n for n, v in (("FIGMA_TOKEN", token), ("FIGMA_URL", figma_url), ("TASK_ID", task_id)) if not v]
    if missing:
        die(f"Variáveis de ambiente obrigatórias ausentes: {', '.join(missing)}")

    assert token and figma_url and task_id  # narrow types pro mypy/linter

    log(f"task_id={task_id}")
    file_key, node_ids = parse_figma_url(figma_url)
    log(f"file_key={file_key} node_ids={node_ids}")

    nodes = fetch_node_metadata(file_key, node_ids, token)
    images = fetch_image_urls(file_key, node_ids, token)
    version = fetch_latest_version(file_key, token)

    out_dir = save_snapshot(
        task_id=task_id,
        figma_url=figma_url,
        file_key=file_key,
        node_ids=node_ids,
        nodes=nodes,
        images=images,
        version=version,
        token=token,
    )
    log(f"OK — snapshot em {out_dir.relative_to(REPO_ROOT)}/")


if __name__ == "__main__":
    main()
