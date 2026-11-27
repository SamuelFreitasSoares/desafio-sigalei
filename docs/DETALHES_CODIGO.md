# Documentação Detalhada do Código

Este documento explica cada decisão de projeto, variável, dependência e fluxo do código para facilitar manutenção e alteração manual sem IA.

---

## Sumário

1. [Dependências e justificativas](#1-dependências-e-justificativas)
2. [coletar.py — detalhamento completo](#2-coletarpy--detalhamento-completo)
3. [verificar.py — detalhamento completo](#3-verificarpy--detalhamento-completo)
4. [testar_verificador.py — detalhamento completo](#4-testar_verificadorpy--detalhamento-completo)
5. [Decisões de projeto e justificativas](#5-decisões-de-projeto-e-justificativas)
6. [Limitações conhecidas](#6-limitações-conhecidas)

---

## 1. Dependências e justificativas

| Pacote | Versão mínima | Por que é necessário |
|--------|---------------|---------------------|
| `requests` | >=2.31.0 | Facilita requisições HTTP com sessão, cookies, retry e headers. `urllib.request` da stdlib seria possível, mas o código ficaria mais verboso e difícil de modificar ao vivo sem IA — `requests` é a escolha mais legível para quem vai manter. |
| `pymupdf` | >=1.24.0 | Lê PDFs em memória (`stream=bytes`), extrai texto nativo (`get_text("text")`), renderiza páginas como imagem (`get_pixmap(dpi=...)`) para OCR e salva cópias comprimidas (`doc.save(..., garbage=4, deflate=True)`). Alternativa seria `pdfminer.six` + `pdf2image` + `Pillow`, mas `pymupdf` unifica tudo em 1 pacote sem dependência de Poppler. |
| `rapidocr` | >=3.0.0 | Motor OCR baseado em PaddleOCR com suporte nativo a português (`Rec.lang_type="pt"`). A versão legada `rapidocr-onnxruntime` não suportava o idioma `pt` diretamente. Escolhido em vez de `pytesseract` para não exigir instalação de binário externo (Tesseract), garantindo reprodutibilidade via `pip install`. |
| `onnxruntime` | >=1.18.0 | Backend de inferência usado pelo `rapidocr` para rodar os modelos ONNX de detecção e reconhecimento de texto. |

**Nenhuma outra dependência é necessária.** Os demais módulos (`argparse`, `json`, `re`, `time`, `html`, `datetime`, `pathlib`) são da biblioteca padrão do Python.

---

## 2. `coletar.py` — detalhamento completo

### Constantes globais

```python
FUSO_BR = timezone(timedelta(hours=-3))
```
Fuso horário fixo UTC-3 (Brasília, Macapá, Fortaleza). Usa `datetime.timezone` em vez de `zoneinfo.ZoneInfo("America/Sao_Paulo")` porque o pacote `tzdata` não está instalado por padrão no Windows dentro de um venv limpo. O UTC-3 fixo é suficiente pois Macapá e Fortaleza não usam horário de verão.

```python
PADRAO_TITULO_MACAPA = re.compile(r"^DI[ÁA]RIO OFICIAL N[º°o]?:\s*(\S+)-(\d{2}/\d{2}/\d{4})$", re.IGNORECASE)
```
Validador do molde observado nos títulos da listagem (ex.: `DIÁRIO OFICIAL Nº: 5421-25/11/2026`). Aceita variações de acento (`Á`/`A`) e símbolo de grau (`º`/`°`/`o`). Títulos fora do molde geram aviso no console.

```python
PADRAO_SUPLEMENTO = re.compile(r"\b\d+-[A-Za-z]+\b")
```
Identifica sufixo alfabético no número da edição (ex.: `5183-A` em suplementos). Encontrado por inspeção manual na fonte.

### `parse_data_br(texto) -> date`
Converte data brasileira (`DD/MM/YYYY`) para `datetime.date`. Usada para converter o campo `date` que vem da listagem Livewire.

### `classificar_tipo(numero_edicao, titulo, url, data_pub) -> str`
Lógica de mapeamento (em ordem de prioridade):
1. **Suplemento:** `"suplement"` no texto combinado OU sufixo `-\w+` no número (ex.: `5183-A`).
2. **Extra:** `"extra"` no texto combinado OU `data_pub.weekday() >= 5` (sábado=5, domingo=6).
3. **Normal:** todos os demais.

**Limitação:** feriados em dias de semana não são detectados como `extra` automaticamente. Detectar feriados sem dependência adicional exigiria uma lista fixa, que pode ficar desatualizada. Veja a seção de limitações.

### `ordenar_blocos_por_coluna(boxes, txts, largura, altura) -> list[str]`
As páginas internas dos diários de Macapá têm 2 colunas. Sem reordenação, o OCR lê de cima para baixo intercalando as colunas (mistura atos diferentes).

**Variáveis internas:**
- `meio_x = largura / 2.0`: coordenada X que divide as duas colunas.
- `topo_y = altura * 0.12`: limite Y abaixo do qual o texto é considerado cabeçalho.
- `grupo`: 0 = cabeçalho/largura total, 1 = coluna esquerda, 2 = coluna direita.
- `cruza_centro`: caixa que começa na esquerda e termina na direita com largura > 35% da página (títulos de seção).

A ordenação final é `(grupo, y0, x0)` — cabeçalho primeiro, depois coluna esquerda inteira, depois coluna direita inteira, sempre de cima para baixo dentro de cada grupo.

### `extrair_texto_pdf_com_retomada(pdf_bytes, ocr, arquivo_parcial, dpi, caminho_pdf_comprimido) -> str`
Extrai texto do PDF página por página com **retomada em caso de interrupção**:

1. Abre o PDF em memória via `pymupdf.open(stream=...)`.
2. Carrega `arquivo_parcial` (JSON em `dados/.parcial/<id>.json`) se existir — contém `{"paginas": {"1": "texto...", "2": "texto..."}}`.
3. Para cada página não presente no parcial:
   - Tenta `pagina.get_text("text")`. Se >= 100 chars, usa o texto nativo.
   - Senão, renderiza a `dpi` DPI, roda `ocr(png_bytes)` e ordena por coluna.
   - **Salva o parcial no disco a cada página concluída** (sobrescrevendo o JSON).
4. Opcionalmente salva cópia comprimida via `doc.save(..., garbage=4, deflate=True)`.
5. Ao concluir todas as páginas, apaga o arquivo parcial.

**Se o processo for interrompido** (ex.: Ctrl+C, queda de energia) no meio da página 7 de 13, na próxima execução as páginas 1-6 já estão no parcial e são reaproveitadas sem repetir o OCR. Apenas a página 7 é refeita.

### `_requisicao_com_retry(metodo, url, tentativas, espera, **kwargs) -> Response`
Wrapper de retry simples: tenta a requisição até `tentativas` vezes, com `espera` segundos de pausa entre falhas. Lança a última exceção se todas falharem.

### `listar_macapa(session, inicio, fim, intervalo) -> list[dict]`
Fluxo completo de comunicação com o Livewire:
1. `GET /diarios-oficiais/` → extrai `data-csrf`, `data-update-uri` e `wire:snapshot`.
2. `POST /livewire/update` com `updates: {initialDate, finalDate}` e `calls: [{method: "search"}]`.
3. Loop de `setPage(2..N)` conforme `totalPages` retornado.
4. Filtra estritamente por `[inicio, fim]` como segurança contra bordas da API.

### `sondar_pontas_macapa(session, registros, intervalo, saida_sondas)`
Sonda `HEAD` em `menor_id - 1` e `maior_id + 1`, montando a URL pelo padrão. Se a URL retornar `200`, **pode** indicar edição omitida na listagem. Se retornar `404`, **não prova** ausência porque a capitalização varia. Resultado salvo em `dados/sondas_macapa.json`.

### `coletar_fortaleza(session, evidence_dir, timeout) -> list[dict]`
Faz 1 requisição honesta (sem camuflagem). Dois cenários possíveis:
- **Resposta recebida:** inspeciona o HTML buscando `"suporte id bot"` ou `"solicitação foi negada"` e salva `fortaleza_bloqueio.html` + `fortaleza_meta.json`.
- **Timeout/erro de rede:** salva `fortaleza_erro.json` com a mensagem de erro.

Nunca sobrescreve arquivos já existentes em `evidence/` (preserva a primeira evidência).

### `coletar_macapa(session, inicio, fim, ..., salvar_txt, salvar_pdf_comprimido) -> list[dict]`
Orquestrador principal:
1. Lista edições via `listar_macapa()`.
2. Para cada edição não presente no JSONL (retomada por `url_documento`):
   - Baixa o PDF.
   - Extrai texto com `extrair_texto_pdf_com_retomada()`.
   - **Grava 1 linha no JSONL** e chama `f.flush()` imediatamente.
   - Opcionalmente gera `.txt` formatado e/ou PDF comprimido.
3. Se interrompido, na próxima execução pula edições já salvas no JSONL.

### `salvar_txt_formatado(registro, pasta_txt)`
Gera `dados/txt/macapa_5421.txt` com cabeçalho (fonte, edição, tipo, data, URL, timestamp) seguido do texto completo. Para inspeção e comparação manual.

### Flags de CLI

| Flag | Padrão | Descrição |
|------|--------|-----------|
| `--inicio` | hoje - 59 dias | Data inicial ISO |
| `--fim` | hoje | Data final ISO |
| `--intervalo` | 3.0 | Segundos entre requisições |
| `--limite` | None | Quantidade máxima de PDFs |
| `--saida` | `dados/diarios.jsonl` | Arquivo de saída |
| `--sobrescrever` | False | Recria o JSONL do zero |
| `--pular-sondas` | False | Não executa sondas nas pontas |
| `--salvar-txt` | False | Gera .txt por edição em `dados/txt/` |
| `--salvar-pdf-comprimido` | False | Salva PDF comprimido em `dados/pdfs_comprimidos/` |

---

## 3. `verificar.py` — detalhamento completo

### Constantes e limiares

- `MIN_CHARS_TEXTO = 200`: páginas válidas de diário oficial têm sempre muito mais que 200 chars. Esse limiar pega texto vazio ou extração completamente falha.
- `MIN_PROPORCAO_LETRAS = 0.45`: texto administrativo em português tipicamente tem >70% de letras. Abaixo de 45% indica OCR que produziu lixo (símbolos, números aleatórios). Valor escolhido conservadoramente para não dar falso positivo em textos com muitas tabelas numéricas.

### `carregar_jsonl(caminho) -> (registros, erros)`
Lê linha a linha. Se uma linha não for JSON válido (ex.: arquivo corrompido por interrupção no meio de uma gravação), registra o erro com número da linha mas **continua lendo as demais**. Se houver qualquer erro de parse, `main()` imprime os erros e retorna código 1 imediatamente, sem tentar validar registros parciais.

### `texto_legivel(texto) -> (bool, motivo)`
1. Remove espaços externos (`strip`).
2. Conta caracteres totais (sem espaços) e letras alfabéticas.
3. Falha se < 200 chars ou se proporção de letras < 45%.

### `numero_presente_no_cabecalho(numero_edicao, texto) -> bool`
Busca o número nos primeiros 1.200 caracteres. Para suplementos como `5183-A`, aceita tanto `5183-a` quanto apenas `5183`. Pega PDFs trocados (download correto mas texto de outra edição) e falhas graves de OCR no cabeçalho.

### `verificar_fonte(fonte, registros, sondas, inicio, fim) -> (erros, avisos)`
Checagens em ordem:
1. **Quantidade > 0**: se a fonte tiver 0 edições, já retorna erro.
2. **Campos obrigatórios**: itera sobre `CAMPOS_OBRIGATORIOS` checando presença e não-vazio.
3. **Intervalo**: se `--inicio`/`--fim` informados, qualquer edição fora gera erro.
4. **Duplicatas**: por `(fonte, numero_edicao, tipo)` e por `url_documento`.
5. **Legibilidade**: tamanho e proporção de letras.
6. **Consistência**: número da edição no cabeçalho do texto.
7. **Lacunas**: sequência numérica apenas de edições `normal` (suplementos como `5183-A` são ignorados).
8. **Sondas**: HTTP 200 dentro do intervalo = erro; fora do intervalo ou 404 = aviso.
9. **Dias úteis**: aviso (nunca erro) quando há dias úteis sem edição.

### Como o código lida com falhas
O verificador **acumula todos os erros e avisos** de todas as fontes antes de reportar. Ele nunca interrompe no primeiro erro — processa todas as edições e todas as fontes, imprime o relatório completo, e só ao final retorna código 1 se qualquer erro existiu. Isso é intencional: um relatório parcial esconderia problemas.

---

## 4. `testar_verificador.py` — detalhamento completo

### Estrutura
Sem framework de testes. Gera registros sintéticos com `gerar_registro()`, grava em JSONL temporário (`tempfile.TemporaryDirectory`) e roda `verificar.py` como subprocesso, comparando o código de saída.

### Cenários testados (15 no total)
| # | Cenário | Esperado | O que testa |
|---|---------|----------|-------------|
| 1 | Base válida com suplemento | exit=0 | Caminho feliz |
| 2 | Fortaleza zerada | exit=1 | Fonte ausente |
| 3 | Lacuna na sequência | exit=1 | Edição normal faltando |
| 4 | Edição duplicada | exit=1 | Mesmo (fonte, num, tipo) repetido |
| 5 | URL duplicada | exit=1 | Mesmo PDF em dois registros |
| 6 | Texto vazio | exit=1 | Campo texto = "" |
| 7 | Texto ilegível | exit=1 | Símbolos sem letras |
| 8 | Número divergente | exit=1 | PDF trocado |
| 9 | Fora do intervalo | exit=1 | --inicio/--fim violado |
| 10 | Sonda HTTP 200 | exit=1 | Edição omitida detectada |
| 11 | Campo vazio | exit=1 | url_documento = "" |
| 12 | Data formato errado | exit=1 | DD/MM/YYYY em vez de ISO |
| 13 | Sem fuso horário | exit=1 | coletado_em sem offset |
| 14 | Tipo inválido | exit=1 | "especial" em vez dos 3 válidos |
| 15 | Linha corrompida | exit=1 | JSON mal-formado no JSONL |

---

## 5. Decisões de projeto e justificativas

### Por que JSONL e não CSV, Parquet ou SQLite?
- **CSV:** corrompe facilmente com textos longos contendo vírgulas, quebras de linha e aspas.
- **Parquet:** excelente para grandes volumes, mas exige `pyarrow` ou `fastparquet` e não é legível diretamente no terminal.
- **SQLite:** bom para consultas, mas exige `sqlite3` e não permite append trivial ou inspeção com `head`/`cat`.
- **JSONL:** append é barato (1 linha = 1 registro), não corrompe vizinhos, legível no editor, ideal para streams e ingestão por LLMs. Desvantagem: ocupa mais espaço que Parquet, aceitável para ~40 edições.

### Por que 150 DPI e não 200 ou 300?
Testamos 150 e 200 DPI nos dois PDFs locais. Os resultados foram quase idênticos em qualidade e acentuação, com 150 DPI ~10-15% mais rápido e usando menos memória. Para 300+ DPI o tempo por página aumentaria significativamente sem ganho proporcional de qualidade com o modelo PP-OCRv6.

### Por que ordenação de 2 colunas no OCR?
Sem reordenação, o RapidOCR mistura linhas das duas colunas (lê de cima para baixo ignorando a divisão horizontal). Isso produz texto incoerente para indexação e LLMs. A solução é simples (~20 linhas) e usa apenas as coordenadas que o próprio OCR já retorna.

### Por que gravação incremental e não batch?
O OCR de 38 PDFs leva ~15-20 minutos. Se o processo cair na edição 30, perder 25 minutos de trabalho é inaceitável. A gravação linha a linha com `flush()` + retomada por `url_documento` garante que qualquer interrupção perde no máximo 1 edição.

### Por que evidência em `evidence/` e não logs no console?
O desafio pede "registre o que aconteceu". Um print no console se perde ao fechar o terminal. Arquivos persistentes (`fortaleza_bloqueio.html`, `fortaleza_meta.json` ou `fortaleza_erro.json`) são auditáveis e reproduzíveis.

### Por que `--salvar-pdf-comprimido` é opcional?
O enunciado diz "os PDFs não precisam ir para o repositório". Mas para auditoria (comparar OCR com original), ter o PDF é valioso. A compressão via `pymupdf` (`garbage=4, deflate=True`) reduz o tamanho significativamente sem perda de qualidade. É opcional (`--salvar-pdf-comprimido`) para não inflar o repositório por padrão.

---

## 6. Limitações conhecidas

### Feriados vs. edições extras
`classificar_tipo()` marca fins de semana como `extra`, mas **não detecta feriados em dias úteis**. Uma lista de feriados nacionais e municipais de Macapá/AP poderia ser adicionada como constante no código (sem dependência), mas:
- Feriados municipais variam e podem mudar por decreto.
- Uma lista fixa ficaria desatualizada.
- O impacto é baixo: o `verificar.py` trata dias úteis sem edição como **aviso**, não erro.

### Rotação de páginas no PDF
O `pymupdf` respeita a propriedade `rotation` do PDF ao extrair texto nativo e ao renderizar. Se a página estiver marcada como rotacionada (90°, 180°, 270°), `get_text()` e `get_pixmap()` já compensam automaticamente. No entanto, se a **imagem escaneada** estiver fisicamente rotacionada sem a flag de rotação no PDF, o OCR pode falhar. O `RapidOCR` inclui um classificador de orientação (`cls`) que tenta corrigir rotações de 180°, mas rotações de 90° sem a flag no PDF seriam problemáticas. Isso não foi observado nos PDFs de Macapá testados.

### Horário exato de publicação
A listagem Livewire de Macapá fornece apenas a **data** de publicação (`date: "25/11/2026"`), sem horário. Os metadados do PDF (`CreationDate`, `ModDate`) poderiam indicar quando o arquivo foi gerado, mas não necessariamente quando foi publicado no site. Não há endpoint na API que forneça timestamp com hora.

### Capitalização dos links
A URL de um PDF usa `Diario-oficial-5414-...` enquanto as demais usam `Diario-Oficial-...`. Montar URLs pelo padrão em vez de usar os links da listagem falharia nesse caso.

### Verificação circular vs. independente
A listagem Livewire é a única fonte de descoberta automatizável. As sondas HEAD nas pontas do intervalo são o segundo caminho independente, mas limitado pela variação de capitalização (404 ≠ ausência). A sequência numérica pega lacunas internas mas não nas pontas. Nenhuma checagem isolada é completa — a confiança vem do conjunto.
