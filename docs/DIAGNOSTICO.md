# Diagnóstico Técnico: Bloqueio e Indisponibilidade em Fortaleza (CE)

## 1. O que aconteceu
Durante a investigação manual inicial (documentada em [Logs.md](docs/Logs.md)), ao acessar `https://diariooficial.fortaleza.ce.gov.br/` de forma automatizada e honesta (via `requests`, sem camuflagem de navegador ou rotação de IP), o servidor respondeu com **HTTP 200**, mas entregou no corpo HTML a mensagem de bloqueio de WAF:

> *"Sua solicitação foi negada. Seu suporte ID Bot é ..."*

Posteriormente, nas execuções controladas do `coletar.py` (com timeout de 30s e depois 60s), o mesmo endereço expirou por **`Read timed out`**, cuja evidência está registrada em [evidence/fortaleza_erro.json](evidence/fortaleza_erro.json).

Por isso, `coletar_fortaleza()` em `coletar.py` trata os dois cenários sem sobrescrever evidências já salvas em `evidence/`:
- Quando há resposta HTTP, inspeciona o conteúdo HTML buscando a assinatura de negação e salva `fortaleza_bloqueio.html` + `fortaleza_meta.json`.
- Quando há timeout ou falha de rede, salva `fortaleza_erro.json`.

## 2. Fontes alternativas investigadas
- **Portal de Dados Abertos de Fortaleza:** publica datasets diversos, mas não disponibiliza os PDFs do Diário Oficial.
- **Querido Diário (Open Knowledge Brasil):** apenas redireciona para o link oficial da prefeitura.
- **Escavador:** exige cadastro para download, possui API paga e apresentava defasagem em relação ao portal oficial.

## 3. O que faria em produção
Seguindo a regra de não contornar proteções (sem spoofing de TLS/headers, resolução de CAPTCHA ou proxies):
1. **Canal oficial:** solicitar à Prefeitura de Fortaleza (via LAI ou contato técnico) a liberação de acesso via API pública, feed RSS/JSON ou inclusão em lista de permissão para monitoramento cívico.
2. **Provedor autorizado:** avaliar a contratação de API oficial/parceira caso haja necessidade imediata de SLA.
3. **Monitoramento:** manter o erro explícito no `verificar.py` para alertar que a fonte está inacessível, em vez de silenciar a ausência de dados.
