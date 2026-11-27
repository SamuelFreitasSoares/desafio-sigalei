# Coletor de Diários Oficiais (Macapá-AP e Fortaleza-CE)

## Como rodar

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Coleta dos últimos 60 dias 
python coletar.py

# Teste rápido com 1 edição (ou --sobrescrever para recomeçar do zero)
python coletar.py --limite 1

# Verificação offline (termina com erro se qualquer fonte falhar)
python verificar.py --inicio 2026-09-29 --fim 2026-11-27

# Teste do verificador (injeta falhas em cópia temporária)
python testar_verificador.py
```

- **Intervalo teste da janela de 60 dias:** início = 2026-09-29 | fim = 2026-11-27.
- **Amostra validada neste repositório:** `coletar.py` listou `39` edições de Macapá na janela e as extraiu integralmente em [dados/diarios.jsonl](dados/diarios.jsonl). (20~25 minutos de OCR)

## Formato, retomada e mapeamento de tipos

- **JSONL (`dados/diarios.jsonl`):** cada linha é um JSON independente; não corrompe com textos longos como CSV, permite gravação incremental (`flush` a cada edição) e é legível diretamente para indexação/LLMs. Durante o OCR de um PDF, o progresso por página é salvo em `dados/.parcial/` e apagado ao concluir.
- **Tipos:** nas edições coletadas, os tipos são `normal`. Em busca manual na fonte, foram observados suplementos com sufixo alfabético (ex.: `5183-A`), às vezes publicados dias depois da edição normal. Assim, `coletar.py` mapeia sufixos `-\w+` (ou `"suplement"`) para `suplemento`, fins de semana (ou `"extra"`) para `extra`, e os demais para `normal`.

## Como cada fonte funciona

- **Macapá (`macapa.ap.gov.br/diarios-oficiais/`):** usa **Livewire (PHP)**. O HTML inicial traz o JSON `wire:snapshot`; o filtro de datas (`search`) e a paginação (`setPage`, 15 itens/página) ocorrem via `POST /livewire/update`. A capitalização dos links varia (`Oficial` vs `oficial`), provando que montar URLs por padrão falharia. A maioria dos PDFs é imagem escaneada (e alguns poucos antigos têm OCR ruidoso), exigindo `pymupdf` + `rapidocr` (`pt`, 150 DPI) com ordenação de 2 colunas.
- **Fortaleza (`diariooficial.fortaleza.ce.gov.br/`):** bloqueia tráfego automatizado via WAF (HTTP 200 com mensagem de negação no HTML) e apresentou timeout de 60s na coleta automatizada, registrado em [evidence/fortaleza_erro.json](evidence/fortaleza_erro.json) e detalhado em [DIAGNOSTICO.md](docs/DIAGNOSTICO.md).

## Como sabemos que não faltou nenhuma edição

1. **Sequência numérica:** `verificar.py` detecta lacunas internas entre a menor e a maior edição `normal` (ignorando suplementos como `5183-A`). Não detecta faltas nas pontas do intervalo.
2. **Consistência conteúdo × metadado:** confirma se `numero_edicao` aparece nos primeiros 1.200 caracteres do texto extraído, além de checar duplicatas e legibilidade.
3. **Sondas independentes nas pontas:** `coletar.py` testa `menor_id - 1` e `maior_id + 1` via `HEAD` em [dados/sondas_macapa.json](dados/sondas_macapa.json). Um `HTTP 200` dentro da janela esperada gera **erro** no verificador. Limitação: `404` não prova ausência devido à variação de capitalização ou possíveis mudanças nos links.
4. **Dias úteis e Fortaleza:** dias úteis sem edição geram apenas **aviso** (possíveis feriados). Fortaleza com `0` edições gera **erro esperado** (`exit=1`), provando que o verificador não silencia fonte inacessível.

## Limitações, fragilidades e uso de IA

- **O que quebraria primeiro:** mudança nos campos do `wire:snapshot` ou nos métodos `search`/`setPage` do Livewire em Macapá, causando falha na busca por conteúdo das páginas e impedindo a coleta dos documentos.
- **Parte mais frágil:** ordenação de 2 colunas no OCR (páginas com 3+ colunas ou tabelas largas podem intercalar trechos) e diferenciação de edição `extra` publicada em feriado de dia útil. Imagens de baixa qualidade, textos sobrepostos com carimbos ou assinaturas, dentre outras anomalias podem prejudicar o reconhecimento de caracteres, e portanto, também, a qualidade do conteúdo extraído.
- **Com mais tempo:** Procurar por mais cenários onde a coleta falha ou edge cases causados pelo site oficial. implementar novas funcionalidades para garantir a integridade dos textos extraídos. Otimizar a parte do OCR pra tentar aumentar sua precisão. Pesquisar soluções alternativas viáveis para completar a tarefa.
- **Uso de IA:** a IA escreveu os scripts, o comparativo de OCR e a documentação (detalhes de manutenção em [DETALHES_CODIGO.md](docs/DETALHES_CODIGO.md)). Durante a revisão, procurei por falhas e inconsistências, pedindo para serem reajustados. EX: filtros baseados em suposições (títulos teriam "suplemento" ou "extra" sempre), assumir que todos os dias úteis sem D.O.M's são erros de coleta, dentre outros menores.
