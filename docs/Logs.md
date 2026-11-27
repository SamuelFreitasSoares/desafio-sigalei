## Linha de Raciocínio 
### 25/11/2026
- Recebi o desafio técnico por email
- Li e analisei os principais pontos
- Iniciei com um entendimento das fontes cujo os dados serão obtidos
	- Entrei nos dois links fornecidos e notei que se tratava de uma página para obter diários oficiais de duas cidades: Macapá e Fortaleza.
	- é possível escolher um intervalo de tempo para a exibição dos diários e seus PDFs para download.
	- Notei que no caso de Macapá os links contendo os PDFs seguem o seguinte padrão: https://macapa.ap.gov.br/portal/wp-content/uploads/{ano}/{mes}/Diario-Oficial-{Num_do_Diário}-{dia}.{mes}.{ano}.pdf
		- Por algum motivo, os PDFs de Macapá são scans de páginas físicas, contendo apenas imagens. 
		- O número do diário parece incrementar em 1 a cada edição, sendo a edição de 25/11/2026 com número 5421 e a edição de 24/11/2026 com número 5420, e assim sucessivamente.
		- Alguns PDFs parecem ter passado por OCR antes de serem postados mas é a exceção e não a regra, a maioria ainda são apenas imagens sem texto selecionável. Para satisfazer as condições do desafio provavelmente terei que usar alguma solução de OCR para extrair as informações.
		- O OCR escolhido (RapidOCR) possui as seguintes métricas de performance em **textos limpos**:
			- detecção de texto (text_dec): Atinge pontuação H-mean de **84,9%**
			- Reconhecimento de caracteres (text_rec): Alcança **95,15%** de acerto por caractere (_Char Match_) e **84,19%** de correspondência exata de linhas (_Exact Match_).
			- Com essas informações, é esperado que o conteúdo obtido pelo projeto não seja 100% preciso, podendo conter caracteres errados, palavras quebradas e linhas incompletas. É um trade-off entre a simplicidade de implementação e performance. Modelos mais avançados podem obter um resultado melhor mas seriam mais difíceis de se utilizar, necessitando a instalação de programas adicionais.
	- Já para Fortaleza, não parece haver um padrão específico mas descobri que a cidade possui uma API para Dados Abertos. Talvez dê para usar isso.
		- Infelizmente essa API é para datasets e não possui DOMs.
		- O site escavador.com possui os diários disponíveis como texto simples na página web e arquivos PDF, porém exige cadastro para realizar o download e parece não estar atualizado (ultimo registro no escavador é do dia 23 e já existe DOM do dia 24). Também notei que possuem uma API de dados mas é paga.
		- Tentei o site "Querido Diário" mas parecem não hospedar arquivos para download, apenas um link redirecionando para o site oficial de Fortaleza. 
	- Com a ajuda do Gemini, obtive a estrutura das requisições (payload, header, response) e criei um script simples para obter os PDFs, pois as URLs dos arquivos não possuem padrão, porém o firewall da prefeitura bloqueou já na primeira requisição e exibiu a mensagem: "Sua solicitação foi negada. Seu suporte ID Bot é 8655823092723793221."
		- O fato de o mesmo endereço funcionar manualmente no navegador e ser rejeitado na primeira requisição automatizada e a mensagem _"Seu suporte ID Bot é..."_ é compatível com a atuação de um Firewall de Aplicação Web (WAF) configurado para filtrar tráfego automatizado.
		- como o desfio proíbe tentativas de burlar, finalizei aqui a busca de um modo de obter arquivos automaticamente direto do site oficial.
		- Acredito que as alternativas mais viáveis seriam contratar os serviços de sites agregadores (como o escavador.com.br ou JusBrasil.com.br) e suas APIs de dados, ou  talvez protocolar um pedido formal à prefeitura de Fortaleza (Lei de Acesso à Informação) solicitando a disponibilização de um canal oficial de dados abertos (API pública ou feed) para consulta automatizada do DOM.
	- Antes de começar o uso de agentes, vou definir o formato escolhido: 
		- **JSONL:** 
			- Justificativa: CSV pode se corromper facilmente com textos longos, enquanto JSONL converte linha a linha e se uma delas quebrar não afeta as outras. Adicionar novas linhas é barato, pois basta acrescentar no final, diferente de um JSON normal onde precisaria reescrever o arquivo inteiro. Não necessita de dependências extras, o módulo ``json`` já resolve. diferente de Parquet e SQLite, é legível e inspecionável, dá pra abrir no editor ou através de comandos num terminal. Apesar de ocupar mais espaço em disco por não ter compressão, para a proposta desse desafio é suficiente, em grandes bases de textos Parquet seria uma escolha mais interessante. Além disso, é um formato bom para machine learning, stream processing e ingestão de Big Data.
	- Defini como diferenciar as diferentes edições:
		- | Tipo de Edição               | Quando é publicada                                                            | Motivo / Finalidade                                                                                                 | Exemplos comuns                                                                                                          |
		| ---------------------------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
		| **Normal (Ordinária)**       | Uma vez por dia útil, pela manhã (de segunda a sexta-feira).                  | Rotina administrativa padrão, reunindo todos os atos enviados dentro do prazo regular.                              | Leis, decretos de rotina, nomeações comuns, editais de licitação e balanços.                                             |
		| **Extra (Extraordinária)**   | A qualquer hora do dia, inclusive à noite, nos fins de semana ou em feriados. | **Urgência.** Quando um ato não pode esperar até a edição normal do dia seguinte.                                   | Medidas Provisórias urgentes, exonerações ou nomeações imediatas de ministros e decretos de emergência.                  |
		| **Suplemento (Suplementar)** | Junto com a edição normal (ou logo após), em um caderno ou arquivo separado.  | **Organização e volume.** Separa matérias muito extensas ou específicas para não sobrecarregar o caderno principal. | Tabelas orçamentárias extensas, listas gigantes de concursos, planos plurianuais e resoluções técnicas (como da Anvisa). |
### 26/11/2026
- Comecei a planejar a estrutura do projeto com auxílio do Claude e Gemini, definindo escopo, objetivos, critérios de parada e sucesso e métodos de verificação.
	- Alimentei o Claude com o contexto geral do projeto e informações que descobri explorando as fontes manualmente.
	- Utilizei o Google Antigravity (modelo Gemini 4 Hydrogen no medium) para criar o esboço inicial do plano de desenvolvimento e mandei os resultados para o Claude conferir se algo estava faltando ou possíveis melhorias.
- Durante o desenvolvimento e com a ajuda do Claude, investiguei o HTML bruto (ctrl + U) da página dos diários de Macapá para entender como são listados e renderizados.
	- Por sorte, o site disponibiliza a listagem dos DOMs no HTML bruto. Também descobri que ele utiliza Livewire (framework PHP). 
- Prossegui com a construção do projeto com o agente durante o resto do dia, analisando as entregas, sugerindo melhorias ou correções com base em detalhes descobertos e esclarecendo dúvidas com relação ao desafio.
- Finalizei uma versão inicial do projeto capaz de cumprir com os requisitos mínimos exigidos.
### 27/11/2026
- Analisei cada arquivo do projeto separadamente para entender como tudo funciona, anotando dúvidas, sugestões e melhorias.
- Enviei as anotações de volta para o agente, tendo que trocar o modelo devido ao limite de uso atingido (Gemini 4 Hydrogen -> Claude Opus 4.6)
- Possível erro encontrado: o backend de Macapá trata initialDate e finalDate de forma exclusiva (>), portanto se a data inicial for dia 15 a coleta só pega os arquivos do dia 16 pra frente. Ao rodar o ``verificar.py``, isso gerava um erro pois ele assumia que a coleta era inclusiva (>= e <=) nos dias finais e iniciais.
	- A correção foi recuar 1 dia da data inicial e adicionar 1 dia à data final na consulta à API.
	- O site exibiu comportamento estranho em Jan/2026, onde pra exibir o arquivo do dia 29 de janeiro a data final do filtro precisa ser 31/01. Vou  ajustar a consulta da API pra buscar 2 dias antes e depois. Já existe um filtro pra garantir que mesmo que consulte com mais dias, irá baixar PDFs apenas no intervalo selecionado.
- Outro erro: o verificar.py roda a partir da data do arquivo mais recente até o atual mesmo passando os parêmtros ``--inicio`` e ``--fim``. Isso causou um erro quando coletei três arquivos de janeiro e o restante a partir de setembro/outubro. O código deu como erro os arquivos que não foram coletados entre esse intervalo.
	- adicionei parâmetros no ``coletar.py`` para fins de teste: mudar o arquivo de  destino do conteúdo extraído e sobrescrever conteudo ja existente
	- adicionei no ``verificar.py`` comando para selecionar o arquivo a ser verificado
- Comecei a ler todos os arquivos .md um a um, ajustando detalhes desatualizados, informações desnecessárias, etc.
- Enviei o projeto para o repositório no Github