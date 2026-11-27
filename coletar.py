"""
Coletor de Diários Oficiais Municipais (Macapá-AP e Fortaleza-CE).

Uso básico:
    python coletar.py
    python coletar.py --inicio 2026-09-28 --fim 2026-11-26
    python coletar.py --limite 1 --salvar-txt --salvar-pdf-comprimido
"""

import argparse
import html
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pymupdf
import requests
from rapidocr import RapidOCR

# Fuso horário fixo UTC-3 (Brasília/Macapá/Fortaleza), sem depender de tzdata no Windows
FUSO_BR = timezone(timedelta(hours=-3))
MACAPA_URL = "https://macapa.ap.gov.br/diarios-oficiais/"
FORTALEZA_URL = "https://diariooficial.fortaleza.ce.gov.br/"

# Molde padrão observado nos títulos de Macapá
PADRAO_TITULO_MACAPA = re.compile(
    r"^DI[ÁA]RIO OFICIAL N[º°o]?:\s*(\S+)-(\d{2}/\d{2}/\d{4})$",
    re.IGNORECASE,
)
# Identifica sufixo de suplemento no número ou URL (ex.: 5183-A)
PADRAO_SUPLEMENTO = re.compile(r"\b\d+-[A-Za-z]+\b")


def parse_data_br(texto: str) -> date:
    """
    Converte uma data no formato brasileiro 'DD/MM/YYYY' para datetime.date.

    Parâmetros:
        texto (str): String de data vinda da listagem (ex.: '25/11/2026').
    Retorno:
        date: Objeto de data correspondente.
    """
    return datetime.strptime(texto.strip(), "%d/%m/%Y").date()


def classificar_tipo(numero_edicao: str, titulo: str, url: str, data_pub: date) -> str:
    """
    Mapeia a edição para um dos três tipos exigidos: 'normal', 'extra' ou 'suplemento'.

    Parâmetros:
        numero_edicao (str): Identificador da edição (ex.: '5421' ou '5183-A').
        titulo (str): Título exibido na listagem da fonte.
        url (str): Link direto do PDF.
        data_pub (date): Data de publicação da edição.
    Retorno:
        str: 'suplemento', 'extra' ou 'normal'.
    """
    combinado = f"{numero_edicao} {titulo} {url}".lower()
    if "suplement" in combinado or PADRAO_SUPLEMENTO.search(combinado):
        return "suplemento"
    if "extra" in combinado or data_pub.weekday() >= 5:
        return "extra"
    return "normal"


def ordenar_blocos_por_coluna(boxes, txts, largura: float, altura: float) -> list[str]:
    """
    Ordena caixas de texto detectadas pelo OCR para páginas em até 2 colunas.

    Parâmetros:
        boxes (ndarray | list): Coordenadas [[x,y], ...] de cada caixa detectada.
        txts (list[str]): Textos reconhecidos correspondentes a cada caixa.
        largura (float): Largura da imagem renderizada em pixels.
        altura (float): Altura da imagem renderizada em pixels.
    Retorno:
        list[str]: Textos ordenados em leitura linear (cabeçalho -> coluna esq -> coluna dir).
    """
    if boxes is None or len(boxes) == 0 or not txts:
        return []

    meio_x = largura / 2.0
    topo_y = altura * 0.12
    itens = []

    for box, txt in zip(boxes, txts):
        if not txt or not txt.strip():
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        x0, x1 = min(xs), max(xs)
        y0 = min(ys)
        centro_x = (x0 + x1) / 2.0
        cruza_centro = x0 < meio_x and x1 > meio_x and (x1 - x0) > largura * 0.35

        if y0 < topo_y or cruza_centro:
            grupo = 0
        elif centro_x < meio_x:
            grupo = 1
        else:
            grupo = 2

        itens.append((grupo, y0, x0, txt.strip()))

    itens.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in itens]


def extrair_texto_pdf_com_retomada(
    pdf_bytes: bytes,
    ocr: RapidOCR,
    arquivo_parcial: Path,
    dpi: int = 150,
    caminho_pdf_comprimido: Path | None = None,
) -> str:
    """
    Extrai texto completo de um PDF em memória, salvando progresso por página.
    Opcionalmente salva uma cópia comprimida do PDF para auditoria.

    Parâmetros:
        pdf_bytes (bytes): Conteúdo binário do PDF baixado.
        ocr (RapidOCR): Instância inicializada do motor RapidOCR.
        arquivo_parcial (Path): Caminho do JSON temporário para retomar páginas já lidas.
        dpi (int): Resolução de renderização quando precisar de OCR (padrão: 150).
        caminho_pdf_comprimido (Path | None): Se informado, salva cópia comprimida neste caminho.
    Retorno:
        str: Texto completo de todas as páginas concatenado.
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    total_paginas = len(doc)

    paginas_prontas: dict[str, str] = {}
    if arquivo_parcial.exists():
        try:
            dados_parciais = json.loads(arquivo_parcial.read_text(encoding="utf-8"))
            paginas_prontas = dados_parciais.get("paginas", {})
        except (json.JSONDecodeError, OSError):
            paginas_prontas = {}

    arquivo_parcial.parent.mkdir(parents=True, exist_ok=True)

    try:
        for idx in range(total_paginas):
            chave = str(idx + 1)
            if chave in paginas_prontas:
                continue

            pagina = doc[idx]
            nativo = pagina.get_text("text").strip()
            if len(nativo) >= 100:
                paginas_prontas[chave] = nativo
            else:
                pix = pagina.get_pixmap(dpi=dpi)
                res = ocr(pix.tobytes("png"))
                if res and res.txts:
                    linhas = ordenar_blocos_por_coluna(
                        res.boxes, res.txts, pix.width, pix.height
                    )
                    paginas_prontas[chave] = "\n".join(linhas)
                else:
                    paginas_prontas[chave] = ""

            arquivo_parcial.write_text(
                json.dumps({"paginas": paginas_prontas}, ensure_ascii=False),
                encoding="utf-8",
            )

        if caminho_pdf_comprimido is not None:
            caminho_pdf_comprimido.parent.mkdir(parents=True, exist_ok=True)
            doc.save(str(caminho_pdf_comprimido), garbage=4, deflate=True)
    finally:
        doc.close()

    texto_final = "\n\n".join(
        paginas_prontas[str(i + 1)] for i in range(total_paginas)
    ).strip()

    if arquivo_parcial.exists():
        arquivo_parcial.unlink()

    return texto_final


def _requisicao_com_retry(
    metodo, url: str, tentativas: int = 3, espera: float = 3.0, **kwargs
) -> requests.Response:
    """
    Executa uma chamada HTTP com novas tentativas em falhas transitórias.

    Parâmetros:
        metodo (callable): Função de requisição (ex.: session.get ou session.post).
        url (str): URL de destino.
        tentativas (int): Número máximo de tentativas.
        espera (float): Segundos de pausa antes de tentar novamente.
    Retorno:
        requests.Response: Resposta HTTP com status 2xx.
    """
    ultimo_erro = None
    for tentativa in range(1, tentativas + 1):
        try:
            resp = metodo(url, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            ultimo_erro = exc
            if tentativa < tentativas:
                print(f"  [retry {tentativa}/{tentativas - 1}] Falha em {url}: {exc}")
                time.sleep(espera)
    raise ultimo_erro


def _extrair_itens_snapshot(snap: dict) -> tuple[list[dict], dict]:
    """
    Extrai a lista de diários e o dicionário de dados do JSON do Livewire.

    Parâmetros:
        snap (dict): Objeto decodificado de wire:snapshot.
    Retorno:
        tuple[list[dict], dict]: Lista de itens encontrados e o bloco 'data' completo.
    """
    data = snap.get("data", {})
    bruto = data.get("searchResults", [[]])[0]
    if not bruto and not data.get("searchActive"):
        bruto = data.get("tabDiaries", [[]])[0]

    itens = []
    for entrada in bruto:
        if isinstance(entrada, list) and entrada and isinstance(entrada[0], dict):
            itens.append(entrada[0])
        elif isinstance(entrada, dict):
            itens.append(entrada)
    return itens, data


def _post_livewire(
    session: requests.Session,
    update_url: str,
    csrf: str,
    snapshot_str: str,
    updates: dict,
    calls: list,
) -> tuple[str, dict]:
    """
    Envia uma atualização de estado para o endpoint Livewire da página.

    Parâmetros:
        session (requests.Session): Sessão HTTP com cookies da página.
        update_url (str): URL do endpoint /livewire/update.
        csrf (str): Token CSRF extraído do HTML inicial.
        snapshot_str (str): Estado serializado atual do componente.
        updates (dict): Campos de modelo a atualizar (ex.: initialDate, finalDate).
        calls (list): Métodos Livewire a invocar (ex.: search, setPage).
    Retorno:
        tuple[str, dict]: Novo snapshot serializado e seu dicionário decodificado.
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-CSRF-TOKEN": csrf,
        "X-Livewire": "true",
    }
    payload = {
        "_token": csrf,
        "components": [{"snapshot": snapshot_str, "updates": updates, "calls": calls}],
    }
    resp = _requisicao_com_retry(
        session.post, update_url, headers=headers, json=payload, timeout=30
    )
    novo_snap_str = resp.json()["components"][0]["snapshot"]
    return novo_snap_str, json.loads(novo_snap_str)


def listar_macapa(
    session: requests.Session, inicio: date, fim: date, intervalo: float
) -> list[dict]:
    """
    Consulta a listagem oficial de Macapá aplicando o filtro de datas e paginação.

    Parâmetros:
        session (requests.Session): Sessão HTTP reutilizada.
        inicio (date): Data inicial do intervalo.
        fim (date): Data final do intervalo.
        intervalo (float): Pausa em segundos entre requisições.
    Retorno:
        list[dict]: Metadados das edições dentro de [inicio, fim].
    """
    resp = _requisicao_com_retry(session.get, MACAPA_URL, timeout=30)

    csrf_match = re.search(r'data-csrf="([^"]+)"', resp.text)
    uri_match = re.search(r'data-update-uri="([^"]+)"', resp.text)
    snap_match = re.search(r'wire:snapshot="([^"]+)"', resp.text)
    if not (csrf_match and uri_match and snap_match):
        raise RuntimeError("Não foi possível localizar wire:snapshot/CSRF em Macapá.")

    csrf = csrf_match.group(1)
    update_url = "https://macapa.ap.gov.br" + uri_match.group(1)
    snap_str = html.unescape(snap_match.group(1))
    
    # Recua e avança 2 dia na consulta à API pois o backend de Macapá trata initialDate e finalDate de forma exclusiva (>, <)
    inicio_consulta = inicio - timedelta(days=2)
    fim_consulta = fim + timedelta(days=2)
    
    time.sleep(intervalo)
    snap_str, snap = _post_livewire(
        session,
        update_url,
        csrf,
        snap_str,
        updates={"initialDate": inicio_consulta.isoformat(), "finalDate": fim_consulta.isoformat()},
        calls=[{"path": "", "method": "search", "params": []}],
    )

    todos_itens, data = _extrair_itens_snapshot(snap)
    total_paginas = int(data.get("totalPages") or 1)

    for pagina in range(2, total_paginas + 1):
        time.sleep(intervalo)
        snap_str, snap = _post_livewire(
            session,
            update_url,
            csrf,
            snap_str,
            updates={},
            calls=[{"path": "", "method": "setPage", "params": [pagina]}],
        )
        itens_pag, _ = _extrair_itens_snapshot(snap)
        todos_itens.extend(itens_pag)
        
    # Mantém o filtro original com 'inicio' para descartar o dia anterior caso ele venha
    return [
        item for item in todos_itens if inicio <= parse_data_br(item["date"]) <= fim
    ]


def sondar_pontas_macapa(
    session: requests.Session, registros: list[dict], intervalo: float, saida_sondas: Path
) -> None:
    """
    Executa sondas HEAD independentes nas pontas do intervalo (menor_id - 1 e maior_id + 1)
    montando URLs pelo padrão observado e salvando o resultado para o verificador offline.

    Parâmetros:
        session (requests.Session): Sessão HTTP.
        registros (list[dict]): Registros coletados de Macapá.
        intervalo (float): Pausa em segundos entre sondas.
        saida_sondas (Path): Caminho do JSON onde o resultado das sondas será salvo.
    """
    ids_numericos = sorted(
        int(r["numero_edicao"]) for r in registros if str(r["numero_edicao"]).isdigit()
    )
    if not ids_numericos:
        return

    menor_reg = min(
        (r for r in registros if str(r["numero_edicao"]) == str(ids_numericos[0])),
        key=lambda r: r["data_publicacao"],
    )
    maior_reg = max(
        (r for r in registros if str(r["numero_edicao"]) == str(ids_numericos[-1])),
        key=lambda r: r["data_publicacao"],
    )

    alvos = [
        ("antes_do_inicio", ids_numericos[0] - 1, date.fromisoformat(menor_reg["data_publicacao"]) - timedelta(days=1)),
        ("depois_do_fim", ids_numericos[-1] + 1, date.fromisoformat(maior_reg["data_publicacao"]) + timedelta(days=1)),
    ]

    resultados = []
    for posicao, num_alvo, dt_alvo in alvos:
        url_padrao = (
            f"https://macapa.ap.gov.br/portal/wp-content/uploads/"
            f"{dt_alvo.year}/{dt_alvo.month:02d}/"
            f"Diario-Oficial-{num_alvo}-{dt_alvo.strftime('%d.%m.%Y')}.pdf"
        )
        time.sleep(intervalo)
        try:
            resp = session.head(url_padrao, timeout=20, allow_redirects=True)
            status = resp.status_code
        except requests.RequestException as exc:
            status = f"erro: {exc}"

        resultados.append(
            {
                "posicao": posicao,
                "numero_testado": str(num_alvo),
                "data_estimada": dt_alvo.isoformat(),
                "url_testada": url_padrao,
                "status_http": status,
                "observacao": "404 nao prova ausencia pois a capitalizacao da URL varia na fonte.",
            }
        )

    saida_sondas.parent.mkdir(parents=True, exist_ok=True)
    saida_sondas.write_text(
        json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def coletar_fortaleza(session: requests.Session, evidence_dir: Path, timeout: int = 60) -> list[dict]:
    """
    Faz 1 requisição simples e honesta para Fortaleza e registra evidência em evidence/
    (HTML do bloqueio WAF ou JSON de erro/timeout), sem sobrescrever arquivos existentes.

    Parâmetros:
        session (requests.Session): Sessão HTTP simples sem camuflagem.
        evidence_dir (Path): Pasta onde as evidências serão salvas.
        timeout (int): Tempo limite em segundos para a tentativa.
    Retorno:
        list[dict]: Lista vazia quando bloqueada ou indisponível.
    """
    evidence_dir.mkdir(parents=True, exist_ok=True)
    arq_html = evidence_dir / "fortaleza_bloqueio.html"
    arq_meta = evidence_dir / "fortaleza_meta.json"
    arq_erro = evidence_dir / "fortaleza_erro.json"

    try:
        resp = session.get(FORTALEZA_URL, timeout=timeout)
        bloqueado = (
            "suporte id bot" in resp.text.lower()
            or "solicitação foi negada" in resp.text.lower()
            or "solicitacao foi negada" in resp.text.lower()
        )
        if not arq_html.exists():
            arq_html.write_text(resp.text, encoding="utf-8")
        if not arq_meta.exists():
            meta = {
                "url": FORTALEZA_URL,
                "status_http": resp.status_code,
                "bloqueado_por_conteudo": bloqueado,
                "coletado_em": datetime.now(FUSO_BR).isoformat(timespec="seconds"),
                "headers": dict(resp.headers),
            }
            arq_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        if bloqueado:
            print(f"[fortaleza] Bloqueio WAF detectado no conteúdo (HTTP {resp.status_code}).")
        else:
            print(f"[fortaleza] Resposta sem assinatura WAF (HTTP {resp.status_code}).")
    except requests.RequestException as exc:
        print(f"[fortaleza] Falha de conexão: {exc}")
        if not arq_erro.exists():
            erro_meta = {
                "url": FORTALEZA_URL,
                "erro": str(exc),
                "coletado_em": datetime.now(FUSO_BR).isoformat(timespec="seconds"),
            }
            arq_erro.write_text(json.dumps(erro_meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return []


def carregar_urls_existentes(saida: Path) -> list[dict]:
    """
    Lê registros válidos já presentes no arquivo JSONL para permitir retomada.

    Parâmetros:
        saida (Path): Caminho do arquivo JSONL.
    Retorno:
        list[dict]: Lista de registros válidos já salvos.
    """
    if not saida.exists():
        return []
    registros = []
    for linha in saida.read_text(encoding="utf-8").splitlines():
        if linha.strip():
            try:
                registros.append(json.loads(linha))
            except json.JSONDecodeError:
                continue
    return registros


def salvar_txt_formatado(registro: dict, pasta_txt: Path) -> None:
    """
    Grava um arquivo .txt legível com cabeçalho e texto extraído para inspeção manual.

    Parâmetros:
        registro (dict): Dicionário completo da edição coletada.
        pasta_txt (Path): Diretório de saída dos arquivos .txt.
    """
    pasta_txt.mkdir(parents=True, exist_ok=True)
    nome_seguro = re.sub(r"[^A-Za-z0-9_-]", "_", str(registro["numero_edicao"]))
    destino = pasta_txt / f"{registro['fonte']}_{nome_seguro}.txt"
    cabecalho = (
        f"Fonte: {registro['fonte']}\n"
        f"Edição: {registro['numero_edicao']} ({registro['tipo']})\n"
        f"Publicação: {registro['data_publicacao']}\n"
        f"URL: {registro['url_documento']}\n"
        f"Coletado em: {registro['coletado_em']}\n"
        + "=" * 60
        + "\n\n"
    )
    destino.write_text(cabecalho + registro["texto"] + "\n", encoding="utf-8")


def coletar_macapa(
    session: requests.Session,
    inicio: date,
    fim: date,
    intervalo: float,
    limite: int | None,
    ocr: RapidOCR,
    saida: Path,
    sobrescrever: bool,
    salvar_txt: bool,
    salvar_pdf_comprimido: bool,
) -> list[dict]:
    """
    Orquestra listagem, download, extração/OCR e gravação incremental de Macapá.

    Parâmetros:
        session (requests.Session): Sessão HTTP reutilizada.
        inicio (date): Data inicial da coleta.
        fim (date): Data final da coleta.
        intervalo (float): Pausa em segundos entre requisições.
        limite (int | None): Limite máximo de edições a processar (ou None para todas).
        ocr (RapidOCR): Instância do motor OCR.
        saida (Path): Caminho do JSONL de saída.
        sobrescrever (bool): Se True, recria o JSONL do zero.
        salvar_txt (bool): Se True, gera .txt formatado em dados/txt/.
        salvar_pdf_comprimido (bool): Se True, salva PDF comprimido em dados/pdfs_comprimidos/.
    Retorno:
        list[dict]: Todos os registros de Macapá presentes na saída após a execução.
    """
    itens = listar_macapa(session, inicio, fim, intervalo)
    print(f"[macapa] {len(itens)} edições listadas entre {inicio} e {fim}.")

    if limite is not None:
        itens = itens[:limite]
        print(f"[macapa] Aplicando --limite {limite}: processando {len(itens)} edição(ões).")

    registros_existentes = [] if sobrescrever else carregar_urls_existentes(saida)
    urls_prontas = {r.get("url_documento") for r in registros_existentes}

    modo = "w" if sobrescrever or not saida.exists() else "a"
    novos = 0
    cache_dir = saida.parent / ".parcial"
    pasta_txt = saida.parent / "txt"
    pasta_pdfs = saida.parent / "pdfs_comprimidos"

    with saida.open(modo, encoding="utf-8") as f:
        for idx, item in enumerate(itens, start=1):
            url = item.get("link", "").strip()
            if url in urls_prontas:
                print(f"[macapa] ({idx}/{len(itens)}) Pulando {item['id']} (já coletado).")
                continue

            titulo = item.get("title", "").strip()
            dt_pub = parse_data_br(item["date"])
            num_edicao = str(item["id"]).strip()

            if not PADRAO_TITULO_MACAPA.match(titulo):
                print(f"[macapa] Aviso: título fora do molde -> {titulo!r}")

            print(f"[macapa] ({idx}/{len(itens)}) Baixando {num_edicao} ({dt_pub})...")
            time.sleep(intervalo)
            pdf_resp = _requisicao_com_retry(session.get, url, timeout=60)

            nome_seguro = re.sub(r"[^A-Za-z0-9_-]", "_", num_edicao)
            caminho_pdf = pasta_pdfs / f"{nome_seguro}.pdf" if salvar_pdf_comprimido else None
            texto = extrair_texto_pdf_com_retomada(
                pdf_resp.content,
                ocr,
                cache_dir / f"{nome_seguro}.json",
                caminho_pdf_comprimido=caminho_pdf,
            )

            reg = {
                "fonte": "macapa",
                "data_publicacao": dt_pub.isoformat(),
                "numero_edicao": num_edicao,
                "tipo": classificar_tipo(num_edicao, titulo, url, dt_pub),
                "url_documento": url,
                "texto": texto,
                "coletado_em": datetime.now(FUSO_BR).isoformat(timespec="seconds"),
            }
            f.write(json.dumps(reg, ensure_ascii=False) + "\n")
            f.flush()
            if salvar_txt:
                salvar_txt_formatado(reg, pasta_txt)

            registros_existentes.append(reg)
            urls_prontas.add(url)
            novos += 1

    print(f"[macapa] {novos} nova(s) edição(ões) gravada(s) em {saida}.")
    return [r for r in registros_existentes if r.get("fonte") == "macapa"]


def main() -> None:
    """Ponto de entrada CLI do coletor."""
    hoje = datetime.now(FUSO_BR).date()
    inicio_padrao = hoje - timedelta(days=59)

    parser = argparse.ArgumentParser(description="Coletor de Diários Oficiais (Macapá e Fortaleza).")
    parser.add_argument("--inicio", default=inicio_padrao.isoformat(), help="Data inicial (YYYY-MM-DD)")
    parser.add_argument("--fim", default=hoje.isoformat(), help="Data final (YYYY-MM-DD)")
    parser.add_argument("--intervalo", type=float, default=3.0, help="Segundos entre requisições")
    parser.add_argument("--limite", type=int, default=None, help="Limita quantidade de PDFs baixados")
    parser.add_argument("--saida", default="dados/diarios.jsonl", help="Arquivo JSONL de saída")
    parser.add_argument("--sobrescrever", action="store_true", help="Recomeça o JSONL do zero")
    parser.add_argument("--pular-sondas", action="store_true", help="Não executa sondas nas pontas")
    parser.add_argument("--salvar-txt", action="store_true", help="Salva .txt formatado por edição para leitura")
    parser.add_argument("--salvar-pdf-comprimido", action="store_true", help="Salva cópia comprimida do PDF para auditoria")
    args = parser.parse_args()

    inicio = date.fromisoformat(args.inicio)
    fim = date.fromisoformat(args.fim)
    saida = Path(args.saida)
    saida.parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    ocr = RapidOCR(params={"Rec.lang_type": "pt"})

    registros_macapa = coletar_macapa(
        session,
        inicio,
        fim,
        args.intervalo,
        args.limite,
        ocr,
        saida,
        args.sobrescrever,
        args.salvar_txt,
        args.salvar_pdf_comprimido,
    )
    if registros_macapa and not args.pular_sondas:
        sondar_pontas_macapa(
            session, registros_macapa, args.intervalo, saida.parent / "sondas_macapa.json"
        )

    time.sleep(args.intervalo)
    coletar_fortaleza(session, Path("evidence"))


if __name__ == "__main__":
    main()
