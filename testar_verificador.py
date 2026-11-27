"""
Teste simples do script verificar.py (sem framework de testes).

Cria cópias temporárias com dados válidos e injeta 13 falhas propositais
para confirmar que verificar.py detecta cada problema e sai com código != 0.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def gerar_registro(
    fonte: str, num: str, data: str, tipo: str = "normal", texto: str | None = None
) -> dict:
    """
    Gera um registro sintético válido para os cenários de teste.

    Parâmetros:
        fonte (str): Nome da fonte ('macapa' ou 'fortaleza').
        num (str): Número da edição.
        data (str): Data ISO ('YYYY-MM-DD').
        tipo (str): 'normal', 'extra' ou 'suplemento'.
        texto (str | None): Texto customizado (ou padrão válido se None).
    Retorno:
        dict: Registro no formato esperado pelo JSONL.
    """
    if texto is None:
        texto = (
            f"PREFEITURA MUNICIPAL - DIÁRIO OFICIAL Nº {num} ({data}). "
            "Portaria administrativa publicada para fins de validação do verificador offline. " * 4
        )
    return {
        "fonte": fonte,
        "data_publicacao": data,
        "numero_edicao": num,
        "tipo": tipo,
        "url_documento": f"https://exemplo.gov.br/{fonte}/{num}-{tipo}.pdf",
        "texto": texto,
        "coletado_em": "2026-11-26T15:00:00-03:00",
    }


def rodar_verificador(
    registros: list[dict] | None,
    tmp_dir: Path,
    sondas: list[dict] | None = None,
    extras_args: list[str] | None = None,
    conteudo_bruto: str | None = None,
) -> int:
    """
    Grava os registros/sondas temporários e executa verificar.py em subprocesso.

    Parâmetros:
        registros (list[dict] | None): Lista de registros a gravar como JSONL.
        tmp_dir (Path): Diretório temporário para os arquivos de teste.
        sondas (list[dict] | None): Lista opcional de sondas simuladas.
        extras_args (list[str] | None): Flags extras passadas ao verificar.py.
        conteudo_bruto (str | None): Conteúdo literal para simular JSONL corrompido.
    Retorno:
        int: Código de saída retornado pelo verificar.py.
    """
    arq = tmp_dir / "teste.jsonl"
    if conteudo_bruto is not None:
        arq.write_text(conteudo_bruto, encoding="utf-8")
    else:
        arq.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in (registros or [])) + "\n",
            encoding="utf-8",
        )

    arq_sondas = tmp_dir / "sondas.json"
    if sondas is not None:
        arq_sondas.write_text(json.dumps(sondas), encoding="utf-8")
    elif arq_sondas.exists():
        arq_sondas.unlink()

    cmd = [
        sys.executable,
        "verificar.py",
        "--arquivo",
        str(arq),
        "--sondas",
        str(arq_sondas),
    ]
    if extras_args:
        cmd.extend(extras_args)

    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode


def main() -> int:
    """Executa todos os cenários (1 válido + 13 falhas propositais) e retorna 0 se todos passarem."""
    base_valida = [
        gerar_registro("macapa", "5419", "2026-11-23"),
        gerar_registro("macapa", "5420", "2026-11-24"),
        gerar_registro("macapa", "5420-A", "2026-11-25", tipo="suplemento"),
        gerar_registro("macapa", "5421", "2026-11-25"),
        gerar_registro("fortaleza", "8001", "2026-11-25"),
    ]

    reg_sem_url = dict(base_valida[0], url_documento="")
    reg_data_br = dict(base_valida[0], data_publicacao="23/11/2026")
    reg_sem_fuso = dict(base_valida[0], coletado_em="2026-11-26T15:00:00")
    reg_tipo_invalido = dict(base_valida[0], tipo="especial")
    reg_url_duplicada = dict(base_valida[0], numero_edicao="5422", texto="DIÁRIO OFICIAL Nº 5422 " + "texto válido " * 25)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        cenarios = [
            ("Base válida com suplemento 5420-A", base_valida, None, None, None, 0),
            ("Fonte Fortaleza zerada", [r for r in base_valida if r["fonte"] != "fortaleza"], None, None, None, 1),
            ("Lacuna na sequência (apaga 5420)", [r for r in base_valida if r["numero_edicao"] != "5420"], None, None, None, 1),
            ("Edição duplicada", base_valida + [base_valida[0]], None, None, None, 1),
            ("URL duplicada entre edições diferentes", base_valida + [reg_url_duplicada], None, None, None, 1),
            ("Texto vazio", [gerar_registro("macapa", "5419", "2026-11-23", texto="")] + base_valida[1:], None, None, None, 1),
            ("Texto ilegível (símbolos)", [gerar_registro("macapa", "5419", "2026-11-23", texto="###@@@ 12345 !!! " * 20)] + base_valida[1:], None, None, None, 1),
            ("Número divergente do texto (PDF trocado)", [gerar_registro("macapa", "5419", "2026-11-23", texto="DIÁRIO OFICIAL Nº 9999 texto administrativo válido " * 10)] + base_valida[1:], None, None, None, 1),
            ("Edição fora do intervalo --inicio/--fim", base_valida, None, ["--inicio", "2026-11-24", "--fim", "2026-11-25"], None, 1),
            ("Sonda HTTP 200 dentro do intervalo", base_valida, [{"posicao": "depois_do_fim", "numero_testado": "5422", "data_estimada": "2026-11-25", "status_http": 200}], ["--inicio", "2026-11-23", "--fim", "2026-11-26"], None, 1),
            ("Campo obrigatório vazio (url_documento)", [reg_sem_url] + base_valida[1:], None, None, None, 1),
            ("Data fora do padrão ISO", [reg_data_br] + base_valida[1:], None, None, None, 1),
            ("Timestamp sem fuso horário", [reg_sem_fuso] + base_valida[1:], None, None, None, 1),
            ("Tipo inválido ('especial')", [reg_tipo_invalido] + base_valida[1:], None, None, None, 1),
            ("JSONL com linha corrompida", None, None, None, '{"fonte": "macapa"\n', 1),
        ]

        falhou_teste = False
        for nome, dados, sondas, extra_args, bruto, esperado in cenarios:
            codigo = rodar_verificador(dados, tmp_dir, sondas, extra_args, bruto)
            ok = codigo == esperado
            print(f"[{'PASS' if ok else 'FAIL'}] {nome} -> exit={codigo} (esperado={esperado})")
            if not ok:
                falhou_teste = True

        return 1 if falhou_teste else 0


if __name__ == "__main__":
    sys.exit(main())
