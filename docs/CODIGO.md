# Guia de Manutenção do Código

Este documento explica o que cada parte do código faz e onde alterar caso a fonte mude ou você precise ajustar regras.

---

## 1. `coletar.py`

### Constantes no topo
- `FUSO_BR`: fuso fixo `UTC-3` (`timezone(timedelta(hours=-3))`), evitando dependência de `tzdata` no Windows.
- `MACAPA_URL` e `FORTALEZA_URL`: URLs base das duas fontes.
- `PADRAO_TITULO_MACAPA` e `PADRAO_SUPLEMENTO`: expressões regulares para validar títulos e identificar suplementos com sufixo alfabético (ex.: `5183-A`).

### Funções principais
- `classificar_tipo(numero_edicao, titulo, url, data_pub)`:
  - Retorna `"suplemento"` se houver `"suplement"` ou sufixo `-\w+` (ex.: `5183-A`).
  - Retorna `"extra"` se houver `"extra"` ou se `data_pub.weekday() >= 5` (sábado/domingo).
  - **Como alterar:** para adicionar uma nova palavra-chave ou uma lista de feriados, edite os dois `if`s iniciais dessa função.
- `ordenar_blocos_por_coluna(boxes, txts, largura, altura)`:
  - Separa cabeçalho (`y0 < 12%` da página ou caixa larga cruzando o centro), depois ordena coluna esquerda (`centro_x < largura/2`) e coluna direita (`centro_x >= largura/2`).
  - **Como alterar:** se uma edição tiver 3 colunas ou cabeçalho maior, ajuste `topo_y = altura * 0.12` ou a divisão por `largura`.
- `extrair_texto_pdf_com_retomada(pdf_bytes, ocr, arquivo_parcial, dpi=150)`:
  - Usa texto nativo se a página tiver `>= 100` caracteres; caso contrário, renderiza a `150` DPI e roda `RapidOCR(pt)`.
  - Salva cada página concluída em `dados/.parcial/<id>.json` e apaga o arquivo ao concluir o PDF.
  - **Como alterar:** mude `dpi=150` para `200` ou ajuste o limiar `100` se páginas escaneadas tiverem rodapés digitais curtos.
- `listar_macapa(session, inicio, fim, intervalo)`:
  - Faz `GET` inicial para ler `data-csrf`, `data-update-uri` e `wire:snapshot`.
  - Dispara `POST /livewire/update` chamando `search` e depois `setPage(2..N)`.
  - **Como alterar:** se a prefeitura mudar o nome do método no botão de busca ou paginação, altere `"method": "search"` ou `"method": "setPage"` nas chamadas `_post_livewire`.
- `sondar_pontas_macapa(session, registros, intervalo, saida_sondas)`:
  - Testa `menor_id - 1` e `maior_id + 1` via `HEAD` e grava em `dados/sondas_macapa.json`.
- `coletar_fortaleza(session, evidence_dir, timeout=60)`:
  - Faz 1 requisição simples. Se receber HTML com bloqueio WAF, salva `fortaleza_bloqueio.html` + `fortaleza_meta.json`; se der erro/timeout, salva `fortaleza_erro.json`. Nunca sobrescreve arquivos já existentes.
- `coletar_macapa(...)`:
  - Grava linha a linha no `dados/diarios.jsonl` (`flush()`) e pula `url_documento` já presente no arquivo (retomada).

---

## 2. `verificar.py`

- **Limiar de qualidade no topo:** `MIN_CHARS_TEXTO = 200` e `MIN_PROPORCAO_LETRAS = 0.45`.
- `carregar_jsonl`: lê o JSONL linha a linha e falha se qualquer linha tiver JSON inválido.
- `texto_legivel`: verifica tamanho mínimo e proporção de letras alfabéticas.
- `numero_presente_no_cabecalho`: confere se `numero_edicao` (ou a base antes do `-`) aparece nos primeiros `1.200` caracteres do texto extraído.
- `verificar_fonte`:
  - Falha se `registros` estiver vazio (`0` edições).
  - Valida campos obrigatórios, datas ISO, duplicatas, sequência numérica de edições `"normal"` e sondas `HTTP 200` dentro de `[--inicio, --fim]`.
  - Dias úteis sem edição geram apenas `[AVISO]` (feriados).
- **Como alterar:** para adicionar um novo campo obrigatório ou relaxar o tamanho mínimo do texto, edite `CAMPOS_OBRIGATORIOS` ou `MIN_CHARS_TEXTO` no topo.

---

## 3. `testar_verificador.py`

- Gera registros sintéticos em pasta temporária (`tempfile.TemporaryDirectory`) e testa 9 cenários (1 válido e 8 falhas injetadas).
- **Como alterar:** adicione uma nova tupla `(nome, dados, sondas, extra_args, codigo_esperado)` na lista `cenarios` dentro de `main()`.
