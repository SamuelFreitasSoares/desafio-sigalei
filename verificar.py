"""
Script de verificação offline dos diários coletados.

Valida cada fonte separadamente (macapa e fortaleza) e termina com código
de saída 1 se qualquer fonte apresentar problema. Opera 100% offline,
usando apenas o JSONL e o arquivo de sondas gravados pelo coletor.

Checagens executadas por fonte:
1. Quantidade > 0 (falha se fonte estiver zerada).
2. Campos obrigatórios, tipos válidos e datas/fuso ISO 8601.
3. Intervalo esperado (--inicio e --fim, quando informados).
4. Duplicatas por (fonte, numero_edicao, tipo) e por url_documento.
5. Legibilidade do texto (tamanho mínimo e proporção de letras).
6. Consistência do número da edição no cabeçalho do texto extraído.
7. Lacunas internas na sequência numérica de edições 'normal'.
8. Sondas independentes (erro se houver HTTP 200 dentro do intervalo).
9. Cobertura de dias úteis (apenas AVISO, pois existem feriados).

Uso:
    python verificar.py
    python verificar.py --inicio 2026-09-28 --fim 2026-11-26
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Fontes que o verificador espera encontrar no JSONL
FONTES_ESPERADAS = ("macapa", "fortaleza")

# Campos que todo registro precisa ter e não pode estar vazio
CAMPOS_OBRIGATORIOS = (
    "fonte",
    "data_publicacao",
    "numero_edicao",
    "tipo",
    "url_documento",
    "texto",
    "coletado_em",
)

# Tipos válidos conforme o mapeamento definido no desafio
TIPOS_VALIDOS = {"normal", "extra", "suplemento"}

# Limiar mínimo de caracteres para considerar texto não-vazio.
# 200 chars é aproximadamente 2-3 frases curtas; qualquer PDF válido
# de diário oficial terá muito mais que isso mesmo numa página.
MIN_CHARS_TEXTO = 200

# Proporção mínima de letras alfabéticas no texto (desconsiderando espaços).
# Textos com OCR totalmente falho produzem sequências de símbolos e números
# com proporção de letras bem abaixo de 45%. Texto administrativo em português
# tipicamente fica acima de 70%.
MIN_PROPORCAO_LETRAS = 0.45


def carregar_jsonl(caminho: Path) -> tuple[list[dict], list[str]]:
    """
    Lê o arquivo JSONL linha a linha, registrando eventuais linhas corrompidas.

    Parâmetros:
        caminho (Path): Caminho do arquivo JSONL a ser lido.
    Retorno:
        tuple[list[dict], list[str]]: Lista de registros válidos e lista de erros de parse.
    """
    registros = []
    erros = []
    if not caminho.exists():
        return [], [f"Arquivo não encontrado: {caminho}"]

    for num_linha, linha in enumerate(caminho.read_text(encoding="utf-8").splitlines(), start=1):
        if not linha.strip():
            continue
        try:
            registros.append(json.loads(linha))
        except json.JSONDecodeError as exc:
            erros.append(f"Linha {num_linha} com JSON inválido: {exc}")
    return registros, erros


def texto_legivel(texto: str) -> tuple[bool, str]:
    """
    Verifica se o texto extraído atende os critérios mínimos de legibilidade.

    Parâmetros:
        texto (str): Texto completo extraído de uma edição.
    Retorno:
        tuple[bool, str]: (True, "") se legível; (False, motivo) caso contrário.
    """
    limpo = texto.strip()
    if len(limpo) < MIN_CHARS_TEXTO:
        return False, f"texto curto/vazio ({len(limpo)} chars < {MIN_CHARS_TEXTO})"

    sem_espacos = "".join(ch for ch in limpo if not ch.isspace())
    if not sem_espacos:
        return False, "texto contém apenas espaços"

    letras = sum(1 for ch in sem_espacos if ch.isalpha())
    proporcao = letras / len(sem_espacos)
    if proporcao < MIN_PROPORCAO_LETRAS:
        return False, f"baixa proporção de letras ({proporcao:.1%}, possível falha de OCR)"
    return True, ""


def numero_presente_no_cabecalho(numero_edicao: str, texto: str) -> bool:
    """
    Confere se o número da edição aparece nos primeiros 1.200 caracteres do texto.

    Parâmetros:
        numero_edicao (str): Identificador da edição (ex.: '5421' ou '5183-A').
        texto (str): Texto completo extraído.
    Retorno:
        bool: True se o número (ou sua parte numérica base) foi encontrado no cabeçalho.
    """
    cabecalho = texto[:1200].lower()
    num_limpo = numero_edicao.strip().lower()
    # Para suplementos como '5183-A', também aceita só a parte numérica '5183'
    base_numerica = num_limpo.split("-")[0]
    return num_limpo in cabecalho or (base_numerica.isdigit() and base_numerica in cabecalho)


def verificar_fonte(
    fonte: str,
    registros: list[dict],
    sondas: list[dict],
    inicio: date | None,
    fim: date | None,
) -> tuple[list[str], list[str]]:
    """
    Executa todas as checagens para uma fonte específica.

    Parâmetros:
        fonte (str): Nome da fonte ('macapa' ou 'fortaleza').
        registros (list[dict]): Registros filtrados dessa fonte.
        sondas (list[dict]): Resultados das sondas independentes nas pontas.
        inicio (date | None): Data inicial esperada (ou None se não informada).
        fim (date | None): Data final esperada (ou None se não informada).
    Retorno:
        tuple[list[str], list[str]]: (erros, avisos) encontrados na validação.
    """
    erros = []
    avisos = []

    # Checagem 1: fonte precisa ter pelo menos 1 edição
    if not registros:
        erros.append("0 edições coletadas (fonte ausente ou bloqueada).")
        return erros, avisos

    chaves_vistas = set()
    urls_vistas = set()
    datas_publicacao = []
    numeros_normais = []

    for idx, reg in enumerate(registros, start=1):
        # Checagem 2: campos obrigatórios
        for campo in CAMPOS_OBRIGATORIOS:
            if campo not in reg or reg[campo] is None or reg[campo] == "":
                erros.append(f"Registro #{idx}: campo obrigatório ausente/vazio '{campo}'.")

        tipo = reg.get("tipo")
        if tipo not in TIPOS_VALIDOS:
            erros.append(f"Registro #{idx}: tipo inválido '{tipo}'.")

        # Validação de data_publicacao (formato ISO)
        dt_pub = None
        try:
            dt_pub = date.fromisoformat(str(reg.get("data_publicacao", "")))
            datas_publicacao.append(dt_pub)
        except ValueError:
            erros.append(f"Registro #{idx}: data_publicacao inválida '{reg.get('data_publicacao')}'.")

        # Checagem 3: intervalo esperado
        if dt_pub and inicio and dt_pub < inicio:
            erros.append(f"Edição {reg.get('numero_edicao')}: data {dt_pub} anterior a --inicio {inicio}.")
        if dt_pub and fim and dt_pub > fim:
            erros.append(f"Edição {reg.get('numero_edicao')}: data {dt_pub} posterior a --fim {fim}.")

        # Validação de coletado_em (ISO 8601 com fuso)
        try:
            dt_col = datetime.fromisoformat(str(reg.get("coletado_em", "")))
            if dt_col.tzinfo is None:
                erros.append(f"Registro #{idx}: coletado_em sem fuso horário.")
        except ValueError:
            erros.append(f"Registro #{idx}: coletado_em inválido '{reg.get('coletado_em')}'.")

        # Checagem 4: duplicatas
        chave = (fonte, str(reg.get("numero_edicao")), str(tipo))
        if chave in chaves_vistas:
            erros.append(f"Duplicata detectada para edição {chave}.")
        chaves_vistas.add(chave)

        url = str(reg.get("url_documento", ""))
        if url in urls_vistas:
            erros.append(f"URL duplicada detectada: {url}")
        urls_vistas.add(url)

        # Checagem 5 e 6: legibilidade e consistência número × cabeçalho
        texto = str(reg.get("texto", ""))
        ok_txt, motivo = texto_legivel(texto)
        if not ok_txt:
            erros.append(f"Edição {reg.get('numero_edicao')}: {motivo}.")
        elif not numero_presente_no_cabecalho(str(reg.get("numero_edicao", "")), texto):
            erros.append(
                f"Edição {reg.get('numero_edicao')}: número não encontrado nos primeiros 1.200 chars do texto."
            )

        # Acumula números de edições normais para checagem de sequência
        if tipo == "normal" and str(reg.get("numero_edicao", "")).isdigit():
            numeros_normais.append(int(reg["numero_edicao"]))

    # Checagem 7: lacunas internas na sequência numérica
    if len(numeros_normais) >= 2:
        ordenados = sorted(set(numeros_normais))
        esperados = set(range(ordenados[0], ordenados[-1] + 1))
        faltantes = sorted(esperados - set(ordenados))
        if faltantes:
            erros.append(
                f"Lacuna(s) na sequência numérica entre {ordenados[0]} e {ordenados[-1]}: {faltantes}"
            )

    # Checagem 9: cobertura de dias úteis (apenas AVISO, pois existem feriados)
    if len(datas_publicacao) >= 2:
        dt_min, dt_max = min(datas_publicacao), max(datas_publicacao)
        conjunto_datas = set(datas_publicacao)
        dias_uteis_sem_edicao = []
        cursor = dt_min
        while cursor <= dt_max:
            if cursor.weekday() < 5 and cursor not in conjunto_datas:
                dias_uteis_sem_edicao.append(cursor.isoformat())
            cursor += timedelta(days=1)
        if dias_uteis_sem_edicao:
            avisos.append(
                f"{len(dias_uteis_sem_edicao)} dia(s) útil(is) sem edição (podem ser feriados): "
                f"{dias_uteis_sem_edicao[:5]}{'...' if len(dias_uteis_sem_edicao) > 5 else ''}"
            )

    # Checagem 8: sondas independentes nas pontas
    if fonte == "macapa" and sondas:
        for s in sondas:
            status = s.get("status_http")
            dt_est_str = s.get("data_estimada")
            dentro_intervalo = False
            if inicio and fim and dt_est_str:
                try:
                    dt_est = date.fromisoformat(dt_est_str)
                    dentro_intervalo = inicio <= dt_est <= fim
                except ValueError:
                    pass

            if status == 200 and dentro_intervalo:
                erros.append(
                    f"Sonda {s.get('posicao')} ({s.get('numero_testado')} / {dt_est_str}) "
                    f"retornou HTTP 200 dentro do intervalo esperado, indicando edição omitida na listagem."
                )
            else:
                avisos.append(
                    f"Sonda {s.get('posicao')} ({s.get('numero_testado')} / {dt_est_str}): HTTP {status}"
                )

    return erros, avisos


def main() -> int:
    """
    Ponto de entrada CLI do verificador.

    Retorno:
        int: 0 se todas as fontes passaram; 1 se qualquer fonte apresentou erro.
    """
    parser = argparse.ArgumentParser(description="Verificador offline da coleta de diários.")
    parser.add_argument("--arquivo", default="dados/diarios.jsonl", help="Caminho do JSONL")
    parser.add_argument("--sondas", default="dados/sondas_macapa.json", help="Arquivo de sondas")
    parser.add_argument("--inicio", default=None, help="Data inicial esperada (YYYY-MM-DD)")
    parser.add_argument("--fim", default=None, help="Data final esperada (YYYY-MM-DD)")
    args = parser.parse_args()

    inicio = date.fromisoformat(args.inicio) if args.inicio else None
    fim = date.fromisoformat(args.fim) if args.fim else None

    registros, erros_globais = carregar_jsonl(Path(args.arquivo))
    if erros_globais:
        for e in erros_globais:
            print(f"[ERRO GLOBAL] {e}")
        return 1

    sondas = []
    arq_sondas = Path(args.sondas)
    if arq_sondas.exists():
        sondas = json.loads(arq_sondas.read_text(encoding="utf-8"))

    falhou = False
    for fonte in FONTES_ESPERADAS:
        regs_fonte = [r for r in registros if r.get("fonte") == fonte]
        erros, avisos = verificar_fonte(fonte, regs_fonte, sondas, inicio, fim)
        status = "FALHA" if erros else "OK"
        print(f"=== Fonte: {fonte} | Edições: {len(regs_fonte)} | Status: {status} ===")
        for av in avisos:
            print(f"  [AVISO] {av}")
        for er in erros:
            print(f"  [ERRO]  {er}")
        if erros:
            falhou = True

    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
