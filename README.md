# Conselho do dia no X

Automação para transformar os conselhos de H. Jackson Brown, Jr., do *Pequeno Manual de Instruções para a Vida*, em cartões PNG do serif.sh e posts no X. O modo padrão é dry-run; publicar exige `--publish`.

## Arquivos

- `daily.py`: coordena renderização, postagem, estado e registro diário.
- `render.py`: gera `out/conselho-<n>.png` e verifica overflow e OCR.
- `post.py`: valida o post e usa OAuth 1.0a para acessar o X.
- `conselhos.json`: lista de 1001 objetos com `n` e `text`.
- `estado.example.json`: modelo do estado; `estado.json` guarda `proximo`, `ultimo_enviado` e `data_ultimo_envio`.
- `.env.example`: modelo das credenciais; `.env` contém os valores locais.
- `log.jsonl`: registro de publicações confirmadas (`n`, `id`, `url`, `data`).
- [README-render.md](README-render.md) e [README-post.md](README-post.md): detalhes dos scripts individuais.

## Requisitos e instalação

Python 3.10+, Node.js com npm, Tesseract com português e Chromium do Playwright.

Clone e inicie o serif.sh em outro terminal:

```bash
git clone https://github.com/prof-ramos/serif-sh
cd serif-sh
git checkout abc59e082e476385326f7a7e840f08965f9e6f00
npm ci && npm run dev -- --port 5173 --host 127.0.0.1
```

Instale o OCR no Debian/Ubuntu:

```bash
sudo apt update
sudo apt install tesseract-ocr tesseract-ocr-por
```

No macOS, os pacotes equivalentes via Homebrew são:

```bash
brew install tesseract tesseract-lang
```

No diretório deste projeto, de preferência em um ambiente virtual:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-render.txt
python -m playwright install chromium
```

## Configuração do X e estado

Crie um app no X Developer Portal com permissão **Read and Write** e gere as credenciais OAuth 1.0a de usuário com essa permissão. Configure:

```bash
cp .env.example .env
chmod 600 .env
cp estado.example.json estado.json
```

Preencha `.env` com `X_CONSUMER_KEY`, `X_CONSUMER_SECRET`, `X_ACCESS_TOKEN` e `X_ACCESS_TOKEN_SECRET`. Variáveis do ambiente têm prioridade. O arquivo padrão fica ao lado de `post.py`; `X_ENV_FILE` pode indicar outro caminho, e `post.py --env-file` permite especificá-lo diretamente. Não versione credenciais.

Revise o estado copiado: o exemplo contém um envio anterior, inclusive uma data. Ajuste `proximo` para o conselho desejado e, para começar sem histórico, use `null` em `ultimo_enviado` e `data_ultimo_envio`.

## Executar

Com o serif.sh rodando na porta 5173, teste:

```bash
python3 daily.py
python3 daily.py --dry-run
```

O dry-run gera e valida o PNG e consulta o usuário autenticado no X: **requer rede e credenciais válidas**, mas não envia mídia nem publica. Não avança o estado nem grava o log. Se o estado não existir, copia o modelo mesmo no dry-run.

Para publicar:

```bash
python3 daily.py --publish
```

Opções: `--estado /caminho/estado.json`, `--conselhos /caminho/conselhos.json` e `--url http://127.0.0.1:5173`. Os caminhos padrão ficam no diretório do script; caminhos fornecidos são relativos ao diretório atual. O log e a pendência ficam no mesmo diretório de `--estado` (por padrão, ao lado do script).

A imagem recebe o texto do conselho, autor e fonte. O post contém somente a imagem, sem a chave `text` no payload. O texto alternativo contém o número e o conselho na primeira linha, o autor na segunda e a fonte na terceira. O resumo JSON inclui `image_only_ok` (payload sem `text` e com IDs de mídia) e `alt_text`. Argumentos são passados diretamente, sem shell, com quebras de linha reais.

Em `--publish`, se `data_ultimo_envio` já for hoje em `America/Sao_Paulo`, termina sem renderizar nem publicar. Após sucesso, substitui o estado atomicamente com `proximo=n+1`, `ultimo_enviado=n` e a data de hoje, e acrescenta uma linha a `log.jsonl`. Falhas retornam código diferente de zero; a saída é JSON, sem credenciais. Ao terminar a lista, é necessário definir novos conselhos ou ajustar o estado.

A rotina usa um lock local e registra `publication.pending.json` antes de acessar o X em modo publicação. Uma tentativa pendente bloqueia novos envios, inclusive no mesmo dia. O recibo confirmado é salvo antes do log e do estado; a pendência só é removida depois de ambos serem persistidos. Uma falha no texto alternativo impede a criação do post.

No GitHub Actions, a intenção é commitada e enviada a `main` **antes** do envio ao X. Se esse push falhar, não há publicação. Se o push final falhar, a intenção permanece no GitHub e impede repetir o post. O workflow tenta preservar o estado mesmo se a rotina falhar e disponibiliza `publication-recovery` como artefato. Não há repetição automática de chamadas de publicação.

O fluxo só publica em `main`. PRs e pushes executam testes sem segredos; renderização e consulta da conta são executadas por agendamento ou despacho manual. `PUBLISH_ENABLED=true` habilita o envio agendado às 08h03 de São Paulo; o despacho manual continua com dry-run por padrão.

### Recuperar uma tentativa interrompida

1. Pare execuções concorrentes e confira o post na conta do X. Não apague a pendência nem use novamente `--prepared-attempt` para tentar resolver uma resposta incerta.
2. Atualize o checkout de `main` e baixe o artefato `publication-recovery` da execução que falhou. Compare `attempt`, `n` e a data com a intenção do GitHub antes de usar o recibo do artefato. Preserve uma cópia dos arquivos atuais.
3. Se o artefato contém `publication.pending.json` com `status=confirmed`, ID e URL correspondentes ao post verificado, copie **esse recibo** para o checkout e execute:

   ```bash
   python3 daily.py --recover
   python3 ci_state.py 'reconciliar publicação confirmada'
   ```

   Isso reconcilia log e estado, remove a pendência e persiste o resultado sem acessar o X ou publicar. O log não recebe outra linha para o mesmo conselho/ID.
4. Se não há recibo confirmado, a rotina para: a API pode ter aceitado o post antes de a conexão cair. Confira a conta e os logs antes de qualquer ação. Se o post existe, preencha o recibo com o ID/URL verificados e `status=confirmed`, preservando `attempt`, `n` e `data`, e use `--recover`. Se foi confirmado que não houve publicação, remova a pendência e faça commit/push dessa remoção antes de uma nova tentativa. **Ausência de resposta não comprova ausência de post.**

O registro reduz duplicações, mas não cria uma transação entre Git e X. Checkouts independentes em computadores diferentes não compartilham o lock: centralize os envios no workflow; o uso direto de `post.py --publish` não possui a proteção da rotina diária.

## Testes e versões

```bash
python3 -m unittest discover -s tests -v
```

Os testes usam diretórios temporários, Git local e respostas simuladas nas fronteiras com o X/renderizador. Não exigem credenciais nem publicam. Cobrem texto alternativo, payload só com imagem, falhas de gravação, respostas incertas, recuperação, lock local e rejeição de pushes.

`requirements-render.txt` fixa dependências diretas e transitivas da execução validada do nº 4. O workflow fixa também o commit do `serif-sh`. Para atualizar, altere as versões/commit explicitamente, execute os testes e valide um despacho com `dry_run=true` antes do envio seguinte. Não é necessário instalar dependências de renderização para executar os testes.

## Agendamento

Exemplo de crontab para as 8h de São Paulo em sistemas cujo cron suporta `CRON_TZ`:

```cron
CRON_TZ=America/Sao_Paulo
0 8 * * * cd /caminho/conselho-do-dia-x && /usr/bin/python3 daily.py --publish >> cron.log 2>&1
```

Se usar ambiente virtual, troque `/usr/bin/python3` pelo caminho absoluto de `.venv/bin/python`. Garanta que o cron encontre o Tesseract e o Chromium instalado para o mesmo usuário. O serif.sh precisa estar rodando no horário: sugere-se iniciá-lo via systemd, pm2 ou uma entrada `@reboot`. Em implementações sem `CRON_TZ`, configure o fuso do serviço de agendamento.

`.env`, `estado.json`, `out/`, `cron.log` e `log.jsonl` ficam fora do versionamento.
